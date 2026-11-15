##############################
# core/resources/manager.py - 资源获取/索引/查询统一入口
##############################

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from Moge.core.materials import MinecraftBlock
from Moge.core.resources import bedrock, java
from Moge.core.resources.catalog import choose_face
from Moge.core.resources.database import ResourceDatabase
from Moge.core.resources.network import file_hashes
from Moge.core.resources.paths import (
    database_path,
    ensure_layout,
    resource_root,
)

JAVA_TARGETS = ("1.12.2", "1.16.5", "1.18.2", "1.20.1", "1.21.4")

RESOURCE_STATES = (
    "UNAVAILABLE",
    "DOWNLOADING",
    "VERIFYING",
    "PARSING",
    "PARTIAL",
    "READY",
    "CORRUPTED",
)

_STATUS_MAP = {
    "not-downloaded": "UNAVAILABLE",
    "not-available": "UNAVAILABLE",
    "pending": "UNAVAILABLE",
    "downloading": "DOWNLOADING",
    "verifying": "VERIFYING",
    "parsing": "PARSING",
    "partial": "PARTIAL",
    "ready": "READY",
    "failed": "CORRUPTED",
    "corrupted": "CORRUPTED",
}


def normalize_status(status: str) -> str:
    """ 将索引库内部状态映射为对外的七态枚举 """
    return _STATUS_MAP.get(str(status).lower(), "UNAVAILABLE")


def _failure_state(exc: Exception) -> str:
    text = str(exc).lower()
    if any(key in text for key in ("sha", "校验", "hash", "mismatch", "size")):
        return "corrupted"
    return "failed"


class ResourceManager:
    """ CLI 与 GUI 共用的资源管理核心 """

    def __init__(self, root: Path = None):
        self.root = ensure_layout(Path(root) if root else resource_root())
        self.db = ResourceDatabase(database_path(self.root))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---------- Java ---------- #
    def sync_java_manifest(self, force: bool = False) -> dict:
        manifest = java.load_manifest(self.root, force=force)
        return {
            "count": len(manifest.get("versions", [])),
            "latest": manifest.get("latest", {}),
        }

    def list_java_versions(self, release_only: bool = True, limit: int = 0) -> list[dict]:
        manifest = java.load_manifest(self.root)
        versions = java.list_versions(manifest, release_only=release_only)
        rows = []
        for entry in versions:
            row = self.db.get_version("java", entry["id"]) or {}
            rows.append(
                {
                    "edition": "java",
                    "version": entry["id"],
                    "version_type": entry.get("type", ""),
                    "url": entry.get("url", ""),
                    "status": row.get("status", "not-downloaded"),
                    "state": normalize_status(row.get("status", "not-downloaded")),
                    "blocks": self.db.block_count(int(row["id"])) if row.get("id") else 0,
                }
            )
        return rows[:limit] if limit else rows

    def fetch_java(
        self,
        version: str,
        force: bool = False,
        dry_run: bool = False,
        progress: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> dict:
        manifest = java.load_manifest(self.root)
        entry = java.find_version(manifest, version)
        if entry is None:
            raise ValueError(f"官方清单中没有版本 {version}")
        metadata = java.version_metadata(manifest, version, self.root)
        client = (metadata.get("downloads") or {}).get("client") or {}
        local = java.find_local_client_jar(version)

        existing = self.db.get_version("java", version)
        if existing and existing["status"] == "ready" and not force:
            return {
                "edition": "java",
                "version": version,
                "status": "ready",
                "skipped": True,
                "blocks": self.db.block_count(int(existing["id"])),
                "textures": self.db.texture_count(),
                "resource_path": existing["resource_path"],
            }

        plan = {
            "edition": "java",
            "version": version,
            "type": entry.get("type"),
            "url": client.get("url"),
            "size": client.get("size"),
            "sha1": client.get("sha1"),
            "local_jar": str(local) if local else "",
        }
        if dry_run:
            return plan

        version_id = self.db.upsert_version(
            "java", version, entry.get("type", ""), "mojang-piston", client.get("url", ""), status="downloading"
        )
        try:
            if progress:
                progress(1, f"准备 Java {version}")
            self.db.set_status(version_id, "verifying", "")
            jar_path, jar_sha, origin = java.ensure_client_jar(
                version,
                metadata,
                self.root,
                progress=lambda done, total: progress(
                    int(5 + 35 * done / total) if total else 5,
                    f"下载客户端 {done // 1048576}/{max(1, (total or 0) // 1048576)} MB",
                ) if progress else None,
                should_cancel=should_cancel,
            )
            if progress:
                progress(45, "解析 blockstate / model / texture")
            self.db.set_status(version_id, "parsing", "")
            stats = java.parse_client_jar(
                jar_path,
                version_id,
                self.db,
                self.root,
                progress=lambda done, total: progress(
                    45 + int(50 * done / total) if total else 50, f"解析方块 {done}/{total}"
                ) if progress else None,
                should_cancel=should_cancel,
            )
            status = "ready" if stats["complete_blocks"] else "partial"
            self.db.upsert_version(
                "java", version, entry.get("type", ""), origin, client.get("url", ""),
                status=status, error="", resource_path=str(jar_path),
                resource_sha256=jar_sha, fetched_at=datetime.now().isoformat(timespec="seconds"),
            )
            if progress:
                progress(100, "Java 资源索引完成")
            return {"edition": "java", "version": version, "status": status, "jar": str(jar_path), **stats}
        except Exception as exc:
            self.db.set_status(version_id, _failure_state(exc), str(exc))
            raise

    def resolve_java_range(self, from_version: str, to_version: str, release_only: bool = True) -> list[str]:
        manifest = java.load_manifest(self.root)
        start = java.parse_version_tuple(from_version)
        end = java.parse_version_tuple(to_version)
        if start is None or end is None:
            raise ValueError("版本范围格式无效")
        selected = []
        for entry in java.list_versions(manifest, release_only=release_only):
            current = java.parse_version_tuple(entry["id"])
            if current is None:
                continue
            if start <= current <= end:
                selected.append(entry["id"])
        return sorted(set(selected), key=java.parse_version_tuple)

    # ---------- Bedrock ---------- #
    def list_bedrock_versions(self) -> list[dict]:
        releases = bedrock.fetch_releases(self.root)
        rows = []
        targets = list(bedrock.TARGET_VERSIONS)
        for row in self.db.list_versions("bedrock"):
            if row["version"] not in targets:
                targets.append(row["version"])
        for target in targets:
            release = bedrock.find_release(releases, target)
            row = self.db.get_version("bedrock", target) or {}
            rows.append(
                {
                    "edition": "bedrock",
                    "version": target,
                    "version_type": "release",
                    "tag": release.get("tag_name", "") if release else "",
                    "status": row.get("status", "not-available" if release is None else "not-downloaded"),
                    "state": normalize_status(row.get("status", "not-available" if release is None else "not-downloaded")),
                    "blocks": self.db.block_count(int(row["id"])) if row.get("id") else 0,
                }
            )
        return rows

    def fetch_bedrock(
        self,
        version: str,
        force: bool = False,
        dry_run: bool = False,
        progress: Optional[Callable[[int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> dict:
        if dry_run:
            return bedrock.fetch_and_parse(version, 0, self.db, self.root, dry_run=True)
        existing = self.db.get_version("bedrock", version)
        if existing and existing["status"] == "ready" and not force:
            return {
                "edition": "bedrock",
                "version": version,
                "status": "ready",
                "skipped": True,
                "blocks": self.db.block_count(int(existing["id"])),
            }

        version_id = self.db.upsert_version(
            "bedrock", version, "release", "bedrock-samples", "", status="downloading"
        )
        try:
            if progress:
                progress(2, f"查询 Bedrock {version} Release")
            self.db.set_status(version_id, "downloading", "")
            stats = bedrock.fetch_and_parse(
                version,
                version_id,
                self.db,
                self.root,
                progress=lambda done, total: progress(
                    int(5 + 85 * done / total) if total else 10,
                    f"下载 Bedrock 资源 {done // 1048576}/{max(1, (total or 0) // 1048576)} MB",
                ) if progress else None,
                should_cancel=should_cancel,
            )
            status = "ready" if stats["complete_blocks"] else "partial"
            cached_zip = Path(bedrock.bedrock_cache_dir(self.root)) / f"{version}.zip"
            zip_sha256 = file_hashes(cached_zip)[1] if cached_zip.exists() else ""
            self.db.upsert_version(
                "bedrock", version, "release", "bedrock-samples", stats.get("tag", ""),
                status=status, error="", resource_path=str(cached_zip),
                resource_sha256=zip_sha256,
                fetched_at=datetime.now().isoformat(timespec="seconds"),
            )
            if progress:
                progress(100, "Bedrock 资源索引完成")
            return {"edition": "bedrock", "version": version, "status": status, **stats}
        except Exception as exc:
            self.db.set_status(version_id, _failure_state(exc), str(exc))
            raise

    # ---------- 查询/维护 ---------- #
    def versions(self, edition: Optional[str] = None) -> list[dict]:
        return self.db.list_versions(edition)

    def build_catalog(self, edition: str, version: str) -> list[MinecraftBlock]:
        """ 从真实资源库构建候选方块；缺少面数据的方块不会进入映射 """
        blocks = []
        for row in self.db.get_blocks(edition, version):
            if not row["complete"] or not row["faces"]:
                continue
            face = choose_face(row["faces"], row["visible_face"])
            if face is None:
                continue
            blocks.append(
                MinecraftBlock(
                    block_id=row["block_id"],
                    name=row["name"],
                    rgb=tuple(face["rgb"]),
                    category=row["category"],
                    obtainability=row["obtainability"],
                    renewable=bool(row["renewable"]),
                    buildable=bool(row["buildable"]),
                    gravity=bool(row["gravity"]),
                    transparent=bool(row["transparent"]),
                    orientation=row["orientation"],
                    visible_face=row["visible_face"],
                    source="mojang-resource",
                    note=row["notes"] or "真实贴图",
                    geometry=row.get("geometry") or "unknown",
                    block_state=row.get("block_state") or "",
                    texture_sha256=face.get("sha256", ""),
                    texture_path=face.get("path", ""),
                    verified=bool(row.get("verified")),
                    complexity=float(face.get("complexity", 0.0)),
                    brightness_std=float(face.get("brightness_std", 0.0)),
                    median_rgb=tuple(face.get("median_rgb") or (0, 0, 0)),
                    tinted=bool(row.get("tinted")),
                )
            )
        return blocks

    def coverage(self, edition: str, version: str) -> dict:
        """ 原版资源覆盖率（分子/分母明确） """
        return self.db.block_coverage(edition, version)

    def texture_preview_path(self, sha256: str) -> Optional[str]:
        return self.db.texture_path(sha256)

    def verify(self, edition: str, version: str, full: bool = False) -> dict:
        row = self.db.get_version(edition, version)
        if not row:
            raise ValueError("版本未索引")
        missing = []
        checked = 0
        for block in self.db.get_blocks(edition, version):
            for face in block["faces"].values():
                path = face.get("path") or self.db.texture_path(face["sha256"])
                checked += 1
                if not path or not Path(path).exists():
                    missing.append(face["sha256"])
        if full and row["resource_path"] and Path(row["resource_path"]).exists():
            sha1, sha256 = file_hashes(Path(row["resource_path"]))
            if row["resource_sha256"] and sha256 != row["resource_sha256"]:
                missing.append("resource-sha256-mismatch")
        state = normalize_status(row["status"])
        if missing and state == "READY":
            state = "CORRUPTED"
        return {
            "edition": edition,
            "version": version,
            "state": state,
            "checked_faces": checked,
            "missing": sorted(set(missing)),
            "coverage": self.db.block_coverage(edition, version),
            "ok": not missing,
        }

    def delete(self, edition: str, version: str) -> dict:
        row = self.db.get_version(edition, version)
        if not row:
            return {"deleted": False}
        path = Path(row["resource_path"]) if row["resource_path"] else None
        self.db.delete_version(edition, version)
        if path and path.exists() and path.is_file():
            path.unlink(missing_ok=True)
        removed = self.db.prune_orphan_textures()
        return {"deleted": True, "orphan_textures_removed": removed}

    def rebuild(self, edition: str, version: str, progress=None, should_cancel=None) -> dict:
        row = self.db.get_version(edition, version)
        if not row:
            raise ValueError("版本未索引")
        resource = Path(row["resource_path"])
        if not resource.exists():
            raise FileNotFoundError(f"缓存资源不存在：{resource}")
        if edition == "java":
            stats = java.parse_client_jar(resource, int(row["id"]), self.db, self.root,
                                          progress=None, should_cancel=should_cancel)
        else:
            stats = bedrock.parse_bedrock_zip(resource, int(row["id"]), self.db, self.root,
                                              should_cancel=should_cancel)
        status = "ready" if stats["complete_blocks"] else "partial"
        self.db.set_status(int(row["id"]), status, "")
        return {"edition": edition, "version": version, "status": status, **stats}

    def diff(self, edition: str, version_a: str, version_b: str) -> dict:
        return self.db.block_diff(edition, version_a, version_b)

    def cache_size(self) -> int:
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                total += path.stat().st_size
        return total

    def report(self) -> dict:
        versions = []
        for row in self.db.list_versions():
            versions.append(
                {
                    "edition": row["edition"],
                    "version": row["version"],
                    "status": row["status"],
                    "state": normalize_status(row["status"]),
                    "blocks": row["blocks"],
                    "source": row["source"],
                    "error": row["error"],
                }
            )
        return {
            "root": str(self.root),
            "stats": self.db.stats(),
            "cache_bytes": self.cache_size(),
            "versions": versions,
        }
