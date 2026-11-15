##############################
# ui/bead_info_dialog.py - 拼豆色卡来源与许可详情
##############################

from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from Moge.core.beads.catalog import load_catalog_with_meta


class BeadPaletteInfoDialog(QDialog):
    """ 集中展示色卡来源、许可、可信度与系列清单 """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("拼豆色卡详情")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        view.setHtml(self._build_html())

    @staticmethod
    def _build_html() -> str:
        catalog, meta = load_catalog_with_meta()
        if not meta:
            return "<h3>拼豆色卡</h3><p>当前使用内置近似色卡，没有 SQLite 数据源信息。</p>"
        sources = "".join(
            f"<li>{source.get('name')} · {source.get('license')} · "
            f"<a href='{source.get('url')}'>{source.get('url')}</a><br>"
            f"<i>{source.get('notes') or ''}</i></li>"
            for source in meta.get("sources", [])
        )
        trust = meta.get("trust_counts") or {}
        material = meta.get("material_counts") or {}
        rows = "".join(
            f"<tr><td>{palette['brand']}</td><td>{palette['series']}</td>"
            f"<td>{palette.get('size') or '-'}</td><td align='right'>{palette.get('color_count')}</td>"
            f"<td>{palette.get('trust')}</td></tr>"
            for palette in meta.get("palettes", [])
        )
        conflicts = meta.get("conflict_examples") or []
        conflict_rows = "".join(
            f"<li>{item['brand']} {item['code']}：{item['palette_a']} {item['hex_a']} ↔ "
            f"{item['palette_b']} {item['hex_b']}（ΔE00 {item['delta_e00']}）</li>"
            for item in conflicts[:8]
        )
        return (
            "<h3>拼豆色卡来源与许可</h3>"
            f"<p><b>颜色总数</b>：{meta.get('colors')}；<b>系列</b>：{len(meta.get('palettes') or [])}；"
            f"<b>来源冲突</b>：{meta.get('conflicts')} 条（保留双份，不覆盖）<br>"
            f"<b>更新时间</b>：{meta.get('updated_at') or '-'}</p>"
            f"<p><b>可信度</b>：官方 {trust.get('official', 0)} · 社区 {trust.get('community', 0)} · "
            f"采样 {trust.get('sampled', 0)} · 未知 {trust.get('unknown', 0)}<br>"
            f"<b>材质</b>：实色 {material.get('solid', 0)} · 透明 {material.get('transparent', 0)} · "
            f"夜光 {material.get('glow', 0)} · 荧光 {material.get('fluorescent', 0)} · "
            f"珠光 {material.get('pearl', 0)} · 金属 {material.get('metallic', 0)}</p>"
            f"<h4>数据源</h4><ul>{sources}</ul>"
            "<p>公开 RGB 为屏幕参考值，不等同品牌官方实物测量色；官方与社区数据已分别标记。</p>"
            "<h4>系列</h4><table border='0' cellspacing='4'>"
            "<tr><th align='left'>品牌</th><th align='left'>系列</th><th align='left'>尺寸</th>"
            "<th align='right'>颜色</th><th align='left'>可信度</th></tr>"
            f"{rows}</table>"
            "<h4>来源冲突示例</h4>"
            f"<ul>{conflict_rows or '<li>无</li>'}</ul>"
        )
