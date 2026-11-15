# Minecraft 真实贴图切换与版本隔离修复报告

- 修复日期：2026-11-15
- 目标：消除 GUI 中的版本混用，确保候选集合、材质、纹理、画布均来自同一 edition/version
- 验证方式：真实资源库 + 真实 GUI 处理 + 像素级纹理断言

## 1. 实际故障根因

审计结论：**数据链路本身没有跨版本查询**，问题出在 UI 的“旧结果未失效”。

| 环节 | 实际行为 | 结论 |
|---|---|---|
| 资源下载/导入 | Java 5 版本、Bedrock 4 版本已索引 | 正常 |
| 版本数据库查询 | `db.get_blocks(edition, version)` 按 `version_id` 过滤 | 正常 |
| 候选集合 | 1.12.2 = 209，1.20.1 = 348，1.21.4 = 389，Bedrock 1.21.50 = 582 | 正常 |
| 缓存 | `_REAL_CATALOG_CACHE` 键含 `(db, edition, version, mtime, size)` | 正常，无跨版本命中 |
| 颜色匹配 | 量化为当前候选集合 | 正常 |
| GridDocument | 保存当前结果 materials | 正常 |
| Renderer | 读取 `entry.meta.texture_path` 对应 PNG | 正常 |
| **版本切换回调** | 只刷新版本下拉，不标记旧结果 | **根因** |

复现（修复前）：

```
已处理 Java 1.20.1 → 候选 348，含 netherite_block 等
仅把下拉切到 Java 1.12.2，不重新处理
界面显示版本 1.12.2，但 materials/Canvas/调色板仍是 1.20.1 的 348 个方块
状态栏仍为“处理完成”，没有任何旧结果提示
```

因此截图中的 Netherite Block、Chiseled Polished Blackstone、Mud Bricks、Target、Fletching Table 全部来自**上一次 1.20.1/1.21.4 结果**，不是 1.12.2 查询泄漏。

## 2. 修复内容

### 2.1 结果状态机

新增三种状态（`ui/main_window.py`）：

| 状态 | 含义 |
|---|---|
| `CURRENT` | 结果 edition/version 与当前选择一致，筛选签名一致 |
| `STALE` | 版本或筛选已变化，结果仍可查看，但需重新处理 |
| `INVALID` | 结果包含目标版本不支持的材料（跨版本混用） |

实现：

- `_mc_target()`：读取当前 UI 的 edition/version。
- `_mc_candidate_ids()`：按目标版本加载完整方块 ID 集合（带 8 条缓存）。
- `_mc_signature()`：版本 + 类别 + 获取条件 + 完整方块筛选 + 排除透明/重力 + 资源模式的签名。
- `_mc_state_text()`：先判定 INVALID（存在目标版本外材料），再判定 STALE（版本或筛选变化），否则 CURRENT。
- `_on_mc_context_changed()`：版本、获取条件、类别、几何筛选、资源模式变化时立即刷新统计/状态栏，**不自动重新处理**。

### 2.2 状态展示

- 状态栏：`INVALID · 旧结果（java 1.12.2）包含 48 个 java 1.20.1 不支持的材料…请重新处理`
- 统计页顶部彩色状态：`CURRENT / STALE / INVALID`，同时显示：
  - 结果版本（实际生成）
  - 当前选择（UI 当前）
- 旧结果允许继续查看，但不会再被当作新版本结果。

### 2.3 处理完成校验

`_on_processed()` 对 Minecraft 结果执行目标版本校验：

- 逐个比对 `entry.id` 与目标版本方块 ID 集合；
- 结果写入 `stats["version_isolated"]`，违规时记录 `isolation_violations` 与日志；
- 重新处理会创建新的 `RenderResult` 与新的 `GridDocument`（identity token 变化），调色板、统计、画布、纹理引用全部重建。

### 2.4 编辑保护

当结果为 `STALE`/`INVALID` 时，编辑工具拒绝修改网格，并提示“请重新处理后再编辑”，避免在旧版本数据上继续创作。

### 2.5 真实纹理切换

- 纯色预览：`render_grid` 使用材料 RGB。
- 真实纹理预览：`render_textured` 读取目标版本 PNG，`cv2.INTER_NEAREST` 放大到 16×16 单元格。
- 切换前检查**所有已用材料**：
  - 缺少 `texture_path` 或文件不存在 → 拒绝切换，弹窗列出缺失色号/方块，保持纯色预览；
  - 不再静默回退纯色后仍显示“真实纹理预览”。
- 纹理预览按钮仅在全部已用材料都有真实 PNG 时启用。

## 3. 版本筛选前后对比

| 场景 | 修复前 | 修复后 |
|---|---|---|
| Java 1.12.2 候选 | 209（本身正确，但界面可能显示旧版本 348） | 209；`netherite_block` 等 0 个 |
| 仅切换 1.12.2（不重新处理） | 仍显示 1.20.1 的 348 个材料 | `INVALID`：列出目标版本不支持的 48 个材料，提示重新处理 |
| 1.12.2 → 1.20.1（不重新处理） | 无提示 | `INVALID`：旧 1.12.2 的 48 个旧 ID（如 `brick_block`）被识别 |
| 重新处理 1.12.2 | — | 新 GridDocument，209 个材料全部属于 1.12.2，状态 CURRENT |
| Bedrock 1.21.50 | 可能复用 Java 结果 | 重新处理，582 个候选，状态 CURRENT |

## 4. 纹理渲染证据

### 4.1 确定性 3×1 测试（Java 1.12.2）

Stone / Oak Planks / Cobblestone，分别渲染纯色与真实纹理：

- 纯色像素 = 材料 RGB。
- 纹理像素 = 原始 PNG 经 `cv2.resize(..., INTER_NEAREST)` 放大 16×16 后逐像素相等（测试断言 `np.array_equal`）。
- 切换预览前后 `GridDocument.labels` 与 `stats["counts"]` 完全不变。
- 对照图：[mc-texture-3x1-1122.png](evidence/mc-texture-3x1-1122.png)

### 4.2 跨版本纹理隔离

| 版本 | Stone 贴图 SHA-256（前 16 位） |
|---|---|
| Java 1.12.2 | `489928bc2549424b` |
| Java 1.20.1 | `0096954ee757a218` |
| Bedrock 1.21.50 | `12f1c99206df13e9` |

三者不同，证明 Renderer 实际读取对应版本 PNG，而不是复用其它版本纹理。

GUI 实测（18×14 网格）：

- 纹理预览画布尺寸 288×224 = 18×16 / 14×16，最近邻放大。
- 已用材料逐项校验：`texture_path` 存在，文件 SHA-256 == `meta.texture_sha256`。
- 截图：
  - [Java 1.12.2 纯色](evidence/mc-1122-solid.png)
  - [Java 1.12.2 真实纹理](evidence/mc-1122-texture.png)
  - [切换版本后的旧结果 INVALID](evidence/mc-stale-result.png)
  - [Java 1.20.1 重新处理](evidence/mc-1201-current.png)
  - [Bedrock 1.21.50 真实纹理](evidence/mc-bedrock-12150-texture.png)
  - 日志：[mc-version-isolation-log.txt](evidence/mc-version-isolation-log.txt)

## 5. 修改文件

| 文件 | 修改 |
|---|---|
| `ui/main_window.py` | 结果状态机、版本/筛选信号、INVALID 校验、旧结果状态展示、纹理切换校验、编辑保护 |
| `tests/test_texture_version_isolation.py` | 新增 8 项版本隔离/纹理像素/旧结果状态测试 |

未修改下载器与资源库；未重新下载资源。

## 6. 测试结果

```
pytest：141 passed
ruff check .：All checks passed
```

新增测试覆盖：

1. Java 1.12.2 候选不含 Netherite/Blackstone/Mud Bricks/Target/Fletching Table。
2. 版本缓存隔离：1.12.2 与 1.20.1 候选集合不同，互不污染。
3. Java 1.12.2 / 1.20.1 / 1.21.4 / Bedrock 1.21.50 的 3×1 纹理像素与预期 PNG 完全一致。
4. 管道输出材料全部属于目标版本，纹理 SHA-256 与文件一致。
5. GUI：1.20.1 处理 → 切 1.12.2 标记 INVALID → 重新处理变 CURRENT，且全部材料属于 1.12.2。
6. 预览切换不改变文档/统计（既有测试）与纹理缺失显式提示（实现校验）。

## 7. 剩余问题

1. 旧结果仍保留在画布上供查看；已通过状态色、统计横幅、状态栏三重标记，编辑被阻止，但未自动清空。
2. 生物群系 tint（草/树叶/水）仍未应用，真实纹理中呈灰度底。
3. Java 1.12.2 与基岩版使用旧方块 ID（如 `planks`），跨版本 ID 差异按原版数据保留，不做名称映射。
4. 纹理缺失检测基于本地文件存在性；如果文件在处理后被外部删除，预览会拒绝切换并提示，但不会自动重新下载。
