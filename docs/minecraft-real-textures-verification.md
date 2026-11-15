# Minecraft 真实贴图获取与验证报告（Java 1.20.1 / 基岩版）

- 验证日期：2026-11-15
- 资源根目录：`C:\Users\MSIPC\AppData\Local\Moge\resources`
- 索引数据库：`index.db`（7,041,024 字节，9 个版本 / 7,806 方块 / 2,110 张贴图）
- 验证方式：真实下载的官方客户端 JAR + 本地索引库实测，非模拟数据

## 1. 审计结论：截图中的 509 / 0 / “Mojang 真实贴图”为什么不一致

截图三个字段的数据来源原本不同：

| 界面字段 | 原数据来源 | 问题 |
|---|---|---|
| 候选方块 509 | `filter_blocks` 过滤后的真实目录方块 | 数值本身正确，但包含了玻璃板、末地烛、红石线等非完整方块 |
| 贴图覆盖 0 | `stats["texture_overrides"]` | 这是**用户附加资源包**的覆盖数，不是原版贴图覆盖；真实资源存在时必然为 0 |
| 合成来源 | 任一候选方块带真实贴图即判定 | 判定正确，但与“贴图覆盖 0”并列展示，造成“宣称真实却没有贴图”的误导 |

本轮修复：
- “贴图覆盖率”拆分为三项，且每项都有明确分子/分母：原版资源覆盖率、可渲染候选覆盖率、附加资源包覆盖率。
- 资源状态统一为 `UNAVAILABLE / DOWNLOADING / VERIFYING / PARSING / PARTIAL / READY / CORRUPTED` 七态（`core/resources/manager.py`）。
- 每个方块记录新增 `geometry`、`block_state`、`verified`，并可通过 `get_blocks()` 读取 `edition / version / block_id / block_state / face / texture_path / texture_hash(source_hash) / verified`。
- 非完整几何方块默认排除：`buildable_only=True` 时仅保留 `geometry == full_cube` 的方块。

## 2. Java 1.20.1 真实资源校验结果

| 项目 | 实际值 |
|---|---|
| 官方元数据 | `https://piston-meta.mojang.com/mc/game/version_manifest_v2.json` → 1.20.1 |
| 客户端 JAR | `C:\Users\MSIPC\AppData\Local\Moge\resources\java\1.20.1\client.jar` |
| 文件大小 | 23,028,853 字节（与官方 `downloads.client.size` 完全一致） |
| 官方 SHA-1 | `0c3ec587af28e5a785c0b4a7b8a30f9a8f78f838` |
| 本地 SHA-1 | `0c3ec587af28e5a785c0b4a7b8a30f9a8f78f838`（**匹配**） |
| 本地 SHA-256 | `56b71336d2b4fdffd197f56595b0da93e32a946f78f382a299b8f4b92758bb0f`（与索引库 `resource_sha256` 一致） |
| blockstate 解析 | 1,005 个方块状态 |
| 含可用贴图面 | 865 个 |
| 完整立方体（几何判定） | 371 个 |
| 去重后贴图文件 | 659 个（内容寻址，SHA-256 命名） |
| 校验通过方块 | 865 / 865，缺失贴图文件 0 |

识别方式为真实解析 `blockstates → models（含 parent 继承）→ textures`，并非名称/色表推导：
- 完整立方体判定：模型 `elements` 的包围盒是否填满 16³（带旋转的元素直接判否）；无 `elements` 时以贴图槽位（`all` / `top+side` / `end+side` / `down+up` / 六面）或 `block/cube*` 父模板判定。
- `block_state` 记录实际取面的变体键（如 `snowy=false`、`axis=x`、`multipart`）。

### 2.1 实际方块 → 贴图证据（节选）

贴图均为 16×16 原始 PNG，位于 `resources/textures/<sha256>.png`：

| 方块 ID | block_state | 几何 | 校验 | 贴图 SHA-256（前 16 位） | 均值（BGRA） |
|---|---|---|---|---|---|
| `stone` | - | full_cube | 1 | `0096954ee757a218…` | (126,126,126,255) |
| `oak_planks` | - | full_cube | 1 | `3b00412fec87bd07…` | (79,131,162,255) |
| `grass_block` | snowy=false | full_cube | 1 | `b2aa2204118c7323…` | (147,147,147,255) |
| `white_concrete` | - | full_cube | 1 | `6ad27d2fa69de165…` | (214,213,207,255) |
| `glass` | - | full_cube | 1 | `cb89c706dce86eac…` | (151,150,140,65) |
| `iron_block` | - | full_cube | 1 | `b13979f2c26a9d55…` | (220,220,220,255) |
| `sandstone` | - | full_cube | 1 | `0b9288de5f054826…` | (156,203,216,255) |
| `deepslate` | axis=x | full_cube | 1 | `fcba18a824b97915…` | (83,80,80,255) |

### 2.2 特殊方块筛选结果（Java 1.20.1）

| 方块 | geometry | 默认候选 |
|---|---|---|
| `glass_pane` / `white_stained_glass_pane` | partial（multipart） | 排除 |
| `iron_bars` / `oak_fence` | partial（multipart） | 排除 |
| `end_rod` | partial（facing=down） | 排除 |
| `redstone_wire` | partial（multipart） | 排除 |
| `torch` / `lantern` | partial | 排除 |
| `oak_slab` / `oak_stairs` | partial | 排除 |
| `stone` / `glass` / `oak_planks` / `white_concrete` | full_cube | 保留 |

默认候选数量由 509 降为 **348**（完整立方体 + 可建造筛选）。

## 3. 覆盖率（分子 / 分母，均为实测）

Java 1.20.1 运行结果（48×36 网格，真实管道）：

| 指标 | 分子 / 分母 | 比例 |
|---|---|---|
| 原版资源覆盖率 | 865 / 1005 | 86.1% |
| 可渲染候选覆盖率 | 348 / 348 | 100% |
| 附加资源包覆盖率 | 0 / 348 | 0%（未导入资源包） |

- 原版资源覆盖率 = 至少有一个真实贴图面且贴图文件存在的方块数 / 解析出的 blockstate 总数。
- 可渲染候选覆盖率 = 候选中同时具备 `texture_path` 与 `verified` 的方块数 / 候选总数。
- 附加资源包覆盖率 = 候选中被用户资源包覆盖的方块数 / 候选总数。

## 4. 真实贴图是否用于渲染

是。`ui.canvas` 的“真实纹理预览”读取每个材料 `meta["texture_path"]` 指向的真实 PNG，按 16×16 最近邻平铺到单元格（`core/render.py`），切换预览只改变渲染方式，不重新量化、不改变统计。

对照图（左侧纯色、右侧真实纹理）：[moge-mc-texture-compare.png](evidence/moge-mc-texture-compare.png)
编辑/查看界面截图：[canvas-edit-mode.png](evidence/canvas-edit-mode.png) · [canvas-view-mode.png](evidence/canvas-view-mode.png)

## 5. 全部版本实测汇总

| 版本 | 状态 | 方块数 | 有贴图 | 完整立方体 | 校验通过 | 去重贴图 | 缺失文件 |
|---|---|---|---|---|---|---|---|
| Java 1.12.2 | READY | 407 | 407 | 235 | 407 | 350 | 0 |
| Java 1.16.5 | READY | 764 | 656 | 295 | 656 | 515 | 0 |
| Java 1.18.2 | READY | 900 | 791 | 343 | 791 | 595 | 0 |
| Java 1.20.1 | READY | 1005 | 865 | 371 | 865 | 659 | 0 |
| Java 1.21.4 | READY | 1097 | 952 | 413 | 952 | 713 | 0 |
| Bedrock 1.20.0 | READY | 714 | 681 | 0 | 675 | 577 | 0 |
| Bedrock 1.20.80 | READY | 867 | 854 | 0 | 850 | 716 | 0 |
| Bedrock 1.21.0 | READY | 953 | 939 | 0 | 932 | 772 | 0 |
| Bedrock 1.21.50 | READY | 1099 | 1084 | 0 | 1077 | 809 | 0 |

Java 版本由官方清单动态提供，不写死版本号；基岩版通过 `Mojang/bedrock-samples` Releases 精确匹配版本（Release 无附件时使用官方 tag 源码归档，来源标记 `github-source`）。

## 6. 测试与验收

```
pytest：125 passed
ruff check .：All checks passed
```

与真实贴图直接相关的测试（`tests/test_real_textures_and_modes.py`）：
1. Java 1.20.1 版本状态、方块记录字段、贴图文件存在性、覆盖率一致性。
2. 几何筛选：玻璃板 / 末地烛 / 红石线 / 台阶 / 楼梯 / 火把默认排除，完整方块保留。
3. 真实 PNG 渲染：输出尺寸 `格数×16`、Alpha 正常、像素非单色（证明使用了纹理细节）。
4. 管道覆盖率拆分：`resource_source == mojang-resource`，三项覆盖率分子/分母有效。
5. 预览切换不改变材料统计与网格数据。
6. 查看模式单击不触发编辑；编辑模式正常触发。

## 7. 未解决问题（如实说明）

1. **生物群系着色（tint）**：草方块、树叶、水等原版贴图为灰度叠层 + 群系 tint，索引目前未保存 tint 数据，真实纹理预览会显示灰度底色。材料匹配仍使用灰度均值，后续应补充 tint 元数据。
2. **基岩版几何**：`bedrock-samples` 的 resource pack 不含方块模型几何，无法判定完整立方体，`geometry` 记为 `unknown`（默认可候选仍保留，界面/报告已注明），因此基岩版没有应用完整方块筛选。
3. **资源包叠加**：附加资源包仍是“平均色”覆盖，尚未接入真实贴图渲染路径。
4. **版本覆盖**：Java 采用按需下载，未预取全部正式版本；当前实际完成 5 个 Java 版本与 4 个基岩版本。
