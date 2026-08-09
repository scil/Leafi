# Carema-Kis-AI 项目约定

家用 AI Agent:门外走廊摄像头 + 语音,提醒并验证 10 岁孩子的日常习惯(晨起喝水、早晚刷牙)。
设计文档 = [方案.md](方案.md)(v0.2,先读它);实施状态见 README.md 的状态表。

## 不可谈判的红线(改代码前必读)

1. **影像/人脸/姿态数据永不出局域网**。视觉推理全部本地(Frigate + YOLO-pose + Ollama VLM);云端(Claude API)只收纯文字,prompt 里不得出现图像或身份信息。
2. **摄像头永不进卫生间**,只装门外走廊;验证靠"门外可见动作 + 门口 zone 停留推断"。
3. 对孩子透明:这是陪伴教练不是暗中监控;话术风格是"教练+队友"(平等/幽默/不训斥,忌幼稚化)。

## 常用命令

```powershell
.venv\Scripts\python -m pytest -q                     # 单测(必须全绿再提交)
.venv\Scripts\python -m agent.main --mock --now brush_pm   # mock 联调(配 scripts/fake_event.py)
.venv\Scripts\python -m agent.webui                        # 动作编辑界面 → 127.0.0.1:8770
docker compose up -d                                  # Frigate + mosquitto
```

- Python 3.12 venv(uv 创建);系统 Python 是 3.9,**别用系统 pip**。
- MQTT 宿主端口是 **18830**(Windows 保留了 1883 所在端口段),容器内仍是 1883。
- torch 要装 cu128 版(RTX 5070 Ti / Blackwell):`pip install torch --index-url https://download.pytorch.org/whl/cu128`

## 结构速览

- `agent/` 主程序:`main.py`(APScheduler 入口)→ `session.py`(状态机:提醒→等到场→验证→上报)
  - `tasks.py` **任务注册表**:一个动作=一条 TaskSpec(标题/排程/验证策略/阈值/判据/话术/终裁提问)。
    数据在 `config/tasks.yml`,**加新动作走界面**:`scripts\win\taskeditor.bat` → 127.0.0.1:8770。
    读取带 mtime 检查,改完即时生效;**只有排程时刻要重启 agent**。
    yml 缺失时回退 `tasks.py` 里的 BUILTIN + `phrases.py`/`vlm.py` 的静态兜底。
    改动前先看 `validate()`——校验规则(含红线 01:终裁提问必须写明不识别身份)集中在那里
  - `webui/` 动作编辑界面(标准库 http.server,只监听回环;两个接口 + 一张单页)
  - `presence.py` Frigate MQTT 事件;`speaker.py` TTS→摄像头喇叭(go2rtc tapo://)或本机 ffplay
  - `brain.py` Claude Haiku 生成台词(无 key 回退 `phrases.py` 静态话术)
  - `vision/` P1 验证引擎:`scorer.py`(周期动作计分,纯逻辑;判据 anchor/axis 见其 PRESETS)、`dwell.py`(门内停留)、`vlm.py`(Ollama 终裁)、`verifier.py`(编排;RTSP 部分待实机)
- `config/frigate/config.yml` Frigate 模板(占位符从 .env 注入);`config/tasks.yml` 动作注册表(界面读写);`tests/` 58 项单测
- 会话记录:SQLite `data/sessions.db`(storage.py,含连击/周统计)

## 摄像头:多机型一键切换

- 过渡机(现有,**已跑通**):**小米智能摄像机 3 云台版** = `cam_xiaomi`——P2P 源在**宿主 go2rtc**(tools/go2rtc,自建带补丁版,必读 tools/go2rtc/PATCHES.md),容器只中继;建连需外网取密钥;喇叭 opus(16k 单声道模板)
- 终选候选(待下单):**Tapo C260** = `cam_tapo`(RTSP + tapo:// 喇叭;编码 pcma)
- 切机型只改 `.env` 的 `STREAM_NAME`(+`SPEAKER_AUDIO_CODEC`),Frigate 取流与喇叭推送同步切换。

## 当前待实机验证

~~xiaomi 流入 Frigate~~、~~喇叭推送~~(均已于 2026-08-07 实测跑通);剩:rtsp_kp_stream 真流、dwell 启发式校准。
