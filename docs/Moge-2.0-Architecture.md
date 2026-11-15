# Moge 2.0 架构说明

## 1. 定位

Moge 2.0 是在保留原有像素化能力的基础上扩展出的三模式本地桌面工作台：

- 普通像素化（Pixel Art）
- Minecraft 方块画（纯色近似 + 版本/条件筛选）
- 拼豆图纸（内置近似色卡 + 用户 CSV 色卡）

技术栈保持 PyQt5 + NumPy + OpenCV，未引入 Web/Electron，未改变 `python main.py`、`moge` 与 PyInstaller 入口。

## 2. 模块结构

```text
main.py                     入口：QApplication、单实例、日志、MainWindow
core/
  models.py                 数据模型（GridSpec/PixelGrid/RenderResult/ResizeMode/ProcessingCancelled）
  color_spaces.py           sRGB ↔ Lab(D65)、CIEDE2000、最近色索引
  grid.py                   网格采样（mean/mode/center/edge）、渲染、孤立单元统计
  clustering.py             量化算法注册表：KMeans/MiniBatch/Ward（RGB/Lab）
  optimization.py           孤立单元合并（受色差阈值约束）
  pipeline.py               注册式阶段管线、进度与取消
  materials.py              Minecraft 方块近似库、拼豆色卡、资源包/CSV 导入
  benchmarks.py             合成基准图、指标、算法/预设/材料对照
  resources/                Minecraft 官方资源获取、解析、SQLite 索引与 CLI
    network.py              清单缓存、断点续传、哈希校验、取消
    safezip.py              ZIP/JAR 路径穿越与体积校验
    java.py                 Java blockstate → model → texture
    bedrock.py              Bedrock terrain_texture / blocks.json
    database.py             versions/textures/blocks/faces SQLite
    manager.py              CLI/GUI 共用资源管理入口
  modes/
    pixel.py                普通像素化配置、效果预设与透明自动规则
    minecraft.py            版本/类别/获取条件筛选、材料映射
    beads.py                品牌/系列/库存/禁色筛选、分板统计
    registry.py             模式注册与配置构建
exporters/
  png.py                    PNG/JPEG 导出（含透明）
  csv.py                    材料/颜色清单
  blueprint_pdf.py          分页图纸 PDF（坐标、色号、图例）
  project.py                .moge 工程读写（ZIP + JSON schema 1）
ui/
  main_window.py            三模式工作台、参数面板、任务管理、编辑、导出
  canvas.py                 可缩放/平移/最近邻渲染/网格叠层的编辑画布
  worker.py                 PipelineWorker（任务 ID、进度与取消）
  theme.py                  浅色/深色主题
tools/run_benchmarks.py     基准脚本（输出 JSON 与 Markdown 报告）
tests/                      单元、集成、UI 冒烟、基准指标测试
```

## 3. 数据模型与真相来源

- `PixelGrid` 是结果真相：`labels`（int32）保存 entries 下标，`-1` 表示透明/空单元（仅像素化模式允许）。
- `PaletteEntry` 与 `MaterialRef` 使用稳定 ID：
  - 生成色：`gen-0000`
  - Minecraft：`block_id`（如 `white_concrete`）
  - 拼豆：`bead:{brand}:{series}:{code}`
- `RenderResult` 同时携带预览图、网格、统计、算法、耗时和诊断，预览 PNG 不承担状态职责。
- `.moge` 工程文件为 ZIP：`manifest.json`（schema=1）+ `thumbnail.png`，只允许这两个成员。

## 4. 处理管线

阶段通过 `@register_stage` 注册，`PipelineConfig.stages` 决定组合：

| 阶段 | 作用 | 使用模式 |
| --- | --- | --- |
| `sample_grid` | 源图 → 逻辑网格颜色 | 全部 |
| `quantize_colors` | 颜色量化 + 生成调色板 | 像素化 |
| `map_materials` | 合法方块筛选 + Lab 最近色映射 | Minecraft |
| `map_beads` | 品牌/系列/库存筛选 + 映射 + 分板 | 拼豆 |
| `optimize_spatial` | 孤立单元合并（可关闭） | 像素化（平整预设） |
| `render_preview` | 网格 → RGB/RGBA 预览 | 全部 |
| `build_stats` | 用量、孤立单元、种类统计 | 全部 |

约定：

- 算法层不依赖 PyQt5，可单独测试与批处理。
- 每个阶段接收取消回调并检查；取消抛出 `ProcessingCancelled`。
- 进度按阶段区间映射到 0–100，主线程只通过信号更新 UI。
- 同一输入、种子、参数与内置资源哈希下结果确定。

## 5. 线程与任务隔离

- `PipelineWorker` 在 `QThread` 中执行 `run_pipeline`，携带自增 `task_id`。
- UI 只接受 `task_id == active_task` 的进度/结果/错误，旧任务结果不会覆盖新结果。
- 处理期间禁用打开/保存/导出/模式切换，但保留取消按钮；取消在下一个检查点生效。
- 关闭窗口时先取消并等待线程，避免 QThread 被销毁。

## 6. 兼容性

- 旧版 `ProcessingParams`、`PixelMethod`、`image_processor` 处理函数与 `ProcessingWorker` 已移除，统一使用 `PipelineWorker + run_pipeline`。
- `ResizeMode` 与 `ProcessingCancelled` 合并到 `core/models.py`；`GridSpec.from_block_size` 保留旧块大小推导能力。
- `main.py`、`moge`、`Moge.spec` 入口保持不变。

## 7. 已知边界

- 透明输入在采样前按白底合成，并在统计中记录透明像素数；只有像素化模式的编辑可以把单元设为透明。
- Minecraft/拼豆使用屏幕近似色，不含真实贴图或官方色卡；资源包只读取方块贴图平均色。
- 谱聚类、GMM、BIRCH、DBSCAN、Mean Shift、Affinity Propagation 未实现，未接入 UI。
- 未实现 `.schem`/`.litematic` 结构导出，也未实现地图画子模式。

## 8. 关键命令

```powershell
python main.py
python -m pytest --cov=Moge.core --cov-report=term-missing
python tools/run_benchmarks.py
pyinstaller --noconfirm Moge.spec
```
