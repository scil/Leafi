"""向本地 MQTT 发一条伪造的 Frigate person 事件,用于无摄像头联调。

用法(先 docker compose up -d mosquitto):
  终端 A: python -m agent.main --mock --now brush_pm
  终端 B: python scripts/fake_event.py
"""
import json

import paho.mqtt.publish as publish

payload = {"type": "new", "after": {"label": "person", "camera": "hallway", "sub_label": None}}
publish.single("frigate/events", json.dumps(payload), hostname="127.0.0.1")
print("已发送伪造 person 事件 → frigate/events")
