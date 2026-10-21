from pydantic_settings import BaseSettings, SettingsConfigDict

from . import parsers


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 18830  # 宿主机映射端口(Windows 保留了 1883 所在端口段)
    go2rtc_url: str = "http://127.0.0.1:1984"
    frigate_url: str = "http://127.0.0.1:15000"  # 宿主映射端口(5000 在 Windows 保留段内)
    camera_name: str = "hallway"
    stream_name: str = "sink_cam"

    schedule: str = "water:07:20,brush_am:07:35,brush_pm:20:30"
    wait_presence_min: int = 15
    wait_retry_min: int = 10

    tts_voice: str = "zh-CN-YunxiNeural"
    tts_voice_en: str = "en-US-JennyNeural"  # --say 传入纯英文文本时自动改用这个声线
    speaker_backend: str = "go2rtc"     # go2rtc(摄像头喇叭)| local(本机 ffplay,开发用)
    speaker_audio_codec: str = "pcma"   # 喇叭推送编码:tapo→pcma | xiaomi→opus
    speaker_src_dir: str = "/cache/tts" # go2rtc 读 TTS 文件的路径:容器实例=/cache/tts;宿主实例=Windows 路径
    bark_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_with_snapshot: bool = False  # owner opt-in: attach one frame to Telegram (ADR-0011); default off

    # ---- P1 视觉验证(方案.md §4)----
    verify_mode: str = "presence"       # presence(P0 仅到场)| vision(P1 动作验证)
    ollama_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "qwen3-vl:8b"
    pose_model: str = "yolo11n-pose.pt"
    # 以下三条是 pose_dwell 类任务的全局默认;单个任务可在 agent/tasks.py 的 TaskSpec 里覆盖
    target_active_seconds: int = 100     # 可见动作 + 门内停留(封顶)需达到的总秒数
    min_visible_active_seconds: int = 60 # 门外可见动作的最低秒数
    inside_credit_cap: int = 40          # 门内停留的信任上限(防"进去玩水")
    verify_window_s: int = 300          # 单次验证会话时长上限
    child_face_label: str = ""          # Frigate 人脸训练后填孩子名;空 = 任何 person 都算

    # ---- P2 对话大脑 ----
    brain_model: str = "claude-haiku-4-5"
    anthropic_api_key: str = ""

    # ---- 家长周报(P3 预览):周几:时:分;留空禁用 ----
    weekly_report: str = "sun:20:45"

    mock: bool = False

    def parsed_weekly_report(self) -> tuple[str, int, int] | None:
        """"sun:20:45" -> ("sun", 20, 45);空串 = 禁用。解析在 agent/parsers.py(设置页用同一个函数校验)。"""
        return parsers.parse_weekly_report(self.weekly_report)

    def parsed_schedule(self) -> list[tuple[str, str]]:
        """SCHEDULE="water:07:20,brush_pm:20:30" -> [("water","07:20"), ...]"""
        return parsers.parse_schedule(self.schedule)


settings = Settings()
