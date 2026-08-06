"""P1 视觉验证会话编排(方案.md §4)。

kp 源可注入:测试喂合成关键点序列;生产用 rtsp_kp_stream()(RTSP 抽帧 → YoloPose)。
⚠️ rtsp_kp_stream 依赖真机摄像头,属"待实机联调"部分;判定逻辑本身已单测覆盖。
"""
import asyncio
import base64
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..config import settings
from .dwell import InsideTracker
from .scorer import KP, BrushScorer
from .vlm import Verdict, verdict

log = logging.getLogger("verifier")

Sample = tuple[float, KP | None, bytes | None]  # (t, 关键点, 该帧jpg——仅采样帧带)


@dataclass
class VerifyResult:
    brush_seconds: float = 0.0
    inside_seconds: float = 0.0
    vlm: Verdict | None = None
    verified: bool = False
    snapshots: list[bytes] = field(default_factory=list)

    def summary(self) -> str:
        v = "✅" if self.verified else "❌"
        vlm = f",VLM {self.vlm.confidence:.0%}" if self.vlm else ",VLM 未启用"
        return (f"{v} 可见刷牙 {self.brush_seconds:.0f}s + 门内 {self.inside_seconds:.0f}s"
                f"(上限 {settings.inside_credit_cap}s){vlm}")


async def run_brush_verification(
    kp_source: AsyncIterator[Sample],
    inside: InsideTracker,
    duration_s: float = 300,
    fps_hint: float = 8.0,
    on_milestone=None,
) -> VerifyResult:
    """消费 kp 流直到超时或流结束;30/60/90s 里程碑回调;结束做 VLM 终裁。"""
    scorer = BrushScorer(fps_hint=fps_hint)
    result = VerifyResult()
    fired: set[int] = set()
    start: float | None = None
    last_t: float | None = None

    async for t, kp, jpg in kp_source:
        start = t if start is None else start
        last_t = t
        if t - start > duration_s:
            break
        if kp is not None:
            qualified = scorer.push(kp)
            if qualified and jpg is not None and len(result.snapshots) < 8:
                result.snapshots.append(jpg)
        for ms in (30, 60, 90):
            if scorer.brush_seconds >= ms and ms not in fired:
                fired.add(ms)
                if on_milestone:
                    await on_milestone(ms)

    now = last_t if last_t is not None else time.monotonic()
    result.brush_seconds = scorer.brush_seconds
    result.inside_seconds = inside.finalize(now)

    visible_ok = result.brush_seconds >= settings.min_visible_brush_seconds
    total = result.brush_seconds + min(result.inside_seconds, settings.inside_credit_cap)
    total_ok = total >= settings.target_brush_seconds
    if visible_ok and total_ok:
        imgs = [base64.b64encode(s).decode() for s in result.snapshots]
        result.vlm = await verdict(imgs, kind="brush")
        result.verified = result.vlm.verified if result.vlm else True
    return result


# ---------- 生产 kp 源:RTSP → YOLO-pose(待实机联调) ----------

def _capture_thread(url: str, sample_interval: float, out_q, stop: threading.Event):
    import cv2  # 随 ultralytics 安装

    cap = None
    while not stop.is_set():
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                time.sleep(2)
                continue
        last = 0.0
        while not stop.is_set():
            ok, frame = cap.read()
            if not ok:
                cap.release()
                cap = None
                break
            now = time.monotonic()
            if now - last >= sample_interval:
                last = now
                try:
                    out_q.put_nowait((now, frame))
                except Exception:
                    pass  # 队列满就丢帧
    if cap is not None:
        cap.release()


async def rtsp_kp_stream(
    url: str | None = None, fps: float = 8.0, duration_s: float = 300
) -> AsyncIterator[Sample]:
    """RTSP 抽帧 → 姿态推理,产出 (t, KP, jpg)。运行在 GPU 上,每天仅任务时段活跃。"""
    import queue

    import cv2

    from .pose import YoloPose

    url = url or f"rtsp://127.0.0.1:8554/{settings.stream_name}"
    pose = YoloPose(settings.pose_model)
    q: queue.Queue = queue.Queue(maxsize=4)
    stop = threading.Event()
    th = threading.Thread(
        target=_capture_thread, args=(url, 1.0 / fps, q, stop), daemon=True
    )
    th.start()
    loop = asyncio.get_running_loop()
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration_s:
            try:
                t, frame = await loop.run_in_executor(None, q.get, True, 2.0)
            except Exception:
                continue
            kp = await loop.run_in_executor(None, pose.infer, frame, t)
            jpg = None
            if kp is not None:
                ok, buf = cv2.imencode(".jpg", frame)
                jpg = buf.tobytes() if ok else None
            yield (t, kp, jpg)
    finally:
        stop.set()
