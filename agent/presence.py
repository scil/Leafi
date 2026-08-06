import asyncio
import json
import logging

import paho.mqtt.client as mqtt

from .config import settings

log = logging.getLogger("presence")


class Presence:
    """订阅 Frigate MQTT 事件,提供 '等到有人出现' 的异步原语。
    P0: 任何 person 都算;P1 起按 sub_label(人脸识别结果)过滤是不是孩子。"""

    def __init__(self) -> None:
        self._event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._event = asyncio.Event()
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        c.connect_async(settings.mqtt_host, settings.mqtt_port)
        c.loop_start()  # 后台线程;broker 掉线会自动重连

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT 已连接 %s:%s", settings.mqtt_host, settings.mqtt_port)
        client.subscribe("frigate/events")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        after = data.get("after") or {}
        if after.get("label") == "person" and data.get("type") in ("new", "update"):
            # TODO(P1): if after.get("sub_label") != 孩子名: return
            log.info("检测到 person(camera=%s, sub_label=%s)",
                     after.get("camera"), after.get("sub_label"))
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
