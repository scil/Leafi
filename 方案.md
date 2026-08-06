# Carema-Kis-AI 技术方案

> 通过摄像头与孩子互动、提醒并**验证**早晚刷牙的家用 AI Agent
> v0.2 · 2026-08-05 · 基于两路专项调研(摄像头选型 / 技术栈)+ 四项已确认决策 + 三项部署确认(年龄 / 安装位 / GPU,见 §11)

---

## 0. 已锁定的决策(方案地基)

| 决策点 | 你的选择 | 对方案的硬约束 |
|---|---|---|
| 隐私架构 | **本地视觉 + 云端大脑** | 影像、人脸、姿态数据**永不出局域网**;云端只收纯文字(对话内容、状态摘要) |
| 交互渠道 | 四个全要(分阶段) | P0 摄像头喇叭喊话 + 家长推送 → P1 视觉验证 → P2 语音对话 → P3 带屏卡通形象 |
| 验证深度 | **视觉确认刷牙动作** | 需要动作识别管线,判定"真的刷了、且刷满 ~2 分钟" |
| 硬件 | 现有 Windows PC + 新购摄像头 | PC 24 小时跑 Docker;摄像头必须开放 RTSP 本地流 |

**部署画像已全部确认**:孩子 10 岁;洗手台在卫生间内、但孩子刷牙时经常叼着牙刷走到外面;显卡 RTX 5070 Ti(16GB)。三项确认如何落进方案,见 §11。

**习惯清单**:早晚刷牙 + **晨起第一杯水**(v0.2 新增)。架构按"可插拔习惯"设计——每个习惯 = {提醒时刻, 验证器, 话术},后续加"收玩具""练字"同理。

---

## 1. 一页纸架构

```mermaid
flowchart LR
    subgraph LAN["🏠 局域网(影像红线之内)"]
        CAM["摄像头 Tapo C225<br/>RTSP 视频流 + tapo:// 喇叭"]
        FRIGATE["Frigate 0.17 (Docker)<br/>人形检测 · 人脸识别(是不是孩子)<br/>事件录像 · 内置 go2rtc"]
        POSE["验证管线(本地)<br/>RTMPose 姿态计分<br/>+ Qwen3-VL 终裁 (Ollama)"]
        AGENT["Agent 主程序 (Python)<br/>APScheduler 定时 · MQTT 订阅<br/>状态机:提醒→教练→验证→上报"]
        VOICE["语音层<br/>FunASR 识别(本地)<br/>Edge-TTS/Kokoro 合成"]
        SCREEN["P3: 旧平板卡通形象<br/>(WebSocket 驱动)"]
    end
    subgraph CLOUD["☁️ 云端(只有文字)"]
        LLM["Claude Haiku 4.5<br/>对话生成 · 周报文案"]
    end
    PARENT["📱 家长手机<br/>Bark / Telegram"]

    CAM -->|RTSP| FRIGATE -->|MQTT: 孩子出现| AGENT
    FRIGATE -->|快照/流| POSE --> AGENT
    AGENT <-->|纯文字| LLM
    AGENT --> VOICE -->|tapo:// 或 USB 音箱| CAM
    AGENT --> SCREEN
    AGENT -->|结果+单帧快照| PARENT
```

数据边界一句话:**摄像头画面、人脸库、姿态数据全部留在这台 PC 上;出网的只有"该说什么话"的文字请求和发到你手机的通知。**

---

## 2. 摄像头选型

### 2.1 结论(短名单)

| 档位 | 型号 | 参考价 | 理由 |
|---|---|---|---|
| **主推 ⭐** | **TP-Link Tapo C225**(2K 云台) | ~CAD $65(Canada Computers 实查 $64.99) | 唯一同时满足全部需求:RTSP/ONVIF 本地流 + **喇叭可被第三方程序调用**(go2rtc `tapo://`,社区实测教程完善)+ F1.6 星光级低光 + **物理隐私模式**(镜头翻转收纳,浴室场景刚需)+ 云台可编程转向。弱点:直播 15 fps——动作识别完全够用 |
| 省钱位 | Tapo C220(2K/30fps)/ C210 | ~CAD $35–60 | 同样的 RTSP + `tapo://` 全链路,少了星光低光和物理隐私模式 |
| 国内采购位 | 小米智能摄像机 3 云台版 | ¥249 | go2rtc v1.9.13+ 新增 `xiaomi://` 源,**含双向音频**,3K 画质;代价:绑米家账号,每次建连需联网取密钥(流量本身走局域网) |
| 后期升级位 | Raspberry Pi 5 + Camera Module 3 + AI HAT+(13/26 TOPS) | ~CAD $230–300 | 完全掌控、端侧推理(YOLO ~36ms/帧)、语音走 USB 音箱零兼容坑;等 P0–P2 跑通后想把系统从你 PC 上搬走时再上 |

> 价格为 2026-08 调研街价,下单以零售页为准。

### 2.2 为什么是这几个标准

1. **RTSP 本地流是底线**:没有它,一切自定义 agent 无从谈起。
2. **喇叭可编程是 P0 的关键**:你选了"摄像头喇叭喊话"做第一阶段输出。三条路里(ONVIF backchannel / go2rtc 专有协议 / 独立音箱),`tapo://` 是目前**最便宜且文档最完善**的专有协议通道;ONVIF backchannel 名义合规但实测个体差异大,不作为硬指标。
3. **1080p–2K 足够**:1–3 米近距场景,4K 纯浪费(解码负担 + 无收益)。
4. **单只室内机走 WiFi 可接受**(Frigate 只警告"多路 WiFi 摄像头"场景);建议给它专用 5GHz SSID。
5. **物理隐私遮蔽**:浴室场景特殊,C225 的镜头收纳模式可以在非刷牙时段"眼睛闭上",对孩子的信任感和实际隐私都重要。

### 2.3 明确避开(封闭云生态)

| 品牌 | 原因 |
|---|---|
| Google Nest | 2022 年砍掉 RTSP,只剩云中转 WebRTC API |
| Ring | 从未有本地流,强制 AWS + 订阅 |
| Wyze | 官方 RTSP 固件已弃更,2025 年起连社区桥接(docker-wyze-bridge)都陷入猫鼠游戏 |
| Eufy | RTSP 仅部分型号+依赖 HomeBase,稳定性口碑差 |
| Reolink 室内机(E1 Pro 等) | 画质好但**喇叭走专有协议、第三方调不动**;可当"纯眼睛"用,不适合本项目 P0 |
| Hikvision / Dahua | 技术上最强(`isapi://` 双向音频可用),但 NDAA/FCC 限制导致北美渠道萎缩、固件更新存疑;不推荐新购 |

### 2.4 为什么 USB 摄像头不是首选

`cv2.VideoCapture(0)` 即插即用确实香,但 **USB 线缆 5 米上限**意味着你的 PC 必须紧挨洗手台,还没有红外夜视、不防潮、无隐私遮蔽。除非你的电脑恰好就在洗手台隔壁,否则 IP 摄像头 + WiFi 解耦位置是正解。

### 2.5 安装与网络

- **位置(已定案)**:装在**卫生间门外的走廊/过道**,画面覆盖门口 + 孩子刷牙时游走的区域(2–4 米),**摄像头永不进卫生间**。这正好利用孩子"边刷牙边走出来"的习惯——大部分刷牙动作恰好发生在门外镜头里;门内零入镜(隐私彻底解决)、无湿气问题、10 岁孩子的体面也保住了。C225 的云台还可编程转向孩子常待的方向。
- **网络**:路由器上给摄像头建 VLAN 或防火墙规则**禁止出公网**(Tapo 云账号只在初始配置时需要);关闭固件自动更新(历史上有固件短暂弄坏 RTSP 的先例),升级前查社区反馈。

---

## 3. 技术栈总表

| 层 | 首选 | 备选 | 说明 |
|---|---|---|---|
| NVR/检测底座 | **Frigate 0.17**(Docker)+ 内置 go2rtc | Scrypted(仅当你重度 Apple 生态) | 人形检测、人脸识别、事件 MQTT、录像保留、快照 API 一站全有 |
| 检测加速 | **RTX 5070 Ti → ONNX/TensorRT**(Blackwell 架构需较新 Frigate 镜像;若遇兼容问题先退 CPU/OpenVINO——单摄 5fps 检测 CPU 也扛得住) | **别买 Coral**(驱动上游已弃更,官方不再推荐) | 将来迁 Pi 5 配 Hailo AI HAT+ |
| 识别"是谁" | **Frigate 内置人脸识别**,model_size: **large**(ArcFace,走 GPU) | InsightFace/DeepFace 自写 | UI 里传 20–30 张照片训练;结果作为 person 的 sub_label 走 MQTT;**只在本地做,永不上云** |
| 刷牙动作计分 | **RTMPose-m**(i7 CPU 90+ FPS)或 YOLO-pose 启发式 | MediaPipe Pose(更轻);Frigate 0.17 UI 自训"brushing/not"分类器做第二票 | 纯 CPU 可跑,见 §4 |
| 视觉终裁 VLM | **Ollama + Qwen3-VL-8B**(Q4≈10–12GB,16GB 显存放得下,按需加载/卸载) | 云端 VLM 违反隐私默认,仅作显式放开后的选项 | 会话结束对 6–10 帧做最终判定;想全离线时对话也可切本地 Qwen3-8B |
| 对话大脑 | **Claude Haiku 4.5**($1/$5 每百万 token,纯文字) | Sonnet 5(更自然);本地 Qwen3-8B(零云依赖) | 月成本 ~$1–2 |
| ASR(中文) | **FunASR SenseVoiceSmall**(本地,官方基准中文错误率 ~7.8%,CPU 17× 实时) | faster-whisper(中文明显更弱) | 阿里开源,活跃维护 |
| TTS(童声中文) | **Edge-TTS**(免费,`zh-CN-XiaoyiNeural` 等少女/儿童感声线) | 本地兜底:**Kokoro-82M-zh**(100 个中文声线,CPU 实时);想给角色克隆专属声音:CosyVoice(GPU) | Edge-TTS 属非官方接口、有限流风险,所以必须备好本地兜底 |
| 唤醒词 | **不需要**——到点主动开口、见人即互动 | 真要:Porcupine(官方支持中文自训)/ sherpa-onnx KWS | 免唤醒是摄像头方案的天然优势 |
| Agent 编排 | **Python 3.12 + APScheduler + paho-mqtt + Anthropic Tool Runner**(`@beta_tool`) | Claude Agent SDK(要长驻会话/MCP 生态时);LangGraph(要断点续跑时) | 固定流程状态机,轻框架最可控省 token |
| 家长通知 | **Bark**(iOS,免费开源,GET 即推)或 **Telegram Bot**(免费,带图带按钮) | Server酱(推微信,免费档 5 条/天);Home Assistant App | 带单帧快照 + 当日摘要 |
| 屏幕形象(P3) | 旧平板/手机浏览器 kiosk + Web 动画角色(WebSocket 收状态) | ESP32-S3-BOX(~$50 带屏) | 工程量约 +30%,放最后 |

---

## 4. 刷牙验证管线(核心难点)

三层漏斗,逐层过滤、互为校验:

```
L1 触发(7×24 常开,便宜)
   到点提醒后,Frigate 在门口/走廊检测到 person 且人脸 sub_label=孩子
   → MQTT 事件唤醒 Agent,会话开始

L2 双信号计分(会话期间,每秒)
   信号 a|可见刷牙秒数:孩子游走进画面时,姿态启发式累计
        (手腕—口鼻距离 < 阈值,且腕点 2–5Hz 小幅周期抖动;左右手都算)
        —— 孩子"边刷边往外走"的习惯让大部分动作直接可见,比对着洗手台还好拍
   信号 b|门内停留秒数:由门口 zone 的进/出事件推断,计入时设信任上限(防"进去玩水")
   判定:可见刷牙 ≥60s 且 (可见刷牙 + 门内停留) ≥110s
        —— 阈值先跑一周、按孩子的真实行为数据再调
   并行第二票(可选):Frigate 0.17 UI 自训 brushing/not-brushing 状态分类器
   实验加分项(可选):Frigate 音频事件(YAMNet 类别含牙刷声/水龙头声),隔门衰减大,仅作佐证

L3 终裁(会话结束,一次)
   优先从"游走片段"抽 6–10 帧 → 本地 Qwen3-VL-8B:
   "这些帧是否显示同一个孩子手持/口含牙刷在刷牙?输出 JSON {verified, confidence, note}"
   → 与 L2 合并出最终结论
```

**误报源与对策**

| 场景 | 对策 |
|---|---|
| 洗脸/喝水(手也靠近嘴) | 时长阈值天然过滤(没人洗脸洗 2 分钟);L3 终裁兜底 |
| 全程待在门内刷、画面看不见 | 门内停留时长兜底计分;教练话术顺势引导("出来走两步,让教练看看你的姿势") |
| 中途跑掉再回来 | 在场秒数与动作秒数分开累计,允许中断 |
| 干刷糊弄(不挤牙膏) | 视觉管线不解决,靠 P3 游戏化激励 + 家长快照抽查;目标是习惯养成不是牙科质检 |

**晨起喝水(v0.2 新增习惯)**:动作短(10–30 秒)、无周期性,姿态启发式不适用,用"持杯 + 仰头"的 VLM 单帧判定即可。**前提是把孩子的水杯固定放在摄像头视野内**(走廊小桌/门口柜上)——一个小布置让喝水从"纯口头提醒"升级成可验证习惯;不想布置就先做纯提醒。

每次会话产出一条结构化记录:`{date, task: 喝水/刷牙, slot: 早/晚, present: bool, active_seconds, verified: bool, confidence, snapshot_path}`,落 SQLite,供通知、周报、P3 积分使用。

**学术/商业佐证**:CES 2026 刚发布的 Kolibree Kids System(Baracoda)就是"摄像头 AI 刷牙教练"的商业成品,思路与本方案几乎同款——问题已被验证可做;学界也有 RGB-D + IMU 的刷牙监测论文和 ROBAS-UCLA 刷牙区域识别开源项目可参考。

---

## 5. 语音交互与人设

**会话流程(P2 完整形态)**:

```
晨间例程 07:20 起 | 晚间 20:30(时刻均可配)
 ├─ 早:先提醒「起床第一杯水」(验证见 §4 附注)→ 完成/超时后进入刷牙流程
 ├─ 摄像头喇叭首次提醒(P0 就有):"刷牙时间到——两分钟,连击别断。"
 ├─ 15 分钟内孩子未出现 → 二次提醒(话术升级) → 仍未出现 → 通知家长(黄色)
 └─ 孩子出现 → 教练模式:
      开场白(按人设) → 计分中里程碑口播(30s/60s/90s:"combo 保持住,还差 30 秒破纪录!")
      → 达标 → 表扬 + 记录 + 通知家长(绿色)
      → 到场但没刷够 → 温和催促一轮 → 通知家长(黄色,附快照)
```

**人设(10 岁定制)**:定位是**教练 + 队友**,不是哄小孩的精灵——10 岁孩子吃"平等 + 幽默 + 数据"这一套,忌幼稚化。名字让孩子自己起(参与感 = 接受度,"帮老爸调教 AI"本身就是卖点)。系统提示词要点:短句、损友式幽默但只鼓励不训斥、里程碑用倒计时/连击(combo)口播、战绩用数据说话("本周 13/14,历史最长连击 9 天")。TTS 默认声线建议用少年感的 `zh-CN-YunxiNeural` 而非幼女声。

**技术链路**:麦克风(USB 会议扬声麦,~CAD $40–130,自带回声消除)→ FunASR 流式识别 → Claude Haiku(带当日状态上下文)→ Edge-TTS → 音箱。回合制目标延迟 <2s;打断式对话(barge-in)不做,除非 P3 想升级再上 Pipecat 框架。

---

## 6. Agent 状态机与代码骨架

```
IDLE ──(cron 07:30/20:30)──► REMIND ──► WAIT_PRESENCE(≤15min)
        ▲                                    │见人           │超时
        │                              COACHING(计分)      REMIND_2 ──超时──► NOTIFY(黄)
        │                              │达标      │超时未达标
        │                           VERIFIED   NUDGE ──► NOTIFY(黄+快照)
        │                              │
        └───── LOG + PRAISE + NOTIFY(绿) ◄┘
```

```python
# agent/main.py(示意 —— 实际 P0 约 200 行胶水代码)
SLOTS = {"morning": "07:30", "evening": "20:30"}

async def brushing_session(slot: str):
    await speak(opening_line(slot))                      # P0: go2rtc tapo:// → 摄像头喇叭
    if not await wait_presence(sub_label="kid", timeout=900):   # Frigate MQTT
        await speak(second_reminder())
        if not await wait_presence(sub_label="kid", timeout=600):
            return notify_parent(slot, status="missed")
    score = await coach_and_score(target_sec=100)        # L2: RTMPose 计分 + 里程碑鼓励
    verdict = await vlm_verdict(sample_frames(6))        # L3: 本地 Qwen3-VL 终裁
    save_session(slot, score, verdict)                   # SQLite
    notify_parent(slot, status="done" if verdict.ok else "partial",
                  snapshot=verdict.snapshot)
```

**LLM 的接入方式**:状态流转、计时、调度全部在本地代码里(确定性、零 token);Claude 只负责"此刻对孩子说什么"和"给家长的周报怎么写"——通过 Anthropic Tool Runner 注册 `speak` / `get_today_stats` / `notify_parent` 几个工具即可。若后期想要长驻会话记忆(记得孩子昨天说过什么),再迁 Claude Agent SDK。

**Frigate/go2rtc 关键配置(示意)**:

```yaml
# frigate.yml
go2rtc:
  streams:
    sink_cam:
      - rtsp://frigate_user:pass@192.168.1.50:554/stream1   # 视频+麦克风(摄像头账号)
      - tapo://cloud_password@192.168.1.50                  # 喇叭回传通道(双向音频)
cameras:
  hallway:
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/sink_cam
          roles: [detect, record]
    detect: { width: 1280, height: 720, fps: 5 }
    objects: { track: [person] }
    zones:
      bathroom_door:        # 装好后在 Frigate UI 画出门口区域再回填坐标(§4 门内停留计时靠它)
        coordinates: TODO
face_recognition:
  enabled: true
  model_size: large        # RTX 5070 Ti → ArcFace
record:
  retain: { days: 2, mode: active_objects }
```

---

## 7. 隐私与安全红线清单

1. **影像/人脸/姿态永不出网**——这是你选的架构,也恰好是合规现实:Anthropic 政策禁止用 API 做人脸/身份识别,OpenAI 要求处理 13 岁以下儿童数据须启用零保留(ZDR),Gemini 对含未成年人的图片拒答率高。**身份判断只在本地 Frigate 做,云端 prompt 里永远不出现图像和身份信息。**
2. 云端只收:纯文字的对话生成请求("孩子刷到 60 秒了,说句鼓励的话")和周报文案请求。
3. **保留策略**:Frigate 录像 retain 1–2 天、仅事件片段;VLM 采样帧用后即删;家长通知只带单帧。
4. **网络隔离**:摄像头 VLAN/防火墙禁出公网;Frigate/MQTT 设密码;Web 界面仅局域网访问。
5. **对孩子透明**:10 岁的孩子必须知情并参与——一起装、一起给教练起名字、说清"摄像头在门外、只在任务时段睁眼"(非任务时段联动 C225 物理镜头收纳)。被尊重的感觉是这个产品能用下去的前提,偷偷监控只会换来对抗;**摄像头永不进卫生间是不可谈判的底线**。
6. PC 端:Docker 容器跑非管理员权限;SQLite/快照目录加 BitLocker(你的机器大概率已开)。

---

## 8. 分阶段实施路线

| 阶段 | 内容 | 工作量 | 验收标准 |
|---|---|---|---|
| **P0 跑通闭环** | 买 C225 → Frigate Docker 起底座 → APScheduler 定时(喝水 07:20 / 早刷牙 07:35 / 晚刷牙 20:30)→ Edge-TTS 语音经 `tapo://` 从摄像头喇叭播提醒 → Frigate 检测到人/没人 → Bark/Telegram 推送结果 | **1 个周末** | 三个时点自动喇叭提醒;你手机收到"已到场 / 超时未出现"+快照 |
| **P1 视觉验证** | 人脸训练(20–30 张照片区分孩子/大人)→ RTMPose 计分管线 → Ollama+Qwen3-VL 终裁 →(可选)Frigate 自训分类器第二票 | 1–2 周业余时间 | 通知升级为"刷了 X 秒,判定 ✅/❌";误报率肉眼可接受 |
| **P2 语音教练** | USB 扬声麦 → FunASR + Claude Haiku + Edge-TTS 回合制对话;里程碑鼓励;简单问答("刷完了吗"→听懂"刷完啦") | 1–2 周业余时间 | 孩子全程有来有回地被"精灵"陪着刷完 |
| **P3 形象+习惯系统** | 旧平板 Web 卡通角色(表情随状态变化)+ 积分/贴纸奖励 + Haiku 生成的家长周报;可扩展到收玩具、写作业等习惯 | 2–4 周,可选 | 连续打卡数据 + 每周日晚自动周报 |

每个阶段结束都是一个**完整可用的产品**,随时可以停在任何一阶。

---

## 9. 预算

**硬件(一次性)**

| 项 | 金额 | 必要性 |
|---|---|---|
| Tapo C225 | ~CAD $65 | P0 必须 |
| USB 会议扬声麦(Anker PowerConf 级) | ~CAD $40–130 | P2 才需要 |
| 旧平板/手机(屏幕形象) | $0(利旧) | P3 |
| **合计** | **< CAD $200** | |

**运行(每月)**

| 项 | 金额 |
|---|---|
| Claude Haiku 4.5(对话+周报,纯文字) | ~$1–3 |
| 视觉推理(全本地) | $0 |
| 通知(Bark/Telegram) | $0 |
| PC 24 小时运行电费增量(约 70–100W) | ~CAD $7–10(隐藏成本;将来迁 N100 迷你主机/Pi 5 可降到 1/10) |

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| Edge-TTS 非官方接口被限流/失效 | Kokoro-82M-zh 本地 CPU 兜底,一行配置切换 |
| Tapo 固件更新破坏 RTSP/`tapo://`(历史发生过) | 关自动更新;升级前查 go2rtc/Frigate 社区 |
| 孩子躲镜头/糊弄 | 在场秒数+动作秒数双指标;家长通知带原始快照;根本解法是 P3 把它做成游戏而非监工 |
| WiFi 不稳 | 专用 5GHz SSID;极端情况电力猫/拉网线 |
| PC 睡眠/重启断服务 | 电源计划设永不睡眠;服务用 NSSM 注册为 Windows 服务自启 |
| TP-Link 政策尾部风险(美国调查主要针对路由器) | 本地 RTSP 不受影响;真下架也不影响已购设备局域网使用 |
| 浴室湿气损伤设备 | 安装位远离淋浴、通风;C225 非防水型号,门外安装更佳(见 §11) |

---

## 11. 已确认的部署配置(原:三个待确认项)

| 确认项 | 结果 | 落进方案的位置 |
|---|---|---|
| 孩子年龄 | **10 岁** | §5 人设改为"教练+队友",连击/成就/数据化战绩;TTS 换少年感声线 |
| 洗手台位置 | **卫生间内;但孩子刷牙时经常叼着牙刷走到门外游走** | §2.5 摄像头定案:门外走廊、门内零入镜;§4 验证改为"门外可见刷牙动作 + 门内停留时长"双信号——孩子的游走习惯反而成了最佳观测窗口 |
| PC 显卡 | **ASUS Prime RTX 5070 Ti(16GB)** | §3 视觉全本地满配:TensorRT 检测 + ArcFace 人脸 + Qwen3-VL-8B 终裁,16GB 全放得下;想进一步全离线,对话也可切本地 Qwen3-8B |
| 习惯清单(v0.2 新增) | 早晚刷牙 + **晨起第一杯水** | §4 附注(水杯放进摄像头视野即可验证)、§5 晨间例程、§8 P0 三时点 |

---

## 12. 关键参考(调研来源精选)

**摄像头**
- go2rtc 双向音频支持列表(README):https://github.com/AlexxIT/go2rtc
- Tapo + Frigate 双向音频实操教程:https://www.dima.pm/integrating-tapo-cameras-with-frigate-including-2-way-audio/
- Tapo RTSP/ONVIF 官方 FAQ:https://www.tp-link.com/us/support/faq/4465/
- go2rtc 小米 `xiaomi://` 源文档:https://go2rtc.org/internal/xiaomi/ (机型列表 issue #1982)
- Frigate 硬件推荐(含"别再买 Coral"):https://docs.frigate.video/frigate/hardware/
- Reolink 各系 RTSP/ONVIF 支持矩阵:https://support.reolink.com/articles/900000617826
- Wyze RTSP 官方声明(已弃更):https://support.wyze.com/hc/en-us/articles/360026245231-Wyze-Cam-RTSP

**技术栈**
- Frigate 人脸识别文档(0.16+ 内置):https://docs.frigate.video/configuration/face_recognition
- LLM Vision(HA 集成,若走 HA 路线):https://github.com/valentinfrlch/ha-llmvision
- RTMPose(CPU 90+ FPS 姿态):https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose
- FunASR / SenseVoice(中文 ASR):https://github.com/modelscope/FunASR
- Kokoro-82M v1.1-zh(本地中文 TTS):https://huggingface.co/onnx-community/Kokoro-82M-v1.1-zh-ONNX
- CosyVoice(音色克隆):https://github.com/FunAudioLLM/CosyVoice
- Edge-TTS:https://github.com/rany2/edge-tts
- Claude 模型与定价:https://platform.claude.com/docs/en/about-claude/models/overview.md
- Anthropic 儿童安全/使用政策:https://www.anthropic.com/policy
- 商业对照 Kolibree Kids System(CES 2026):https://us.kolibree.com/
- 相邻开源:ROBAS-UCLA 刷牙区域检测 https://github.com/ROBAS-UCLA/Toothbrushing-region-detection

---

*下一步:下单 Tapo C225。仓库已含 P0 骨架(Frigate/MQTT 容器 + 三时点喇叭提醒 + 家长推送),摄像头到货后填 `.env` 即可联调——见 README.md。*
