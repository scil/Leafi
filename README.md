# Carema-Kis-AI

通过门外走廊的摄像头,与 10 岁的孩子互动、提醒并验证日常习惯(晨起喝水、早晚刷牙)的家用 AI Agent。

完整设计见 **[方案.md](方案.md)**(v0.2)。当前代码为 **P0 骨架**:定时喇叭提醒 → 到场检测 → 家长手机推送。

## 硬件清单

- [ ] TP-Link **Tapo C225**(~CAD $65)——待下单
- [x] Windows 11 PC(RTX 5070 Ti)24 小时运行 Docker + agent

## 前置

- Docker Desktop(WSL2 后端)
- Python 3.12+

## 快速开始

```powershell
# 1) 配置
copy .env.example .env      # 编辑 .env:摄像头 IP/账号、提醒时刻、通知渠道

# 2) 起底座(Frigate + MQTT)
docker compose up -d

# 3) 装依赖、跑 agent
pip install -r requirements.txt
python -m agent.main            # 常驻:按 SCHEDULE 定时执行
python -m agent.main --now brush_pm   # 立即跑一次"晚刷牙"流程(联调用)
```

## 无摄像头联调(mock 模式)

摄像头到货前就能把主流程跑通:

```powershell
docker compose up -d mosquitto
python -m agent.main --mock --now brush_pm
# 另开一个终端,伪造一条"检测到人"事件:
python scripts/fake_event.py
```

mock 模式下喇叭播报与手机推送只打日志。联调时可把 `.env` 里 `WAIT_PRESENCE_MIN` 临时改成 1。

## 摄像头到货后的接入清单

1. Tapo App 完成配网 → **我 → 工具 → 相机账号** 创建本地账号(`.env` 的 `CAM_USER/CAM_PASSWORD`)
2. App 里开启**第三方兼容**开关(启用 RTSP/ONVIF)
3. 路由器上给摄像头**固定 IP**(填入 `.env` 的 `CAM_IP`),并加防火墙/VLAN 规则**禁止其访问公网**
4. 关闭摄像头**固件自动更新**(历史上有更新破坏 RTSP 的先例)
5. `TAPO_CLOUD_PASSWORD` 填 TP-Link 云账号密码(`tapo://` 喇叭通道用)
6. `docker compose restart frigate` → 打开 http://localhost:5000 应能看到画面
7. VLC 打开 `rtsp://CAM_USER:CAM_PASSWORD@CAM_IP:554/stream1` 二次验证
8. go2rtc 控制台 http://localhost:1984 里对 `sink_cam` 测试两-way audio(网页按住说话)
9. 安装位:**卫生间门外走廊**,覆盖门口+孩子游走区(摄像头永不进卫生间);孩子的水杯固定放在视野内
10. 在 Frigate UI 画出 `bathroom_door` zone,坐标回填 `config/frigate/config.yml`

## 已知待实机验证项(诚实清单)

- `agent/speaker.py` 经 go2rtc 向摄像头喇叭推音频的 `src` 参数语法,需按 [go2rtc API 文档](https://github.com/AlexxIT/go2rtc#api) 在真机上微调
- Tapo 新固件对 `tapo://` 云密码校验偶有变动,联调时以 go2rtc 社区 issue 为准
- Frigate 检测器 P0 先用 CPU;P1 换 ONNX/TensorRT(RTX 5070 Ti)

## 路线图

P0 提醒+到场推送(本骨架)→ P1 视觉验证(人脸/姿态/Qwen3-VL)→ P2 语音对话教练 → P3 卡通形象+积分周报。详见 [方案.md](方案.md) §8。
