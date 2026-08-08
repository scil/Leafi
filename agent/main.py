import argparse
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import speaker
from .config import settings
from .phrases import TASKS
from .presence import presence
from .report import send_weekly_report
from .session import run_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-9s %(message)s")
log = logging.getLogger("main")


async def amain(args: argparse.Namespace) -> None:
    if args.say:
        # 纯喇叭测试:不碰 MQTT/任务流程,说完即退
        await speaker.say(args.say)
        return

    presence.start(asyncio.get_running_loop())
    if args.now:
        await run_task(args.now)
        return

    sched = AsyncIOScheduler()
    for task, hhmm in settings.parsed_schedule():
        if task not in TASKS:
            log.warning("SCHEDULE 里的任务 %r 没有话术定义,跳过", task)
            continue
        h, m = hhmm.split(":")
        sched.add_job(run_task, CronTrigger(hour=int(h), minute=int(m)), args=[task], id=task)
        log.info("已排程 %s @ %s", task, hhmm)
    weekly = settings.parsed_weekly_report()
    if weekly:
        day, h, m = weekly
        sched.add_job(
            send_weekly_report, CronTrigger(day_of_week=day, hour=h, minute=m), id="weekly_report"
        )
        log.info("已排程 家长周报 @ %s %02d:%02d", day, h, m)
    sched.start()
    log.info("Agent 常驻运行中(mock=%s)。Ctrl+C 退出。", settings.mock)
    await asyncio.Event().wait()


def main() -> None:
    p = argparse.ArgumentParser(description="Carema-Kis-AI P0 agent")
    p.add_argument("--now", choices=list(TASKS), help="立即执行一次指定任务(联调用)")
    p.add_argument("--mock", action="store_true", help="mock 模式:喇叭/通知只打日志")
    p.add_argument("--say", metavar="TEXT", help="仅向喇叭播报一段任意文本后退出(测试用)")
    p.add_argument("--voice", help="临时指定 TTS 声线(配 --say,如 en-US-JennyNeural)")
    args = p.parse_args()
    if args.mock:
        settings.mock = True
    if args.voice:
        settings.tts_voice = args.voice
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
