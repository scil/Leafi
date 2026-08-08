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

## 补丁 2:ch0 命令通道满员杀连接(播放中途截断根因)

同文件 `worker()`:相机在对讲期间往 **channel 0(命令应答通道,popBuf 仅 10 条)**发确认,
播放期间无人消费该通道,10 条一满 `Push` 报错,worker 直接拆掉整条 cs2 连接(视频流同死)。
修法:ch0 溢出改为丢弃而非致命:

```go
if err != nil {
    if ch == 0 {
        // Command-reply channel has no consumer during media/speaker
        // sessions. Drop overflow instead of killing the connection.
        err = nil
        continue
    }
    c.err = fmt.Errorf("%s: %w", "cs2", err)
    return
}
```

此坑为本项目独立发现(2026-08-07),上游尚无对应 issue/PR。

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
