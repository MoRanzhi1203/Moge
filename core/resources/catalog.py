##############################
# core/resources/catalog.py - 真实资源与内置元数据合并
##############################

from typing import Optional

from Moge.core.materials import MC_BLOCKS

BUILTIN_BY_ID = {block.block_id: block for block in MC_BLOCKS}

NON_FULL_TOKENS = (
    "air", "water", "lava", "fire", "piston_head", "moving_piston", "bubble_column",
    "structure_void", "barrier", "light", "command_block", "jigsaw", "spawner",
    "chest", "door", "bed", "sign", "banner", "torch", "flower", "sapling", "rail",
    "button", "lever", "pressure_plate", "trapdoor", "fence", "wall", "stairs",
    "slab", "carpet", "candle", "lantern", "chain", "ladder", "scaffolding",
    "campfire", "anvil", "cauldron", "composter", "hopper", "path", "farmland",
)


def prettify(block_id: str) -> str:
    return block_id.replace("_", " ").title()


def _guess_category(block_id: str) -> str:
    rules = (
        ("concrete", "concrete"),
        ("wool", "wool"),
        ("glazed", "glazed"),
        ("terracotta", "terracotta"),
        ("planks", "planks"),
        ("_log", "log"),
        ("_stem", "log"),
        ("_wood", "log"),
        ("deepslate", "stone"),
        ("stone", "stone"),
        ("cobble", "stone"),
        ("sand", "sandstone"),
        ("dirt", "dirt"),
        ("gravel", "sand"),
        ("glass", "glass"),
        ("nether", "nether"),
        ("blackstone", "nether"),
        ("basalt", "nether"),
        ("end_stone", "end"),
        ("purpur", "end"),
        ("iron", "mineral"),
        ("gold", "mineral"),
        ("copper", "mineral"),
        ("diamond", "mineral"),
        ("emerald", "mineral"),
        ("lapis", "mineral"),
        ("redstone", "mineral"),
        ("quartz", "mineral"),
        ("leaves", "natural"),
        ("grass", "natural"),
        ("moss", "natural"),
    )
    for token, category in rules:
        if token in block_id:
            return category
    return "other"


def _is_buildable(block_id: str, builtin) -> bool:
    if builtin is not None:
        return builtin.buildable
    return not any(token in block_id for token in NON_FULL_TOKENS)


def metadata_for(block_id: str) -> dict[str, object]:
    """ 优先使用内置元数据；未知方块不伪造获取条件，标记 unknown """
    builtin = BUILTIN_BY_ID.get(block_id)
    if builtin is not None:
        return {
            "name": builtin.name,
            "category": builtin.category,
            "obtainability": builtin.obtainability,
            "renewable": builtin.renewable,
            "buildable": builtin.buildable,
            "gravity": builtin.gravity,
            "transparent": builtin.transparent,
            "orientation": builtin.orientation,
            "visible_face": builtin.visible_face,
            "metadata_verified": False,
            "notes": "获取条件/建造属性来自内置近似元数据，未逐一验证",
        }
    transparent = any(token in block_id for token in ("glass", "leaves", "ice", "water"))
    return {
        "name": prettify(block_id),
        "category": _guess_category(block_id),
        "obtainability": "unknown",
        "renewable": False,
        "buildable": _is_buildable(block_id, None),
        "gravity": any(token in block_id for token in ("sand", "gravel", "concrete_powder")),
        "transparent": transparent,
        "orientation": "axis" if any(token in block_id for token in ("_log", "_stem", "_wood")) else "none",
        "visible_face": "top" if block_id in ("grass_block", "mycelium", "podzol") else "side",
        "metadata_verified": False,
        "notes": "真实贴图已获取；获取条件/建造属性未验证",
    }


def choose_face(faces: dict[str, dict], visible_face: str) -> Optional[dict]:
    """ 根据可见面选择用于预览/匹配的颜色，保持确定性回退 """
    order = {
        "top": ("top", "side", "all", "bottom", "front"),
        "front": ("front", "side", "all", "top", "bottom"),
        "side": ("side", "all", "front", "top", "bottom"),
        "all": ("side", "all", "front", "top", "bottom"),
    }.get(visible_face, ("side", "all", "top", "bottom", "front"))
    for key in order:
        if key in faces:
            return faces[key]
    return next(iter(faces.values()), None)
