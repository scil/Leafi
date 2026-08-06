# Carema-Kis-AI

通过门外走廊的摄像头,与 10 岁的孩子互动、提醒并**验证**日常习惯(晨起喝水、早晚刷牙)的家用 AI Agent。完整设计见 **[方案.md](方案.md)**(v0.2)。

## 当前状态

| 阶段 | 状态 |
|---|---|
| P0 提醒闭环(定时喇叭提醒 → 到场检测 → 家长推送) | ✅ 代码就绪,mock 模式可无摄像头联调 |
| P1 视觉验证引擎(姿态计分 / 门内停留 / VLM 终裁) | ✅ 代码就绪,28 项单测通过;待摄像头实拍校准 |
| P2 对话大脑(Claude 生成教练台词,无 key 自动回退静态话术) | ✅ 代码就绪 |
| P3 家长周报(每周日 20:45 推送本周战绩,`WEEKLY_REPORT` 可调/禁用) | ✅ 代码就绪 |
| 硬件 | ⏳ **待下单:TP-Link Tapo C225**(~CAD $65) |

## 前置

- Docker Desktop(WSL2 后端)、Python 3.12(仓库用 `.venv`,由 `uv venv --python 3.12 .venv` 创建)
- P1 另需:NVIDIA 驱动 + `torch`(CUDA 12.8)+ `ultralytics` + Ollama(见下)

## 快速开始

```powershell
copy .env.example .env      # 编辑:摄像头、时刻表、通知渠道
docker compose up -d        # Frigate + MQTT
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m agent.main              # 常驻:按 SCHEDULE 定时执行
.venv\Scripts\python -m agent.main --now brush_pm   # 立即跑一次(联调用)
```

## 无摄像头联调(mock)

```powershell
docker compose up -d mosquitto
.venv\Scripts\python -m agent.main --mock --now brush_pm
# 另开终端,伪造一条"检测到人"事件:
.venv\Scripts\python scripts/fake_event.py
```

想在 PC 上**真听到**教练声音:`.env` 设 `SPEAKER_BACKEND=local`(用 ffplay 播放),去掉 `--mock` 再跑。

## 测试

```powershell
.venv\Scripts\python -m pytest -q
```

覆盖:刷牙计分器(合成刷牙/喝水/发呆序列)、门内停留推断、验证编排(里程碑/VLM 否决/门内补分)、存储与连击统计、会话状态机三分支、时刻表解析。

## P1 启用步骤(摄像头到货后)

1. 装依赖:
   ```powershell
   .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128
   .venv\Scripts\pip install -r requirements-p1.txt
   ```
2. 本地 VLM:`scoop install ollama` → `ollama serve` → `ollama pull qwen3-vl:8b`
3. Frigate UI 上传孩子/家长照片各 20–30 张训练人脸 → `.env` 填 `CHILD_FACE_LABEL=孩子名`,并在 `config/frigate/config.yml` 打开 `face_recognition`(model_size: large)
4. Frigate UI 画出 `bathroom_door` zone,坐标回填 `config/frigate/config.yml`
5. `.env` 改 `VERIFY_MODE=vision`;先跑一周收数据,再按方案.md §4 调阈值

冒烟脚本(不必等摄像头):

```powershell
.venv\Scripts\python scripts/test_pose.py 某段有人的视频.mp4   # 姿态→计分链路
.venv\Scripts\python scripts/test_vlm.py 某张照片.jpg          # Ollama VLM 终裁
```

## 摄像头到货后的接入清单

1. Tapo App 配网 → **我 → 工具 → 相机账号** 创建本地账号(`.env` 的 `CAM_USER/CAM_PASSWORD`)
2. App 开启**第三方兼容**(RTSP/ONVIF)
3. 路由器固定 IP(填 `CAM_IP`)+ 防火墙/VLAN **禁其出公网**
4. 关闭固件自动更新(历史上有更新破坏 RTSP 的先例)
5. `TAPO_CLOUD_PASSWORD` 填 TP-Link 云账号密码(`tapo://` 喇叭通道)
6. `docker compose restart frigate` → http://localhost:5000 应见画面
7. VLC 验证 `rtsp://CAM_USER:CAM_PASSWORD@CAM_IP:554/stream1`
8. go2rtc 控制台 http://localhost:1984 对 `sink_cam` 测试双向语音
9. 安装位:**卫生间门外走廊**,覆盖门口+孩子游走区(摄像头永不进卫生间);孩子的水杯固定放在视野内
10. 画 `bathroom_door` zone → 回填配置

## 已知待实机验证项(诚实清单)

- `agent/speaker.py` 经 go2rtc 向摄像头喇叭推音频的 `src` 语法,按 [go2rtc API](https://github.com/AlexxIT/go2rtc#api) 实机微调
- `agent/vision/verifier.py` 的 RTSP 抽帧循环(`rtsp_kp_stream`)未接过真流;判定逻辑本身已单测覆盖
- 门内停留推断(`dwell.py`)的启发式需按真实 Frigate 事件流校准
- Tapo 新固件对 `tapo://` 云密码校验偶有变动,以 go2rtc 社区 issue 为准

## 路线图

P0 提醒闭环 → P1 视觉验证 → P2 语音对话教练(FunASR+麦克风)→ P3 卡通形象+积分周报。详见 [方案.md](方案.md) §8。
