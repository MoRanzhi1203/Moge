# 画布双模式（查看 / 编辑）验收报告

- 验收日期：2026-11-15
- 执行方式：真实 GUI 渲染（Qt 离屏抓图）+ 自动化测试，非纯设计文档
- 相关文件：`core/document.py`、`core/render.py`、`ui/canvas.py`、`ui/main_window.py`

## 1. 数据与渲染分离

新增统一文档模型 `GridDocument`（`core/document.py`）：

| 字段 | 含义 |
|---|---|
| `spec` | 图像尺寸（网格宽高） |
| `labels` | 单元格数据（entries 下标，-1 为空） |
| `entries` / `materials` | 颜色或材料引用（含真实贴图 SHA-256 / 路径 / 校验位） |
| `mode` | pixel / minecraft / beads |
| `locked` | 区域锁定掩码 |
| `selection` | 矩形选区 |
| `_history` / `_redo` / `dirty` | 编辑历史与修改状态 |

结果对象 `RenderResult.grid.labels` 与 `GridDocument.labels` 是**同一份数组**，渲染、编辑、导出、工程保存读取同一数据，不存在“只改预览 QPixmap”的情况。

渲染器 `core/render.py`：
- `render_document(document, "solid")`：按材料颜色渲染（原逻辑）。
- `render_document(document, "texture")`：读取每个材料的真实 PNG，最近邻平铺为 16×16 单元格像素，缺失贴图回退纯色。
- 切换预览只调用渲染器，不触发重采样/量化，不修改 `labels` 与统计。

## 2. 查看模式（默认）

- 启动后默认进入查看模式（工具栏“查看模式”选中）。
- 左键拖动平移；单击（位移 ≤ 4px）触发 `cellInspected`，在“统计”页展示材料详情：名称、ID、RGB、来源、几何、block_state、贴图 SHA-256、路径、校验位。
- 支持缩放（滚轮）、适应窗口、重置视图、显示网格、对比原图、坐标定位。
- 查看模式下画布不发出 `cellPressed`，`_apply_tool` 也有二次保护，无法修改网格。
- 自动化证据：`test_canvas_view_mode_never_edits` 断言查看模式单击 `cellPressed == []`，编辑模式同样操作会触发。

## 3. 编辑模式

工具栏新增“查看模式 / 编辑模式”切换（`Ctrl+E` 进入编辑），切换时清理临时工具状态（选区、笔画标记、拖拽状态），但不丢失作品数据。

支持工具：

| 工具 | 快捷键 | 说明 |
|---|---|---|
| 画笔 | B | 逐格绘制，拖动连续绘制 |
| 填充 | G | 四邻域泛洪，跳过锁定单元 |
| 吸管 | I | 选中材料 |
| 橡皮擦 | E | 仅像素模式可置空 |
| 替换同类 | R | 全图同类替换，跳过锁定单元 |
| 矩形框选 | S | 拖动生成选区，虚线高亮 |
| 区域锁定 | L | 点击切换单格锁定；`Ctrl+L` 锁定选区 |

- 锁定单元显示橙色半透明斜线覆盖，画笔/填充/替换均无法修改。
- 撤销 / 重做基于文档历史（最多 50 步），`Ctrl+Z` / `Ctrl+Shift+Z`；每次编辑更新网格、预览、调色板统计、工程修改状态与动作可用性。
- 拖动绘制期间侧栏刷新合并为 120ms 防抖，笔画结束后统一刷新，避免逐格重建列表造成卡顿。
- 编辑后仍写入底层 `labels`，PNG / CSV / PDF / `.moge` 导出与保存读取同一数据。

## 4. 预览切换（纯色 / 真实纹理）

- 工具栏“纯色预览 / 真实纹理预览”互斥切换。
- 无真实贴图时“真实纹理预览”自动禁用；强制切换会回退纯色并提示。
- 自动化证据：`test_gui_preview_switch_does_not_change_stats` 断言切换前后 `stats["counts"]`、`labels` 完全一致，画布图像高度由 `格数` 变为 `格数×16`。

## 5. GUI 截图证据

使用真实 Java 1.20.1 资源运行 48×36 网格后抓取：

- 查看模式：[canvas-view-mode.png](evidence/canvas-view-mode.png)
- 编辑模式（矩形选区 + 锁定 + 真实纹理预览）：[canvas-edit-mode.png](evidence/canvas-edit-mode.png)
- 纯色 vs 真实纹理对照：[moge-mc-texture-compare.png](evidence/moge-mc-texture-compare.png)

窗口尺寸验收：最小窗口 820×560；`tests/test_round2.py` 在 900×620 下断言左侧面板 `minimumSizeHint().width()` 不超过滚动视口，右侧栏 ≥ 220px、画布 ≥ 280px，无裁切；截图窗口为 1500×940。高 DPI 由主入口启用 `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps`。

## 6. 自动化验收

```
pytest：125 passed（原 117 + 新增 8）
ruff check .：All checks passed
```

覆盖本轮要求的测试项：

| 验收项 | 测试 |
|---|---|
| Java 1.20.1 官方资源下载与 SHA-1 校验 | 真实校验脚本 + `test_java_1201_records_are_traceable` |
| 实际纹理 PNG 提取与解码 | 同上（读取 PNG 尺寸/均值） |
| 方块 ID → 纹理文件映射 | `test_java_1201_records_are_traceable` |
| 原版纹理与近似色预览对照 | `test_texture_renderer_uses_real_png` + 对照图 |
| 更换版本后纹理/候选更新 | `test_minecraft_pipeline_reports_split_coverage`（1.20.1）+ 多版本索引重建 |
| 玻璃板/红石线/末地烛默认筛选 | `test_geometry_filter_excludes_partial_blocks` |
| 查看模式不修改网格 | `test_canvas_view_mode_never_edits` |
| 编辑模式画笔/吸管/填充/撤销重做 | `test_gui_edit_lock_and_project_roundtrip` + `test_workbench_three_modes_edit_and_switch` |
| 预览切换不改变材料统计 | `test_gui_preview_switch_does_not_change_stats` |
| 工程保存/恢复一致 | `test_gui_edit_lock_and_project_roundtrip` |
| 下载/解析不阻塞主界面 | 处理运行在 `PipelineWorker` 线程；资源获取在 `ResourceTaskWorker` 线程 |
| 窗口尺寸不裁切 | `test_workbench_layout_and_palette_filters` |

## 7. 最终回答

1. **Java 1.20.1 的真实贴图是否已经获取？** 是。官方客户端 JAR 已缓存并通过 SHA-1、大小、SHA-256 三重校验。
2. **实际获取并验证了多少个贴图文件？** Java 1.20.1 解析出 659 张去重 PNG，865 个方块面引用全部通过校验，缺失 0；本机全部 9 个版本共 2,110 张贴图，缺失 0。
3. **这些贴图是否用于真实预览？** 是。材料条目携带真实贴图 SHA-256/路径，“真实纹理预览”直接读取 PNG 渲染，纯色/纹理切换不改变统计。
4. **基岩版哪些版本已经实际完成？** 1.20.0（714 方块 / 577 贴图）、1.20.80（867 / 716）、1.21.0（953 / 772）、1.21.50（1099 / 809），状态均为 READY，缺失文件 0。
5. **查看模式与编辑模式是否均通过真实 GUI 验收？** 是。查看模式点击检查、拖动平移且不可编辑；编辑模式画笔/填充/选区/锁定/撤销重做/工程往返均有自动化测试与截图证据。

## 8. 遗留问题

- 生物群系 tint（草、树叶、水）尚未应用，真实纹理预览中呈灰度底色。
- 基岩版 resource samples 无模型几何，无法执行完整立方体筛选，界面已标注 `geometry=unknown`。
- 用户附加资源包仍以平均色叠加，未进入真实纹理渲染路径。
