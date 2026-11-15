##############################
# core/beads/database.py - 拼豆色卡 SQLite 索引
##############################

import sqlite3
from pathlib import Path
from typing import Optional

from Moge.core.materials import BeadColor

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
    id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    url TEXT DEFAULT '',
    license TEXT DEFAULT '',
    trust TEXT DEFAULT 'community',
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS palettes(
    id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    series TEXT NOT NULL,
    size TEXT DEFAULT '',
    source_id TEXT DEFAULT '',
    trust TEXT DEFAULT 'community',
    expected_count INTEGER DEFAULT 0,
    color_count INTEGER DEFAULT 0,
    license TEXT DEFAULT '',
    fetched_at TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS colors(
    palette_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT DEFAULT '',
    r INTEGER DEFAULT 0,
    g INTEGER DEFAULT 0,
    b INTEGER DEFAULT 0,
    alpha INTEGER DEFAULT 255,
    hex TEXT DEFAULT '',
    color_family TEXT DEFAULT '',
    material TEXT DEFAULT 'solid',
    trust TEXT DEFAULT 'unknown',
    source_url TEXT DEFAULT '',
    source_quality TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    verified INTEGER DEFAULT 0,
    contributor TEXT DEFAULT '',
    PRIMARY KEY(palette_id, code),
    FOREIGN KEY(palette_id) REFERENCES palettes(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS conflicts(
    brand TEXT NOT NULL,
    code TEXT NOT NULL,
    palette_a TEXT NOT NULL,
    palette_b TEXT NOT NULL,
    hex_a TEXT DEFAULT '',
    hex_b TEXT DEFAULT '',
    delta_e00 REAL DEFAULT 0,
    resolution TEXT DEFAULT 'kept-separate',
    PRIMARY KEY(brand, code, palette_a, palette_b)
);
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_colors_palette ON colors(palette_id);
CREATE INDEX IF NOT EXISTS idx_palettes_brand ON palettes(brand);
"""


class BeadPaletteDatabase:
    """ 色卡索引读写；同一色号来自不同来源时分行保存，不覆盖 """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # ---------- 写入 ---------- #
    def replace_all(self, palettes: list[dict], sources: list[dict], conflicts: list[dict], meta: dict):
        cursor = self.connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("DELETE FROM conflicts")
        cursor.execute("DELETE FROM colors")
        cursor.execute("DELETE FROM palettes")
        cursor.execute("DELETE FROM sources")
        cursor.execute("DELETE FROM meta")
        for source in sources:
            cursor.execute(
                "INSERT OR REPLACE INTO sources(id, name, url, license, trust, notes) VALUES(?,?,?,?,?,?)",
                (
                    source.get("id", ""), source.get("name", ""), source.get("url", ""),
                    source.get("license", ""), source.get("trust", "community"), source.get("notes", ""),
                ),
            )
        for palette in palettes:
            cursor.execute(
                """
                INSERT INTO palettes(id, brand, series, size, source_id, trust, expected_count,
                                     color_count, license, fetched_at, notes)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    palette["id"], palette["brand"], palette["series"], palette.get("size", ""),
                    palette.get("source_id", ""), palette.get("trust", "community"),
                    int(palette.get("expected_count", 0)), int(palette.get("color_count", 0)),
                    palette.get("license", ""), palette.get("fetched_at", ""), palette.get("notes", ""),
                ),
            )
            for color in palette.get("colors", []):
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO colors(palette_id, code, name, r, g, b, alpha, hex,
                        color_family, material, trust, source_url, source_quality, notes,
                        verified, contributor)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        palette["id"], color["code"], color.get("name", ""),
                        color["r"], color["g"], color["b"], color.get("alpha", 255),
                        color.get("hex", ""), color.get("color_family", ""),
                        color.get("material", "solid"), color.get("trust", "unknown"),
                        color.get("source_url", ""), color.get("source_quality", ""),
                        color.get("notes", ""), int(bool(color.get("verified", False))),
                        color.get("contributor", ""),
                    ),
                )
        for conflict in conflicts:
            cursor.execute(
                """
                INSERT OR REPLACE INTO conflicts(brand, code, palette_a, palette_b, hex_a, hex_b, delta_e00, resolution)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    conflict["brand"], conflict["code"], conflict["palette_a"], conflict["palette_b"],
                    conflict.get("hex_a", ""), conflict.get("hex_b", ""),
                    float(conflict.get("delta_e00", 0)), conflict.get("resolution", "kept-separate"),
                ),
            )
        for key, value in meta.items():
            cursor.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (str(key), str(value)))
        self.connection.commit()

    # ---------- 查询 ---------- #
    def color_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) AS n FROM colors").fetchone()["n"])

    def palette_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) AS n FROM palettes").fetchone()["n"])

    def palette_rows(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM palettes ORDER BY brand, series, size"
        ).fetchall()
        return [dict(row) for row in rows]

    def source_rows(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM sources ORDER BY id").fetchall()]

    def conflict_rows(self, brand: Optional[str] = None) -> list[dict]:
        if brand:
            rows = self.connection.execute(
                "SELECT * FROM conflicts WHERE brand=? ORDER BY code", (brand,)
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM conflicts ORDER BY brand, code").fetchall()
        return [dict(row) for row in rows]

    def meta_value(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def load_catalog(self) -> list[BeadColor]:
        """ 载入全部颜色；来源/可信度/材质随记录保留，便于 UI 标注 """
        rows = self.connection.execute(
            """
            SELECT c.*, p.brand, p.series, p.size AS palette_size, p.license, p.source_id,
                   p.trust AS palette_trust, p.fetched_at
            FROM colors c JOIN palettes p ON p.id = c.palette_id
            ORDER BY p.brand, p.series, c.code
            """
        ).fetchall()
        catalog = []
        for row in rows:
            catalog.append(
                BeadColor(
                    brand=row["brand"],
                    series=row["series"],
                    code=row["code"],
                    name=row["name"] or row["code"],
                    rgb=(int(row["r"]), int(row["g"]), int(row["b"])),
                    availability="unknown",
                    source=row["source_id"] or "palette-db",
                    revision=row["fetched_at"] or "",
                    product_line=row["palette_id"],
                    verified=bool(row["verified"]),
                    size=row["palette_size"] or "",
                    color_family=row["color_family"] or "",
                    material=row["material"] or "solid",
                    trust=row["trust"] or "unknown",
                    source_url=row["source_url"] or "",
                    license=row["license"] or "",
                    palette_id=row["palette_id"],
                )
            )
        return catalog

    def metadata(self) -> dict:
        """ 供 UI 展示：来源、许可、可信度与材质统计 """
        palettes = self.palette_rows()
        sources = self.source_rows()
        trust_rows = self.connection.execute(
            "SELECT trust, COUNT(*) AS n FROM colors GROUP BY trust"
        ).fetchall()
        material_rows = self.connection.execute(
            "SELECT material, COUNT(*) AS n FROM colors GROUP BY material"
        ).fetchall()
        return {
            "database": str(self.path),
            "updated_at": self.meta_value("updated_at"),
            "palettes": palettes,
            "sources": sources,
            "colors": self.color_count(),
            "trust_counts": {row["trust"]: int(row["n"]) for row in trust_rows},
            "material_counts": {row["material"]: int(row["n"]) for row in material_rows},
            "conflicts": len(self.conflict_rows()),
            "conflict_examples": self.conflict_rows()[:10],
        }
