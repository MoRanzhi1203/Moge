# Moge 2.0 变更记录

## 2026-11-15 · Minecraft 真实资源获取系统

- 新增 `core/resources/`：Mojang 版本清单、客户端 JAR 下载/校验、Bedrock Releases/tag 归档、安全 ZIP、SQLite 索引、颜色/复杂度特征、CLI。
- Java 解析 blockstate → model → texture，兼容 1.12 旧版 `textures/blocks` 与无前缀模型引用；Bedrock 解析 `terrain_texture.json`、`blocks.json` 与材质实例，支持 JSONC 注释。
- 新增 GUI“版本资源管理”：刷新/搜索版本、单/批量获取、进度与取消、校验、删除、重建、版本差异、真实贴图预览。
- Minecraft 模式接入真实候选集与 `[真实]/[近似]` 标识；资源来源可切换“自动优先真实 / 仅真实 / 内置近似”，未下载版本会提示打开资源管理。
- 实测：Java 1.12.2/1.16.5/1.18.2/1.20.1/1.21.4，Bedrock 1.20.0/1.20.80/1.21.0/1.21.50；9 版本、7806 方块、2110 贴图；缓存 462.4 MB；`verify` 4035 面通过。
- 测试 117 项、核心覆盖率 83%、ruff 0；打包 241.2 MB / 220 文件。详见 `docs/minecraft-resource-acquisition-report.md`。

## 2026-11-15 · 第二轮界面与功能优化

- 布局：三栏不可折叠、左右最小宽度、画布优先；左侧按基础/模式/高级分组；右侧调色板搜索/排序/仅已用、侧栏收起；输入控件与列表最小宽度收紧，消除水平滚动与裁切；启动尺寸按屏幕自适应。
- 高 DPI：入口启用缩放属性；100% / 125% / 150% 布局探针与启动截图。
- 画布：原图对比（按钮 + 按住 C）、重置视图、坐标定位；网格数据与预览图分离。
- Minecraft：新增朝向/透明/重力筛选、筛选诊断、方块朝向与可见面元数据、资源包名与 `[近似]/[贴图]` 标识。
- 拼豆：库存 CSV 导入、每包数量与采购包数、库存候选限制、默认仅显示已用颜色；CSV 增加 `packs` 列。
- 算法：新增 ≤1024 区域谱聚类实验与 Python 内存峰值指标；实测谱聚类 ΔE/耗时/内存均劣于 K-Means，未进入 UI；细节保护仍不进入 UI；平整色块保留。
- 测试：新增布局、画布、调色板、库存、采购、空材料、谱聚类与回退测试；`97 passed`，核心覆盖率 90%。
- 文档：新增 `docs/Moge-2.0-Round2-Optimization.md`。

## 2026-11-15 · Moge 2.0（分支 `feature/moge-2-modes`）

### 新增能力

- **统一数据模型与管线**：`ProjectDocument`、`SourceImage` 语义、`GridSpec`、`PixelGrid`、`PaletteEntry`、`MaterialRef`、`PipelineConfig`、`RenderResult`、`ExportJob`；阶段注册、进度、取消、任务 ID 隔离。
- **三种模式**：普通像素化、Minecraft 方块画、拼豆图纸；共享源图、网格、调色板、统计与导出框架。
- **像素画布**：最近邻缩放、滚轮缩放、中键/空格平移、网格叠层、坐标提示、画笔/填充/吸管/替换/撤销/重做、像素化模式透明单元。
- **三模式 UI**：菜单/工具栏、模式切换、左侧参数、右侧调色板/统计、状态栏进度与取消、浅色/深色主题、面板与窗口状态记忆、拖放打开。
- **算法注册表**：K-Means++（RGB/Lab）、MiniBatch（RGB/Lab）、Ward 代表点合并（Lab），统一种子与颜色数约束。
- **基准体系**：7 类合成图 × 3 网格 × 4 色数 × 5 算法；CIEDE2000、边缘相关、孤立单元、耗时；JSON 原始记录与 Markdown 报告。
- **Minecraft**：内置近似方块库、结构化版本比较、类别/获取条件/成本/可建造筛选、100% 合法性核对、资源包 ZIP 只读导入（贴图平均色）。
- **拼豆**：内置近似色卡、用户 CSV 导入与校验、品牌/系列隔离、库存/禁用筛选、分板统计、PDF/CSV/PNG 导出。
- **导出与工程**：PNG/JPEG、材料 CSV、分页 PDF、`.moge` 工程（schema 1，拒绝未知成员与未知版本）。

### 行为与取舍变化

- “细节保护”预设经基准未显示稳定边缘收益，已从正式 UI 预设与自动规则中移除；代码保留在实验/基准路径。
- 自动选择只使用透明规则：大网格走 MiniBatch，其余走 Lab K-Means；不宣称训练模型。
- Minecraft/拼豆默认直接合法材料匹配，不先做 K-Means（基准显示直接匹配色差更低）。
- 平铺色块预设保留：基准显示平均孤立单元减少约 5.83%，色差变化约 +0.013。
- 透明度：输入透明像素按白底合成；统计记录透明像素数。

### 兼容性

- `main.py`、`moge`、`Moge.spec` 入口保持。
- 旧 `ProcessingParams`/`PixelMethod`/`image_processor` 处理函数已移除；`ResizeMode`/`ProcessingCancelled` 合并到 `core/models.py`，统一走 `PipelineWorker`。
- 新增包：`Moge.core.modes`、`Moge.exporters`，已加入 `pyproject.toml` 打包配置。

### 代码精简（2026-11-15）

- 删除 `core/image_processor.py`、`ProcessingWorker` 与对应旧测试。
- 清理未使用的函数、常量、模型方法、画布接口与重复测试等待逻辑。
- 删除构建产物、缓存、覆盖率文件及旧版贴图下载缓存（约 1.2 GB）。

### 提交

- `52bc9d4` feat(core): add Moge 2.0 pipeline, color science, and material catalogs
- `5288662` feat(ui): add three-mode workbench, editable canvas, and exporters
- `2c31a5e` feat: add resource pack import and measured clustering benchmarks
- 当前文档与验收记录为后续文档提交。

### 已知问题

- 真实 Minecraft 贴图与官方拼豆色卡未包含；内置色值为近似。
- 未实现谱聚类、BIRCH、GMM、DBSCAN、Mean Shift、Affinity Propagation。
- 未实现 `.schem`/`.litematic`、地图画、Bedrock 专属资源结构、人工盲测、大图压力测试。
- 本分支未推送；CI 未在 GitHub 上验证新代码。
