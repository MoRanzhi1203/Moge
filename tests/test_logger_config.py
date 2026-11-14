from Moge.utils.logger_config import get_log_dir, get_module_logger


def test_get_log_dir_is_writable():
    log_dir = get_log_dir()
    assert log_dir.is_dir()

    probe = log_dir / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def test_module_logger_names():
    assert get_module_logger("Moge.ui.main_window").name == "Moge.ui.main_window"
    assert get_module_logger("ui.worker").name == "Moge.ui.worker"
