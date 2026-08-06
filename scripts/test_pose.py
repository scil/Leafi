"""姿态→刷牙计分链路冒烟(摄像头到货前可用任意含人的视频/本机摄像头验证)。

用法(repo 根目录):
  .venv\\Scripts\\python scripts/test_pose.py <视频路径|RTSP地址|0(本机摄像头)>
每秒打印一次累计:present(在画面)/ brush(判定在刷)秒数。Ctrl+C 结束。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from agent.vision.pose import YoloPose  # noqa: E402
from agent.vision.scorer import BrushScorer  # noqa: E402


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "0"
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened():
        sys.exit(f"打不开视频源: {src}")
    pose = YoloPose()
    scorer = BrushScorer(fps_hint=8)
    last_print = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = time.monotonic()
            kp = pose.infer(frame, t)
            if kp is not None:
                scorer.push(kp)
            if t - last_print >= 1.0:
                last_print = t
                print(f"present={scorer.present_seconds:6.1f}s  brush={scorer.brush_seconds:6.1f}s")
    except KeyboardInterrupt:
        pass
    print(f"\n最终:present={scorer.present_seconds:.1f}s  brush={scorer.brush_seconds:.1f}s")


if __name__ == "__main__":
    main()
