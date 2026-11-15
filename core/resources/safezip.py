##############################
# core/resources/safezip.py - 安全的 ZIP/JAR 读取
##############################

import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

MAX_MEMBERS = 30000
MAX_TOTAL_UNCOMPRESSED = 600 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024


class UnsafeArchiveError(ValueError):
    pass


def validate_members(archive: zipfile.ZipFile, allowed_prefixes: Optional[Iterable[str]] = None) -> list:
    """ 校验路径穿越、符号链接、成员数量与解压体积 """
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise UnsafeArchiveError(f"压缩包成员过多：{len(infos)}")
    total = 0
    allowed = tuple(allowed_prefixes) if allowed_prefixes else None
    valid = []
    for info in infos:
        name = info.filename.replace("\\", "/")
        parts = name.split("/")
        if name.startswith("/") or ".." in parts or ":" in parts[0]:
            raise UnsafeArchiveError(f"非法路径：{name}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise UnsafeArchiveError(f"成员过大：{name}")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise UnsafeArchiveError("压缩包解压体积超过上限")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise UnsafeArchiveError(f"不允许符号链接：{name}")
        if info.is_dir():
            continue
        if allowed is not None and not name.startswith(allowed):
            continue
        valid.append(info)
    return valid


def extract(archive_path: Path, destination: Path, allowed_prefixes: Optional[Iterable[str]] = None) -> list:
    """ 解压到 destination，返回实际写出的文件列表 """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in validate_members(archive, allowed_prefixes):
            target = destination / info.filename.replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            written.append(target)
    return written
