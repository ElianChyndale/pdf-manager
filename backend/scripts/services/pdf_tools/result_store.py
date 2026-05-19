import os
import time
import threading
from pathlib import Path


_RESULTS_DIR: Path | None = None
_CLEANUP_INTERVAL = 3600  # 1 hour
_TTL_SECONDS = 3600


def init_result_store(base_dir: str | Path) -> None:
    global _RESULTS_DIR
    _RESULTS_DIR = Path(base_dir) / "pdf-tools-results"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _start_cleanup_worker()


def store_result(file_name: str, data: bytes) -> str:
    result_id = f"{int(time.time())}_{os.urandom(4).hex()}"
    result_dir = _RESULTS_DIR / result_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / file_name).write_bytes(data)
    (result_dir / ".meta").write_text(
        f"file_name={file_name}\ncreated_at={time.time()}\n"
    )
    return result_id


def get_result(result_id: str) -> tuple[str, bytes] | None:
    result_dir = _RESULTS_DIR / result_id
    if not result_dir.exists():
        return None
    meta_text = (result_dir / ".meta").read_text()
    file_name = ""
    for line in meta_text.strip().splitlines():
        if line.startswith("file_name="):
            file_name = line.split("=", 1)[1]
            break
    data = (result_dir / file_name).read_bytes()
    return file_name, data


def _cleanup_expired() -> None:
    now = time.time()
    if not _RESULTS_DIR or not _RESULTS_DIR.exists():
        return
    for entry in _RESULTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        meta_path = entry / ".meta"
        if not meta_path.exists():
            continue
        for line in meta_path.read_text().strip().splitlines():
            if line.startswith("created_at="):
                created = float(line.split("=", 1)[1])
                if now - created > _TTL_SECONDS:
                    import shutil
                    shutil.rmtree(entry, ignore_errors=True)
                break


def _start_cleanup_worker() -> None:
    def _worker():
        while True:
            time.sleep(_CLEANUP_INTERVAL)
            try:
                _cleanup_expired()
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
