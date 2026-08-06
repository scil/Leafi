"""YOLO-pose 后端:BGR 帧 → KP(取画面中最大的人)。

ultralytics 延迟导入 —— 未装 P1 依赖(requirements-p1.txt)时,导入本模块不报错,
实例化时才给出清晰提示。COCO 17 关键点:0=nose, 5/6=shoulders, 9/10=wrists。
"""
from .scorer import KP


class YoloPose:
    def __init__(self, model_path: str = "yolo11n-pose.pt", conf: float = 0.4):
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError(
                "缺少 P1 依赖:.venv\\Scripts\\pip install -r requirements-p1.txt"
            ) from e
        self.model = YOLO(model_path)
        self.conf = conf

    def infer(self, frame, t: float = 0.0) -> KP | None:
        res = self.model.predict(frame, verbose=False)[0]
        if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
            return None
        # 取 bbox 面积最大的人
        areas = [(float((b[2] - b[0]) * (b[3] - b[1])), i)
                 for i, b in enumerate(res.boxes.xyxy.tolist())]
        _, idx = max(areas)
        xy = res.keypoints.xy[idx].tolist()
        kconf = (res.keypoints.conf[idx].tolist()
                 if res.keypoints.conf is not None else [1.0] * len(xy))

        def pt(j: int) -> tuple[float, float] | None:
            if j >= len(xy) or kconf[j] < self.conf:
                return None
            x, y = xy[j]
            if x == 0 and y == 0:  # ultralytics 对不可见点输出 (0,0)
                return None
            return (float(x), float(y))

        l_sh, r_sh = pt(5), pt(6)
        shoulder_w = None
        if l_sh and r_sh:
            shoulder_w = ((l_sh[0] - r_sh[0]) ** 2 + (l_sh[1] - r_sh[1]) ** 2) ** 0.5
        return KP(t=t, nose=pt(0), l_wrist=pt(9), r_wrist=pt(10), shoulder_w=shoulder_w)
