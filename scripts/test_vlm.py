"""VLM 终裁冒烟:需要 Ollama 在运行且已拉取 VLM_MODEL。

用法(repo 根目录):
  .venv\\Scripts\\python scripts/test_vlm.py 图1.jpg [图2.jpg ...] [--water]
"""
import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.vision.vlm import verdict  # noqa: E402


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    kind = "water" if "--water" in sys.argv else "brush"
    if not args:
        sys.exit(__doc__)
    imgs = [base64.b64encode(Path(p).read_bytes()).decode() for p in args]
    v = await verdict(imgs, kind=kind)
    if v is None:
        sys.exit("VLM 不可用:确认 `ollama serve` 在跑、模型已 pull(见 README)")
    print(f"kind={kind}  verified={v.verified}  confidence={v.confidence:.0%}  note={v.note}")


if __name__ == "__main__":
    asyncio.run(main())
