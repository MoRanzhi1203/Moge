##############################
# exporters/blueprint_pdf.py - 分页图纸 PDF 导出
##############################

from pathlib import Path
from typing import Optional

import numpy as np
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPagedPaintDevice, QPainter, QPdfWriter, QPen

from Moge.core.materials import board_partitions
from Moge.core.models import RenderResult


def _text_color(rgb: tuple[int, int, int]) -> QColor:
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return QColor("#111111") if luminance > 140 else QColor("#ffffff")


def _entry_label(entry) -> str:
    meta = entry.meta or {}
    code = meta.get("code") or meta.get("block_id") or ""
    return f"{code} {entry.name}".strip()


def export_blueprint_pdf(
    result: RenderResult,
    path: str,
    title: str = "Moge 图纸",
    board_width: int = 29,
    board_height: int = 29,
) -> str:
    """ 按底板/区域分页导出 PDF，包含坐标、色块、色号与图例 """
    target = Path(path)
    if target.suffix.lower() != ".pdf":
        target = target.with_suffix(".pdf")

    spec = result.grid.spec
    boards = board_partitions(spec.width, spec.height, board_width, board_height)
    labels = result.grid.labels
    entries = result.grid.entries

    writer = QPdfWriter(str(target))
    writer.setPageSize(QPagedPaintDevice.A4)
    writer.setResolution(150)
    writer.setTitle(title)
    painter = QPainter(writer)
    if not painter.isActive():
        raise OSError("无法启动 PDF 绘制")

    try:
        page_width = float(writer.width())
        page_height = float(writer.height())
        margin = 50.0
        header = 70.0
        legend_height = 120.0

        for board in boards:
            if board["index"] > 0:
                writer.newPage()

            area_width = board["x1"] - board["x0"]
            area_height = board["y1"] - board["y0"]
            grid_width = page_width - 2 * margin - 24
            grid_height = page_height - 2 * margin - header - legend_height
            cell = max(2.0, min(grid_width / area_width, grid_height / area_height))

            painter.setPen(QColor("#111111"))
            title_font = QFont("Arial", 13)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.drawText(
                QRectF(margin, margin, page_width - 2 * margin, 28),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{title}  ·  区域 {board['index'] + 1}/{len(boards)}  ·  行 {board['row'] + 1} 列 {board['col'] + 1}",
            )
            painter.setFont(QFont("Arial", 8))
            painter.drawText(
                QRectF(margin, margin + 30, page_width - 2 * margin, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"网格 {spec.width}x{spec.height}  ·  单元格 {area_width}x{area_height}  ·  模式 {result.mode}",
            )

            origin_x = margin + 24
            origin_y = margin + header
            painter.setPen(QPen(QColor("#555555"), 0.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(origin_x, origin_y, area_width * cell, area_height * cell))

            coordinate_font = QFont("Arial", 6 if cell < 16 else 7)
            painter.setFont(coordinate_font)

            for local_row in range(area_height):
                for local_col in range(area_width):
                    label = int(labels[board["y0"] + local_row, board["x0"] + local_col])
                    rect = QRectF(
                        origin_x + local_col * cell,
                        origin_y + local_row * cell,
                        cell,
                        cell,
                    )
                    if label >= 0:
                        rgb = entries[label].rgb
                        painter.fillRect(rect, QColor(*rgb))
                        if cell >= 13:
                            meta = entries[label].meta or {}
                            text = meta.get("code") or str(label + 1)
                            painter.setPen(_text_color(rgb))
                            painter.setFont(QFont("Arial", max(4, int(cell * 0.3))))
                            painter.drawText(rect, Qt.AlignCenter, str(text)[:5])
                            painter.setFont(coordinate_font)
                    painter.setPen(QPen(QColor("#777777"), 0.4))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(rect)

            # 坐标轴
            painter.setPen(QColor("#333333"))
            painter.setFont(coordinate_font)
            for local_col in range(area_width):
                painter.drawText(
                    QRectF(origin_x + local_col * cell, origin_y - 14, cell, 12),
                    Qt.AlignCenter,
                    str(board["x0"] + local_col + 1),
                )
            for local_row in range(area_height):
                painter.drawText(
                    QRectF(margin, origin_y + local_row * cell, 22, cell),
                    Qt.AlignRight | Qt.AlignVCenter,
                    str(board["y0"] + local_row + 1),
                )

            # 图例
            painter.setPen(QColor("#111111"))
            painter.setFont(QFont("Arial", 8))
            legend_top = origin_y + area_height * cell + 16
            painter.drawText(QRectF(margin, legend_top, page_width - 2 * margin, 16), Qt.AlignLeft, "图例 / 用料")
            painter.setFont(QFont("Arial", 7))

            section = labels[board["y0"]:board["y1"], board["x0"]:board["x1"]].reshape(-1)
            valid = section[section >= 0]
            values, counts = np.unique(valid, return_counts=True) if valid.size else (np.array([]), np.array([]))
            line_height = 14
            column_width = (page_width - 2 * margin) / 3.0
            for index, (value, count) in enumerate(zip(values, counts)):
                entry = entries[int(value)]
                col = index % 3
                row = index // 3
                x = margin + col * column_width
                y = legend_top + 20 + row * line_height
                painter.fillRect(QRectF(x, y + 2, 10, 10), QColor(*entry.rgb))
                painter.setPen(QColor("#111111"))
                painter.drawText(
                    QRectF(x + 14, y, column_width - 16, 12),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    f"{_entry_label(entry)} ×{int(count)}",
                )

            painter.setFont(QFont("Arial", 7))
            painter.setPen(QColor("#666666"))
            painter.drawText(
                QRectF(margin, page_height - margin + 6, page_width - 2 * margin, 14),
                Qt.AlignRight,
                "Moge 图纸 · 色值为屏幕近似，请以实际材料为准",
            )
    finally:
        painter.end()

    return str(target)


def board_count(result: RenderResult, board_width: int = 29, board_height: int = 29) -> int:
    spec = result.grid.spec
    return len(board_partitions(spec.width, spec.height, board_width, board_height))


def used_codes(result: RenderResult, limit: Optional[int] = None) -> list[str]:
    counts = result.stats.get("counts", {})
    entries = sorted(result.grid.entries, key=lambda entry: -int(counts.get(entry.id, 0)))
    labels = [_entry_label(entry) for entry in entries if int(counts.get(entry.id, 0)) > 0]
    return labels[:limit] if limit else labels
