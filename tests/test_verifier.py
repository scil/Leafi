import math

import pytest

from agent.tasks import spec
from agent.vision import verifier as V
from agent.vision.dwell import InsideTracker
from agent.vision.scorer import KP
from agent.vision.vlm import Verdict

SPEC = spec("brush_pm")
FRAME = object()  # 占位"原始帧";真正的编码由 _encode_jpg 做,测试里 monkeypatch 掉


@pytest.fixture(autouse=True)
def _fake_encode(monkeypatch):
    monkeypatch.setattr(V, "_encode_jpg", lambda frame: b"fake-jpg")


async def kp_stream(duration: float = 120, fps: float = 10):
    for i in range(int(duration * fps)):
        t = i / fps
        rel = 0.05 * math.sin(2 * math.pi * 3 * t)
        yield (t,
               KP(t=t, nose=(500.0, 300.0), l_wrist=(510.0, 300.0 + rel * 100),
                  r_wrist=None, shoulder_w=100.0),
               FRAME)


async def test_verified_with_milestones(monkeypatch):
    async def fake_verdict(imgs, kind="brush", prompt=""):
        assert imgs, "达标后应带采样帧调用 VLM"
        return Verdict(True, 0.9)

    monkeypatch.setattr(V, "verdict", fake_verdict)
    milestones = []

    async def on_ms(ms):
        milestones.append(ms)

    res = await V.run_pose_verification(
        kp_stream(), InsideTracker(), SPEC, duration_s=300, fps_hint=10, on_milestone=on_ms
    )
    assert res.verified
    assert res.active_seconds >= 100
    assert milestones == [30, 60, 90]
    assert 1 <= len(res.snapshots) <= 8
    assert "✅" in res.summary()


async def test_insufficient_skips_vlm(monkeypatch):
    async def fake_verdict(imgs, kind="brush", prompt=""):
        raise AssertionError("时长不达标不应调用 VLM")

    monkeypatch.setattr(V, "verdict", fake_verdict)
    res = await V.run_pose_verification(
        kp_stream(duration=20), InsideTracker(), SPEC, duration_s=300, fps_hint=10
    )
    assert not res.verified
    assert res.active_seconds < 25


async def test_inside_credit_makes_up_total(monkeypatch):
    """门外只刷了 70s(≥min_visible),门内停留补足到 target。"""
    async def fake_verdict(imgs, kind="brush", prompt=""):
        return Verdict(True, 0.8)

    monkeypatch.setattr(V, "verdict", fake_verdict)
    inside = InsideTracker()
    inside.on_event({"type": "end", "after": {"label": "person",
                                              "current_zones": ["bathroom_door"]}}, now=0.0)
    inside.on_event({"type": "new", "after": {"label": "person"}}, now=50.0)  # 门内 50s
    res = await V.run_pose_verification(
        kp_stream(duration=70), inside, SPEC, duration_s=300, fps_hint=10
    )
    # 70s 可见 + min(50, cap=40) = 110 ≥ 100 → 达标
    assert res.verified
    assert res.inside_seconds == 50.0


async def test_encode_is_lazy_and_capped(monkeypatch):
    """1200 帧里只该编码 8 次:不合格的帧不编,攒够 8 张后也不再编。"""
    calls = []

    def counting_encode(frame):
        calls.append(frame)
        return b"jpg"

    monkeypatch.setattr(V, "_encode_jpg", counting_encode)

    async def fake_verdict(imgs, kind="brush", prompt=""):
        return Verdict(True, 0.9)

    monkeypatch.setattr(V, "verdict", fake_verdict)
    res = await V.run_pose_verification(
        kp_stream(), InsideTracker(), SPEC, duration_s=300, fps_hint=10
    )
    assert len(res.snapshots) == 8
    assert len(calls) == 8


async def test_vlm_veto(monkeypatch):
    """时长够但 VLM 否决(比如拿的是勺子不是牙刷)→ 不通过。"""
    async def fake_verdict(imgs, kind="brush", prompt=""):
        return Verdict(False, 0.7, "未见牙刷")

    monkeypatch.setattr(V, "verdict", fake_verdict)
    res = await V.run_pose_verification(
        kp_stream(), InsideTracker(), SPEC, duration_s=300, fps_hint=10
    )
    assert not res.verified
