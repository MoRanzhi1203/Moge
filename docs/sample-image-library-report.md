# Moge 2.0 内置测试图片与示例图库验收报告

- 验收日期：2026-11-15
- 工作目录：`e:\PyQt5_demo\Moge`
- 资源清单：`assets/samples/manifest.json`（19 条）
- 许可与署名：`assets/samples/CREDITS.md`
- 获取记录：`docs/sample-images-acquisition.json`
- GUI 证据：`docs/evidence/`

## 1. 结果摘要

| 项目 | 结果 |
|---|---|
| 实际下载并入库图片 | 19 张（Wikimedia Commons 17 张 + 程序生成 2 张） |
| 图片总体积 | 7,942,706 字节（约 7.57 MiB） |
| 缩略图 | 19 张，783,755 字节 |
| 分类 | 8 类：portraits 3、animals 3、landscapes 3、flowers 2、architecture 2、illustrations 2、transparent 2、synthetic 2 |
| 许可构成 | Public domain 7、CC0 5、CC BY 2.0 3、CC BY 4.0 2、CC0-1.0 (generated) 2 |
| 禁止许可 | 未使用任何 SA / NC / ND 作品 |
| 哈希校验 | 19/19 与 manifest 中的 SHA-256 一致 |
| PyInstaller 资源 | `dist/Moge/_internal/assets/samples` 内含 19 张图片与 manifest |
| 自动化测试 | 155 passed（pytest） |
| 静态检查 | `ruff check .` → All checks passed |
| GUI 验收 | 欢迎页、图库、加载、三模式、透明图、无图色卡、色卡详情均通过 |

## 2. 获取与许可核验流程

1. 通过 Wikimedia Commons `action=query`、`generator=search`、`prop=imageinfo`
   读取每个候选文件的 `extmetadata`，仅接受 CC0、Public Domain、CC BY（2.0/4.0）
   许可；含 SA、NC、ND 或无法识别的许可直接跳过。
2. 记录原始页面、作者、许可名称与许可链接，再执行下载。
3. 下载后按最长边 1400 像素等比缩放（保留透明通道），生成 360 像素缩略图。
4. SHA-256 以**实际保存后的文件**计算，避免下载负载与落盘文件不一致。
5. 图片许可独立于 Moge 软件许可；完整署名写入 `CREDITS.md` 与 manifest。
6. 获取脚本：`scripts/fetch_sample_images.py`，可重复执行并自动跳过重复哈希。

## 3. 许可清单（19 张）

| 文件 | 分类 | 标题 / 来源 | 作者 | 许可 | 尺寸 | 字节 | SHA-256（前 16 位） |
|---|---|---|---|---|---|---|---|
| synthetic/gradient_rgb.png | synthetic | RGB 渐变（程序生成） | Moge Project | CC0-1.0 (generated) | 1024×768 | 184,245 | `5af29958fc4a6f6b` |
| synthetic/color_matrix.png | synthetic | 色块与灰阶矩阵（程序生成） | Moge Project | CC0-1.0 (generated) | 960×720 | 61,073 | `23fd6ac54cb08057` |
| portraits/portraits-1.jpg | portraits | [1927 Portrait-von-Frieda-Gertrud-Claus.jpg](https://commons.wikimedia.org/wiki/File:1927_Portrait-von-Frieda-Gertrud-Claus.jpg) | Friedrich Eduard Claus (1874-1954) | Public domain | 871×1400 | 172,568 | `1817450a9c32e33f` |
| portraits/portraits-2.png | portraits | [Antonín Cífka - portrait photograph (c. 1880).png](https://commons.wikimedia.org/wiki/File:Anton%C3%ADn_C%C3%ADfka_-_portrait_photograph_(c._1880).png) | Unknown author | Public domain | 726×693 | 704,774 | `84dd4efb7fda0900` |
| portraits/portraits-3.jpg | portraits | [August Petrtýl, Sokol member from Chicago](https://commons.wikimedia.org/wiki/File:August_Petrt%C3%BDl,_Sokol_member_from_Chicago_-_portrait_photograph_(J._Tom%C3%A1%C5%A1).jpg) | Jan Tomáš | Public domain | 847×1400 | 171,775 | `c6941d677ce61b31` |
| animals/animals-1.jpg | animals | [A photograph of a cat lying down 0002.jpg](https://commons.wikimedia.org/wiki/File:A_photograph_of_a_cat_lying_down_0002.jpg) | Asabae2752 | CC0 | 1400×1050 | 674,904 | `a58ce93115ded54c` |
| animals/animals-2.jpg | animals | [An Afghan elder and his cat](https://commons.wikimedia.org/wiki/File:An_Afghan_elder_and_his_cat_sit_outside_his_store_at_the_Anaba_bazaar_in_Panjshir_province,_Afghanistan.jpg) | Sgt. Teddy Wade | Public domain | 1065×1400 | 410,613 | `742c91702f4c8004` |
| animals/animals-3.jpg | animals | [Cat in Efremov, Russia1.jpg](https://commons.wikimedia.org/wiki/File:Cat_in_Efremov,_Russia1.jpg) | Юрий Д.К. | CC BY 4.0 | 1258×1400 | 383,881 | `ca188cdb8e2b385c` |
| landscapes/landscapes-1.png | landscapes | ["Wind Mountain" Columbia R - NARA](https://commons.wikimedia.org/wiki/File:%22Wind_Mountain%22_Columbia_R_-_NARA_-_102278851_(page_1).png) | James Madison Alden | Public domain | 1400×898 | 2,347,731 | `1f1e02e716ecb875` |
| landscapes/landscapes-2.jpg | landscapes | [Anza-Borrego Desert State Park landscape](https://commons.wikimedia.org/wiki/File:Anza-Borrego_Desert_State_Park_landscape_-_2022-12.jpg) | John D. from Pasadena, USA | CC BY 2.0 | 1400×656 | 286,412 | `309b6c876f03c047` |
| landscapes/landscapes-3.jpg | landscapes | [Carl Spitzweg - Mountain Landscape](https://commons.wikimedia.org/wiki/File:Carl_Spitzweg_(1808-1885)_-_Mountain_Landscape_-_WA1954.70.164_-_Ashmolean_Museum.jpg) | Carl Spitzweg | Public domain | 944×663 | 136,892 | `4cced48a287ad571` |
| flowers/flowers-1.jpg | flowers | [Flower close-up filter 2](https://commons.wikimedia.org/wiki/File:Flower_close-up_filter_2_(2433589147).jpg) | Anderson Mancini | CC BY 2.0 | 1400×933 | 225,089 | `6327df916948b064` |
| flowers/flowers-2.jpg | flowers | [Vermilion flower close-up](https://commons.wikimedia.org/wiki/File:Vermilion_flower_close-up_(224534328).jpg) | Audrey | CC BY 2.0 | 1024×768 | 152,154 | `8d5f53a1890f9f6c` |
| architecture/architecture-1.jpg | architecture | [AUS Perth, Fremantle, Cliff Street 020.jpg](https://commons.wikimedia.org/wiki/File:AUS_Perth,_Fremantle,_Cliff_Street_020.jpg) | -wuppertaler | CC BY 4.0 | 1400×960 | 361,978 | `565499cfcd9708ac` |
| architecture/architecture-2.jpg | architecture | [Building in Paulista Avenue 09.jpg](https://commons.wikimedia.org/wiki/File:Building_in_Paulista_Avenue_09.jpg) | Wilfredor | CC0 | 1400×1175 | 572,577 | `58c27522e698022a` |
| illustrations/illustrations-1.jpg | illustrations | [Celtique (civilisation) - Celtic](https://commons.wikimedia.org/wiki/File:Celtique_(civilisation)_-_Celtic_-_Public_domain_illustration_from_Larousse_du_XX%C3%A8me_si%C3%A8cle_1932.jpg) | EN NOIR & BLANC | CC0 | 1400×1050 | 684,618 | `29df740bcb137e26` |
| illustrations/illustrations-2.jpg | illustrations | [Cerf - deer](https://commons.wikimedia.org/wiki/File:Cerf_-_deer_-_Public_domain_illustration_from_Larousse_du_XX%C3%A8me_si%C3%A8cle_1932.jpg) | EN NOIR & BLANC | CC0 | 750×735 | 168,371 | `edb90e48a6004fd8` |
| transparent/transparent-1.png | transparent | [Audemars Piguet logo transparent bg.png](https://commons.wikimedia.org/wiki/File:Audemars_Piguet_logo_transparent_bg.png) | Jeromluther | CC0 | 1400×385 | 114,140 | `50574b89ea33817d` |
| transparent/transparent-2.png | transparent | [Emile Foundation logo Transparent 1200w.png](https://commons.wikimedia.org/wiki/File:Emile_Foundation_logo_Transparent_1200w.png) | Unknown author | Public domain | 1200×422 | 128,911 | `aa65597e9e4e3488` |

> 完整 SHA-256、许可链接、原始尺寸与推荐网格见 `assets/samples/manifest.json`。
> 透明样本 `transparent-1.png` 的 alpha 最小/最大值为 0 / 255，已确认透明通道未被丢弃。

## 4. 功能实现

### 4.1 欢迎页与入口

- 中央区域改为 `QStackedWidget`，初始显示欢迎页，而不是空白画布。
- 欢迎页提供三个入口：**打开图片**、**打开工程**、**使用示例图片**。
- 工具栏与文件菜单均新增“示例图库”动作，可直接打开图库。

### 4.2 示例图库

- 缩略图网格：19 张图片、8 个分类 + “全部分类”，支持标题/作者/分类关键字搜索。
- 右侧预览 + 许可信息：标题、分类、作者、许可、原始页面、尺寸、推荐网格、SHA-256 前缀。
- 双击或“使用推荐参数”直接加载到当前工作台；“保留当前参数”沿用现有网格。
- 已有画布内容时先弹出覆盖确认，避免误丢失未保存作品。

### 4.3 加载与三种模式

- 示例图通过 `open_image(path, suggested_spec=..., keep_grid=...)` 进入现有处理管线。
- 人物样本 `portraits-1.jpg`（871×1400）自动推荐 40×64 网格，三种模式均能完成处理。
- 透明 PNG 使用 `QImage.Format_RGBA8888` 读入，保留 alpha。

### 4.4 左侧色卡统计简化

- 左侧仅保留一行摘要：`SQLite 色卡 · {品牌} {系列} · {N} 色 · MIT`。
- 新增“色卡详情...”按钮，详细来源、可信度、材质、系列与冲突示例移至
  `BeadPaletteInfoDialog`。

### 4.5 右侧调色板范围切换

- 新增“已用颜色 / 全部颜色”下拉。
- 无图片时切换为拼豆模式并选择“全部颜色”，仍可浏览 221 项品牌色卡。
- 保留隐藏的 `palette_used_only` 兼容既有测试与旧状态恢复逻辑。

### 4.6 离线与打包

- `core/samples.py` 统一解析资源目录：
  - 打包环境优先 `sys._MEIPASS/assets`；
  - 开发环境回退到仓库 `assets/`。
- 图库只读取本地 manifest、图片与缩略图，不发起网络请求，断网可用。
- `Moge.spec` 增加 `assets` 数据目录；`pyproject.toml` 增加 `assets/samples/**/*` 包数据。
- 重新构建后 `dist/Moge/_internal/assets/samples` 中 19 张图片、缩略图与 manifest 均存在。

## 5. 验证记录

### 5.1 自动化测试

```text
python -m pytest -q
155 passed in 26.27s

.\.venv\Scripts\ruff.exe check .
All checks passed!
```

新增 `tests/test_sample_library.py` 覆盖：

- manifest 条目数、分类、许可白名单；
- 文件存在性与 SHA-256 一致性；
- 尺寸不超长边 1400、缩略图存在；
- 透明图 alpha 范围；
- 推荐网格合法；
- PyInstaller `_MEIPASS` 资源路径解析；
- 欢迎页三入口、图库 19 个缩略图/9 个分类项；
- 示例加载、三模式处理、无图品牌色卡、关闭时内存释放。

### 5.2 真实 GUI 验收

验收脚本启动真实 Qt 窗口（非纯离屏），在示例图库中向 `portraits-1` 缩略图发送
完整的双击事件序列，触发对话框的 `itemDoubleClicked → accept` 真实路径，随后进入
`open_sample_library → open_image` 加载流程。输出
`docs/evidence/sample-library-log.txt`：

```text
manifest images: 19
welcome buttons: 打开图片 打开工程 使用示例图片
dialog entries: 19 categories: 9
after double-click: accepted=1 recommended=True
double-click loaded: portraits-1.jpg grid 40x64
loaded: 处理完成：kmeans_lab · 57 ms
mode pixel grid GridSpec(width=40, height=64) palette 16
mode minecraft grid GridSpec(width=40, height=64) palette 348
mode beads grid GridSpec(width=40, height=64) palette 221
transparent sample alpha min/max: 0 255
catalog palette without image: 221 scope all
```

截图：

- [欢迎页](evidence/sample-welcome.png)
- [示例图库](evidence/sample-gallery.png)
- [示例图加载后](evidence/sample-loaded.png)
- [像素模式](evidence/sample-mode-pixel.png)
- [Minecraft 模式](evidence/sample-mode-minecraft.png)
- [拼豆模式](evidence/sample-mode-beads.png)
- [透明图](evidence/sample-transparent.png)
- [无图状态品牌色卡](evidence/sample-palette-no-image.png)
- [色卡详情](evidence/sample-bead-info.png)

### 5.3 打包验证

- `pyinstaller --noconfirm Moge.spec` 构建成功。
- 包内示例图片 19 张，manifest 与 CREDITS 均存在。
- 逐文件 SHA-256 与 manifest 一致（19/19）。

## 6. 修改文件

新增：

- `scripts/fetch_sample_images.py`
- `core/samples.py`
- `ui/sample_dialog.py`
- `ui/bead_info_dialog.py`
- `tests/test_sample_library.py`
- `assets/samples/`（manifest、CREDITS、8 个分类目录、19 张图片、19 张缩略图）
- `docs/evidence/sample-*.png`、`docs/evidence/sample-library-log.txt`
- `docs/sample-images-acquisition.json`
- 本报告

修改：

- `ui/main_window.py`
- `pyproject.toml`
- `Moge.spec`

## 7. 已知限制

- Wikimedia Commons 搜索结果的标题/作者为社区填写，个别作者显示为 “Unknown author”，
  已在 manifest 与 CREDITS 中如实保留。
- 部分图片为适配体积执行了等比缩放（长边 ≤1400），原始尺寸记录在 manifest 的
  `original_width/original_height` 字段。
- 图库分类为英文目录名（portraits/animals/...），界面暂未做中文别名映射。
