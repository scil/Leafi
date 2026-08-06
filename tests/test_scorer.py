import math

from agent.vision.scorer import KP, BrushScorer


def brushing_frames(duration: float, fps: float):
    """合成刷牙:手腕贴近口鼻 + 3Hz 小幅纵向往复。"""
    for i in range(int(duration * fps)):
        t = i / fps
        rel = 0.05 * math.sin(2 * math.pi * 3 * t)
        yield KP(t=t, nose=(500.0, 300.0),
                 l_wrist=(510.0, 300.0 + rel * 100), r_wrist=None, shoulder_w=100.0)


def test_brushing_counts():
    s = BrushScorer(fps_hint=10)
    for kp in brushing_frames(120, 10):
        s.push(kp)
    assert s.brush_seconds >= 100
    assert s.present_seconds >= 115


def test_drinking_hold_not_counted():
    """喝水=手贴嘴但静止:near 满足、无周期抖动 → 不计。"""
    s = BrushScorer(fps_hint=10)
    for i in range(200):
        s.push(KP(t=i / 10, nose=(500, 300), l_wrist=(505, 310), r_wrist=None, shoulder_w=100))
    assert s.brush_seconds < 3


def test_idle_far_wrist_not_counted():
    s = BrushScorer(fps_hint=10)
    for i in range(100):
        s.push(KP(t=i / 10, nose=(500, 300), l_wrist=(500, 700), r_wrist=None, shoulder_w=100))
    assert s.brush_seconds == 0


def test_missing_keypoints_safe():
    s = BrushScorer(fps_hint=10)
    s.push(KP(t=0, nose=None, l_wrist=None, r_wrist=None, shoulder_w=None))
    s.push(KP(t=0.1, nose=(1, 1), l_wrist=None, r_wrist=None, shoulder_w=100))
    assert s.brush_seconds == 0


def test_low_fps_variance_mode():
    """<8fps 退化为方差判据(如直接用 Frigate detect 流)。"""
    s = BrushScorer(fps_hint=5)
    for i in range(int(60 * 5)):
        t = i / 5
        rel = 0.05 * math.sin(2 * math.pi * 3 * t)
        s.push(KP(t=t, nose=(500, 300), l_wrist=(510, 300 + rel * 100), r_wrist=None, shoulder_w=100))
    assert s.brush_seconds >= 40
