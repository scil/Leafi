"""Prototype P-5: Kokoro → prepared clip → camera speaker: end-to-audible latency and truncation.

AUDIBLE IN THE CHILD'S HOME. Run only when the owner says so, with the owner next to the camera
(AGENTS.md: never play audio on the camera speaker unasked). Measures what performance.md budgets at
≤ 2.5 s end-to-audible on the camera (0.9 s head pad is fixed cost) and whether a word and a line are
truncated at the start or the end.

Owner's command (host go2rtc running, camera online):
    scripts\\win\\go2rtc-host.bat
    .venv\\Scripts\\python scripts/proto/p5_camera_latency.py --i-am-present
Then answer the prompts: press Enter the moment you HEAR the sound start, and say whether the first/last
word was cut. The script prints synthesis time, push-accepted time, your reaction time and the clip length.
Without `--i-am-present` it only prepares the clips and prints the push command it would send.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from leafi.core.config import Settings  # noqa: E402

LINES = ["through", "Let's try that word once more.", "The little brown dog walked slowly down the hill."]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--i-am-present", action="store_true", help="the owner is at the camera and wants sound")
    a = ap.parse_args()
    from leafi import app as composition
    from leafi.services import tts

    settings = Settings()
    built = composition.build(settings, text_mode=False, voice_policy="primary")
    cam = built.devices.get("desk_cam")
    if cam is None:
        print("desk_cam is disabled (missing .env values?):", built.warnings)
        return
    service = tts.create(settings)
    for text in LINES:
        t0 = time.perf_counter()
        clip = await service.synth(text, "en")
        t_synth = time.perf_counter() - t0
        prepared = await cam.prepare(clip)
        t_prep = time.perf_counter() - t0
        src = cam.source_for(prepared)
        print(f"\n'{text}': synth {t_synth:.2f}s, prepared {t_prep:.2f}s, clip {clip.duration_s:.2f}s, src={src}")
        if not a.i_am_present:
            print("  (dry run) would POST", f"{cam.url}/api/streams?dst={cam.stream}&src={src}")
            continue
        input("  Press Enter to push, then press Enter again the moment you hear it start… ")  # noqa: ASYNC250 - owner-run
        t_push = time.perf_counter()
        task = asyncio.create_task(cam.play(clip))
        await asyncio.get_running_loop().run_in_executor(None, input, "")
        heard = time.perf_counter() - t_push
        await task
        cut = input("  Was the first word cut? the last word? (none / first / last / both): ").strip()  # noqa: ASYNC250
        print(f"  end-to-audible {heard:.2f}s (budget 2.5 s incl. 0.9 s head pad); truncation: {cut or 'none'}")


if __name__ == "__main__":
    asyncio.run(main())
