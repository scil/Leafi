"""静态话术库(10 岁定制:教练+队友口吻,平等、幽默、不训斥)。
P2 起由 agent/brain.py 的 Claude 动态生成,这里是离线兜底与风格基准。"""
import random

TASKS: dict[str, dict] = {
    "water": {
        "title": "晨起喝水",
        "opening": [
            "早!起床第一件事——把水杯干了,一整杯。",
            "教练晨报:先喝水,再谈刷牙。杯子在老地方。",
        ],
        "retry": ["水还没喝?一分钟的事,别让连击断在一杯水上。"],
        "arrived": ["看到你了。咕咚咕咚,干杯!"],
        "done": ["水分补给完成,开局漂亮。"],
        "partial": ["杯子好像没动啊,教练看着呢。"],
    },
    "brush_am": {
        "title": "早刷牙",
        "opening": [
            "刷牙时间——两分钟,连击别断。",
            "教练上线。牙刷拿起来,今天继续保持纪录。",
        ],
        "retry": ["还没见到人。再不来,今早战绩记零。"],
        "arrived": ["看到你了,开刷!两分钟,计时开始。"],
    },
    "brush_pm": {
        "title": "晚刷牙",
        "opening": ["睡前最后一关——刷牙两分钟,刷完今天完美收官。"],
        "retry": ["第二次提醒——牙刷在等你,连击要保不住了。"],
        "arrived": ["到位。两分钟,开始。"],
    },
}

GENERIC = {
    "milestone": [
        "combo 保持住,还差一点破纪录!",
        "节奏不错,别停。",
        "过半了,牙缝里的细菌已经在撤退。",
    ],
    "done": ["达标!今天的记录保住了,漂亮。", "任务完成,战绩+1。"],
    "partial": ["嗯……时长好像不太够,教练先记半分,明天找回来。"],
}


def pick(task: str, kind: str) -> str:
    opts = TASKS.get(task, {}).get(kind) or GENERIC.get(kind) or ["好嘞。"]
    return random.choice(opts)


def title(task: str) -> str:
    return TASKS.get(task, {}).get("title", task)
