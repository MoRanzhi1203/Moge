# Minecraft 资源获取与索引报告

> 执行时间：2026-11-15
> 分支：`feature/mc-resource-acquisition`（未推送、未修改 `main`）
> 数据源：Mojang Piston Meta、Mojang/bedrock-samples 官方 GitHub Releases / tag 归档
> 本地资源目录：`%LOCALAPPDATA%\Moge\resources`（不进入 Git 仓库）

## 1. 实际执行结果

### Java 版（官方客户端 JAR → blockstate/model/texture 解析）

| 版本 | 方块总数 | 完整 | 不完整 | 贴图 | 染色标记 | 缺失纹理 | 来源 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1.12.2 | 407 | 407 | 0 | 350 | 17 | 0 | Mojang Piston |
| 1.16.5 | 764 | 656 | 108 | 515 | 26 | 0 | Mojang Piston |
| 1.18.2 | 900 | 791 | 109 | 595 | 29 | 0 | Mojang Piston |
| 1.20.1 | 1005 | 865 | 140 | 659 | 28 | 0 | Mojang Piston |
| 1.21.4 | 1097 | 952 | 145 | 713 | 29 | 1 | Mojang Piston |

- 全部 5 个目标版本均实际下载、SHA-1 校验、解压解析并写入 SQLite。
- 1.12.2 使用旧版 `textures/blocks` 与无前缀模型引用，已单独适配。
- 未完成的 108–145 个方块主要是技术方块、无 elements 的模型或无法可靠解析的面引用；**标记为 incomplete，不进入映射候选**。
- 染色方块（草、树叶等）记录了 tint 标记，但未模拟生物群系染色。

### Bedrock 版（官方 bedrock-samples）

| 版本 | 官方 tag | 方块总数 | 完整 | 不完整 | 贴图 | 缺失纹理 | 来源 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1.20.0 | v1.20.0.1 | 714 | 681 | 33 | 577 | 57 | GitHub tag 源码归档 |
| 1.20.80 | v1.20.80.5 | 867 | 854 | 13 | 716 | 25 | GitHub tag 源码归档 |
| 1.21.0 | v1.21.0.3 | 953 | 939 | 14 | 772 | 32 | GitHub tag 源码归档 |
| 1.21.50 | v1.21.50.7 | 1099 | 1084 | 15 | 809 | 33 | GitHub tag 源码归档 |

- 4 个目标 Bedrock 版本均已实际下载、解析并写入数据库。
- 目标 Release 的 GitHub **资产列表为空**；因此回退到同一官方 tag 的源码归档，内容包含完整 `resource_pack`。
- 该回退没有上游资产摘要；程序下载后计算 SHA-256 并写入数据库，`verify --full` 可校验本地一致性，但无法与官方摘要比对。这是本报告明确记录的限制。
- Bedrock 解析使用 `terrain_texture.json` + `resource_pack/blocks.json` + 纹理目录；新版本若存在 `blocks/*.json` 材质定义则优先使用。
- 缺失纹理与不完整方块不猜测，不进入候选。

### 索引与缓存

- 数据库：**9 个版本、7806 个方块记录、2110 张贴图特征、DB 6.85 MB**。
- 本地缓存：**462.4 MB**（JAR、Bedrock ZIP、内容寻址 PNG、数据库、版本元数据）。
- 贴图按 SHA-256 去重；同一 PNG 只保存一份。
- `verify --edition java --version 1.20.1 --full`：检查 4035 个面引用，全部存在，结果 `ok=true`。

## 2. 实现结构

```text
core/resources/
  network.py       JSON 缓存、重试、断点续传下载、SHA-1/SHA-256 校验、取消
  safezip.py       路径穿越/符号链接/成员数/解压体积校验
  features.py      均值/中位数/Lab/明暗差异/复杂度/Alpha
  database.py      SQLite：versions/textures/blocks/block_faces/resources
  catalog.py       真实方块与内置元数据合并，未知项标记 unknown
  java.py          官方清单、客户端 JAR、blockstate→model→texture
  bedrock.py       Releases/tag 映射、ZIP 解析、terrain_texture/blocks.json
  manager.py       CLI 与 GUI 共用的获取、校验、删除、重建、差异
  cli.py           list/fetch/fetch-range/sync/verify/delete/rebuild/report
ui/resource_dialog.py  版本资源管理、下载进度/取消、校验/删除/重建/对比/贴图预览
```

- 下载资源只写入 `%LOCALAPPDATA%`，不写入 Git 仓库。
- GUI 的下载、解压、解析、特征计算均在 `QThread` 后台任务中执行，支持取消与进度。
- 资源库切换：Minecraft 模式提供“自动（优先真实）/仅真实/内置近似色”三种来源；选择未下载的真实版本会提示打开资源管理。
- 真实候选集接入现有类别/获取条件/成本/朝向/透明/重力筛选；真实贴图来源在调色板标记 `[真实]`。
- 未验证的获取条件保持 `unknown`，不冒充确定事实。

## 3. CLI 使用

```powershell
# 列出 Java 正式版本（含本地状态）
python -m Moge.core.resources.cli list --edition java --limit 20

# 预览/获取单个版本
python -m Moge.core.resources.cli fetch --edition java --version 1.20.1 --dry-run
python -m Moge.core.resources.cli fetch --edition java --version 1.20.1

# Bedrock
python -m Moge.core.resources.cli fetch --edition bedrock --version 1.20.80

# 范围（按官方清单动态解析，支持 1.20 这类前缀）
python -m Moge.core.resources.cli fetch-range --start 1.20 --end 1.20.2 --dry-run

# 元数据同步、校验、删除、重建、覆盖报告
python -m Moge.core.resources.cli sync-manifest
python -m Moge.core.resources.cli verify --edition java --version 1.20.1 --full
python -m Moge.core.resources.cli rebuild --edition java --version 1.20.1
python -m Moge.core.resources.cli delete --edition java --version 1.12.2
python -m Moge.core.resources.cli report --output docs/minecraft-resource-report.json
```

安装为包后也可使用 `moge-resources` 命令。

## 4. 测试与验证

| 项目 | 结果 |
| --- | --- |
| 单元/集成测试 | **117 passed** |
| 核心覆盖率 | **83%** |
| 静态检查 | ruff 0 error |
| Java 端到端 | 1.12.2 / 1.16.5 / 1.18.2 / 1.20.1 / 1.21.4 下载、校验、解析成功 |
| Bedrock 端到端 | 1.20.80 / 1.21.50 下载、解析成功 |
| SQLite 去重 | 相同 SHA-256 只保留一条贴图与一份文件 |
| 损坏缓存修复 | `verify` / `delete` / `rebuild` 已实现并测试 |
| GUI 真实模式 | 1.20.1 真实候选集生效，调色板标记 `[真实]`；资源管理对话框正常打开（103 个 Java 正式版本行） |
| GUI 下载任务 | 后台 Worker 的进度与取消有单元测试 |
| 打包 | PyInstaller 成功，**241.2 MB / 220 files**；exe 启动成功（首次约 13 秒，受构建体积与系统扫描影响） |
| 安全 | ZIP 路径穿越拒绝、成员/体积上限、哈希校验、只读解析、不落盘到仓库 |

## 5. 失败与未完成项

1. **Bedrock 无官方资产摘要**：目标 Release 无附件，只能使用官方 tag 源码归档；本地 SHA-256 只能证明缓存未变，不能证明与官方发布字节一致。
2. **无自动重试无限循环**：网络请求最多 3 次重试；失败版本记录 `failed`，继续处理其他版本。
3. **Bedrock 安装包/版本覆盖**：4 个目标版本 1.20.0、1.20.80、1.21.0、1.21.50 均已下载解析；未覆盖其它历史版本。
4. **Java 不完整方块**：技术方块、复杂模型、无 elements 模型未强行猜测，保持 incomplete。
5. **染色/动画**：记录 tint 与动画标记，但未做生物群系染色、动画帧、透明叠底的真实渲染。
6. **Bedrock 面定义**：使用 `blocks.json`/材质实例的纹理键；未解析完整几何与多面模型。
7. **GUI 大版本列表**：Java 正式版约 103 行，已支持搜索；未做虚拟列表优化。
8. **CI**：分支未推送，GitHub Actions 未运行；本地完成同等 ruff/pytest/构建验证。

## 6. 任务日志

1. 审计：分支 `feature/moge-2-modes`、97 项测试、ruff 0；新建 `feature/mc-resource-acquisition`。
2. 连通性：Mojang manifest 923 个版本、Bedrock Releases API 可读。
3. 实现核心：下载/哈希/断点续传、安全 ZIP、SQLite、颜色特征、Java/Bedrock 解析、CLI。
4. 修复：`minecraft:` 命名空间、Alpha 贴图 reshape、UTF-8 BOM、JSONC 注释、1.12 无前缀模型、Bedrock `blocks.json` 回退。
5. 端到端：Java 5 版本、Bedrock 4 版本真实下载解析；`verify` 4035 面通过。
6. GUI：真实候选集、资源管理对话框、后台 Worker 进度/取消；打包与启动验证。
7. 回归：117 项测试、83% 覆盖率、ruff 0、PyInstaller 241.2 MB。

## 7. 复现

```powershell
git switch feature/mc-resource-acquisition
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
python -m Moge.core.resources.cli sync-manifest
python -m Moge.core.resources.cli fetch --edition java --version 1.20.1
python -m Moge.core.resources.cli fetch --edition bedrock --version 1.20.80
python main.py
```
