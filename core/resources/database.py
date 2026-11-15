##############################
# core/resources/database.py - SQLite 资源索引
##############################

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edition TEXT NOT NULL,
    version TEXT NOT NULL,
    version_type TEXT DEFAULT '',
    source TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    error TEXT DEFAULT '',
    resource_path TEXT DEFAULT '',
    resource_sha256 TEXT DEFAULT '',
    fetched_at TEXT DEFAULT '',
    UNIQUE(edition, version)
);
CREATE TABLE IF NOT EXISTS textures (
    sha256 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    animated INTEGER DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    has_alpha INTEGER DEFAULT 0,
    alpha_mean REAL DEFAULT 255,
    mean_r INTEGER DEFAULT 0,
    mean_g INTEGER DEFAULT 0,
    mean_b INTEGER DEFAULT 0,
    median_r INTEGER DEFAULT 0,
    median_g INTEGER DEFAULT 0,
    median_b INTEGER DEFAULT 0,
    lab_l REAL DEFAULT 0,
    lab_a REAL DEFAULT 0,
    lab_b REAL DEFAULT 0,
    complexity REAL DEFAULT 0,
    brightness_std REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    block_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    category TEXT DEFAULT 'other',
    obtainability TEXT DEFAULT 'unknown',
    renewable INTEGER DEFAULT 0,
    buildable INTEGER DEFAULT 1,
    gravity INTEGER DEFAULT 0,
    transparent INTEGER DEFAULT 0,
    orientation TEXT DEFAULT 'none',
    visible_face TEXT DEFAULT 'side',
    complete INTEGER DEFAULT 0,
    tinted INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    UNIQUE(version_id, block_id),
    FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS block_faces (
    block_row_id INTEGER NOT NULL,
    face TEXT NOT NULL,
    texture_sha256 TEXT DEFAULT '',
    rgb_r INTEGER DEFAULT 0,
    rgb_g INTEGER DEFAULT 0,
    rgb_b INTEGER DEFAULT 0,
    lab_l REAL DEFAULT 0,
    lab_a REAL DEFAULT 0,
    lab_b REAL DEFAULT 0,
    PRIMARY KEY(block_row_id, face),
    FOREIGN KEY(block_row_id) REFERENCES blocks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_blocks_version ON blocks(version_id);
CREATE INDEX IF NOT EXISTS idx_versions_edition ON versions(edition);
"""


class ResourceDatabase:
    """ 资源索引数据库；所有写操作使用事务 """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---------- 版本 ---------- #
    def upsert_version(self, edition: str, version: str, version_type: str = "", source: str = "",
                       source_url: str = "", status: str = "pending", error: str = "",
                       resource_path: str = "", resource_sha256: str = "", fetched_at: str = "") -> int:
        self.connection.execute(
            """
            INSERT INTO versions(edition, version, version_type, source, source_url, status, error,
                                 resource_path, resource_sha256, fetched_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(edition, version) DO UPDATE SET
                version_type=excluded.version_type,
                source=excluded.source,
                source_url=excluded.source_url,
                status=excluded.status,
                error=excluded.error,
                resource_path=excluded.resource_path,
                resource_sha256=excluded.resource_sha256,
                fetched_at=excluded.fetched_at
            """,
            (edition, version, version_type, source, source_url, status, error,
             resource_path, resource_sha256, fetched_at),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT id FROM versions WHERE edition=? AND version=?", (edition, version)
        ).fetchone()
        return int(row["id"])

    def set_status(self, version_id: int, status: str, error: str = ""):
        self.connection.execute(
            "UPDATE versions SET status=?, error=? WHERE id=?", (status, error, version_id)
        )
        self.connection.commit()

    def get_version(self, edition: str, version: str) -> Optional[dict]:
        row = self.connection.execute(
            "SELECT * FROM versions WHERE edition=? AND version=?", (edition, version)
        ).fetchone()
        return dict(row) if row else None

    def list_versions(self, edition: Optional[str] = None, downloaded_only: bool = False) -> list[dict]:
        query = "SELECT * FROM versions"
        params = []
        clauses = []
        if edition:
            clauses.append("edition=?")
            params.append(edition)
        if downloaded_only:
            clauses.append("status='ready'")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY edition, version"
        rows = self.connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["blocks"] = self.block_count(int(row["id"]))
            result.append(item)
        return result

    def delete_version(self, edition: str, version: str):
        self.connection.execute("DELETE FROM versions WHERE edition=? AND version=?", (edition, version))
        self.connection.commit()

    # ---------- 贴图 ---------- #
    def upsert_texture(self, sha256: str, path: str, size: int, features: dict, animated: bool = False):
        mean = features.get("mean_rgb", (0, 0, 0))
        median = features.get("median_rgb", (0, 0, 0))
        lab = features.get("lab", (0, 0, 0))
        self.connection.execute(
            """
            INSERT INTO textures(sha256, path, size, animated, width, height, has_alpha, alpha_mean,
                                 mean_r, mean_g, mean_b, median_r, median_g, median_b,
                                 lab_l, lab_a, lab_b, complexity, brightness_std)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sha256) DO UPDATE SET path=excluded.path, size=excluded.size
            """,
            (
                sha256, str(path), int(size), int(bool(animated)),
                features.get("width", 0), features.get("height", 0),
                features.get("has_alpha", 0), features.get("alpha_mean", 255),
                mean[0], mean[1], mean[2], median[0], median[1], median[2],
                lab[0], lab[1], lab[2],
                features.get("complexity", 0), features.get("brightness_std", 0),
            ),
        )

    def texture_path(self, sha256: str) -> Optional[str]:
        row = self.connection.execute("SELECT path FROM textures WHERE sha256=?", (sha256,)).fetchone()
        return row["path"] if row else None

    def orphan_textures(self) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT * FROM textures
            WHERE sha256 NOT IN (SELECT texture_sha256 FROM block_faces WHERE texture_sha256 <> '')
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def prune_orphan_textures(self) -> int:
        rows = self.orphan_textures()
        for row in rows:
            Path(row["path"]).unlink(missing_ok=True)
        self.connection.execute(
            "DELETE FROM textures WHERE sha256 NOT IN "
            "(SELECT texture_sha256 FROM block_faces WHERE texture_sha256 <> '')"
        )
        self.connection.commit()
        return len(rows)

    def texture_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) AS n FROM textures").fetchone()["n"])

    # ---------- 方块 ---------- #
    def replace_blocks(self, version_id: int, blocks: Iterable[dict]):
        """ 写入某版本的方块与面数据；先删除旧数据 """
        self.connection.execute("DELETE FROM blocks WHERE version_id=?", (version_id,))
        for block in blocks:
            cursor = self.connection.execute(
                """
                INSERT INTO blocks(version_id, block_id, name, category, obtainability, renewable,
                                   buildable, gravity, transparent, orientation, visible_face,
                                   complete, tinted, notes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version_id, block["block_id"], block.get("name", ""),
                    block.get("category", "other"), block.get("obtainability", "unknown"),
                    int(bool(block.get("renewable", False))), int(bool(block.get("buildable", True))),
                    int(bool(block.get("gravity", False))), int(bool(block.get("transparent", False))),
                    block.get("orientation", "none"), block.get("visible_face", "side"),
                    int(bool(block.get("complete", False))), int(bool(block.get("tinted", False))),
                    block.get("notes", ""),
                ),
            )
            row_id = cursor.lastrowid
            for face, data in (block.get("faces") or {}).items():
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO block_faces(block_row_id, face, texture_sha256,
                                                       rgb_r, rgb_g, rgb_b, lab_l, lab_a, lab_b)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        row_id, face, data.get("sha256", ""),
                        data.get("rgb", (0, 0, 0))[0], data.get("rgb", (0, 0, 0))[1],
                        data.get("rgb", (0, 0, 0))[2],
                        data.get("lab", (0, 0, 0))[0], data.get("lab", (0, 0, 0))[1],
                        data.get("lab", (0, 0, 0))[2],
                    ),
                )
        self.connection.commit()

    def block_count(self, version_id: int) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM blocks WHERE version_id=?", (version_id,)
        ).fetchone()
        return int(row["n"])

    def get_blocks(self, edition: str, version: str) -> list[dict]:
        version_row = self.get_version(edition, version)
        if not version_row:
            return []
        rows = self.connection.execute(
            "SELECT * FROM blocks WHERE version_id=? ORDER BY block_id", (version_row["id"],)
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            faces = self.connection.execute(
                "SELECT * FROM block_faces WHERE block_row_id=?", (row["id"],)
            ).fetchall()
            item["faces"] = {
                face["face"]: {
                    "sha256": face["texture_sha256"],
                    "rgb": (face["rgb_r"], face["rgb_g"], face["rgb_b"]),
                    "lab": (face["lab_l"], face["lab_a"], face["lab_b"]),
                }
                for face in faces
            }
            result.append(item)
        return result

    def block_diff(self, edition: str, version_a: str, version_b: str) -> dict:
        a = {row["block_id"] for row in self.get_blocks(edition, version_a)}
        b = {row["block_id"] for row in self.get_blocks(edition, version_b)}
        return {"only_in_a": sorted(a - b), "only_in_b": sorted(b - a), "common": len(a & b)}

    def stats(self) -> dict:
        versions = self.connection.execute("SELECT COUNT(*) AS n FROM versions").fetchone()["n"]
        blocks = self.connection.execute("SELECT COUNT(*) AS n FROM blocks").fetchone()["n"]
        return {
            "versions": int(versions),
            "blocks": int(blocks),
            "textures": self.texture_count(),
            "database_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
