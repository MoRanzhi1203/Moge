##############################
# core/materials.py - Minecraft 方块与拼豆色卡（内置近似数据 + 导入）
##############################

import csv
import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

RGB = tuple[int, int, int]

MC_CATEGORIES: dict[str, str] = {
    "concrete": "混凝土",
    "wool": "羊毛",
    "terracotta": "陶瓦",
    "glazed": "带釉陶瓦",
    "planks": "木板",
    "log": "原木",
    "stone": "石头",
    "sandstone": "砂岩",
    "dirt": "泥土",
    "sand": "沙/砾石",
    "glass": "玻璃",
    "mineral": "矿物/金属",
    "nether": "下界",
    "end": "末地",
    "natural": "自然材料",
}

MC_VERSIONS: tuple[str, ...] = ("1.12.2", "1.16.5", "1.20.1", "1.21.4")


def parse_version(value: str) -> tuple[int, ...]:
    """ 结构化版本比较，避免字符串字面比较 """
    parts = re.findall(r"\d+", str(value))
    if not parts:
        raise ValueError(f"无法解析版本号：{value}")
    return tuple(int(part) for part in parts)


@dataclass(frozen=True)
class MinecraftBlock:
    """ 内置方块近似数据（显示色为屏幕近似，非真实贴图） """

    block_id: str
    name: str
    rgb: RGB
    category: str
    obtainability: str = "survival"  # survival / renewable / creative
    renewable: bool = False
    buildable: bool = True
    gravity: bool = False
    transparent: bool = False
    editions: tuple[str, ...] = ("java", "bedrock")
    introduced: str = "1.0"
    removed: Optional[str] = None
    cost_tier: int = 2
    orientation: str = "none"  # none / axis / facing
    visible_face: str = "all"  # all / top / side / front
    source: str = "builtin-approx"
    note: str = ""

    def available_in(self, version: str, edition: str = "java") -> bool:
        if edition not in self.editions:
            return False
        current = parse_version(version)
        if current < parse_version(self.introduced):
            return False
        if self.removed and current >= parse_version(self.removed):
            return False
        return True


def _block(block_id, name, rgb, category, **kwargs) -> MinecraftBlock:
    return MinecraftBlock(block_id=block_id, name=name, rgb=rgb, category=category, **kwargs)


# 颜色为近似显示色，仅用于纯色预览；未包含任何游戏贴图
MC_BLOCKS: tuple[MinecraftBlock, ...] = (
    _block("white_concrete", "白色混凝土", (207, 213, 214), "concrete", cost_tier=1),
    _block("orange_concrete", "橙色混凝土", (224, 97, 0), "concrete", cost_tier=1),
    _block("magenta_concrete", "品红色混凝土", (169, 48, 159), "concrete", cost_tier=1),
    _block("light_blue_concrete", "淡蓝色混凝土", (36, 137, 199), "concrete", cost_tier=1),
    _block("yellow_concrete", "黄色混凝土", (240, 175, 21), "concrete", cost_tier=1),
    _block("lime_concrete", "黄绿色混凝土", (94, 169, 24), "concrete", cost_tier=1),
    _block("pink_concrete", "粉红色混凝土", (213, 101, 142), "concrete", cost_tier=1),
    _block("gray_concrete", "灰色混凝土", (54, 57, 61), "concrete", cost_tier=1),
    _block("light_gray_concrete", "淡灰色混凝土", (125, 125, 115), "concrete", cost_tier=1),
    _block("cyan_concrete", "青色混凝土", (21, 119, 136), "concrete", cost_tier=1),
    _block("purple_concrete", "紫色混凝土", (100, 32, 156), "concrete", cost_tier=1),
    _block("blue_concrete", "蓝色混凝土", (44, 46, 143), "concrete", cost_tier=1),
    _block("brown_concrete", "棕色混凝土", (96, 59, 31), "concrete", cost_tier=1),
    _block("green_concrete", "绿色混凝土", (73, 91, 36), "concrete", cost_tier=1),
    _block("red_concrete", "红色混凝土", (142, 32, 32), "concrete", cost_tier=1),
    _block("black_concrete", "黑色混凝土", (8, 10, 15), "concrete", cost_tier=1),
    _block("white_wool", "白色羊毛", (233, 236, 236), "wool", renewable=True, cost_tier=1),
    _block("orange_wool", "橙色羊毛", (240, 118, 19), "wool", renewable=True, cost_tier=1),
    _block("magenta_wool", "品红色羊毛", (189, 68, 179), "wool", renewable=True, cost_tier=1),
    _block("light_blue_wool", "淡蓝色羊毛", (58, 175, 217), "wool", renewable=True, cost_tier=1),
    _block("yellow_wool", "黄色羊毛", (248, 198, 39), "wool", renewable=True, cost_tier=1),
    _block("lime_wool", "黄绿色羊毛", (112, 185, 25), "wool", renewable=True, cost_tier=1),
    _block("pink_wool", "粉红色羊毛", (237, 141, 172), "wool", renewable=True, cost_tier=1),
    _block("gray_wool", "灰色羊毛", (62, 68, 71), "wool", renewable=True, cost_tier=1),
    _block("light_gray_wool", "淡灰色羊毛", (142, 142, 134), "wool", renewable=True, cost_tier=1),
    _block("cyan_wool", "青色羊毛", (21, 137, 145), "wool", renewable=True, cost_tier=1),
    _block("purple_wool", "紫色羊毛", (121, 42, 172), "wool", renewable=True, cost_tier=1),
    _block("blue_wool", "蓝色羊毛", (53, 57, 157), "wool", renewable=True, cost_tier=1),
    _block("brown_wool", "棕色羊毛", (114, 71, 40), "wool", renewable=True, cost_tier=1),
    _block("green_wool", "绿色羊毛", (84, 109, 27), "wool", renewable=True, cost_tier=1),
    _block("red_wool", "红色羊毛", (161, 39, 34), "wool", renewable=True, cost_tier=1),
    _block("black_wool", "黑色羊毛", (20, 21, 25), "wool", renewable=True, cost_tier=1),
    _block("terracotta", "陶瓦", (152, 94, 67), "terracotta", renewable=True, cost_tier=2),
    _block("white_terracotta", "白色陶瓦", (209, 178, 161), "terracotta", renewable=True, cost_tier=2),
    _block("orange_terracotta", "橙色陶瓦", (161, 83, 37), "terracotta", renewable=True, cost_tier=2),
    _block("white_glazed_terracotta", "白色带釉陶瓦", (188, 212, 202), "glazed", orientation="facing", cost_tier=3),
    _block("orange_glazed_terracotta", "橙色带釉陶瓦", (154, 118, 58), "glazed", orientation="facing", cost_tier=3),
    _block("oak_planks", "橡木木板", (162, 130, 78), "planks", renewable=True, cost_tier=1),
    _block("spruce_planks", "云杉木板", (114, 84, 48), "planks", renewable=True, cost_tier=1),
    _block("birch_planks", "白桦木板", (192, 175, 121), "planks", renewable=True, cost_tier=1),
    _block("oak_log", "橡木原木", (109, 85, 50), "log", renewable=True, orientation="axis", visible_face="side", cost_tier=1),
    _block("spruce_log", "云杉原木", (58, 37, 16), "log", renewable=True, orientation="axis", visible_face="side", cost_tier=1),
    _block("stone", "石头", (125, 125, 125), "stone", cost_tier=1),
    _block("cobblestone", "圆石", (122, 122, 122), "stone", cost_tier=1),
    _block("stone_bricks", "石砖", (122, 121, 121), "stone", cost_tier=1),
    _block("deepslate", "深板岩", (80, 80, 82), "stone", introduced="1.17", cost_tier=1),
    _block("tuff", "凝灰岩", (108, 109, 102), "stone", introduced="1.17", cost_tier=1),
    _block("calcite", "方解石", (223, 224, 220), "stone", introduced="1.17", cost_tier=2),
    _block("sandstone", "砂岩", (216, 203, 155), "sandstone", cost_tier=1),
    _block("red_sandstone", "红砂岩", (188, 98, 35), "sandstone", cost_tier=1),
    _block("sand", "沙子", (219, 207, 163), "sand", gravity=True, cost_tier=1),
    _block("red_sand", "红沙", (188, 101, 30), "sand", gravity=True, cost_tier=1),
    _block("gravel", "沙砾", (131, 127, 126), "sand", gravity=True, cost_tier=1),
    _block("dirt", "泥土", (134, 96, 67), "dirt", cost_tier=1),
    _block("grass_block", "草方块", (95, 159, 53), "natural", renewable=True, visible_face="top", cost_tier=1),
    _block("glass", "玻璃", (190, 220, 225), "glass", transparent=True, cost_tier=2),
    _block("white_stained_glass", "白色染色玻璃", (222, 238, 240), "glass", transparent=True, cost_tier=2),
    _block("iron_block", "铁块", (220, 220, 220), "mineral", cost_tier=3),
    _block("gold_block", "金块", (246, 208, 61), "mineral", cost_tier=3),
    _block("diamond_block", "钻石块", (98, 219, 214), "mineral", cost_tier=3),
    _block("emerald_block", "绿宝石块", (42, 203, 87), "mineral", cost_tier=3),
    _block("lapis_block", "青金石块", (30, 67, 140), "mineral", cost_tier=3),
    _block("redstone_block", "红石块", (175, 24, 5), "mineral", cost_tier=2),
    _block("copper_block", "铜块", (192, 107, 79), "mineral", introduced="1.17", cost_tier=2),
    _block("netherrack", "下界岩", (97, 38, 38), "nether", cost_tier=1),
    _block("nether_bricks", "下界砖块", (44, 22, 26), "nether", cost_tier=2),
    _block("blackstone", "黑石", (42, 38, 43), "nether", introduced="1.16", cost_tier=1),
    _block("end_stone", "末地石", (219, 222, 158), "end", cost_tier=2),
    _block("purpur_block", "紫珀块", (169, 125, 169), "end", cost_tier=2),
    _block("prismarine", "海晶石", (99, 156, 151), "natural", cost_tier=2),
    _block("quartz_block", "石英块", (235, 229, 222), "mineral", cost_tier=2),
    _block("honey_block", "蜂蜜块", (241, 175, 55), "natural", cost_tier=2),
    _block("moss_block", "苔藓块", (89, 109, 45), "natural", introduced="1.17", renewable=True, cost_tier=1),
)


def filter_blocks(
    version: str,
    edition: str = "java",
    categories: Optional[Iterable[str]] = None,
    obtainability: str = "any",
    buildable_only: bool = True,
    max_cost_tier: Optional[int] = None,
    included_ids: Optional[Iterable[str]] = None,
    excluded_ids: Optional[Iterable[str]] = None,
    orientation: str = "any",
    exclude_transparent: bool = False,
    exclude_gravity: bool = False,
    blocks: Optional[Iterable[MinecraftBlock]] = None,
) -> list[MinecraftBlock]:
    """ 按版本、类别、获取条件、朝向与建造限制筛选合法候选方块 """
    category_set: Optional[set[str]] = set(categories) if categories else None
    include_set = set(included_ids) if included_ids else None
    exclude_set = set(excluded_ids) if excluded_ids else set()

    result: list[MinecraftBlock] = []
    for block in (blocks if blocks is not None else MC_BLOCKS):
        if not block.available_in(version, edition):
            continue
        if category_set is not None and block.category not in category_set:
            continue
        if obtainability == "survival" and block.obtainability == "creative":
            continue
        if obtainability == "renewable" and not block.renewable:
            continue
        if buildable_only and not block.buildable:
            continue
        if max_cost_tier is not None and block.cost_tier > max_cost_tier:
            continue
        if orientation != "any" and block.orientation != orientation:
            continue
        if exclude_transparent and block.transparent:
            continue
        if exclude_gravity and block.gravity:
            continue
        if include_set is not None and block.block_id not in include_set:
            continue
        if block.block_id in exclude_set:
            continue
        result.append(block)
    return result


def block_rejection_reason(
    block: MinecraftBlock,
    version: str,
    edition: str = "java",
    categories: Optional[Iterable[str]] = None,
    obtainability: str = "any",
    buildable_only: bool = True,
    max_cost_tier: Optional[int] = None,
    orientation: str = "any",
    exclude_transparent: bool = False,
    exclude_gravity: bool = False,
) -> Optional[str]:
    """ 返回方块被排除的结构化原因（用于诊断展示） """
    if edition not in block.editions:
        return f"不支持 {edition} 版本"
    if not block.available_in(version, edition):
        return f"在 {version} 中不可用（引入 {block.introduced}）"
    if categories is not None and block.category not in set(categories):
        return f"类别 {block.category} 未选中"
    if obtainability == "survival" and block.obtainability == "creative":
        return "生存模式不可获取"
    if obtainability == "renewable" and not block.renewable:
        return "不可再生"
    if buildable_only and not block.buildable:
        return "不是完整可建造方块"
    if max_cost_tier is not None and block.cost_tier > max_cost_tier:
        return "超出成本等级上限"
    if orientation != "any" and block.orientation != orientation:
        return f"朝向依赖为 {block.orientation}"
    if exclude_transparent and block.transparent:
        return "透明方块已排除"
    if exclude_gravity and block.gravity:
        return "重力方块已排除"
    return None


# ------------------- 拼豆色卡 ------------------- #

@dataclass(frozen=True)
class BeadColor:
    """ 拼豆色号；内置数据为屏幕近似且未验证，导入色卡需保留来源 """

    brand: str
    series: str
    code: str
    name: str
    rgb: RGB
    availability: str = "unknown"
    source: str = "builtin-approx-unverified"
    revision: str = "2026.1"
    product_line: str = "demo"
    verified: bool = False

    @property
    def id(self) -> str:
        return f"bead:{self.brand}:{self.series}:{self.code}"

    @property
    def display_name(self) -> str:
        return f"{self.brand} {self.series} {self.code} {self.name}"


def _bead(code: str, name: str, rgb: RGB, availability: str = "unknown") -> BeadColor:
    return BeadColor(
        brand="Generic",
        series="Approx",
        code=code,
        name=name,
        rgb=rgb,
        availability=availability,
    )


BEAD_CATALOG: tuple[BeadColor, ...] = (
    _bead("G01", "白", (245, 245, 240)),
    _bead("G02", "米白", (232, 220, 196)),
    _bead("G03", "浅灰", (190, 190, 190)),
    _bead("G04", "灰", (128, 128, 128)),
    _bead("G05", "深灰", (64, 64, 64)),
    _bead("G06", "黑", (24, 24, 24)),
    _bead("G07", "红", (200, 40, 40)),
    _bead("G08", "深红", (130, 24, 30)),
    _bead("G09", "橙", (235, 120, 30)),
    _bead("G10", "浅橙", (245, 170, 90)),
    _bead("G11", "黄", (245, 210, 60)),
    _bead("G12", "浅黄", (250, 235, 140)),
    _bead("G13", "黄绿", (150, 200, 60)),
    _bead("G14", "绿", (50, 150, 70)),
    _bead("G15", "深绿", (25, 90, 50)),
    _bead("G16", "青", (60, 190, 190)),
    _bead("G17", "浅蓝", (110, 180, 235)),
    _bead("G18", "蓝", (40, 90, 200)),
    _bead("G19", "深蓝", (25, 45, 120)),
    _bead("G20", "紫", (130, 70, 180)),
    _bead("G21", "浅紫", (190, 150, 220)),
    _bead("G22", "粉", (240, 150, 180)),
    _bead("G23", "棕", (120, 75, 45)),
    _bead("G24", "浅棕", (175, 130, 90)),
)


def catalog_brands(catalog: Sequence[BeadColor]) -> list[str]:
    return sorted({item.brand for item in catalog})


def catalog_series(catalog: Sequence[BeadColor], brand: str) -> list[str]:
    return sorted({item.series for item in catalog if item.brand == brand})


def _parse_rgb(value: str) -> RGB:
    text = str(value).strip().lstrip("#")
    if len(text) == 6:
        return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
    parts = re.split(r"[,;\\s]+", text)
    if len(parts) == 3:
        return tuple(int(part) for part in parts)
    raise ValueError(f"无法解析颜色：{value}")


def load_bead_catalog_csv(path: str) -> tuple[list[BeadColor], list[str]]:
    """
    读取用户提供的色卡 CSV；返回 (有效色卡, 错误列表)。
    必需列：brand, series, code, name, rgb
    可选列：availability, source, revision, product_line, verified
    """
    catalog: list[BeadColor] = []
    errors: list[str] = []
    seen = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"brand", "series", "code", "name", "rgb"}
        if not reader.fieldnames or not required.issubset({name.strip() for name in reader.fieldnames}):
            raise ValueError("色卡 CSV 缺少必需列：brand, series, code, name, rgb")

        for line_number, row in enumerate(reader, start=2):
            try:
                brand = row["brand"].strip()
                series = row["series"].strip()
                code = row["code"].strip()
                name = row["name"].strip()
                if not brand or not series or not code:
                    raise ValueError("品牌/系列/色号不能为空")
                key = (brand, series, code)
                if key in seen:
                    raise ValueError("同品牌/系列下色号重复")
                seen.add(key)
                rgb = _parse_rgb(row["rgb"])
                catalog.append(
                    BeadColor(
                        brand=brand,
                        series=series,
                        code=code,
                        name=name,
                        rgb=rgb,
                        availability=(row.get("availability") or "unknown").strip(),
                        source=(row.get("source") or "user-import").strip(),
                        revision=(row.get("revision") or "1").strip(),
                        product_line=(row.get("product_line") or "").strip(),
                        verified=str(row.get("verified", "")).strip().lower() in ("1", "true", "yes"),
                    )
                )
            except Exception as exc:  # 保留行号，跳过坏行
                errors.append(f"第 {line_number} 行：{exc}")
    return catalog, errors


def load_bead_inventory_csv(path: str) -> tuple[dict[str, int], list[str]]:
    """
    读取库存 CSV：brand, series, code 必需，quantity 可选（默认 1）。
    返回 {(brand, series, code): 数量} 与错误列表；数量为 0 的色号视为无库存。
    """
    inventory: dict[str, int] = {}
    errors: list[str] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"brand", "series", "code"}
        if not reader.fieldnames or not required.issubset({name.strip() for name in reader.fieldnames}):
            raise ValueError("库存 CSV 缺少必需列：brand, series, code")

        for line_number, row in enumerate(reader, start=2):
            try:
                brand = row["brand"].strip()
                series = row["series"].strip()
                code = row["code"].strip()
                if not brand or not series or not code:
                    raise ValueError("品牌/系列/色号不能为空")
                quantity_text = (row.get("quantity") or "1").strip()
                quantity = int(float(quantity_text))
                if quantity < 0:
                    raise ValueError("库存数量不能为负数")
                inventory[f"bead:{brand}:{series}:{code}"] = quantity
            except Exception as exc:
                errors.append(f"第 {line_number} 行：{exc}")
    return inventory, errors


def filter_beads(
    catalog: Sequence[BeadColor],
    brand: str,
    series: str,
    inventory_ids: Optional[Iterable[str]] = None,
    disabled_ids: Optional[Iterable[str]] = None,
) -> list[BeadColor]:
    inventory = set(inventory_ids) if inventory_ids is not None else None
    disabled = set(disabled_ids) if disabled_ids else set()
    result: list[BeadColor] = []
    for item in catalog:
        if item.brand != brand or item.series != series:
            continue
        if item.id in disabled or item.code in disabled:
            continue
        if inventory is not None and (item.id not in inventory and item.code not in inventory):
            continue
        result.append(item)
    return result


def board_partitions(width: int, height: int, board_width: int, board_height: int) -> list[dict[str, int]]:
    """ 将网格划分为底板页，按行优先顺序，不重复不遗漏 """
    if board_width < 1 or board_height < 1:
        raise ValueError("底板尺寸必须大于 0")
    boards: list[dict[str, int]] = []
    index = 0
    for row_start in range(0, height, board_height):
        for col_start in range(0, width, board_width):
            boards.append(
                {
                    "index": index,
                    "row": row_start // board_height,
                    "col": col_start // board_width,
                    "x0": col_start,
                    "y0": row_start,
                    "x1": min(col_start + board_width, width),
                    "y1": min(row_start + board_height, height),
                    "width": min(board_width, width - col_start),
                    "height": min(board_height, height - row_start),
                }
            )
            index += 1
    return boards


# ------------------- Minecraft 资源包（只读用户本地文件） ------------------- #

MAX_PACK_MEMBERS = 5000
MAX_TEXTURE_BYTES = 8 * 1024 * 1024
MAX_PACK_UNCOMPRESSED = 200 * 1024 * 1024
BLOCK_TEXTURE_PREFIX = "assets/minecraft/textures/block/"


@dataclass(frozen=True)
class ResourcePackResult:
    """ 资源包导入结果：方块 ID -> 可见面平均色 """

    overrides: dict[str, RGB]
    loaded: int
    skipped: int
    warnings: tuple[str, ...]
    pack_name: str


def load_resource_pack_zip(path: str, allowed_ids: Optional[Iterable[str]] = None) -> ResourcePackResult:
    """
    只读解析用户提供的 Java 版资源包 ZIP，取方块贴图的平均色作为预览/匹配色。
    不落盘、不执行脚本、不读取包内其它路径；路径穿越与超大解压比直接拒绝。
    """
    allowed = set(allowed_ids) if allowed_ids is not None else {block.block_id for block in MC_BLOCKS}
    overrides: dict[str, RGB] = {}
    warnings: list[str] = []
    skipped = 0

    with zipfile.ZipFile(path, "r") as archive:
        members = archive.infolist()
        if len(members) > MAX_PACK_MEMBERS:
            raise ValueError(f"资源包文件数量超过上限 {MAX_PACK_MEMBERS}")
        if sum(info.file_size for info in members) > MAX_PACK_UNCOMPRESSED:
            raise ValueError("资源包解压后体积超过上限")

        for info in members:
            name = info.filename.replace("\\", "/")
            parts = name.split("/")
            if name.startswith("/") or ".." in parts or ":" in parts[0]:
                raise ValueError(f"资源包包含非法路径：{name}")
            if not name.startswith(BLOCK_TEXTURE_PREFIX) or not name.lower().endswith(".png"):
                continue
            if info.file_size > MAX_TEXTURE_BYTES:
                skipped += 1
                warnings.append(f"跳过过大的贴图：{name}")
                continue

            block_id = Path(name).stem
            if block_id not in allowed:
                skipped += 1
                continue

            try:
                data = archive.read(info)
                image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
                if image is None:
                    skipped += 1
                    warnings.append(f"无法解析贴图：{name}")
                    continue
                if image.ndim == 2:
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                if image.ndim == 3 and image.shape[2] == 4:
                    visible = image[..., 3] > 0
                    if not np.any(visible):
                        skipped += 1
                        continue
                    pixels = image[..., :3][visible]
                else:
                    pixels = image.reshape(-1, image.shape[2] if image.ndim == 3 else 1)[:, :3]
                mean_bgr = pixels.reshape(-1, 3).mean(axis=0)
                overrides[block_id] = (
                    int(round(mean_bgr[2])),
                    int(round(mean_bgr[1])),
                    int(round(mean_bgr[0])),
                )
            except Exception as exc:
                skipped += 1
                warnings.append(f"读取失败 {name}：{exc}")

    return ResourcePackResult(
        overrides=overrides,
        loaded=len(overrides),
        skipped=skipped,
        warnings=tuple(warnings[:20]),
        pack_name=Path(path).name,
    )
