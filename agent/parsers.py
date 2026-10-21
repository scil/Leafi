"""纯解析函数:.env 设置页(leafi/envedit.py)拿它们当 validator,agent/config.py 的 parsed_* 也调它们。

两边用同一个函数,页面认可的值和 agent 运行时认可的值才不会分叉。这里不许读文件、读环境变量、
碰 Settings:导入本模块不能有副作用(tests/test_env_validators.py 盯着)。
接受范围与改造前完全一样(比如 "noday:99:99" 仍能解析);收紧规则是另一项改动。
"""


def parse_weekly_report(text: str) -> tuple[str, int, int] | None:
    """"sun:20:45" -> ("sun", 20, 45);空串 = 禁用。"""
    raw = text.strip()
    if not raw:
        return None
    day, hh, mm = raw.split(":")
    return day.strip().lower(), int(hh), int(mm)


def parse_schedule(text: str) -> list[tuple[str, str]]:
    """"water:07:20,brush_pm:20:30" -> [("water","07:20"), ...]"""
    out = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        name, hhmm = item.split(":", 1)
        out.append((name.strip(), hhmm.strip()))
    return out
