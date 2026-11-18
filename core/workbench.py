##############################
# core/workbench.py - 三模式共享工作台适配层
##############################

from typing import Optional

from Moge.core.beads.pattern import abbrev_for, symbol_for_index
from Moge.core.materials import MC_CATEGORIES, filter_beads
from Moge.core.modes import beads as beads_mode
from Moge.core.modes import minecraft as minecraft_mode
from Moge.core.modes import pixel as pixel_mode

MATERIAL_LABELS = {
    "solid": "实色",
    "transparent": "透明",
    "glow": "夜光",
    "fluorescent": "荧光",
    "pearl": "珠光",
    "metallic": "金属",
    "special": "特殊",
    "unknown": "未知",
}

TRUST_LABELS = {
    "official": "官方",
    "community": "社区",
    "sampled": "采样",
    "unknown": "未知",
}


def _hex(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*tuple(int(channel) for channel in rgb[:3]))


def _count_text(count: int, total: int, show_counts: bool) -> str:
    if not show_counts:
        return ""
    if count <= 0:
        return "未使用"
    if total:
        return f"×{count} · {count / total * 100:.1f}%"
    return f"×{count}"


def _ratio(count: int, total: int) -> float:
    return (count / total) if total else 0.0


def _short_entry_name(entry) -> str:
    """ 去除色卡 display_name 中重复的品牌/系列/色号前缀 """
    meta = entry.meta or {}
    name = str(entry.name or "").strip()
    brand = str(meta.get("brand") or "").strip()
    series = str(meta.get("series") or "").strip()
    code = str(meta.get("code") or "").strip()
    for prefix in (f"{brand} {series} {code}".strip(), f"{brand} {series}".strip(), code):
        if prefix and name.startswith(prefix):
            trimmed = name[len(prefix):].strip()
            if trimmed:
                return trimmed
    return name


def _brand_series_text(meta: dict) -> str:
    brand = str(meta.get("brand") or "").strip()
    series = str(meta.get("series") or "").strip()
    if brand and series and brand.casefold() in series.casefold():
        return series
    return " · ".join(part for part in (brand, series) if part)


def prepare_entries(mode: str, entries: list, symbols: Optional[dict] = None) -> dict:
    """ 为所有模式补齐统一格内标记字段：code / cell_code / abbrev / symbol """
    symbols = dict(symbols or {})
    for index, entry in enumerate(entries):
        meta = entry.meta
        symbol = symbols.get(entry.id) or str(meta.get("symbol") or "") or symbol_for_index(index)
        symbols[entry.id] = symbol
        meta.setdefault("symbol", symbol)
        if mode == "pixel":
            code = f"{index + 1:03d}"
            meta.setdefault("code", code)
            meta.setdefault("cell_code", code)
            meta.setdefault("abbrev", f"{index + 1:02d}")
            meta.setdefault("brand", "Pixel")
            meta.setdefault("series", "作品")
        elif mode == "minecraft":
            meta.setdefault("code", entry.id)
            meta.setdefault("cell_code", f"{index + 1:02d}")
            meta.setdefault("abbrev", str(meta.get("code") or entry.id).split(":")[-1][:4])
        else:
            meta.setdefault("code", str(meta.get("code") or ""))
            meta.setdefault("cell_code", str(meta.get("code") or ""))
            meta.setdefault("abbrev", abbrev_for(entry))
        meta["symbol"] = symbol
    return symbols


def prepare_result(result) -> dict:
    adapter = get_adapter(result.mode)
    result.grid.symbols = adapter.prepare_entries(result.grid.entries, result.grid.symbols)
    return result.grid.symbols


def legend_payload(mode: str, entry, index: int, count: int, total: int,
                   symbols: dict, context: dict) -> dict:
    meta = entry.meta or {}
    show_counts = bool(context.get("show_counts", True))
    locked_counts = context.get("locked_counts") or {}
    symbol = symbols.get(entry.id) or str(meta.get("symbol") or "")
    used = count > 0 or not show_counts
    count_text = _count_text(count, total, show_counts)
    payload = {
        "primary": entry.name,
        "secondary": "",
        "count_text": count_text,
        "used": used,
        "rgb": tuple(entry.rgb),
        "transparent": False,
        "special": False,
        "thumbnail_path": "",
        "mode": mode,
        "entry_id": entry.id,
        "index": index,
        "count": count,
        "ratio": _ratio(count, total),
    }

    if mode == "pixel":
        locked = int(locked_counts.get(index, 0))
        payload.update(
            {
                "primary": f"#{index + 1:03d} {entry.name}",
                "secondary": (
                    f"{_hex(entry.rgb)} · RGB({entry.rgb[0]}, {entry.rgb[1]}, {entry.rgb[2]})"
                    f" · 符号 {symbol}" + (f" · 锁定 {locked}" if locked else "")
                ),
                "special": False,
                "transparent": False,
            }
        )
        return payload

    if mode == "minecraft":
        version = str(context.get("version") or meta.get("version") or "")
        edition = str(context.get("edition") or meta.get("edition") or context.get("edition") or "")
        category = MC_CATEGORIES.get(str(meta.get("category") or ""), str(meta.get("category") or "-"))
        face = str(meta.get("visible_face") or "all")
        state = str(meta.get("block_state") or "-")
        parts = [entry.id, f"{edition} {version}".strip(), category, f"面 {face}", f"状态 {state}"]
        if symbol:
            parts.append(f"符号 {symbol}")
        payload.update(
            {
                "primary": entry.name,
                "secondary": " · ".join(part for part in parts if part),
                "transparent": bool(meta.get("transparent")),
                "special": bool(meta.get("transparent") or meta.get("orientation") not in (None, "", "none")),
                "thumbnail_path": str(meta.get("texture_path") or ""),
            }
        )
        if not show_counts:
            payload["secondary"] = " · ".join(
                part for part in (entry.id, f"{edition} {version}".strip(), category, f"符号 {symbol}") if part
            )
        return payload

    material = str(meta.get("material") or "solid")
    parts = [_brand_series_text(meta)]
    if material and material != "solid":
        parts.append(MATERIAL_LABELS.get(material, material))
    if symbol:
        parts.append(f"符号 {symbol}")
    locked = int(locked_counts.get(index, 0))
    if locked:
        parts.append(f"锁定 {locked}")
    short_name = _short_entry_name(entry)
    code = str(meta.get("code") or "").strip()
    primary = code if short_name == code else f"{code} {short_name}".strip()
    payload.update(
        {
            "primary": primary,
            "secondary": " · ".join(part for part in parts if part),
            "transparent": material == "transparent",
            "special": material not in ("", "solid", "unknown"),
            "thumbnail_path": "",
        }
    )
    return payload


def legend_tooltip(mode: str, entry, payload: dict, count: int, total: int) -> str:
    meta = entry.meta or {}
    ratio = _ratio(count, total)
    lines = [str(payload.get("primary") or entry.name)]
    if payload.get("secondary"):
        lines.append(str(payload["secondary"]))
    lines.append(entry.id)
    if payload.get("count_text"):
        lines.append(f"用量 {count}（{ratio * 100:.1f}%）")
    else:
        lines.append("示例调色板（未处理）")
    if mode == "pixel":
        lines.append(f"HEX {_hex(entry.rgb)} · RGB {entry.rgb}")
    elif mode == "minecraft":
        lines.append(f"版本 {meta.get('edition') or '-'} {meta.get('version') or '-'}")
        lines.append(f"贴图 {meta.get('texture_path') or '内置近似色'}")
    else:
        lines.append(f"材质 {MATERIAL_LABELS.get(str(meta.get('material') or 'solid'), meta.get('material'))}")
        lines.append(f"可信度 {TRUST_LABELS.get(str(meta.get('trust') or 'unknown'), meta.get('trust'))}")
        lines.append(f"来源 {meta.get('license') or '-'} · {entry.source}")
    return "\n".join(str(line) for line in lines if line)


def details_html(mode: str, entry, count: int, total: int, context: dict) -> str:
    meta = entry.meta or {}
    ratio = _ratio(count, total)
    lines = [
        f"<h3>{entry.name}</h3>",
        f"<p><b>色块</b>：<span style='background:{_hex(entry.rgb)};'>&nbsp;&nbsp;&nbsp;&nbsp;</span> "
        f"{_hex(entry.rgb)}<br><b>用量</b>：{count}（{ratio * 100:.1f}%）</p>",
    ]
    if mode == "pixel":
        locked = int((context.get("locked_counts") or {}).get(context.get("index", -1), 0))
        lines.append(
            f"<p><b>调色板编号</b>：#{int(context.get('index', 0)) + 1:03d}<br>"
            f"<b>RGB</b>：{entry.rgb}<br><b>HEX</b>：{_hex(entry.rgb)}<br>"
            f"<b>锁定像素</b>：{locked}<br><b>来源</b>：{entry.source}</p>"
        )
    elif mode == "minecraft":
        lines.append(
            f"<p><b>方块 ID</b>：{entry.id}<br>"
            f"<b>版本</b>：{meta.get('edition') or context.get('edition') or '-'} "
            f"{meta.get('version') or context.get('version') or '-'}<br>"
            f"<b>类别</b>：{MC_CATEGORIES.get(str(meta.get('category') or ''), meta.get('category') or '-')}<br>"
            f"<b>状态</b>：{meta.get('block_state') or '-'}<br>"
            f"<b>可见面</b>：{meta.get('visible_face') or '-'}<br>"
            f"<b>几何</b>：{meta.get('geometry') or '-'}<br>"
            f"<b>贴图</b>：{meta.get('texture') or 'approximate'}"
            f"（{meta.get('texture_path') or '未加载'}）<br>"
            f"<b>来源</b>：{entry.source}</p>"
        )
    else:
        lines.append(
            f"<p><b>品牌/系列</b>：{meta.get('brand')} / {meta.get('series')}<br>"
            f"<b>色号</b>：{meta.get('code')}<br><b>符号</b>：{meta.get('symbol') or '-'}<br>"
            f"<b>尺寸</b>：{meta.get('size') or '-'}<br>"
            f"<b>材质</b>：{MATERIAL_LABELS.get(str(meta.get('material') or 'solid'), meta.get('material'))}<br>"
            f"<b>可信度</b>：{TRUST_LABELS.get(str(meta.get('trust') or 'unknown'), meta.get('trust'))}<br>"
            f"<b>许可/来源</b>：{meta.get('license') or '-'} · {entry.source}</p>"
        )
    return "".join(lines)


class ModeAdapter:
    """ 模式适配器：统一向 UI 提供图例、详情与候选调色板数据 """

    mode = ""

    def prepare_entries(self, entries: list, symbols: Optional[dict] = None) -> dict:
        return prepare_entries(self.mode, entries, symbols)

    def legend_payload(self, entry, index: int, count: int, total: int,
                       symbols: dict, context: dict) -> dict:
        return legend_payload(self.mode, entry, index, count, total, symbols, context)

    def tooltip(self, entry, payload: dict, count: int, total: int) -> str:
        return legend_tooltip(self.mode, entry, payload, count, total)

    def details(self, entry, count: int, total: int, context: dict) -> str:
        return details_html(self.mode, entry, count, total, context)

    def browse_entries(self, context: dict) -> list:
        return []


class PixelAdapter(ModeAdapter):
    mode = "pixel"

    def browse_entries(self, context: dict) -> list:
        entries = pixel_mode.reference_entries()
        self.prepare_entries(entries)
        return entries


class MinecraftAdapter(ModeAdapter):
    mode = "minecraft"

    def browse_entries(self, context: dict) -> list:
        settings = context.get("settings") or {}
        try:
            blocks = minecraft_mode.candidate_blocks(settings)
        except Exception:
            return []
        edition = str(settings.get("edition", "java"))
        version = str(settings.get("version", "1.20.1"))
        entries = minecraft_mode.block_entries(
            blocks, version, edition, settings.get("texture_overrides") or {}
        )
        self.prepare_entries(entries)
        return entries


class BeadAdapter(ModeAdapter):
    mode = "beads"

    def browse_entries(self, context: dict) -> list:
        catalog = context.get("catalog") or []
        if not catalog:
            return []
        items = filter_beads(
            catalog,
            brand=str(context.get("brand") or ""),
            series=str(context.get("series") or ""),
            disabled_ids=context.get("disabled_ids") or None,
            size=context.get("size_filter") or None,
            color_family=context.get("family_filter") or None,
            material=context.get("material_filter") or None,
        )
        from Moge.core.models import PaletteEntry

        entries = [
            PaletteEntry(
                id=item.id,
                name=item.display_name,
                rgb=item.rgb,
                source=item.source,
                meta={
                    "brand": item.brand,
                    "series": item.series,
                    "code": item.code,
                    "size": item.size,
                    "color_family": item.color_family,
                    "material": item.material,
                    "trust": item.trust,
                    "source_url": item.source_url,
                    "license": item.license,
                },
            )
            for item in items
        ]
        self.prepare_entries(entries)
        return entries


_ADAPTERS = {
    "pixel": PixelAdapter(),
    "minecraft": MinecraftAdapter(),
    "beads": BeadAdapter(),
}


def get_adapter(mode: str) -> ModeAdapter:
    return _ADAPTERS.get(mode, _ADAPTERS["pixel"])


def mode_label(mode: str) -> str:
    return {
        "pixel": pixel_mode.MODE_LABEL,
        "minecraft": minecraft_mode.MODE_LABEL,
        "beads": beads_mode.MODE_LABEL,
    }.get(mode, mode)
