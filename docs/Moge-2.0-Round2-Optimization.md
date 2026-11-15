# Moge 2.0 第二轮界面与功能优化报告

> 日期：2026-11-15
> 分支：`feature/moge-2-modes`（未推送、未覆盖 `main`）
> 基线：第一轮 86 项测试通过、ruff 0 error；本轮以本地三模式版本为唯一修改基础

## 1. 任务一：工作台布局

### 实测对比（离屏布局探针，900×620）

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 左侧内容最小宽度 | 481 px | 280 px |
| 左侧视口宽度 | 264 px | 284 px |
| 右侧面板初始宽度 | 0 px（被折叠） | 220 px |
| 中央画布宽度（1000 宽窗口） | 704 px（右侧被挤没） | 460 px（三栏均衡，画布仍最大） |
| 左侧/右侧水平滚动条 | 可能出现 | 强制关闭 + 内容宽度受限 |
| 窗口默认尺寸 | 固定 1200×800 | 按可用屏幕 90% 自适应，最小 820×560 |

实现：

- `QSplitter` 三栏设置为不可折叠，左/右最小宽度 300/220，画布 stretch=1。
- 左侧内容统一为“基础设置 / 模式设置 / 高级参数”三组。
- 输入控件统一 `Expanding + 最小 60px`，下拉框使用 `AdjustToMinimumContentsLengthWithIcon`，长选项不再撑破侧栏。
- 右侧调色板支持搜索、排序（用量/名称/色相）、仅已用；列表横向滚动关闭并省略超长文本。
- 右侧面板可通过工具栏/`Ctrl+B` 收起；窗口与分栏状态写入 QSettings。
- 主入口启用 `AA_EnableHighDpiScaling` 与 `AA_UseHighDpiPixmaps`。

Windows 缩放检查：在 `QT_SCALE_FACTOR=1.0/1.25/1.5` 下运行布局探针，逻辑最小宽度保持一致且小于视口；三种缩放的实际启动截图：

- [100%](../.screenshots/moge2-round2-100.png)
- [125%](../.screenshots/moge2-round2-125.png)
- [150%](../.screenshots/moge2-round2-150.png)

## 2. 任务二：画布系统

- 滚轮以光标为锚点缩放（0.2×–64×），中键/空格拖拽平移。
- 新增“对比原图”开关（`Ctrl+Shift+C`，画布内按住 `C` 临时对比），原图与结果图分开存储。
- 新增“重置视图”（`Ctrl+0`）与“定位坐标”（`Ctrl+Shift+L`，输入 `x,y` 居中）。
- 网格叠层、坐标状态栏、适应窗口、1:1 缩放保持。
- 缩放/平移只重绘 `QImage`，不重新采样或量化；网格标签与预览图分离。
- 画笔/吸管/填充/替换/橡皮擦与撤销/重做保持；像素化模式允许 `-1` 透明单元，材料模式禁止擦除为空白。

## 3. 任务三：Minecraft 方块系统

- 版本、类别、获取条件、成本、可建造筛选均实际参与候选集合计算，并新增测试验证。
- 新增筛选项：
  - 朝向：不限制 / 无朝向 / 轴向 / 朝向依赖
  - 排除透明方块
  - 排除重力方块
- 方块库新增沙、红沙、沙砾（重力），原木标记轴向、带釉陶瓦标记朝向、草方块标记顶面；条目 meta 增加 `orientation`、`visible_face`、`gravity`。
- 新增“筛选诊断”：显示候选数、按类别计数、前 30 条排除原因。
- 资源包仍为只读 ZIP、只取贴图平均色；统计与调色板明确标注 `[近似]` / `[贴图]`，并显示资源包名与覆盖数量。**不把未加载贴图的方块伪装成真实原版材质。**

## 4. 任务四：拼豆系统

- 内置 `Generic / Approx` 与用户导入色卡明确区分：界面显示“内置近似（未验证）”或“用户导入（已验证标记）”。
- CSV 色卡校验保持：必需列、颜色格式、同品牌/系列色号唯一、坏行隔离。
- 新增库存 CSV 导入（`brand,series,code,quantity`），支持数量、坏行报告；库存色号直接限制候选集合。
- 新增每包数量（默认 1000）与采购包数统计；CSV 新增 `packs` 列，工程恢复时重新计算。
- 调色板默认在拼豆模式勾选“仅已用”，可取消查看全部；支持搜索与排序。
- 底板分页、数量统计、PDF/CSV 导出沿用并通过回归测试。

## 5. 任务五：算法与材料对照

完整数据见 [聚类基准](Clustering-Benchmarks.md)，本轮复测（Python 3.9.21 / NumPy 2.0.2 / OpenCV 4.11）：

| 64×64 / 16 色 | ΔE00 | 耗时 | Python 峰值 |
| --- | ---: | ---: | ---: |
| K-Means Lab | 2.439 | 13.9 ms | 812 KB |
| Ward Lab | 2.473 | 33.9 ms | 813 KB |
| K-Means RGB | 2.817 | 10.0 ms | 614 KB |
| MiniBatch RGB | 3.183 | 30.3 ms | 1446 KB |
| MiniBatch Lab | 3.288 | 34.5 ms | 1463 KB |

- 全组合平均：Ward ΔE 最低（1.894），但耗时 201 ms、Python 峰值约 65 MB；K-Means Lab 2.203 / 25 ms，是默认基线。
- “细节保护”边缘相关下降 9.37 个百分点，未进入正式 UI。
- “平整色块”减少孤立单元约 5.83%，ΔE 仅 +0.013，保留为可选。
- 直接材料匹配优于“先 K-Means 再映射”：MC +0.275 ΔE、拼豆 +0.375 ΔE 的差距，合法率 100%。
- 谱聚类仅对 32×32（≤1024 区域）实验：ΔE 2.022 vs K-Means 1.829，耗时 375 ms vs 6.4 ms，Python 峰值约 40 MB vs 0.3 MB，**未进入正式 UI**。
- BIRCH/GMM/DBSCAN/Mean Shift/Affinity Propagation 未实现、未接入、未做基准。

## 6. 任务六：测试与验收

```text
ruff check .                                     通过（0 error）
pytest -q                                        97 passed
pytest --cov=Moge.core                          90%
tools/run_benchmarks.py                          420 聚类 + 35 预设 + 14 材料 + 56 谱聚类
pyinstaller --noconfirm Moge.spec                239.2 MB / 218 files
dist/Moge/Moge.exe 启动                          存活，日志确认主窗口初始化
```

新增/覆盖测试：

- 900×620 布局：左/右无水平滚动、三模式面板不超出视口、画布最小宽度、侧栏收起/恢复。
- 画布：对比开关、定位、重置、坐标命中。
- 调色板：仅已用、搜索、排序、选择索引映射。
- 模式切换保留源图、任务取消、空材料集合报错、库存限制、采购包数、工程回读、统计一致性、PDF 输出。

## 7. 主要修改文件

- `ui/main_window.py`：三栏布局、分组面板、右侧搜索/排序/仅已用、对比/重置/定位、MC 诊断、库存导入、采购统计。
- `ui/canvas.py`：原图对比、重置视图、坐标居中。
- `main.py`：高 DPI 属性、2.0 窗口标题。
- `core/materials.py`：朝向/可见面/重力元数据、透明/重力/朝向筛选、库存 CSV。
- `core/modes/minecraft.py`：新筛选参数、资源包名、条目元数据。
- `core/modes/beads.py`：采购包数统计。
- `core/clustering.py`：受限规模谱聚类实验（≤1024 区域，自动回退）。
- `core/benchmarks.py`、`tools/run_benchmarks.py`：内存指标、谱聚类实验与报告。
- `exporters/csv.py`：`packs` 列。
- `tests/test_round2.py`、`tests/test_benchmarks.py`、`tests/conftest.py`：新增测试与 QSettings 隔离。

## 8. 未完成项与原因

1. 真实 Minecraft 版本贴图仍未加载：版权与分发限制；只支持用户资源包平均色，多面贴图/染色/模型未实现。
2. 官方拼豆色卡未提供：无授权数据；内置仍为未验证近似色。
3. Bedrock 资源结构与 Java 的差异未做独立适配。
4. 符号黑白专用打印、库存扣减与补货建议未实现；采购仅按“每包数量”估算。
5. 谱聚类只做 32×32 实验，未在真实照片/大网格验证；已明确不进入 UI。
6. 4K 大图峰值内存、取消延迟、人工盲测未运行。
7. CI 未在 GitHub 上运行本轮分支；本地执行了同等命令。

## 9. 复现

```powershell
git switch feature/moge-2-modes
.venv\Scripts\activate
ruff check .
pytest --cov=Moge.core --cov-report=term-missing
python tools/run_benchmarks.py
python main.py
pyinstaller --noconfirm Moge.spec
```
