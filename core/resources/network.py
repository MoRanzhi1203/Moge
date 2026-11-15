##############################
# core/resources/network.py - JSON 缓存与可恢复下载
##############################

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

USER_AGENT = "Moge/2.0 (Minecraft resource indexer)"
DEFAULT_TIMEOUT = 30
RETRIES = 3
CHUNK = 256 * 1024


class DownloadCancelled(Exception):
    pass


def _request(url: str, headers: dict = None, timeout: int = DEFAULT_TIMEOUT):
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, headers=merged)


def http_json(url: str, timeout: int = DEFAULT_TIMEOUT, retries: int = RETRIES, headers: dict = None):
    """ 带有限重试的 JSON 请求；不无限循环 """
    last_error = None
    for attempt in range(max(1, retries)):
        try:
            with urllib.request.urlopen(_request(url, headers, timeout), timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                raise
            time.sleep(min(2.0 * (attempt + 1), 6.0))
    raise RuntimeError(f"请求失败：{url}：{last_error}")


def cached_json(cache_path: Path, url: str, max_age: int = 86400, force: bool = False, timeout: int = DEFAULT_TIMEOUT):
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if not force and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age <= max_age:
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    data = http_json(url, timeout=timeout)
    cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def download_file(
    url: str,
    destination: Path,
    expected_size: Optional[int] = None,
    sha1: Optional[str] = None,
    sha256: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = RETRIES,
) -> Path:
    """
    下载文件到 destination；支持 .part 断点续传、有限重试、取消与哈希校验。
    progress(downloaded, total)
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_suffix(destination.suffix + ".part")

    if destination.exists():
        if expected_size is None or destination.stat().st_size == expected_size:
            if _hash_matches(destination, sha1, sha256):
                if progress:
                    size = destination.stat().st_size
                    progress(size, size)
                return destination
        destination.unlink(missing_ok=True)

    for attempt in range(max(1, retries)):
        try:
            downloaded = part.stat().st_size if part.exists() else 0
            if expected_size is not None and downloaded > expected_size:
                part.unlink(missing_ok=True)
                downloaded = 0
            headers = {}
            if downloaded:
                headers["Range"] = f"bytes={downloaded}-"
            request = _request(url, headers, timeout)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = expected_size
                if total is None:
                    length = response.headers.get("Content-Length")
                    total = int(length) + downloaded if length else 0
                if downloaded and response.status != 206:
                    downloaded = 0
                hasher1 = hashlib.sha1()
                hasher256 = hashlib.sha256()
                if part.exists() and downloaded:
                    with part.open("rb") as existing:
                        while True:
                            chunk = existing.read(CHUNK)
                            if not chunk:
                                break
                            hasher1.update(chunk)
                            hasher256.update(chunk)
                mode = "ab" if downloaded else "wb"
                with part.open(mode) as handle:
                    while True:
                        if should_cancel is not None and should_cancel():
                            raise DownloadCancelled()
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        hasher1.update(chunk)
                        hasher256.update(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total or downloaded)

            size = part.stat().st_size
            if expected_size is not None and size != expected_size:
                raise OSError(f"文件大小不符：{size} != {expected_size}")
            if sha1 and hasher1.hexdigest().lower() != sha1.lower():
                part.unlink(missing_ok=True)
                raise OSError("SHA-1 校验失败")
            if sha256 and hasher256.hexdigest().lower() != sha256.lower():
                part.unlink(missing_ok=True)
                raise OSError("SHA-256 校验失败")
            os.replace(part, destination)
            return destination
        except DownloadCancelled:
            raise
        except Exception:
            if attempt >= retries - 1:
                raise
            time.sleep(min(2.0 * (attempt + 1), 6.0))
    raise RuntimeError(f"下载失败：{url}")


def _hash_matches(path: Path, sha1: Optional[str], sha256: Optional[str]) -> bool:
    if not sha1 and not sha256:
        return True
    hasher1 = hashlib.sha1()
    hasher256 = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            hasher1.update(chunk)
            hasher256.update(chunk)
    if sha1 and hasher1.hexdigest().lower() != sha1.lower():
        return False
    if sha256 and hasher256.hexdigest().lower() != sha256.lower():
        return False
    return True


def file_hashes(path: Path) -> tuple:
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK)
            if not chunk:
                break
            sha1.update(chunk)
            sha256.update(chunk)
    return sha1.hexdigest(), sha256.hexdigest()
