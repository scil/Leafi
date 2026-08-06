import asyncio
import json
import logging
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

from .config import settings

log = logging.getLogger("presence")

Listener = Callable[[dict, float], None]  # (frigate 事件payload, monotonic 时刻)


class Presence:
    """订阅 Frigate MQTT 事件:提供"等到有人出现"原语 + 原始事件监听(供门内停留推断)。"""

    def __init__(self) -> None:
        self._event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listeners: list[Listener] = []

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._event = asyncio.Event()
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        c.connect_async(settings.mqtt_host, settings.mqtt_port)
        c.loop_start()  # 后台线程;broker 掉线自动重连

    def add_listener(self, fn: Listener) -> Callable[[], None]:
        """注册原始事件监听(在事件循环线程回调);返回取消函数。"""
        self._listeners.append(fn)

        def unsubscribe() -> None:
            if fn in self._listeners:
                self._listeners.remove(fn)

        return unsubscribe

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT 已连接 %s:%s", settings.mqtt_host, settings.mqtt_port)
        client.subscribe("frigate/events")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        after = data.get("after") or {}
        if after.get("label") != "person":
            return
        now = time.monotonic()
        if self._loop:
            for fn in list(self._listeners):
                self._loop.call_soon_threadsafe(fn, data, now)
        if data.get("type") not in ("new", "update"):
            return
        # 人脸过滤:训练好 Frigate 人脸后,在 .env 设 CHILD_FACE_LABEL=孩子名
        sub = after.get("sub_label")
        sub_name = sub[0] if isinstance(sub, (list, tuple)) and sub else sub
        if settings.child_face_label and sub_name != settings.child_face_label:
            return
        log.info("检测到 person(camera=%s, sub_label=%s)", after.get("camera"), sub_name)
        if self._loop and self._event:
            self._loop.call_soon_threadsafe(self._event.set)

    async def wait_for_person(self, timeout_s: float) -> bool:
        assert self._event is not None, "presence.start() 未调用"
        self._event.clear()
        try:
            await asyncio.wait_for(self._event.wait(), timeout_s)
            return True
        except TimeoutError:
            return False


presence = Presence()
