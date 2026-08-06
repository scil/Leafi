"""门内停留时长推断(方案.md §4 L2 信号b)。

启发式:摄像头在卫生间门外,看不到门内。
  - person 目标在 bathroom_door zone 内"消失"(Frigate event type=end 且最后位于该 zone)
    → 视为进了卫生间,开始计时;
  - 之后任何 person 再次出现(type=new) → 视为出来了,结束计时。
粗糙但可用;装机后按真实事件流校准。计入总分时由调用方施加信任上限(inside_credit_cap)。
"""


class InsideTracker:
    def __init__(self, zone: str = "bathroom_door"):
        self.zone = zone
        self.inside_since: float | None = None
        self.inside_seconds = 0.0

    def reset(self) -> None:
        self.inside_since = None
        self.inside_seconds = 0.0

    def on_event(self, payload: dict, now: float) -> None:
        after = payload.get("after") or {}
        if after.get("label") != "person":
            return
        etype = payload.get("type")
        zones = set(after.get("current_zones") or []) | set(after.get("entered_zones") or [])
        if etype == "end" and self.zone in zones:
            if self.inside_since is None:
                self.inside_since = now
        elif etype == "new" and self.inside_since is not None:
            self.inside_seconds += max(0.0, now - self.inside_since)
            self.inside_since = None

    def finalize(self, now: float) -> float:
        """会话结束:若仍"在门内",把开区间也计入;返回累计秒数。"""
        if self.inside_since is not None:
            self.inside_seconds += max(0.0, now - self.inside_since)
            self.inside_since = None
        return self.inside_seconds
