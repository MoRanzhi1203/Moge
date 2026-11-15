# Moge 拼豆色卡自动获取与数据库集成报告

- 执行日期：2026-11-15
- 色卡数据库：`C:\Users\MSIPC\AppData\Local\Moge\palettes\beads.db`
- 原始数据缓存：`C:\Users\MSIPC\AppData\Local\Moge\palettes\raw`
- 获取报告：`C:\Users\MSIPC\AppData\Local\Moge\palettes\acquisition_report.json`
- 执行命令：`.venv\Scripts\python.exe -m Moge.core.beads.acquire`

## 0. 关于 `Moge_Bead_Palette_Fetcher.zip`

该压缩包在当前工作区、下载目录和附件目录中均不存在（已全盘检索 `*Bead*`），因此无法执行“解压并运行 fetch_palettes.py”。

为不中断任务，本轮直接在 Moge 内实现了等价的数据获取与入库模块
[acquire.py](../../core/beads/acquire.py)，数据源仍为任务指定的
`HansBug/pindou-color-data` 与 `maxcleme/beadcolors`，并完成了真实下载、解析、SQLite 入库、UI 接入与测试。
下方所有数字均来自本次实际抓取的数据，不是手工填写。

## 1. 数据来源与许可

| 来源 | 地址 | 许可 | 数据类型 | 可信度 |
|---|---|---|---|---|
| HansBug/pindou-color-data | https://github.com/HansBug/pindou-color-data | MIT | JSON（按系列） | 官方（Artkal 引用官方 PDF/色卡图） / 社区 |
| maxcleme/beadcolors | https://github.com/maxcleme/beadcolors | MIT | v3 CSV（按品牌/尺寸） | 社区（含贡献者字段） |

- 原始 JSON/CSV 缓存 24 小时，`--force` 可强制刷新；缓存与数据库均在用户本地，不进入 Git。
- 每个色号保留 `trust`：`official`（官方 PDF/色卡图）、`community`（社区维护）、`sampled`（官方色卡图采样）、`unknown`。
- 公开 RGB 为屏幕参考值，不等于品牌官方实物测量色；UI 与导出均显示来源/许可/可信度。

## 2. 获取结果

| 指标 | 实际值 |
|---|---|
| 系列（palette） | 26 |
| 颜色记录 | 4,984 |
| 品牌 | 12：Artkal、COCO、Diamond Dotz、Hama、MARD、Nabbi、Perler、Yant、优肯、咪小窝、漫漫、盼盼 |
| 可信度 | 官方 788 / 社区 4,150 / 采样 46 / 未知 0 |
| 材质 | 实色 4,806 / 透明 36 / 夜光 21 / 荧光 32 / 珠光 27 / 金属 11 / 特殊 51 |
| 来源冲突记录 | 1,118（全部保留双份，`resolution=kept-separate`） |

### 2.1 主要系列

| 品牌 | 系列 | 尺寸 | 颜色数 | 可信度 | 来源 |
|---|---|---|---:|---|---|
| MARD | MARD 221 | 2.6mm | 221 | 社区 | pindou-color-data |
| MARD | MARD 221（Alfonse 参考） | 2.6mm | 221 | 社区 | pindou-color-data |
| MARD | MARD 291 | 2.6mm | 291 | 社区 | pindou-color-data |
| MARD | MARD 291（社区） | 2.6mm | 291 | 社区 | beadcolors |
| Hama | Hama Midi / Mini / Maxi | 5mm / 2.6mm / 10mm | 92 / 78 / 25 | 社区 | beadcolors |
| Perler | Perler Standard / Mini / Caps | 5mm / 2.6mm / 5mm | 103 / 41 / 26 | 社区 | beadcolors |
| Artkal | Artkal C 197 | 2.6mm | 197 | 官方 172 + 官方图 2 + 采样 23 | pindou-color-data（官方 PDF/色卡图） |
| Artkal | Artkal M 221 | 2.6mm | 221 | 社区 | pindou-color-data |
| Artkal | Artkal C+M 418 | 2.6mm | 418 | 官方/采样混合 | pindou-color-data |
| Artkal | Artkal A / C（社区） / M（社区） / R / S | 2.6mm / 5mm | 145 / 174 / 220 / 89 / 199 | 社区 | beadcolors |
| COCO | COCO 291 | 2.6mm | 291 | 社区 | pindou-color-data |
| 漫漫 / 盼盼 / 咪小窝 / 优肯 | 278 / 289 / 290 / 174 | 2.6mm | 278 / 289 / 290 / 174 | 社区 | pindou-color-data |
| Nabbi / Yant | Nabbi / Yant | 5mm / 未知 | 30 / 119 | 社区 | beadcolors |
| Diamond Dotz | Diamond Dotz（钻画，非拼豆） | drill | 461 | 社区 | beadcolors |

完整清单见 `acquisition_report.json`。

### 2.2 缺失色号与重复

- 按各系列声明的期望数量核对：**缺失 0、重复 0**。
- MARD 221 的两个来源色号集合完全一致（A1–M15），仅 RGB 有差异。
- MARD 291 完整包含 MARD 221 的 221 个色号，另有 70 个扩展色号（P1–P70）。
- `beadcolors` 的 MARD 291 与 `pindou` 的 MARD 291 色号集合完全一致（0 差异）。
- Artkal M 社区 CSV 实际 220 色，而其 README 标注 174；按实际数据入库并保留来源，不用旧数量覆盖。

### 2.3 来源冲突示例（保留双份）

| 品牌/色号 | 来源 A | 来源 B | ΔE00 |
|---|---|---|---|
| Artkal C01 | `#FFFFFF`（官方 PDF） | `#EAEEF3`（社区） | 4.51 |
| Artkal C02 | `#000000`（官方 PDF） | `#292A2B`（社区） | 10.53 |
| MARD 221 A5 | `pindou` 221 源 | `pindou` Alfonse 源 | 见数据库 `conflicts` 表 |

数据库按 `(palette_id, code)` 分行存储，从不覆盖；冲突表记录双方 HEX 与 Delta E00。

### 2.4 特殊材质

- 透明：36 条（例：Artkal `CT01–CT09`，Hama `Transparent Red`、`Clear`）。
- 夜光：21 条（Artkal `CG01–CG07`，官方商店标注 Glow in Dark）。
- 荧光：32 条（Hama/Perler 名称含 Fluorescent）。
- 珠光：27 条（Artkal `CP1–CP7`，官方标注 Pearl）。
- 金属/特殊：11 / 51 条（名称含 Metallic、Silk、Matte 或无法确认的 `CE` 组）。

材质在数据库、调色板徽标、统计和 CSV 中均单独标记，不当作普通实色。

## 3. 数据库结构

| 表 | 用途 |
|---|---|
| `sources` | 来源名称、URL、许可（MIT）、可信度 |
| `palettes` | 品牌、系列、尺寸、来源、可信度、期望/实际数量、许可 |
| `colors` | 色号、名称、RGB、HEX、色系、材质、可信度、来源 URL、贡献者、校验位 |
| `conflicts` | 同品牌同色号跨来源差异（HEX、ΔE00、保留策略） |
| `meta` | 更新时间、schema、许可汇总 |

筛选维度：品牌、系列、尺寸、视觉色系（红/橙/黄/绿/青/蓝/紫/粉/棕/黑/白/灰）、材质。

## 4. Moge 集成

- 启动时读取 SQLite 色卡库；数据库缺失才回退内置近似色卡。
- 默认选中 **MARD 221（221 色）**，同时可切换 MARD 291 及其他系列。
- 拼豆面板新增“尺寸 / 色系 / 材质”筛选；品牌切换会联动系列与筛选列表。
- 每个图纸单元引用真实 `brand/series/code`；材料条目携带 `trust / material / source_url / license`。
- 调色板列表显示 `[透明] [夜光] [官方] [社区] [采样]` 等徽标；统计页显示来源、许可、可信度与材质分布。
- 查看模式单击材料可显示色号详情，并给出跨品牌 Lab/ΔE00 近似参考（明确标注“仅近似，不是同一色号”）。
- 工程保存不再写入整份色卡（只保留品牌/系列/筛选条件），恢复时从 SQLite 重新加载；`beads-roundtrip.moge` 仅 4,453 字节，标签完全一致。
- 材料 CSV 增加 `size / color_family / material / trust / license / source_url` 列。

## 5. 真实 GUI 验证

| 场景 | 结果 |
|---|---|
| 默认 MARD 221 | 221 个候选，57 个实际色号，432 颗珠子；色号示例 B8×34、B5×31、D10×25；来源/许可/可信度显示为 pindou-color-data / MIT / 社区 |
| 切到 Hama Mini | 78 个候选，31 个色号；材质统计：实色 66 / 透明 5 / 荧光 7 |
| Artkal C 197 + 夜光筛选 | 7 个候选（CG01–CG07），全部标记为夜光、可信度“采样” |
| 工程保存/恢复 | 标签矩阵完全一致，品牌/系列保留，色卡未写入工程文件 |
| 材料 CSV | 生成 13,215 字节，含品牌/系列/色号/尺寸/材质/可信度/许可/来源 URL |

截图与导出证据：

- [MARD 221 界面](evidence/beads-gui-mard221.png)
- [Hama Mini 界面](evidence/beads-gui-hama-mini.png)
- [Artkal 夜光筛选](evidence/beads-gui-artkal-glow.png)
- [MARD 221 材料 CSV](evidence/beads-materials-mard221.csv)
- [工程往返文件](evidence/beads-roundtrip.moge)

## 6. 测试

```
pytest：133 passed
ruff check .：All checks passed
```

新增测试（`tests/test_bead_palettes.py`）覆盖：

1. 数据库存在 4,000+ 色、MARD 221/291 数量正确、Hama/Perler/Artkal 等品牌存在。
2. 默认选择 MARD 221。
3. 尺寸 / 色系 / 材质筛选。
4. 透明、夜光、珠光等特殊材质标记。
5. 跨品牌近似仅返回参考，不合并色号。
6. 拼豆管线输出真实色号与来源字段。
7. CSV 导出包含来源、许可、可信度。
8. 工程保存剥离色卡且恢复后标签一致。
9. GUI 品牌切换联动系列与尺寸。

## 7. 已知限制

1. **公开 RGB ≠ 官方测量值**：Hama、Perler 等只有社区维护数据；Artkal 官方 PDF 覆盖 172 色，特殊材质 23 色为官方色卡图采样，已在 `trust` 区分。
2. **官方 Hama/Perler 色卡**：未找到可直接结构化下载的官方 RGB 表，因此没有伪造“官方”标记；如需更高可信度，需要人工按官方实物色卡校准。
3. **Diamond Dotz** 为钻石画色号，已单独列出（尺寸 `drill`），不应与拼豆混用。
4. **Yant 尺寸** 未在公开数据中给出，保持为空，不做猜测。
5. 色卡数据库为本地文件；更新需重新执行 `moge-beads`（或 `python -m Moge.core.beads.acquire --force`）。
