import uuid

from Moge.main import SingleInstanceGuard


def test_single_instance_guard(qapp):
    key = f"Moge_test_{uuid.uuid4().hex}"
    first = SingleInstanceGuard(key)
    second = SingleInstanceGuard(key)

    assert first.acquire() is True
    assert second.acquire() is False
