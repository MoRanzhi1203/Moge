##############################
# core/modes/registry.py - 模式注册与配置构建
##############################


from Moge.core.models import GridSpec, PipelineConfig
from Moge.core.modes import beads, minecraft, pixel

MODES = {
    pixel.MODE_KEY: pixel.MODE_LABEL,
    minecraft.MODE_KEY: minecraft.MODE_LABEL,
    beads.MODE_KEY: beads.MODE_LABEL,
}


def mode_label(key: str) -> str:
    return MODES.get(key, key)


def mode_options() -> list[tuple]:
    return [(key, label) for key, label in MODES.items()]


def default_settings(mode: str) -> dict[str, object]:
    if mode == pixel.MODE_KEY:
        return dict(pixel.PIXEL_DEFAULTS)
    if mode == minecraft.MODE_KEY:
        return dict(minecraft.MC_DEFAULTS)
    if mode == beads.MODE_KEY:
        return dict(beads.BEAD_DEFAULTS)
    raise ValueError(f"未知模式：{mode}")


def build_config(mode: str, spec: GridSpec, settings: dict[str, object], image=None) -> PipelineConfig:
    if mode == pixel.MODE_KEY:
        return pixel.build_config(spec, settings, image)
    if mode == minecraft.MODE_KEY:
        return minecraft.build_config(spec, settings)
    if mode == beads.MODE_KEY:
        return beads.build_config(spec, settings)
    raise ValueError(f"未知模式：{mode}")
