"""各任务的话术(10 岁定制:教练+队友口吻,平等、幽默、不训斥)。
P2 起改由 Claude 按上下文生成,这里保留为离线兜底。"""
import random

TASKS: dict[str, dict] = {
    "water": {
        "title": "晨起喝水",
        "opening": [
            "早!起床第一件事——把水杯干了,一整杯。",
            "教练晨报:先喝水,再谈刷牙。杯子在老地方。",
        ],
        "retry": [
            "水还没喝?一分钟的事,别让连击断在一杯水上。",
        ],
        "arrived": [
            "看到你了。咕咚咕咚,干杯!",
        ],
    },
    "brush_am": {
        "title": "早刷牙",
        "opening": [
            "刷牙时间——两分钟,连击别断。",
            "教练上线。牙刷拿起来,今天继续保持纪录。",
        ],
        "retry": [
            "还没见到人。再不来,今早战绩记零。",
        ],
        "arrived": [
            "看到你了,开刷!两分钟,计时开始。",
        ],
    },
    "brush_pm": {
        "title": "晚刷牙",
        "opening": [
            "睡前最后一关——刷牙两分钟,刷完今天完美收官。",
        ],
        "retry": [
            "第二次提醒——牙刷在等你,连击要保不住了。",
        ],
        "arrived": [
            "到位。两分钟,开始。",
        ],
    },
}


def pick(task: str, kind: str) -> str:
    return random.choice(TASKS[task][kind])


def title(task: str) -> str:
    return TASKS[task]["title"]
