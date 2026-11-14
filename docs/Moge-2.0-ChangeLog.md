# Moge 2.0 变更记录

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
- 旧 `ProcessingParams`/`PixelMethod`/`image_processor` 函数签名不变，旧测试继续通过。
- 新增包：`Moge.core.modes`、`Moge.exporters`，已加入 `pyproject.toml` 打包配置。

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
