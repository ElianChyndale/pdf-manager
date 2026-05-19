from __future__ import annotations

import os
import random
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_RETRY_ATTEMPTS_ENV = "RETAIN_HTTP_RETRY_ATTEMPTS"
DEFAULT_RETRY_BACKOFF_ENV = "RETAIN_HTTP_RETRY_BACKOFF_SECONDS"
RATE_LIMIT_WAIT_MAX_SECONDS = 300


class RetainNetworkError(RuntimeError):
    pass


class RetainRateLimitError(RetainNetworkError):
    pass


def retry_attempts(env_var: str = DEFAULT_RETRY_ATTEMPTS_ENV, default: int = 3) -> int:
    raw = os.environ.get(env_var, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(1, value)


def retry_backoff_seconds(env_var: str = DEFAULT_RETRY_BACKOFF_ENV, default: float = 0.5) -> float:
    raw = os.environ.get(env_var, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(0.1, value)


def direct_session(*, pool_connections: int = 8, pool_maxsize: int = 8) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies.clear()
    adapter = HTTPAdapter(
        max_retries=Retry(total=0, connect=0, read=0, redirect=0, status=0, backoff_factor=0),
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    attempts: int,
    backoff_seconds: float,
    label: str,
    **kwargs: Any,
) -> requests.Response:
    last_error: Exception | None = None
    accumulated_rate_limit_wait = 0.0
    for attempt in range(1, attempts + 1):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as err:
            last_error = err
            status_code = (
                err.response.status_code
                if isinstance(err, requests.HTTPError) and err.response is not None
                else None
            )
            retryable = status_code in RETRY_STATUS_CODES or isinstance(
                err,
                (requests.Timeout, requests.ConnectionError),
            )
            if not retryable:
                raise
            if attempt >= attempts:
                break
            retry_after = ""
            if isinstance(err, requests.HTTPError) and err.response is not None:
                retry_after = str(err.response.headers.get("Retry-After", "") or "").strip()
            if retry_after.isdigit():
                sleep_seconds = float(max(1, int(retry_after)))
            else:
                sleep_seconds = min(30.0, backoff_seconds * (2 ** max(0, attempt - 1)))
                sleep_seconds += random.uniform(0.0, max(0.1, sleep_seconds * 0.25))
            if status_code == 429:
                accumulated_rate_limit_wait += sleep_seconds
                if accumulated_rate_limit_wait > RATE_LIMIT_WAIT_MAX_SECONDS:
                    raise RetainRateLimitError(
                        f"{label} rate limited: retry-after budget exceeded for {url}"
                    ) from err
            print(
                f"{label} request retry {attempt}/{attempts} method={method.upper()} url={url} "
                f"status={status_code or ''} error={type(err).__name__}: {err}; sleep={sleep_seconds:.2f}s",
                flush=True,
            )
            time.sleep(sleep_seconds)
    assert last_error is not None
    if isinstance(last_error, requests.HTTPError) and last_error.response is not None:
        status_code = int(last_error.response.status_code)
        if status_code == 429:
            raise RetainRateLimitError(f"{label} rate limited after {attempts} attempts: {url}") from last_error
    raise RetainNetworkError(
        f"{label} network request failed after {attempts} attempts: method={method.upper()} url={url}: "
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error
