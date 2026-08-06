"""刷牙动作计分器(方案.md §4 L2 信号a)。纯逻辑、零重依赖,可单测。

帧级判定"在刷":
  near   任一手腕到鼻的距离 < near_k × 肩宽
  动态   采样 ≥8fps 时:窗口内近侧手腕相对纵坐标的速度符号翻转率 ≥ min_flips_per_s
         (刷牙 2–5Hz 小幅往复;喝水是"抬起-保持",翻转率≈0)
         低帧率(<8fps,如直接用 Frigate detect 流)退化为:窗口内位置标准差
         落在 [min_std, max_std] —— 手在动但没有大幅走位
"""
from collections import deque
from dataclasses import dataclass
from statistics import pstdev


@dataclass
class KP:
    """一帧的关键点(像素坐标);缺失置 None。"""
    t: float
    nose: tuple[float, float] | None
    l_wrist: tuple[float, float] | None
    r_wrist: tuple[float, float] | None
    shoulder_w: float | None


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class BrushScorer:
    def __init__(
        self,
        fps_hint: float,
        near_k: float = 1.2,
        window_s: float = 2.0,
        min_flips_per_s: float = 2.0,
        min_std: float = 0.02,
        max_std: float = 0.6,
        noise_eps: float = 0.01,
        max_gap_s: float = 0.6,
    ):
        self.fps_hint = fps_hint
        self.near_k = near_k
        self.window_s = window_s
        self.min_flips_per_s = min_flips_per_s
        self.min_std = min_std
        self.max_std = max_std
        self.noise_eps = noise_eps
        self.max_gap_s = max_gap_s

        self.brush_seconds = 0.0
        self.present_seconds = 0.0
        self._last_t: float | None = None
        self._window: deque[tuple[float, float]] = deque()  # (t, rel_y)

    def push(self, kp: KP) -> bool:
        """喂入一帧;返回该帧是否记为"在刷"。"""
        dt = 0.0
        if self._last_t is not None:
            dt = min(max(kp.t - self._last_t, 0.0), self.max_gap_s)
        self._last_t = kp.t
        self.present_seconds += dt

        near, rel_y = self._near_and_rel(kp)
        if rel_y is not None:
            self._window.append((kp.t, rel_y))
            while self._window and kp.t - self._window[0][0] > self.window_s:
                self._window.popleft()
        else:
            self._window.clear()

        qualified = near and self._is_dynamic()
        if qualified:
            self.brush_seconds += dt
        return qualified

    def _near_and_rel(self, kp: KP) -> tuple[bool, float | None]:
        if kp.nose is None or kp.shoulder_w is None or kp.shoulder_w <= 0:
            return False, None
        wrists = [w for w in (kp.l_wrist, kp.r_wrist) if w is not None]
        if not wrists:
            return False, None
        nearest = min(wrists, key=lambda w: _dist(w, kp.nose))
        near = _dist(nearest, kp.nose) < self.near_k * kp.shoulder_w
        rel_y = (nearest[1] - kp.nose[1]) / kp.shoulder_w
        return near, rel_y

    def _is_dynamic(self) -> bool:
        if len(self._window) < 3:
            return False
        span = self._window[-1][0] - self._window[0][0]
        if span <= 0:
            return False
        ys = [y for _, y in self._window]
        if self.fps_hint >= 8:
            flips = 0
            prev_sign = 0
            for a, b in zip(ys, ys[1:]):
                d = b - a
                if abs(d) < self.noise_eps:
                    continue
                sign = 1 if d > 0 else -1
                if prev_sign and sign != prev_sign:
                    flips += 1
                prev_sign = sign
            return flips / span >= self.min_flips_per_s
        return self.min_std <= pstdev(ys) <= self.max_std
