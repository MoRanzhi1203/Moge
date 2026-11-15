# Moge_Texture_Fetcher 下载与导入报告（Java + Bedrock 官方 Tag 归档）

- 工具版本：`get_textures.py` 1.1（2026-11-15 修订）
- 压缩包：`e:\PyQt5_demo\Moge\Moge_Texture_Fetcher.zip`
- 解压目录：`e:\PyQt5_demo\Moge\Moge_Texture_Fetcher`
- 下载输出：`Moge_Texture_Fetcher\downloaded_textures`
- 导入目标：Moge 资源库 `C:\Users\MSIPC\AppData\Local\Moge\resources\index.db`
- 执行命令：
  - 全量：`python get_textures.py --java 1.12.2 1.16.5 1.18.2 1.20.1 1.21.4 --bedrock 1.20.0 1.20.80 1.21.0 1.21.50`
  - 基岩专项：`python get_textures.py --java --bedrock 1.20.0 1.20.80 1.21.0 1.21.50`

> 原版资源仅保存在本机；`Moge_Texture_Fetcher/` 已在 `.gitignore` 中，不会提交游戏素材。

## 1. 下载器修复内容

`Moge_Texture_Fetcher/get_textures.py` 新增/修改：

1. **Bedrock 获取顺序**
   - 精确匹配非预览 GitHub Release（`tag == version` 或 `version.patch`）。
   - Release 带 ZIP 资产时优先使用，`-full` 优先，`source_kind = release-asset`。
   - Release 无 ZIP 资产时，使用该 Release 的官方 `tag_name` 下载 `https://github.com/Mojang/bedrock-samples/archive/refs/tags/<tag>.zip`，`source_kind = github-tag-archive`。
   - Release 完全缺失时，再查询 Tags API 精确匹配；仍不存在则失败，**不回退其它版本**。
2. **真实 PNG 校验**：检查 PNG 签名与 IHDR，宽高必须有效，拒绝文本/LFS 内容。
3. **Git LFS 识别**：检测 `version https://git-lfs.github.com/spec/v1` 或含 `git-lfs.github.com` 的短文本；发现即抛 `IncompleteResourceError`，不会当贴图使用。
4. **资源完整性**：要求归档含 `terrain_texture.json` 且至少 1 张可解码 PNG；否则报告 `incomplete-resources`。
5. **资源索引**：为每个 Tag 输出 `asset_index.json`（相对路径 + SHA-256 + 宽高）。
6. **状态区分**：`result.json` / `download_report.json` 记录 `status`、`source_kind`（release-asset / github-tag-archive / mojang-piston）、`from_cache`、`reason_code`。
7. **Java 能力保留**：原有 Mojang 清单下载逻辑不变，仅补充报告字段与 SHA-256。

自检结果：构造含 LFS 指针的测试 ZIP，`inspect_bedrock_archive` 正确识别指针，`valid_png_count = 0`，不会误判为有效贴图。

## 2. 实际下载结果（9/9 成功）

### 2.1 Java（Mojang Piston 清单）

| 版本 | 来源 | PNG | 缓存 |
|---|---|---|---|
| Java 1.12.2 | mojang-piston | 478 | 是 |
| Java 1.16.5 | mojang-piston | 694 | 是 |
| Java 1.18.2 | mojang-piston | 818 | 是 |
| Java 1.20.1 | mojang-piston | 928 | 是 |
| Java 1.21.4 | mojang-piston | 1039 | 是 |

### 2.2 Bedrock（官方 Git Tag 源码归档）

四个版本的官方 Release 均**没有 ZIP 附件**，因此全部走官方 Tag 源码归档：

| 请求版本 | 官方 Tag | 来源类型 | 有效 PNG | 解压文件 | 归档 SHA-256 |
|---|---|---|---|---|---|
| 1.20.0 | `v1.20.0.1` | github-tag-archive | 1004 | 1054 | `f5d1501be2b8b76f7efcdd6a71aef76580593dd6a1afcb3abe2b023b081e0eab` |
| 1.20.80 | `v1.20.80.5` | github-tag-archive | 1004 | 1054 | `325816c1d8dfd2fd848539627ab6a3e13b8d2d760b87b2652707e302cf99a99d` |
| 1.21.0 | `v1.21.0.3` | github-tag-archive | 1094 | 1144 | `3b174ca4fe308426a3cff873f57d72c52e667cda80420ef8eed15aae83f63bee` |
| 1.21.50 | `v1.21.50.7` | github-tag-archive | 1123 | 1177 | `a3d75f91362b256e06cc1dae0fba949f91a8d9102ebcdbd438b74cd9ad2c50a1` |

归档大小分别为 85.6 / 91.2 / 97.1 / 101.6 MB。每版本目录下生成 `result.json` 与 `asset_index.json`。

失败数：0。`下载失败` / `资源不完整` / `无官方 Release 附件` 已分别记录，不再把“无附件”等同于“无法下载”。

## 3. 导入 Moge 资源库

使用 Fetcher 下载的归档重新解析（`bedrock.parse_bedrock_zip`），写入内容寻址贴图库：

| 版本 | Tag | 方块状态 | 有真实贴图 | 贴图文件 | verify 缺失 | 覆盖率 |
|---|---|---|---|---|---|---|
| Bedrock 1.20.0 | v1.20.0.1 | 714 | 681 | 577 | 0 | 681/714 |
| Bedrock 1.20.80 | v1.20.80.5 | 867 | 854 | 716 | 0 | 854/867 |
| Bedrock 1.21.0 | v1.21.0.3 | 953 | 939 | 772 | 0 | 939/953 |
| Bedrock 1.21.50 | v1.21.50.7 | 1099 | 1084 | 809 | 0 | 1084/1099 |

内容哈希去重实测：

```
textures_before = 2110
textures_after  = 2110
new_unique_textures = 0
existing_reused = 2110
content_addressed = True   # 文件名 = SHA-256
```

说明这些 Tag 归档中的贴图与库中已有官方文件字节一致，按 SHA-256 直接复用，未重复存储。

方块映射抽检（路径位于 `resources/textures/<sha256>.png`）：

| 版本 | stone SHA-256（前 16 位） | glass SHA-256（前 16 位） | 文件存在 / verified |
|---|---|---|---|
| 1.20.0 | `12f1c99206df13e9` | `d05046fbbde17728` | 是 / 1 |
| 1.20.80 | `12f1c99206df13e9` | `d05046fbbde17728` | 是 / 1 |
| 1.21.0 | `12f1c99206df13e9` | `d05046fbbde17728` | 是 / 1 |
| 1.21.50 | `12f1c99206df13e9` | `d05046fbbde17728` | 是 / 1 |

导入明细：[bedrock-import-summary.json](evidence/bedrock-import-summary.json)

## 4. 真实纹理预览验证

对四个基岩版本执行真实处理管线（32×24 网格），所有材料条目都必须带存在的 PNG：

| 版本 | 候选方块 | 使用材料 | 带真实贴图路径 | 来源 |
|---|---|---|---|---|
| Bedrock 1.20.0 | 346 | 44 | 346 / 346 | mojang-resource |
| Bedrock 1.20.80 | 481 | 65 | 481 / 481 | mojang-resource |
| Bedrock 1.21.0 | 526 | 67 | 526 / 526 | mojang-resource |
| Bedrock 1.21.50 | 582 | 70 | 582 / 582 | mojang-resource |

截图：

- [Bedrock 1.20.0](evidence/fetcher-texture-preview-bedrock-1.20.0.png)
- [Bedrock 1.20.80](evidence/fetcher-texture-preview-bedrock-1.20.80.png)
- [Bedrock 1.21.0](evidence/fetcher-texture-preview-bedrock-1.21.0.png)
- [Bedrock 1.21.50](evidence/fetcher-texture-preview-bedrock-1.21.50.png)
- [GUI 真实纹理预览（Bedrock 1.21.50）](evidence/fetcher-gui-bedrock-texture-preview.png)

## 5. 测试结果

```
pytest：125 passed
ruff check .：All checks passed
```

- Java 回归：`python get_textures.py --java 1.20.1 --bedrock` 缓存命中并成功（928 PNG），Java 下载能力无回归。
- 基岩 LFS 自检：含 Git LFS 指针的 ZIP 被识别，有效 PNG 数为 0，不会导入错误贴图。
- 资源库校验：4 个基岩版本 `verify()` 缺失 0；Moge 既有真实贴图与预览测试全部通过。

## 6. 结论

1. Bedrock 四个预设版本已由修复后的下载器**实际下载**官方 Git Tag 源码归档（非现有资源库反向复制）。
2. 有效 PNG：1004 / 1004 / 1094 / 1123；归档 SHA-256 已记录；无 LFS 指针。
3. 已通过内容哈希导入 Moge，2110 张贴图全部复用，无重复存储；四版本纹理预览均使用真实 PNG。
4. Java 五个版本下载能力保留，全量复跑 9/9 成功。
5. 仍存在的上游限制：`bedrock-samples` Release 不挂 ZIP 资产，因此来源类型为 `github-tag-archive`；这属于官方发布方式，不是资源缺失。
