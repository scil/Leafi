"""向本地 MQTT 发一条伪造的 Frigate person 事件,用于无摄像头联调。

用法(先 docker compose up -d mosquitto):
  终端 A: .venv\\Scripts\\python -m agent.main --mock --now brush_pm
  终端 B: .venv\\Scripts\\python scripts/fake_event.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paho.mqtt.publish as publish  # noqa: E402

from agent.config import settings  # noqa: E402

payload = {"type": "new", "after": {"label": "person", "camera": "hallway", "sub_label": None}}
publish.single(
    "frigate/events",
    json.dumps(payload),
    hostname=settings.mqtt_host,
    port=settings.mqtt_port,
)
print(f"已发送伪造 person 事件 → frigate/events ({settings.mqtt_host}:{settings.mqtt_port})")
