# 拼豆色卡、映射与图纸

## 1. 色卡数据与可信度

仓库内置 `Generic / Approx` 色卡（`G01`–`G24`），来源标记为：

```text
source = builtin-approx-unverified
verified = False
availability = unknown
```

它是**屏幕近似演示数据**，不属于任何真实品牌，也不代表官方色值。界面与统计会显示“色卡已验证：否”。

系统结构支持 `brand`、`series`、`product_line`、`code`、`display_name`、`rgb`、`availability`、`source`、`revision`，并按 `(brand, series, code)` 唯一。

## 2. 用户色卡导入（CSV）

必需列：

```text
brand,series,code,name,rgb
```

可选列：

```text
availability,source,revision,product_line,verified
```

规则：

- `rgb` 支持 `#RRGGBB` 或 `R,G,B`。
- 同一品牌/系列下色号重复会被拒绝。
- 坏行会被跳过并在 UI 中显示前若干条错误。
- 品牌/系列切换时做隔离，不会把不同品牌的相近颜色合并。
- 导入后仅在本机内存与工程文件中使用，不上传。

## 3. 筛选与映射

- 品牌、系列选择。
- “库存色号”文本框（逗号分隔）：非空时只允许这些色号。
- “禁用色号”文本框：无论库存如何都不会出现。
- 候选集合 → Lab(D65) 最近色映射 → 稳定 ID `bead:{brand}:{series}:{code}`。
- 映射后反向核对：每个单元必须属于候选集合，合法率 100%。

直接色卡匹配是默认基线，不做“先 K-Means 再映射”。基准（`docs/Clustering-Benchmarks.md` 第 5 节）显示直接匹配置信度更高。

## 4. 统计与分板

- 总珠子数 = 非空网格单元数。
- 使用颜色数、每色数量、颜色占比（统计面板/CSV）。
- 底板尺寸可配置（默认 29×29，仅示例，不代表所有品牌）。
- `board_partitions` 按行优先切分，返回每块板的行列号与边界；测试验证不重复、不遗漏。
- PDF 每块底板一页，含行列坐标、色号、色块、图例与数量。
- CSV 含 `id/name/hex/rgb/count/brand/series/code/category/source`，UTF-8 BOM 便于 Excel。

## 5. 编辑行为

- 画笔、填充、吸管、替换同类可用。
- 材料/拼豆模式禁止“擦除为空白”，避免产生非法材料单元；像素化模式支持 `-1` 透明单元。
- 编辑后重新计算用量、孤立单元与分板统计；撤销/重做基于标签快照（最多 50 步）。

## 6. 已知限制

- 没有经过校准的真实品牌色卡；颜色匹配使用屏幕近似 RGB。
- 未实现库存文件导入（当前通过文本框输入色号）；未做采购成本。
- 未实现符号黑白打印专用模式；PDF 使用色号文字，黑白打印可读但未做高对比度专用排版。
- 未实现多品牌混合匹配（一次只匹配一个品牌/系列）。
- 未做实体底板物理尺寸与打印缩放校准。

## 7. 测试

```powershell
python -m pytest tests/test_materials.py tests/test_exporters.py -q
```

覆盖：色卡列校验、重复色号、坏行隔离、品牌/系列隔离、库存/禁用筛选、分板覆盖、工程回读、PDF 生成。
