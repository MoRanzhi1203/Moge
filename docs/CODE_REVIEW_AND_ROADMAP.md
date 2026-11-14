# 墨格（Moge）代码审查与优化路线图

> 审查对象：`e:\PyQt5_demo\Moge`
> 审查日期：2026-11-14
> 审查方式：全量源码静态审查 + 关键路径实测基准 + 依赖/打包/Git 度量
> 实测环境：Windows，conda env `pyqt`，Python 3.9.21，NumPy 2.0.2，OpenCV 4.11.0，scikit-learn 1.6.1，PyQt5 5.15.9

---

## 0. 结论摘要

项目功能链路清晰（打开 → 缩放 → 像素化 → 颜色聚类 → 保存），代码规模小（约 25 KB / 4 个模块），但存在 **3 类必须先修的问题**：

1. **功能正确性缺陷**：保存 PNG 实际写入 JPEG 数据；缩放参数类型不匹配导致缩放完全不生效；三种取整算法本身实现错误。
2. **性能与响应性缺陷**：全部计算跑在 GUI 主线程；1080p 频数像素化约 11.9 s、KMeans 约 496 s（噪声图最坏情况），界面全程假死、进度条不刷新、取消无效。
3. **可维护性与交付缺陷**：入口依赖父目录 `sys.path`（在项目根直接 `python main.py` 无法启动，已实测）；日志写入 `_MEIPASS` / 错误嵌套目录；`dist/`、`build/` 被 Git 跟踪（.git 372.6 MB、1614 个跟踪文件）；产物 505 MB 中约 140 MB 是未真正使用的 sklearn/scipy/pandas/matplotlib。

优化后可达成的量化目标（详见第 10 节）：

| 指标 | 现状 | 目标 |
| --- | --- | --- |
| 1080p 均值像素化 | ≈1.28 s（Python 逐块） | ≤0.2 s |
| 1080p 频数像素化 | ≈11.9 s | ≤2 s |
| 1080p KMeans k=16 | ≈496 s（最坏） | ≤5 s |
| UI 阻塞 | 全程阻塞 | 主线程无 >100 ms 阻塞，可取消 |
| 打包产物 | 504.9 MB | ≤250 MB |
| Git 仓库 | 372.6 MB | ≤20 MB（历史清理后） |
| 保存格式 | PNG 存成 JPEG | 格式正确、无损 |

> **复测结果（2026-11-15，Phase 2/3 完成后）**：1080p 均值像素化 **97 ms**、频数像素化 **893 ms**、KMeans 聚类 **736 ms**（输出颜色数 16）；打包产物 **238.8 MB**（全新 headless 环境构建，原 504.9 MB）；打包后的程序启动验证通过，日志正常落盘。

---

## 1. 项目概况

### 1.1 结构

```text
Moge/
├── main.py                     # 入口：单实例检查 + QApplication + MainWindow
├── Moge.spec                   # PyInstaller 配置（绝对路径 pathex）
├── environment.yml             # conda 环境（含 build hash，不可跨平台复现）
├── core/image_processor.py     # 算法：缩放、均值/频数像素化、KMeans 聚类
├── ui/main_window.py           # 主窗口：UI + 文件读写 + 算法编排（全部同线程）
├── utils/logger_config.py      # 日志配置（路径解析有缺陷）
├── build/  dist/               # 构建产物（被 Git 跟踪）
└── Moge/utils/logs/app.log     # 运行时日志误写入包目录，产生同名嵌套目录
```

### 1.2 技术栈与依赖实况

- GUI：PyQt5 5.15.9（pyqt5-qt5 5.15.2）
- 图像：OpenCV 4.11.0、NumPy 2.0.2
- 聚类：scikit-learn 1.6.1
- 打包：PyInstaller 6.11.1，UPX=True
- **声明但代码中完全未使用**：pandas、matplotlib、seaborn、pyqtgraph、qdarkstyle、requests、python-dotenv、pyqt5-tools/qt5-applications（仅开发工具）
- 实测产物体积构成（`dist/Moge_v1.0.0_win10/_internal`）：

| 包 | 体积 | 是否实际需要 |
| --- | --- | --- |
| cv2 | 98.2 MB | 需要（可用 headless 版减小） |
| PyQt5 | 75.3 MB | 需要（可裁未用模块） |
| scipy + scipy.libs | 94.2 MB | 仅为 sklearn KMeans 服务 |
| numpy + numpy.libs | 38.4 MB | 需要 |
| sklearn | 18.1 MB | 可被 cv2.kmeans / PIL 替代 |
| pandas | 17.2 MB | 未使用 |
| matplotlib | 11.0 MB | 未使用 |
| PIL | 3.0 MB | 间接依赖（可转正为量化方案） |

---

## 2. 审查发现总览

优先级定义：**P0 = 功能错误/安全/不可用**；**P1 = 性能或交付显著受损**；**P2 = 可维护性与工程质量**。

| ID | 优先级 | 问题 | 位置 |
| --- | --- | --- | --- |
| H1 | P0 | 保存图片永远按 JPEG 编码，选择 PNG 会产出损坏文件 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L167-L182) |
| H2 | P0 | 缩放参数类型不匹配，缩放功能完全不生效 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L258-L262)、[image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L25-L40) |
| H3 | P0 | 三种取整算法实现错误（"向上取整"实际向下、另两种完全相同） | [image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L25-L36) |
| H4 | P0 | 单实例保护实际失效；且在 `QApplication` 创建前弹 `QMessageBox` | [main.py](file:///e:/PyQt5_demo/Moge/main.py#L14-L36) |
| H5 | P0 | 日志写入包内嵌套目录；打包后写入只读 `_MEIPASS`，日志丢失 | [logger_config.py](file:///e:/PyQt5_demo/Moge/utils/logger_config.py#L15-L33) |
| H6 | P0 | 入口依赖父目录在 `sys.path`，项目根执行 `python main.py` 直接失败（实测） | [main.py](file:///e:/PyQt5_demo/Moge/main.py#L10-L11) |
| H7 | P1 | 重计算在 GUI 线程同步执行，界面假死、进度不刷新、取消无效 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L244-L295) |
| H8 | P1 | KMeans 对全分辨率像素聚类，1080p 实测估算约 496 s | [image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L136-L155) |
| H9 | P1 | 频数像素化纯 Python 逐像素循环，1080p 约 11.9 s | [image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L91-L133) |
| H10 | P1 | 均值像素化 Python 逐块循环，1080p 约 1.28 s | [image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L63-L75) |
| M1 | P1 | 依赖与产物严重臃肿（505 MB），可裁剪约 140 MB 以上 | environment.yml、Moge.spec |
| M2 | P1 | `dist/`、`build/` 被 Git 跟踪，仓库 372.6 MB；LFS 只覆盖 1 个文件 | .gitignore、.gitattributes |
| M3 | P1 | 环境不可复现：无 requirements/pyproject，Python 3.9 已 EOL | environment.yml |
| M4 | P1 | 打包配置硬编码 `E:/` 路径，UPX 易触发杀软误报，无版本信息 | [Moge.spec](file:///e:/PyQt5_demo/Moge/Moge.spec#L4-L16) |
| M5 | P2 | 图像格式/透明度处理不完整：强制 RGB888 丢弃 alpha，频数算法含死代码 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L142-L146)、[image_processor.py](file:///e:/PyQt5_demo/Moge/core/image_processor.py#L105-L108) |
| M6 | P2 | 重复显示缩放：`setPixmap` 两次；窗口 resize 后不重绘 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L207-L215) |
| M7 | P2 | 冗余内存拷贝：原图 copy 后再 resize，算法内部再 copy/astype | main_window.py:251、image_processor.py:60、88 |
| M8 | P2 | 无输入尺寸上限，超大图/解压炸弹可致 OOM | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L120-L149) |
| M9 | P2 | 异常路径不关闭模态进度框；取消按钮未接线；小图 K 过大直接抛 ValueError | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L297-L305) |
| M10 | P2 | UI 与算法强耦合，无 service/worker/config 层 | ui/main_window.py 整体 |
| L1 | P2 | 日志器命名重复（`Moge.Moge.ui.main_window`）；50MB×7 日志无清理策略 | [logger_config.py](file:///e:/PyQt5_demo/Moge/utils/logger_config.py#L28-L66) |
| L2 | P2 | `cluster_group` 被重复 `addWidget`；无用判断与未用变量 | [main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L95-L102) |
| L3 | P2 | 无测试、无 lint/format/type 配置、无 CI、README 仅 1 行 | 项目根 |
| L4 | P2 | 未启用高 DPI 缩放，高分屏显示模糊；无全局异常钩子 | [main.py](file:///e:/PyQt5_demo/Moge/main.py#L36-L41) |

---

## 3. P0 问题详解与修复方案

### H1 保存图片格式错误（数据损坏）

现状：无论用户选择 PNG 还是 JPEG，都执行 `cv2.imencode('.jpg', ...)` 并写入用户给的路径（[main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L167-L182)）。选择 `a.png` 会得到扩展名 PNG、内容 JPEG 的损坏文件；同时忽略 `imencode` 返回值，写入失败也被吞掉。

修复要点：

```python
path, selected_filter = QFileDialog.getSaveFileName(
    self, "保存图片", "", "PNG文件 (*.png);;JPEG文件 (*.jpg *.jpeg)"
)
if not path:
    return
ext = Path(path).suffix.lower()
if ext not in {".png", ".jpg", ".jpeg"}:
    ext = ".png" if "PNG" in selected_filter else ".jpg"
    path += ext
save_img = cv2.cvtColor(self.processed_img, cv2.COLOR_RGB2BGR)
params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext in {".jpg", ".jpeg"} else [cv2.IMWRITE_PNG_COMPRESSION, 3]
ok, buf = cv2.imencode(ext, save_img, params)
if not ok:
    raise IOError("图像编码失败")
buf.tofile(path)
```

收益：修复损坏文件；PNG 支持无损与透明（配合 M5）。成本：S。

### H2 + H3 缩放功能失效与算法错误

现状（已实测验证）：

- `process_image` 传入 `self.resize_method.currentIndex()`（int），而 `img_resize` 与中文字符串比较 → 永远落入 `else`，**完全不缩放**。输入 `1001×1999`，任何选项输出仍为 `1001×1999`。
- `math.ceil(h // block_size) * block_size` 中 `//` 已向下取整，`ceil` 无效 → "向上取整" 实际是向下取整（`1001 → 1000`）。
- "四舍五入" 写成 `math.floor(h / block_size) * block_size`，与 "向下取整" 完全相同。

修复要点：用枚举/常量代替中文字符串，UI 与算法共用同一映射；公式改为：

```python
class ResizeMode(Enum):
    CEIL = "向上取整"
    FLOOR = "向下取整"
    ROUND = "四舍五入"

def _fit(n: int, bs: int, mode: ResizeMode) -> int:
    if mode is ResizeMode.CEIL:
        return math.ceil(n / bs) * bs
    if mode is ResizeMode.ROUND:
        return max(bs, round(n / bs) * bs)
    return max(bs, (n // bs) * bs)
```

收益：功能恢复正确；消除一类"比较字符串"引发的隐性 bug。成本：S。

### H4 单实例检查失效 + Qt 初始化顺序错误

两个独立缺陷：

1. `QSharedMemory` 是局部变量，函数返回即析构并 detach，共享内存段被释放 → 后续实例仍可创建，**单实例保护形同虚设**。
2. `QMessageBox.warning` 在 `QApplication` 创建之前调用（[main.py](file:///e:/PyQt5_demo/Moge/main.py#L36)），Qt 控件在无应用对象时行为未定义，可能崩溃或无提示。

修复要点（推荐 `QLocalServer`，Windows/Linux 行为一致；若保留共享内存，必须把对象保存到模块级/窗口属性并显式 `detach`）：

```python
app = QApplication(sys.argv)          # 先创建
guard = SingleInstanceGuard("Moge")   # 模块级/实例级持有
if guard.already_running():
    QMessageBox.warning(None, "警告", "应用程序已经在运行。")
    return 1
```

收益：单实例真正生效，启动路径稳定。成本：S。

### H5 日志路径缺陷

现状：`get_resource_path` 以 `utils/` 的父目录为基准，再拼 `"Moge/utils/logs"`，实测得到 `e:\PyQt5_demo\Moge\Moge\utils\logs`（源码树内产生同名嵌套目录）。打包后 `sys._MEIPASS` 是只读临时目录，进程退出即删除：

- 日志写不进去（或权限异常）；
- 安装到 `Program Files` 时非管理员无法写入。

修复要点：日志目录与资源目录分离，使用系统可写目录：

```python
from PyQt5.QtCore import QStandardPaths
log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
log_dir.mkdir(parents=True, exist_ok=True)
```

并修正 `get_module_logger` 的重复前缀（`__name__` 已含 `Moge.`，见 L1）。同时清理仓库内已产生的 `Moge/utils/logs/` 与 `utils/logs/`。

收益：日志可靠、符合 Windows 权限模型、源码树不再被污染。成本：S。

### H6 入口导入路径不可移植

现状：`from Moge.utils...` 要求 `e:\PyQt5_demo` 在 `sys.path`。实测在项目根执行 `python main.py` 报 `ModuleNotFoundError: No module named 'Moge.utils.logger_config'`（根目录下有一个无 `__init__.py` 的 `Moge` 命名空间包，会被误命中）。当前只能依赖 IDE 工作目录或父目录启动。

两种兼容方案：

- **方案 A（低成本，立即可用）**：把导入改为包内相对导入 `from utils.logger_config import ...`，并在 `main.py` 中加入 `sys.path` 修正；同时把 `Moge.spec` 的 `pathex` 改为基于 `SPECPATH` 的相对路径。
- **方案 B（推荐，改动稍大）**：将源码迁入 `src/moge/`（或保持 `Moge/` 作为包目录且根目录不再叫 Moge），提供 `pyproject.toml` 与 `python -m moge` 入口。

收益：任意工作目录可运行、可被 PyInstaller 稳定分析。成本：A 为 S，B 为 M（需同步修改 spec、日志路径、文档）。

---

## 4. P1 问题详解（性能 / 体积 / 交付）

### H7 计算阻塞 GUI 线程

现状：`process_image` 在槽函数内同步完成缩放、像素化、聚类（[main_window.py](file:///e:/PyQt5_demo/Moge/ui/main_window.py#L244-L295)）。Qt 事件循环被占用：

- `QProgressDialog` 不会重绘（进度数值变化无视觉反馈）；
- "取消"按钮点击无效（未连接且事件循环阻塞）；
- Windows 会把窗口标记为"未响应"。

修复要点：`QThread + Worker(QObject)`（或 `QThreadPool + QRunnable`），通过信号回传 `progress(int)`、`finished(np.ndarray)`、`failed(str)`；取消用 `threading.Event`/`bool` 标志在算法块循环中检查。算法层保持纯函数，不依赖 Qt。

收益：交互可用性达标，是大图处理的前提。成本：M。

### H8 KMeans 全量聚类不可用

实测：256×256、k=16、随机噪声图耗时 **15.7 s**，按像素线性外推 1080p 约 **496 s**（真实照片会更快，但量级问题不变）。理论复杂度 O(N·K·iter)，且 `pixels = img.reshape(-1, 3)` 后要生成 `cluster_centers_[labels]` 全量索引数组，内存额外占用约 1 份图像 + N 个 int 标签。

分两步走：

1. **立即可做（不改依赖）**：对像素做确定性等距子采样（≤ 50k），`fit` 后分批 `predict`（每批 25 万像素），可获 10–30× 提升；
2. **体积优化阶段**：改用 `cv2.kmeans`（`attempts=1, max_iter=10`，`cv2.setRNGSeed(seed)`）或 `PIL.Image.quantize(colors=k)`，从而移除 scikit-learn/scipy（约 112 MB）。

同时增加边界：`k = min(k, 唯一颜色数)`，唯一色数 ≤ k 时直接返回原图。

```python
def color_clustering(img, n_colors, seed, max_samples=50_000):
    pixels = img.reshape(-1, 3)
    if len(np.unique(pixels, axis=0)) <= n_colors:
        return img
    step = max(1, len(pixels) // max_samples)
    sample = pixels[::step]
    km = KMeans(n_clusters=n_colors, random_state=seed, n_init=1).fit(sample)
    out = np.empty_like(pixels)
    for i in range(0, len(pixels), 250_000):
        out[i:i+250_000] = km.cluster_centers_[km.predict(pixels[i:i+250_000])]
    return out.reshape(img.shape).astype(np.uint8)
```

收益：从分钟级降到秒级；内存峰值下降。成本：S（采样）/ M（替换依赖）。

### H9 / H10 像素化算法向量化

实测（256×256，block=8）：

| 实现 | 256² 实测 | 1080p 线性估算 |
| --- | --- | --- |
| 频数（现状） | 375 ms | **11.85 s** |
| 频数（向量化对照） | 40 ms | **1.25 s** |
| 均值（现状） | 40 ms | **1.28 s** |
| 均值（向量化对照） | — | **118 ms** |

均值向量化（去 Python 循环、单次 mean）：

```python
def img_pixelize_mean(img, bs):
    h, w = img.shape[:2]
    ph, pw = (-h) % bs, (-w) % bs
    padded = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="edge").astype(np.float32)
    blocks = padded.reshape(padded.shape[0] // bs, bs, padded.shape[1] // bs, bs, 3)
    return blocks.mean(axis=(1, 3)).astype(np.uint8).repeat(bs, 0).repeat(bs, 1)
```

频数向量化：块内像素打包为 `uint32` 后逐块 `np.unique(return_counts=True)` 取众数（对照实现已实测 ~9.5×）；若需进一步提速，可用 `np.bincount`（`minlength=1<<24` 会占 64 MB，需按需）或 `cv2.calcHist` 方案。

收益：均值 ~10×，频数 ~9.5×，且结果可逐像素对齐验证。成本：S。

### M1 依赖与构建体积

- 移除 sklearn/scipy/joblib/threadpoolctl（聚类改 `cv2.kmeans`/PIL）：约 **-112 MB**
- 移除 pandas/matplotlib/seaborn/pytz/contourpy/kiwisolver/fonttools 等未使用依赖：约 **-30 MB**
- `opencv-python` → `opencv-python-headless`（项目未用 `cv2.imshow/waitKey`）：实测仅 **-0.6 MB**，因为体积主要是 `cv2.pyd`（71 MB）与 ffmpeg 插件（27 MB），headless 只去掉 Qt 插件
- PyQt5 裁剪未用模块（Qml、Quick、DBus、WebSockets、Qt5 translations、imageformats 中不需要的插件）：约 **-30~40 MB**
- `Moge.spec` 增加 `excludes=['tkinter','matplotlib','pandas','seaborn','scipy','sklearn',...]`（在替换依赖后），并关闭 UPX 或仅对非 DLL 启用

预期产物：**505 MB → 238.8 MB（已实测）**。成本：M（需回归验证）。

### M2 Git 仓库卫生

- `dist/`、`build/` 已被跟踪（1614 个文件），`.git` 372.6 MB；`.gitignore` 虽写了 `dist/`，但对已跟踪文件无效。
- `.gitattributes` 仅对 `cv2.pyd` 配了 LFS，`dist` 内其余二进制未覆盖。

处理：`git rm -r --cached dist build` 并提交；后续禁止提交产物。若必须瘦身历史，使用 `git filter-repo`/BFG（**破坏性操作**，需先备份分支并团队同步）。成本：S（去跟踪）/ M（清历史）。

### M3 依赖可复现性

- 仅 `environment.yml`，含 conda build hash 与 `prefix`，跨平台/跨机器不可复现；无运行时锁定文件。
- Python 3.9 已于 2025-10 EOL，不再获得安全补丁。

建议：新增 `pyproject.toml`（项目元数据 + 依赖区间）与锁定文件（`pip-compile` 或 `uv lock`）；计划升级至 Python 3.11/3.12 + PyQt5 5.15.11（保持 API 兼容）；CI 中用 `pip-audit` 做依赖漏洞扫描。成本：M。

### M4 打包配置

- `pathex=['E:/PyQt5_demo/Moge']` 硬编码绝对路径，其他机器无法构建；
- `upx=True` 对 Qt/OpenCV DLL 压缩，易被杀软误报，也影响启动；
- 缺少 `icon`、`version`、`company` 等元信息，无签名。

建议：`pathex=[SPECPATH]`（或相对路径）；`upx=False` 或 `upx_exclude=['*.dll']`；补充 `version_info`；发布时提供 SHA256 校验值。成本：S。

---

## 5. P2 问题（可维护性 / 安全加固）

| ID | 问题 | 建议 | 成本 |
| --- | --- | --- | --- |
| M5 | 打开图片强制 `Format_RGB888`，PNG 透明通道丢失；`mode_color` 中的 alpha 分支永远走不到 | 明确产品是否支持透明：支持则全链路 RGBA；不支持则删除死代码并提示 | S/M |
| M6 | `show_image` 连续两次 `setPixmap(scaled(...))`，第一次结果被覆盖；窗口拉伸后图像不重新缩放 | 保存 `self._pixmap` 原始对象，仅 `resizeEvent` 中缩放一次 | S |
| M7 | `self.original_img.copy()` 后 `img_resize` 又生成新数组；像素化内部再 `copy().astype(np.float32)` | 去掉多余拷贝，算法返回新数组；大图内存峰值可降 2~3 份 | S |
| M8 | 无像素上限，超大图/恶意图片可致 OOM | 加载后校验 `w*h <= N`（如 64 MP），超限提示并可选择降采样 | S |
| M9 | 异常时 `QProgressDialog` 不关闭；取消按钮未连接；`n_clusters > 唯一色数` 抛原始 `ValueError` | `try/finally` 关闭；连接 `canceled`；聚类前做边界约束并给出中文提示 | S |
| M10 | UI 直接编排算法、参数散落在控件中 | 引入 `ProcessingParams` dataclass + `ImageService`，UI 仅收集参数、调用服务、渲染结果 | M |
| L1 | 日志器名 `Moge.Moge.ui.main_window`；50 MB×7=400 MB 无上限 | `get_module_logger` 去掉重复前缀；改为 5 MB×3 或按天轮转 | S |
| L2 | `cluster_group` 被 `addWidget` 两次；`except Exception as e` 未用 `e`；`if processed_img is not None` 嵌套冗余 | 清理 | S |
| L3 | 无测试/CI/lint/类型；README 仅一行 | `ruff` + `black` + `pytest`（core 单测优先）+ GitHub Actions；补 README | M |
| L4 | 未设置 `AA_EnableHighDpiScaling` / `AA_UseHighDpiPixmaps`；无 `sys.excepthook` | 在 `QApplication` 前设置属性；全局异常写日志并提示 | S |
| — | 日志/异常信息可能包含完整路径 | 属低敏感度，保持现状；如对外发布可做路径脱敏 | S |

---

## 6. 架构分析

### 6.1 现状

```text
main.py
  └─> MainWindow (ui)  ──直接调用──> core.image_processor (纯函数)
        │                              └─> sklearn / cv2 / numpy
        └─> utils.logger_config
```

- **优点**：算法是纯函数、无全局状态，易测试；模块划分（ui/core/utils）方向正确；无网络与数据库，攻击面小。
- **问题**：
  1. UI 承担了编排、线程、文件 IO、错误提示、参数收集五种职责；
  2. 算法层参数用中文字符串做契约（H2/H3 的根因）；
  3. 无配置层（窗口尺寸、日志策略、图像上限均为魔法数）；
  4. 无并发模型（H7）；
  5. 资源路径与日志路径混为一谈（H5）。

### 6.2 目标结构（不引入新框架，保持 PyQt5 + OpenCV + NumPy）

```text
main.py                  # 仅负责 QApplication 生命周期、单实例、全局异常
app/
  config.py              # 常量/枚举/默认值/上限
  worker.py              # QThreadPool Worker + 信号（进度/取消/错误）
core/
  image_processor.py     # 纯函数（向量化），参数使用 Enum/dataclass
  models.py              # ProcessingParams / ProcessingResult
ui/
  main_window.py         # 只做布局、参数收集、结果渲染
  image_view.py          # 可自适应缩放的画布控件
utils/
  logger_config.py       # 可写目录、统一 logger 命名
```

约束：保持 `core` 对外函数名不变（先加可选参数与内部重写），避免破坏性变更；UI 控件与交互不变。

---

## 7. 五大优化场景落地要点

### 7.1 代码冗余消除

- 删除未使用依赖与未使用导入（`e`、`cv2` 仅保存用可保留）。
- 删除 `mode_color` 中不可达的 alpha 分支（或补齐 RGBA 支持，二选一）。
- 删除重复 `setPixmap`、重复 `addWidget`、冗余 `if processed_img is not None`。
- 删除 `params["resize_method"]` 这类"取了不用"的字段，统一由枚举驱动。
- 合并两处取整逻辑为 `_fit()` 单一实现。

### 7.2 运行时性能

| 措施 | 预期收益 | 成本 |
| --- | --- | --- |
| 算法向量化（均值/频数） | 均值 ~10×，频数 ~9.5× | S |
| KMeans 子采样 + 分批 predict | 10–30× | S |
| 移除逐像素 Python 循环 | 消除 GIL 瓶颈 | S |
| 工作线程 + 进度/取消 | UI 不阻塞 | M |
| 减少大图拷贝 | 内存峰值 -30%~50% | S |

### 7.3 构建体积精简

见 M1。执行顺序：先替换聚类实现，再删除 sklearn/scipy，再切换 headless OpenCV，最后在 spec 中加 `excludes` 与 Qt 模块裁剪；每一步都跑一遍功能回归并记录体积。

### 7.4 可维护性

- 参数与结果 dataclass 化；算法契约用 Enum。
- 日志/异常/配置集中。
- 核心算法单测（含黄金图像对比 + 性能回归阈值）。
- `ruff`、`black`、`pytest`、`pre-commit`、GitHub Actions。
- README 补：环境安装（两种方式）、启动、构建、已知限制。

### 7.5 安全加固

- **输入边界**：图像像素上限、`block_size` 与 `k` 的联合约束、`k ≤ 唯一色数`，避免 OOM/异常崩溃。
- **文件写入**：格式与扩展名强一致；校验 `imencode` 返回值；捕获并提示 `PermissionError`（已有）。
- **日志**：改为可写目录 + 更小轮转（400 MB → 15 MB 量级）。
- **打包**：关闭全局 UPX，补版本信息，发布附 SHA256；如分发对外，考虑代码签名。
- **依赖**：Python 3.9 EOL，升级基线；`pip-audit` 纳入 CI；移除未使用的 `requests`（减少供应链面）。
- **单实例**：修复后确保异常退出不残留（`QLocalServer` 方案天然无残留）。

---

## 8. 分阶段实施路线图

> 原则：每个阶段独立可发布、可回滚；先修正确性，再谈性能与体积；不改变 UI 交互与对外函数签名。

### Phase 0 — 建立基线与护栏

1. 新增 `tests/` 与基准脚本（均值/频数/聚类/启动），记录当前数值（本报告第 0 节可作为初始基线）。
2. 建立"黄金样例"：3 张图（小图非 8 倍数尺寸、1080p 照片、带透明 PNG）。
3. 记录产物体积、启动耗时、内存峰值。

**退出标准**：基准可一键复现；三项指标入库。

### Phase 1 — P0 正确性修复（行为修正，不改架构）✅ 已完成

> 状态（2026-11-14）：H1–H6 已全部修复并通过自动化验证（缩放矩阵、PNG/JPEG 文件头、日志落盘位置、单实例互斥、根目录导入）。

1. H1 保存格式修复 + 扩展名/返回值校验。
2. H2/H3 缩放枚举化，三种取整公式修正，UI 与算法共用映射。
3. H4 单实例重写（`QApplication` 先创建；守卫对象持久化）。
4. H5 日志目录改为用户可写目录（`%LOCALAPPDATA%`，缺失时回退用户主目录）；清理嵌套目录；修 logger 命名。
5. H6 入口导入修正（方案 A 先行）。

**验证标准**：
- `1001×1999` 输入：向上 → `1008×2000`，向下 → `1000×1992`，四舍五入 → `1000×2000`；
- 保存 `a.png` 后文件头为 `89 50 4E 47`，保存 `a.jpg` 为 `FF D8 FF`；
- 双击两次只出现一个实例与一条提示，且无 Qt 初始化告警；
- 从项目根与父目录、任意 cwd 均能启动；
- 日志出现在 `%LOCALAPPDATA%` 下，不再写入源码树。

### Phase 2 — 响应性与性能 ✅ 已完成

> 状态（2026-11-15）：引入 `QThread + ProcessingWorker`（进度信号、取消、异常回传、关闭窗口等待线程）；`ProcessingParams` dataclass 统一参数；均值/频数像素化向量化并与旧实现逐像素一致；聚类改为采样 + `cv2.kmeans` + 分批归类，结果确定且可取消。实测 1080p：均值 97 ms、频数 893 ms、聚类 736 ms。

1. 抽出 `ProcessingParams` 与纯函数服务。
2. 引入 Worker 线程 + 进度信号 + 取消标志；异常统一回主线程弹窗。
3. 均值/频数像素化向量化。
4. KMeans 子采样 + 分批 predict + `k` 边界处理。

**验证标准**：
- 1080p：均值 ≤ 200 ms，频数 ≤ 2 s，聚类 ≤ 5 s（同机同图对比基线）；
- 处理过程中窗口可拖动、进度条递增、取消 ≤ 300 ms 生效、无"未响应"；
- 向量化结果与原实现逐像素一致（允许聚类因采样有 ≤1% 像素差异，需在报告中说明）。

### Phase 3 — 体积与依赖 ✅ 已完成（历史清理待决策）

> 状态（2026-11-15）：已移除 sklearn/scipy 代码依赖；`environment.yml` 精简为 numpy + opencv-python-headless + PyQt5 + PyInstaller；`Moge.spec` 增加 `excludes` 并关闭 UPX。在**全新 venv** 中安装最小依赖后：功能/性能验证全部通过，构建产物 **238.8 MB / 216 文件**（原 504.9 MB，下降 53%），打包后可正常启动。已取消跟踪 `dist/`、`build/`、`__pycache__`、日志（跟踪文件从 1614 降至 14）。仅剩 Git 历史重写（破坏性，需单独确认）。

1. 聚类替换为 `cv2.kmeans`/PIL（保留花籽参数语义）。
2. 移除 sklearn/scipy/pandas/matplotlib/seaborn 等。
3. `opencv-python-headless`。
4. spec：相对 `pathex`、`excludes`、关闭全局 UPX、Qt 模块裁剪、版本信息。
5. Git：取消跟踪 `dist/`、`build/`；评估是否清理历史。

**验证标准**：
- 产物 ≤ 250 MB，且功能回归全部通过；
- 在新机器（无 conda 缓存）按 README 可完成构建；
- `git ls-files | wc -l` 不含产物文件。

### Phase 4 — 工程化与长期维护

1. `pyproject.toml` + 锁定依赖；Python 3.11 验证分支。
2. `ruff`/`black`/`pytest`/`pre-commit` + CI（lint + test + build + pip-audit）。
3. README/CHANGELOG/发布流程（SHA256、版本号）。
4. 架构分层落地（config/worker/view 拆分），补充类型提示。

**验证标准**：
- CI 全绿；`ruff` 0 error；核心算法覆盖率 ≥ 80%；
- `pip-audit` 无 high/critical；
- 任意新成员可在 10 条命令内完成环境搭建与测试。

---

## 9. 兼容性与风险控制

- **API 兼容**：`img_resize/img_pixelize_mean/img_pixelize_common/color_clustering` 保留原签名，新参数一律带默认值；UI 控件与文案不变。
- **行为变更需公告**：保存格式、缩放结果、日志位置属于"修复类变更"，需在 CHANGELOG 标注。
- **依赖替换的兼容风险**：`cv2.kmeans` 与 sklearn 的初始化策略不同，聚类结果可能有细微差异；先以采样版 sklearn 落地，体积阶段再替换，并保留一键回退。
- **线程安全**：算法层不得触碰 Qt 对象；结果通过信号传递 `np.ndarray`（只读拷贝或所有权转移），避免跨线程共享可变状态。
- **历史清理风险**：`git filter-repo` 会改写提交哈希，需团队协调并备份；非必要可只做"取消跟踪 + 新提交"。
- **不建议引入**：新 GUI 框架、异步框架、数据库、服务化拆分、过度分层；当前规模下保持单进程 + 纯函数 + Worker 即可。

---

## 10. 验收指标总表

| 维度 | 指标 | 基线 | 目标 | 验证方法 |
| --- | --- | --- | --- | --- |
| 正确性 | PNG/JPEG 保存 | PNG 实为 JPEG | 格式与扩展名一致 | 文件头断言 |
| 正确性 | 缩放三模式 | 全部不生效 | 符合取整定义 | 参数化单测 |
| 正确性 | 启动方式 | 仅父目录 | 任意 cwd / `python -m` | CI 多 cwd 冒烟 |
| 性能 | 1080p 均值 | ~1.28 s | ≤0.2 s | 基准脚本 5 次中位数 |
| 性能 | 1080p 频数 | ~11.9 s | ≤2 s | 同上 |
| 性能 | 1080p 聚类 k=16 | ~496 s（最坏） | ≤5 s | 同上（真实照片 + 噪声图） |
| 响应性 | 主线程阻塞 | 全程 | 无 >100 ms 阻塞 | 事件循环心跳计时 |
| 响应性 | 取消延迟 | 不可取消 | ≤300 ms | 自动化点击 |
| 体积 | 产物 | 504.9 MB | ≤250 MB | 目录求和 |
| 仓库 | 跟踪文件/体积 | 1614 / 372.6 MB | 无产物 / ≤20 MB | `git ls-files`、`.git` 求和 |
| 质量 | lint / 测试 | 无 | ruff 0 error；core 覆盖率 ≥80% | CI |
| 安全 | 依赖漏洞 | 未扫描 | 无 high/critical | `pip-audit` |
| 安全 | 输入上限 | 无 | 超限友好拒绝 | 单测（超大尺寸伪造头） |

---

## 11. 落地顺序建议（最小改动优先）

1. 保存格式（H1）→ 缩放参数与公式（H2/H3）→ 单实例与启动顺序（H4）→ 日志路径（H5）→ 导入路径（H6）。这 5 项互不依赖，可独立提交。
2. 线程化（H7）→ 向量化（H9/H10）→ 聚类采样（H8）。先改线程还是先向量化均可；建议先向量化（纯函数、易验证），再加线程。
3. 依赖替换与体积裁剪（M1/M4）→ 仓库清理（M2）。
4. 工程化（M3/L3）与架构分层（M10）随日常迭代推进，不阻塞发布。

以上每一步都可单独验收、单独回滚，且不改变现有 UI 与技术栈。
