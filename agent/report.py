"""家长周报(P3 预览):汇总一周战绩推送到家长手机。纯文字,不含影像。"""
import datetime as dt
import logging

from . import storage
from .notify import send
from .phrases import title

log = logging.getLogger("report")


def build_report(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    stats = storage.week_stats(today=today)
    streak = storage.streak_days(today=today)
    if stats["total"] == 0:
        return "本周还没有任何打卡记录(系统刚上线或摄像头未接入)。"
    lines = [
        f"本周战绩:完成 {stats['done']} 次,漏掉 {stats['missed']} 次,当前连击 {streak} 天。"
    ]
    for task, (done, missed) in storage.week_by_task(today=today).items():
        seg = f"· {title(task)}:完成 {done} 次"
        if missed:
            seg += f",未完成 {missed} 次"
        lines.append(seg)
    if stats["missed"] == 0:
        lines.append("零漏打卡,值得表扬一下。")
    return "\n".join(lines)


async def send_weekly_report() -> None:
    text = build_report()
    log.info("发送家长周报:\n%s", text)
    await send("📊 本周习惯周报", text)
