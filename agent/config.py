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
    bark_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

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
