# Moge 2.0 验收记录

> 验收日期：2026-11-15
> 分支：`feature/moge-2-modes`（未推送、未覆盖 `main`）
> 环境：Windows 10，Python 3.9.21，项目内 `.venv`（Conda 处于离线模式，无法创建 `moge-dev`）

## 1. 命令与结果

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 静态检查 | `ruff check .` | 通过，0 error |
| 单元/集成测试 | `pytest -q` | **97 passed** |
| 核心覆盖率 | `pytest --cov=Moge.core --cov-report=term-missing` | **90%**（阈值 80%） |
| 基准测试 | `python tools/run_benchmarks.py` | 420 条量化记录、35 条预设、14 条材料对照 |
| GUI 启动 | `.venv\Scripts\python.exe main.py` | 进程存活，日志写入 `%LOCALAPPDATA%\Moge\logs\app.log` |
| GUI 截图 | 主屏截图 | `.screenshots/moge2-main.png`（第一轮）、`.screenshots/moge2-round2-100/125/150.png` |
| 打包 | `pyinstaller --noconfirm Moge.spec` | 成功，**239.2 MB / 218 文件** |
| 打包启动 | 运行 `dist/Moge/Moge.exe` | 存活 7 秒，日志确认主窗口初始化 |

## 2. 功能验收矩阵

| 验收点 | 状态 | 说明 |
| --- | --- | --- |
| 旧版 `python main.py` / `moge` 入口 | 通过 | 入口未改名；旧算法兼容函数保留 |
| 旧像素化（均值/频数/缩放/聚类） | 通过 | 旧测试与新增回归测试均通过 |
| 三模式切换保留源图 | 通过 | UI 集成测试断言 `original_img` 未被清空 |
| 窄窗口布局（900×620） | 通过 | 左右水平滚动关闭，内容最小宽度 ≤ 视口，画布 ≥ 280 px |
| 100% / 125% / 150% 缩放 | 通过（离屏探针 + 启动截图） | 三种缩放下逻辑布局一致，截图非空白 |
| 像素化模式（采样/算法/预设/颜色数） | 通过 | 5 种算法可运行；自动规则仅使用 quick/fidelity |
| 网格画布缩放/平移/网格叠层 | 通过 | 离屏 UI 测试与实际启动验证 |
| 画笔/填充/吸管/替换/撤销/重做 | 通过 | 集成测试覆盖画笔与撤销/重做；其余工具共用同一标签写入路径 |
| 透明 PNG 输入 | 部分 | 采样前白底合成并记录透明像素数；仅像素化编辑可用 `-1` 透明单元 |
| Minecraft 版本/类别/获取条件/成本筛选 | 通过 | 版本过滤、类别交集、可再生、成本上限均有测试 |
| Minecraft 合法性 | 通过 | 映射结果 100% 属于候选集 |
| Minecraft 真实贴图 | 未完成 | 仅支持资源包 ZIP 的方块贴图平均色；无多面/染色/模型 |
| Java/Bedrock 差异 | 未完成 | 内置库两版本共用元数据，未验证基岩资源结构 |
| 拼豆品牌/系列/库存/禁用筛选 | 通过 | 单品牌/系列匹配，色号隔离有测试 |
| 拼豆官方色卡 | 未完成 | 内置为未验证近似色；用户 CSV/库存导入可用 |
| 拼豆采购数量 | 通过 | 每包数量可配置，`packs_required` 与 CSV `packs` 一致 |
| 谱聚类 | 实验完成、未进 UI | 32×32 实测劣于 K-Means，保留在基准脚本 |
| 分板与数量一致性 | 通过 | 分板覆盖测试与总数一致性测试 |
| PNG 导出（含透明） | 通过 | 中文/空格路径测试通过 |
| CSV 导出 | 通过 | UTF-8 BOM，数量与填充单元一致 |
| PDF 图纸 | 通过 | 多页 PDF 文件生成，含坐标/色号/图例 |
| `.moge` 工程保存/回读 | 通过 | 网格、调色板、参数一致；拒绝未知成员与未来 schema |
| 资源包安全 | 通过（合成 ZIP） | 路径穿越拒绝、成员/体积上限、只读解析 |
| 大图内存/取消延迟 | 未运行 | 未做峰值内存与 4K 压力测试 |
| 人工盲测/主观画质 | 未运行 | 只有合成图客观指标，无盲测 |
| Python 3.11 新代码 | 未运行 | 本机无 3.11；CI 尚未运行新分支 |

## 3. 关键复现步骤

```powershell
# 1. 环境
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# 2. 质量门禁
ruff check .
pytest --cov=Moge.core --cov-report=term-missing

# 3. 基准
python tools/run_benchmarks.py

# 4. 运行 GUI
python main.py

# 5. 打包
pyinstaller --noconfirm Moge.spec
```

## 4. 截图

- 主界面：`.screenshots/moge2-main.png`
- 说明：截图为实际启动后主屏捕获，用于证明 GUI 可打开；未对每个模式逐一截图。

## 5. 未完成项与原因

1. **真实 Minecraft 贴图/版本资源**：版权与分发限制；仅提供用户本地资源包只读导入，且只取平均色。
2. **官方拼豆色卡**：无授权数据源；内置数据明确标记未验证，支持用户 CSV 导入。
3. **谱聚类/BIRCH/GMM/DBSCAN/Mean Shift/Affinity Propagation**：未实现，未做基准，未接入 UI。
4. **`.schem`/`.litematic` 导出、地图画子模式、Bedrock 专属结构**：超出本轮范围，未实现。
5. **大图内存与取消延迟压力测试、人工盲测**：未运行。
6. **CI**：`.github/workflows/ci.yml` 仍适用于新代码，但本分支未推送，未在 GitHub 上运行；本地已执行同等命令。
