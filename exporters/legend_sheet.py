##############################
# exporters/legend_sheet.py - 图例面板 PNG 导出
##############################

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter


@dataclass
class LegendSheetOptions:
    """ 图例 PNG 导出选项：主题、列数、标题与说明 """

    title: str = "Moge 拼豆图例"
    subtitle: str = ""
    theme: str = "dark"
    columns: int = 0
    width: int = 900
    scale: int = 2
    row_height: int = 56
    padding: int = 24
    gap: int = 12
    font_family: str = "Microsoft YaHei"


def _theme_colors(theme: str) -> dict:
    if theme == "light":
        return {
            "bg": QColor("#f4f6f9"),
            "card": QColor("#ffffff"),
            "border": QColor("#d5dbe5"),
            "text": QColor("#20232a"),
            "text_secondary": QColor("#5b6b80"),
            "text_muted": QColor("#8a94a3"),
            "accent": QColor("#2f6feb"),
            "footer": QColor("#7a879a"),
        }
    return {
        "bg": QColor("#20232a"),
        "card": QColor("#262a33"),
        "border": QColor("#3a3f4b"),
        "text": QColor("#e8edf5"),
        "text_secondary": QColor("#9fb2c8"),
        "text_muted": QColor("#7d8798"),
        "accent": QColor("#6d9bff"),
        "footer": QColor("#8a93a6"),
    }


def _auto_columns(count: int) -> int:
    if count <= 10:
        return 1
    if count <= 60:
        return 2
    return 3


def _draw_swatch(painter: QPainter, rect: QRect, row: dict, border: QColor):
    transparent = bool(row.get("transparent"))
    if transparent:
        half_w = rect.width() // 2
        half_h = rect.height() // 2
        painter.fillRect(rect, QColor("#cfcfcf"))
        painter.fillRect(QRect(rect.left(), rect.top(), half_w, half_h), QColor("#f2f2f2"))
        painter.fillRect(
            QRect(rect.left() + half_w, rect.top() + half_h, half_w, half_h),
            QColor("#f2f2f2"),
        )
    rgb = row.get("rgb")
    if rgb:
        painter.setOpacity(0.55 if transparent else 1.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*rgb))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)
        painter.setOpacity(1.0)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(border)
    painter.drawRoundedRect(rect, 3, 3)
    if row.get("special"):
        dot = QRect(rect.right() - 7, rect.top() + 2, 6, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ef6c00"))
        painter.drawEllipse(dot)


def render_legend_sheet(rows: list[dict], options: Optional[LegendSheetOptions] = None) -> QImage:
    """ 将当前图例数据渲染为独立图片，不依赖面板滚动位置与可视区域 """
    options = options or LegendSheetOptions()
    colors = _theme_colors(options.theme)
    columns = options.columns if options.columns > 0 else _auto_columns(len(rows))
    columns = max(1, min(int(columns), 4))
    scale = max(1, int(options.scale))
    width = max(420, int(options.width))
    padding = int(options.padding)
    gap = int(options.gap)
    row_height = int(options.row_height)
    row_gap = 4
    column_width = max(220, (width - padding * 2 - gap * (columns - 1)) // columns)
    lines = max(1, (len(rows) + columns - 1) // columns)
    header_height = 86 if options.subtitle else 58
    footer_height = 30
    height = padding * 2 + header_height + lines * row_height + footer_height

    image = QImage(width * scale, height * scale, QImage.Format_ARGB32)
    image.fill(colors["bg"])
    painter = QPainter(image)
    if not painter.isActive():
        raise OSError("无法启动图例绘制")
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(scale, scale)

    title_font = QFont(options.font_family, 16)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(colors["text"])
    painter.drawText(
        QRectF(padding, padding, width - padding * 2, 30),
        Qt.AlignLeft | Qt.AlignVCenter,
        options.title,
    )
    subtitle_font = QFont(options.font_family, 9)
    painter.setFont(subtitle_font)
    painter.setPen(colors["text_secondary"])
    if options.subtitle:
        subtitle = QFontMetrics(subtitle_font).elidedText(
            options.subtitle, Qt.ElideRight, width - padding * 2
        )
        painter.drawText(
            QRectF(padding, padding + 30, width - padding * 2, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            subtitle,
        )
    painter.setPen(colors["border"])
    painter.drawLine(
        int(padding),
        int(padding + header_height - 14),
        int(width - padding),
        int(padding + header_height - 14),
    )

    primary_font = QFont(options.font_family, 10)
    secondary_font = QFont(options.font_family, 8)
    count_font = QFont(options.font_family, 9)
    count_font.setBold(True)
    fm_primary = QFontMetrics(primary_font)
    fm_secondary = QFontMetrics(secondary_font)
    fm_count = QFontMetrics(count_font)

    grid_top = padding + header_height
    for index, row in enumerate(rows):
        column = index % columns
        line = index // columns
        x = padding + column * (column_width + gap)
        y = grid_top + line * row_height
        card = QRect(x, y + 2, column_width, row_height - row_gap)
        painter.setPen(colors["border"])
        painter.setBrush(colors["card"])
        painter.drawRoundedRect(card, 5, 5)

        swatch_size = 26
        swatch = QRect(
            card.left() + 10,
            card.top() + (card.height() - swatch_size) // 2,
            swatch_size,
            swatch_size,
        )
        _draw_swatch(painter, swatch, row, colors["border"])

        used = bool(row.get("used", True))
        text_left = swatch.right() + 10
        count_text = str(row.get("count_text") or "")
        count_width = fm_count.horizontalAdvance(count_text) if count_text else 0
        count_left = card.right() - 10 - count_width
        text_right = count_left - 8 if count_width else card.right() - 10
        text_width = max(12, text_right - text_left)

        primary = fm_primary.elidedText(str(row.get("primary") or ""), Qt.ElideRight, text_width)
        secondary_raw = str(row.get("secondary") or "")
        secondary = fm_secondary.elidedText(secondary_raw, Qt.ElideRight, text_width) if secondary_raw else ""
        if secondary:
            content_height = fm_primary.height() + 3 + fm_secondary.height()
            top = card.top() + (card.height() - content_height) // 2
            primary_baseline = top + fm_primary.ascent()
            secondary_baseline = top + fm_primary.height() + 3 + fm_secondary.ascent()
        else:
            top = card.top() + (card.height() - fm_primary.height()) // 2
            primary_baseline = top + fm_primary.ascent()
            secondary_baseline = 0

        painter.setFont(primary_font)
        painter.setPen(colors["text"] if used else colors["text_muted"])
        painter.drawText(text_left, primary_baseline, primary)
        if secondary:
            painter.setFont(secondary_font)
            painter.setPen(colors["text_secondary"] if used else colors["text_muted"])
            painter.drawText(text_left, secondary_baseline, secondary)
        if count_text and count_width:
            painter.setFont(count_font)
            painter.setPen(colors["text"] if used else colors["text_muted"])
            painter.drawText(
                QRect(count_left, top, count_width, fm_primary.height()),
                Qt.AlignRight | Qt.AlignVCenter,
                count_text,
            )

    painter.setFont(QFont(options.font_family, 8))
    painter.setPen(colors["footer"])
    painter.drawText(
        QRectF(padding, height - padding - 14, width - padding * 2, 14),
        Qt.AlignRight | Qt.AlignVCenter,
        "Moge 图例导出 · 空白格不计入总颗数 · 色值为屏幕近似",
    )
    painter.end()
    return image


def export_legend_png(rows: list[dict], path: str, options: Optional[LegendSheetOptions] = None) -> str:
    """ 导出当前图例为高分辨率 PNG """
    target = Path(path)
    if target.suffix.lower() != ".png":
        target = target.with_suffix(".png")
    image = render_legend_sheet(rows, options)
    if not image.save(str(target), "PNG"):
        raise OSError(f"PNG 保存失败：{target}")
    return str(target)
