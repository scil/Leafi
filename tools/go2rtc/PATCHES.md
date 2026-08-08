# 宿主 go2rtc 本地补丁记录

当前 `go2rtc.exe` 是 **v1.9.14 + 两个本地补丁**的自建版(版本号显示 `1.9.14+dev.b5948cf.dirty`)。
上游发版包含这些修复之前,重装/升级都必须重新打补丁构建,否则小米喇叭回退成噪音/截断。

## 补丁 1:WritePacket 把 payload 落在包外(纯噪音根因)

`pkg/xiaomi/miss/cs2/conn.go` 的 `WritePacket`:

```go
copy(req[offset:], hdr)
copy(req[offset+hdrSize:], hdr)      // ← bug:又复制了一遍 hdr
// 修为:
copy(req[offset+hdrSize:], payload)
```

音频 payload 从未装进 cs2 包,相机收到"加密头+零填充",解码即纯静电噪音。
上游:[issue #2175](https://github.com/AlexxIT/go2rtc/issues/2175)(2026-08-07 由 RuiFG 定位)、修复 [PR #2406](https://github.com/AlexxIT/go2rtc/pull/2406)(draft)。

## 补丁 2:缓冲区满即杀连接(播放截断 + 每 5 分钟掉线的共同根因)

`dataChannel` 的 popBuf 一满,`Push` 就返回错误,`worker()` 收到错误**直接拆掉整条 cs2 连接**
(视频、音频、喇叭全断)。而重连要跑一趟小米云换密钥——比丢几帧昂贵几个数量级,
云端慢的时候甚至重连不上(实测撞见过 `miss_get_vendor` 连续三次 `context deadline exceeded`)。

两个通道都会中招,先后暴露为两种症状:

- **channel 0(命令应答,缓冲 10)**:相机在对讲期间回执,播放时无人消费 → 喇叭播报中途整句被截断。
- **channel 2(媒体,缓冲原 100)**:消费端偶尔跟不上 → 视频流每 5–20 分钟断一次重连。

修法(统一策略,`Push` 内一处解决):缓冲满时**丢弃最旧的一块**腾位置,连接照常存活;
媒体缓冲同时从 100 扩到 512 吸收突发。

```go
select {
case c.popBuf <- c.waitData[:c.waitSize]:
default:
    // Consumer fell behind. Drop the oldest chunk to make room instead of
    // failing: the caller treats a full buffer as fatal and tears down the
    // whole P2P connection, and reconnecting costs a cloud round-trip.
    select {
    case <-c.popBuf:
    default:
    }
    select {
    case c.popBuf <- c.waitData[:c.waitSize]:
    default:
    }
}
```

丢最旧而非最新,是为了让延迟有界(丢掉的是已经过时的画面)。
此坑为本项目独立发现(2026-08-07);媒体通道那半边对应上游
[issue #2057](https://github.com/AlexxIT/go2rtc/issues/2057)(仍 open,无人给出根因)。

**实测(2026-08-08 00:02–00:29,27 分钟连续观测)**:补丁前同长度窗口内 P2P 重连 10 次、
缓冲错误反复、伴随小米云 `miss_get_vendor` 连续三次超时;补丁后重连 **0 次**
(P2P 远端端口 25 次采样恒为 19652)、缓冲错误 **0**、日志零错误零警告、
Frigate `camera_fps 5.1 / skipped_fps 0`。

## 重建步骤

```powershell
git clone --depth 1 --branch v1.9.14 https://github.com/AlexxIT/go2rtc
# 打上面两个补丁(pkg/xiaomi/miss/cs2/conn.go)
cd go2rtc && go build -o go2rtc-patched.exe .
# 停进程 → 替换 tools/go2rtc/go2rtc.exe → scripts/win/go2rtc-host.bat 重启
```

防火墙规则按程序路径匹配,同路径换新 exe 不需重新放行。

## 配套的喇叭链路参数(缺一即劣化)

- `go2rtc-host.yaml` 覆盖 ffmpeg opus 模板:`16k 单声道 40ms voip`(默认 48k 立体声 20ms 有持续底噪)
- `agent/tts.py` 合成时烘入首尾静音(头 0.9s 防功放唤醒吃字,尾 0.6s 防截尾)
- API 动态源禁止空格("source with spaces may be insecure"),所以垫片不能走 `#raw=`
- `-re` 实时速率是 go2rtc 默认(`-readrate_initial_burst 0.001 -re`),无需自加
