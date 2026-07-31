"""Stage-scoped cache with code fingerprints, atomic writes and integrity.

Caching must never serve stale entries because an unrelated file changed.  Each
cache consumer computes a **stage code fingerprint** — a hash of only the files
that actually affect that stage's output (its own module, its prompt files, its
config and the relevant policy fields) — not the whole git commit.  The
fingerprint is part of the cache schema so a code change to that stage
invalidates only that stage's cache.

Writes are atomic (temp file in the same dir + ``os.replace``) and guarded by a
file lock; reads verify the stored content hash and schema, and corrupt caches
are isolated (renamed away) rather than served or silently rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

CACHE_SCHEMA_PREFIX = "engineering-drawing-cache-v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_code_fingerprint(*, paths: list[Path], extra_payload: Mapping[str, Any] | None = None) -> str:
    """Hash the bytes of the given stage-relevant files plus optional context."""
    digest = hashlib.sha256()
    for path in sorted(Path(p) for p in paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        if path.is_file():
            digest.update(path.read_bytes())
        else:
            digest.update(b"<missing>")
    if extra_payload:
        digest.update(json.dumps(extra_payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def load_cache(path: Path | None, *, schema: str) -> dict[str, dict[str, Any]]:
    """Load a cache file, verifying schema + content hash; isolate corrupt files."""
    if path is None or not Path(path).is_file():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _isolate_corrupt(Path(path))
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        _isolate_corrupt(Path(path))
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        _isolate_corrupt(Path(path))
        return {}
    # Verify the stored content hash (when present) before serving.
    stored = payload.get("content_sha256")
    if stored and str(stored) != _entries_digest(entries):
        _isolate_corrupt(Path(path))
        return {}
    return {str(key): dict(value) for key, value in entries.items() if isinstance(value, dict)}


def save_cache(path: Path | None, entries: Mapping[str, dict[str, Any]], *, schema: str) -> None:
    """Atomically write a cache file under a file lock."""
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": schema,
        "content_sha256": _entries_digest(entries),
        "entries": dict(entries),
    }
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _file_lock(lock_path):
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def _entries_digest(entries: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(entries), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _isolate_corrupt(path: Path) -> None:
    """Rename a corrupt cache aside so it can be inspected, never served."""
    try:
        quarantined = path.with_suffix(path.suffix + ".corrupt")
        Path(path).replace(quarantined)
    except OSError:
        pass


class _file_lock:
    """Advisory lock via exclusive create of a lock file (works on Windows)."""

    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)

    def __enter__(self) -> None:
        acquired = False
        for _ in range(200):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                acquired = True
                break
            except FileExistsError:
                import time

                time.sleep(0.02)
        if not acquired:
            # Stale lock: force-break only if older than 10s.
            if self.lock_path.exists():
                try:
                    age = os.path.getmtime(self.lock_path)
                    import time

                    if time.time() - age > 10:
                        self.lock_path.unlink()
                        return self.__enter__()
                except OSError:
                    pass
            raise TimeoutError(f"could not acquire cache lock: {self.lock_path}")

    def __exit__(self, *_: Any) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass


__all__ = [
    "CACHE_SCHEMA_PREFIX",
    "file_sha256",
    "load_cache",
    "save_cache",
    "stage_code_fingerprint",
]
