from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    go2rtc_url: str = "http://127.0.0.1:1984"
    frigate_url: str = "http://127.0.0.1:5000"
    camera_name: str = "hallway"
    stream_name: str = "sink_cam"

    schedule: str = "water:07:20,brush_am:07:35,brush_pm:20:30"
    wait_presence_min: int = 15
    wait_retry_min: int = 10

    tts_voice: str = "zh-CN-YunxiNeural"
    speaker_backend: str = "go2rtc"     # go2rtc(摄像头喇叭)| local(本机 ffplay,开发用)
    bark_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ---- P1 视觉验证(方案.md §4)----
    verify_mode: str = "presence"       # presence(P0 仅到场)| vision(P1 动作验证)
    ollama_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "qwen3-vl:8b"
    pose_model: str = "yolo11n-pose.pt"
    target_brush_seconds: int = 100     # 可见刷牙 + 门内停留(封顶)需达到的总秒数
    min_visible_brush_seconds: int = 60 # 门外可见刷牙动作的最低秒数
    inside_credit_cap: int = 40         # 门内停留的信任上限(防"进去玩水")
    verify_window_s: int = 300          # 单次验证会话时长上限
    child_face_label: str = ""          # Frigate 人脸训练后填孩子名;空 = 任何 person 都算

    # ---- P2 对话大脑 ----
    brain_model: str = "claude-haiku-4-5"
    anthropic_api_key: str = ""

    mock: bool = False

    def parsed_schedule(self) -> list[tuple[str, str]]:
        """SCHEDULE="water:07:20,brush_pm:20:30" -> [("water","07:20"), ...]"""
        out = []
        for item in self.schedule.split(","):
            item = item.strip()
            if not item:
                continue
            name, hhmm = item.split(":", 1)
            out.append((name.strip(), hhmm.strip()))
        return out


settings = Settings()
