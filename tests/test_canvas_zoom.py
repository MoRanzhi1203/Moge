import numpy as np
from Moge.ui.canvas import GridCanvas
from PyQt5.QtCore import QPoint
from PyQt5.QtTest import QTest


class _WheelEvent:
    def __init__(self, position, delta):
        self._position = position
        self._delta = delta
        self.accepted = False

    def pos(self):
        return self._position

    def angleDelta(self):
        return QPoint(0, self._delta)

    def accept(self):
        self.accepted = True


def _canvas(qapp):
    canvas = GridCanvas()
    canvas.resize(420, 320)
    canvas.set_image(np.zeros((40, 60, 3), dtype=np.uint8), (60, 40))
    canvas.fit_to_view()
    canvas.show()
    qapp.processEvents()
    return canvas


def test_wheel_small_delta_uses_proportional_zoom(qapp):
    canvas = _canvas(qapp)
    old = canvas.zoom()
    event = _WheelEvent(canvas.rect().center(), 15)
    canvas.wheelEvent(event)
    assert event.accepted
    assert abs(canvas.zoom() - old * (1.25 ** (15 / 120))) < 1e-6
    assert canvas._zoom_badge_text.startswith("缩放")


def test_wheel_respects_zoom_limits(qapp):
    canvas = _canvas(qapp)
    canvas.wheelEvent(_WheelEvent(canvas.rect().center(), 12000))
    assert canvas.zoom() == 64.0
    assert canvas._zoom_badge_text.startswith("最大缩放")
    canvas.wheelEvent(_WheelEvent(canvas.rect().center(), -12000))
    assert canvas.zoom() == 0.2
    assert canvas._zoom_badge_text.startswith("最小缩放")


def test_wheel_keeps_pointer_cell_under_cursor(qapp):
    canvas = _canvas(qapp)
    position = canvas.rect().center()
    before = canvas.cell_at(position)
    canvas.wheelEvent(_WheelEvent(position, 120))
    after = canvas.cell_at(position)
    assert before is not None and after is not None
    assert before == after


def test_zoom_badge_hides_after_timeout(qapp):
    canvas = _canvas(qapp)
    canvas.wheelEvent(_WheelEvent(canvas.rect().center(), 120))
    assert canvas._zoom_badge_text
    QTest.qWait(1100)
    assert canvas._zoom_badge_text == ""
