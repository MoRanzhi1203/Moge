##############################
# exporters/bead_sheet.py - 拼豆施工图渲染与 PNG/PDF 导出
##############################

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPagedPaintDevice, QPainter, QPdfWriter, QPen

from Moge.core.beads.pattern import (
    bead_summary,
    board_regions,
    build_symbols,
    legend_rows,
)


@dataclass
class BeadSheetOptions:
    """ 施工图导出选项；同一套参数供 PNG 与后续 PDF 分页复用 """

    mode: str = "blueprint"  # preview / blueprint / mono
    cell_size: int = 20
    margin: int = 28
    title: str = "Moge 拼豆施工图"
    show_axes: bool = True
    show_coordinate_numbers: bool = True
    coordinate_step: int = 1
    show_guides_5: bool = True
    show_guides_10: bool = True
    show_board_partitions: bool = False
    board_width: int = 29
    board_height: int = 29
    show_codes: bool = True
    show_symbols: bool = False
    show_legend: bool = True
    transparent_background: bool = False
    max_pixels: int = 20000
    x_offset: int = 0
    y_offset: int = 0
    region_label: str = ""


def _text_color(rgb) -> QColor:
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return QColor("#111111") if luminance > 150 else QColor("#ffffff")


def _entry_code(entry) -> str:
    return str((entry.meta or {}).get("code") or "")


def _effective_step(step: int, cell: float) -> int:
    step = max(1, int(step))
    if step == 1:
        if cell < 7:
            return 10
        if cell < 12:
            return 5
    return step


def _cell_marker(entry, cell: float, mode: str, symbol: str, show_codes: bool, show_symbols: bool) -> str:
    if mode == "preview":
        return ""
    if mode == "mono":
        return symbol if show_symbols and cell >= 6 else ""
    if show_codes:
        code = _entry_code(entry)
        if code and cell >= 9:
            return code
    if show_symbols and symbol and cell >= 7:
        return symbol
    return ""


def _draw_empty_cell(painter: QPainter, rect: QRectF, mode: str):
    if mode == "mono":
        painter.fillRect(rect, QColor("#ffffff"))
        return
    painter.fillRect(rect, QColor("#f5f5f5"))


def render_bead_sheet(grid, options: Optional[BeadSheetOptions] = None) -> QImage:
    """ 将逻辑网格渲染为施工图/成品图/黑白符号图，返回 QImage """
    options = options or BeadSheetOptions()
    mode = options.mode if options.mode in ("preview", "blueprint", "mono") else "blueprint"
    labels = grid.labels
    entries = grid.entries
    height, width = labels.shape
    cell = max(4, int(options.cell_size))
    symbols = dict(grid.symbols) or build_symbols(entries)

    preview = mode == "preview"
    show_axes = bool(options.show_axes and not preview)
    ruler = 26 if show_axes else 0
    title_h = 0 if preview else 46

    legend = []
    if options.show_legend and not preview:
        legend = legend_rows(labels, entries, symbols, include_unused=False)
        legend.sort(key=lambda row: (-row["count"], row["code"], row["name"]))
    legend_columns = 4
    legend_row_h = 22
    legend_h = 0
    if legend:
        legend_h = 40 + ((len(legend) + legend_columns - 1) // legend_columns) * legend_row_h

    total_w = options.margin * 2 + ruler + width * cell
    total_h = options.margin * 2 + title_h + ruler + height * cell + legend_h
    if total_w > options.max_pixels or total_h > options.max_pixels:
        raise ValueError(
            f"导出尺寸 {total_w}x{total_h} 超过上限 {options.max_pixels}，请降低单元格像素或分区导出"
        )

    image = QImage(total_w, total_h, QImage.Format_ARGB32)
    image.fill(Qt.transparent if options.transparent_background else QColor("#ffffff"))

    painter = QPainter(image)
    if not painter.isActive():
        raise OSError("无法启动施工图绘制")
    painter.setRenderHint(QPainter.Antialiasing, True)

    origin_x = options.margin + ruler
    origin_y = options.margin + title_h + ruler
    grid_rect = QRectF(origin_x, origin_y, width * cell, height * cell)

    if not preview:
        painter.setPen(QColor("#111111"))
        title_font = QFont("Microsoft YaHei", 14)
        title_font.setBold(True)
        painter.setFont(title_font)
        summary = bead_summary(labels, entries)
        brand = str((entries[0].meta or {}).get("brand") if entries else "")
        series = str((entries[0].meta or {}).get("series") if entries else "")
        title = options.title
        if options.region_label:
            title = f"{title}  ·  分区 {options.region_label}"
        subtitle = (
            f"{brand} {series}  ·  {width}×{height}  ·  总珠子 {summary['total_beads']}"
            f"  ·  空白格 {summary['empty_cells']}  ·  色号 {summary['used_colors']}"
        )
        painter.drawText(
            QRectF(options.margin, options.margin, total_w - options.margin * 2, 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )
        painter.setFont(QFont("Microsoft YaHei", 9))
        painter.setPen(QColor("#555555"))
        painter.drawText(
            QRectF(options.margin, options.margin + 24, total_w - options.margin * 2, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            subtitle,
        )

    # 单元格底色与格内标记
    painter.setRenderHint(QPainter.Antialiasing, False)
    for row in range(height):
        for col in range(width):
            value = int(labels[row, col])
            rect = QRectF(origin_x + col * cell, origin_y + row * cell, cell, cell)
            if value < 0 or value >= len(entries):
                _draw_empty_cell(painter, rect, mode)
                continue
            entry = entries[value]
            if mode == "mono":
                painter.fillRect(rect, QColor("#ffffff"))
            else:
                painter.fillRect(rect, QColor(*entry.rgb))
            marker = _cell_marker(
                entry,
                cell,
                mode,
                symbols.get(entry.id, ""),
                options.show_codes,
                options.show_symbols,
            )
            if marker:
                font_size = max(5, min(11, int(cell * 0.34)))
                painter.setFont(QFont("Arial", font_size, QFont.Bold if mode == "mono" else QFont.Normal))
                painter.setPen(QColor("#111111") if mode == "mono" else _text_color(entry.rgb))
                painter.drawText(rect, Qt.AlignCenter, marker)

    # 网格线与 5/10 格辅助线
    if not preview:
        for step, color, line_width in (
            (1, QColor(190, 190, 190, 120), 1),
            (5, QColor(120, 120, 120, 180), 1),
            (10, QColor(40, 40, 40, 220), 2),
        ):
            if step == 5 and not options.show_guides_5:
                continue
            if step == 10 and not options.show_guides_10:
                continue
            painter.setPen(QPen(color, line_width))
            for col in range(step, width, step):
                if step == 10 and col % 10 != 0:
                    continue
                if step == 5 and col % 10 == 0 and options.show_guides_10:
                    continue
                x = origin_x + col * cell
                painter.drawLine(QPointF(x, origin_y), QPointF(x, origin_y + height * cell))
            for row in range(step, height, step):
                if step == 10 and row % 10 != 0:
                    continue
                if step == 5 and row % 10 == 0 and options.show_guides_10:
                    continue
                y = origin_y + row * cell
                painter.drawLine(QPointF(origin_x, y), QPointF(origin_x + width * cell, y))
        painter.setPen(QPen(QColor("#333333"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(grid_rect)

    # 底板分区
    if options.show_board_partitions and not preview:
        painter.setPen(QPen(QColor("#ef6c00"), 2))
        painter.setBrush(Qt.NoBrush)
        for region in board_regions(width, height, options.board_width, options.board_height):
            rect = QRectF(
                origin_x + region["x0"] * cell,
                origin_y + region["y0"] * cell,
                region["width"] * cell,
                region["height"] * cell,
            )
            painter.drawRect(rect)
            tag_font = QFont("Arial", 9)
            tag_font.setBold(True)
            painter.setFont(tag_font)
            tag_rect = QRectF(rect.left() + 3, rect.top() + 3, 34, 16)
            painter.fillRect(tag_rect, QColor("#ef6c00"))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(tag_rect, Qt.AlignCenter, region["label"])
            painter.setPen(QPen(QColor("#ef6c00"), 2))

    # 坐标尺
    if show_axes:
        strip = QColor("#f3f3f3")
        painter.fillRect(QRectF(origin_x, origin_y - ruler, width * cell, ruler), strip)
        painter.fillRect(QRectF(origin_x - ruler, origin_y, ruler, height * cell), strip)
        painter.setPen(QPen(QColor("#999999"), 1))
        painter.drawLine(QPointF(origin_x, origin_y), QPointF(origin_x + width * cell, origin_y))
        painter.drawLine(QPointF(origin_x, origin_y), QPointF(origin_x, origin_y + height * cell))
        step = _effective_step(options.coordinate_step, cell)
        axis_font = QFont("Arial", 7)
        painter.setFont(axis_font)
        painter.setPen(QColor("#333333"))
        if options.show_coordinate_numbers:
            for col in range(0, width, step):
                x = origin_x + (col + 0.5) * cell
                painter.drawLine(QPointF(x, origin_y - 4), QPointF(x, origin_y))
                painter.drawText(
                    QRectF(x - cell, origin_y - ruler, cell * 2, ruler - 4),
                    Qt.AlignCenter,
                    str(options.x_offset + col + 1),
                )
            for row in range(0, height, step):
                y = origin_y + (row + 0.5) * cell
                painter.drawLine(QPointF(origin_x - 4, y), QPointF(origin_x, y))
                painter.drawText(
                    QRectF(origin_x - ruler, y - 7, ruler - 6, 14),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(options.y_offset + row + 1),
                )
        painter.setPen(QPen(QColor("#333333"), 1))
        painter.drawRect(grid_rect)

    # 图例
    if legend:
        legend_top = origin_y + height * cell + 18
        painter.setPen(QColor("#111111"))
        legend_font = QFont("Microsoft YaHei", 9)
        legend_font.setBold(True)
        painter.setFont(legend_font)
        painter.drawText(
            QRectF(options.margin, legend_top, total_w - options.margin * 2, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"图例 / 用料（{len(legend)} 色）",
        )
        column_width = (total_w - options.margin * 2) / legend_columns
        row_font = QFont("Microsoft YaHei", 7)
        painter.setFont(row_font)
        for index, row in enumerate(legend):
            column = index % legend_columns
            line = index // legend_columns
            x = options.margin + column * column_width
            y = legend_top + 26 + line * legend_row_h
            painter.fillRect(QRectF(x, y + 3, 14, 14), QColor(*row["rgb"]))
            painter.setPen(QPen(QColor("#666666"), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x, y + 3, 14, 14))
            painter.setPen(QColor("#111111"))
            code = row["code"] or row["name"]
            label = f"{code} {row['name']} ×{row['count']}"
            if mode == "mono" and row["symbol"]:
                label = f"[{row['symbol']}] {label}"
            painter.drawText(
                QRectF(x + 18, y, column_width - 20, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )

    if not preview:
        painter.setPen(QColor("#777777"))
        painter.setFont(QFont("Microsoft YaHei", 7))
        painter.drawText(
            QRectF(options.margin, total_h - options.margin - 12, total_w - options.margin * 2, 12),
            Qt.AlignRight | Qt.AlignVCenter,
            "Moge 施工图 · 色值为屏幕近似 · 空白格不计入珠子数量",
        )

    painter.end()
    return image


def export_bead_png(result, path: str, options: Optional[BeadSheetOptions] = None) -> str:
    """ 高分辨率拼豆图纸 PNG 导出，支持成品预览/施工图/黑白符号三种模式 """
    target = Path(path)
    if target.suffix.lower() != ".png":
        target = target.with_suffix(".png")
    image = render_bead_sheet(result.grid, options)
    if not image.save(str(target), "PNG"):
        raise OSError(f"PNG 保存失败：{target}")
    return str(target)


def export_partition_pngs(result, directory: str, options: Optional[BeadSheetOptions] = None) -> list[str]:
    """ 按当前分区规格逐区导出 PNG，坐标标签保留全局行列号 """
    options = options or BeadSheetOptions()
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    width = int(result.grid.spec.width)
    height = int(result.grid.spec.height)
    symbols = dict(result.grid.symbols) or build_symbols(result.grid.entries)
    paths = []
    for region in board_regions(width, height, options.board_width, options.board_height):
        labels = result.grid.labels[region["y0"]:region["y1"], region["x0"]:region["x1"]]
        grid = SimpleNamespace(labels=labels, entries=result.grid.entries, symbols=symbols)
        region_options = replace(
            options,
            x_offset=region["x0"],
            y_offset=region["y0"],
            region_label=region["label"],
            show_board_partitions=False,
        )
        image = render_bead_sheet(grid, region_options)
        path = target_dir / f"moge-part-{region['label']}.png"
        if not image.save(str(path), "PNG"):
            raise OSError(f"分区 PNG 保存失败：{path}")
        paths.append(str(path))
    return paths


def export_bead_pdf(result, path: str, options: Optional[BeadSheetOptions] = None) -> str:
    """ 单页 PDF 导出（复用同一套渲染参数，后续可扩展为按底板分页） """
    target = Path(path)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")
    image = render_bead_sheet(result.grid, options)

    writer = QPdfWriter(str(target))
    writer.setPageSize(QPagedPaintDevice.A4)
    writer.setResolution(300)
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError("无法启动 PDF 绘制")
    try:
        page = QRectF(0, 0, writer.width(), writer.height())
        scaled = image.scaled(
            int(page.width()),
            int(page.height()),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        painter.drawImage(
            QPointF((page.width() - scaled.width()) / 2.0, (page.height() - scaled.height()) / 2.0),
            scaled,
        )
    finally:
        painter.end()
    return str(target)
