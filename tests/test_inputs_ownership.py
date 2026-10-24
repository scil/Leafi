"""Input ownership (M7 design D21, rev 9) through the real `Inputs`: an input belongs to the prompt that was current
when the learner finished it; an unowned listen keeps M6's behaviour (the rest of the suite)."""

from __future__ import annotations

import time

import anyio
import pytest

from leafi.core.ports import ListenerLost
from leafi.core.text import typed_utterance
from leafi.study.harness.activities import _hint_reply
from leafi.study.harness.inputs import StaleInput, _Item, _Switched
from tests.test_controls import make, run_with


class Stamped:
    """Delivers (delay_s, text) items; each utterance is stamped as finished when its read began (the learner
    spoke then; recognition took `delay_s`). Text None raises ListenerLost. Then blocks."""

    def __init__(self, items, voice: bool = False) -> None:
        self.items, self.is_voice = list(items), voice

    async def next_utterance(self, timeout_s):
        if not self.items:
            await anyio.sleep(3600)
        began = time.monotonic()
        delay, text = self.items.pop(0)
        await anyio.sleep(delay)
        if text is None:
            raise ListenerLost("microphone unplugged")
        u = typed_utterance(text, "voice" if self.is_voice else "console")
        u.ended_at = began
        return u

    async def pause(self) -> None: ...

    async def resume(self, after_s: float = 0.0) -> None: ...


A, B = ("act", 1, 1), ("act", 1, 2)


async def test_a_late_answer_to_one_question_is_not_given_to_the_next(tmp_path):
    inputs = make(tmp_path, Stamped([(0.3, "an answer for A"), (0.05, "an answer for B")]))

    async def body(i, out):
        out.append(await i.listen(0.05, A))  # A times out while its answer is still being recognised
        out.append((await i.listen(2, B)).text)  # A's late answer is dropped; B's own read follows (no hang)

    assert await run_with(inputs, body) == [None, "an answer for B"]


async def test_a_skip_is_posted_only_by_its_own_prompt(tmp_path):
    inputs = make(tmp_path, Stamped([(0.2, "skip"), (0.3, "skip"), (0.05, "yes")]))

    async def body(i, out):
        await i.listen(0.05, A)  # A's skip arrives later, during B
        u = await i.listen(2, B)  # B's own skip (stamped during B) is posted and returned, as M6
        out.append((u.text, i.latch.take_skip()))
        out.append([it.kind for it in i.take_late()])  # A's skip waited in `late`, never posted
        out.append(i.latch.take_skip())

    assert await run_with(inputs, body) == [("skip", True), ["skip"], False]


async def test_a_page_turn_during_a_brain_wait_goes_to_the_caller(tmp_path):
    inputs = make(tmp_path, Stamped([(0.05, "/page 5"), (0.05, "hello")]))

    async def body(i, out):
        async with i.controls_only(("wait", 3)) as taken:
            await anyio.sleep(0.3)
        out.append([(it.kind, it.u.text) for it in taken])
        out.append((await i.listen(1)).text)  # the other line stays queued for the next listen

    assert await run_with(inputs, body) == [[("page", "/page 5")], "hello"]


async def test_an_ear_lost_at_a_boundary_is_absorbed_and_inside_an_activity_ends_it(tmp_path):
    console = Stamped([(0.2, "typed on the console"), (0.2, "more")])
    inputs = make(tmp_path, Stamped([(0.05, None)], voice=True), control=console)

    async def body(i, out):
        out.append((await i.listen(2, ("offer", 1, 1))).text)  # absorbed: no activity was running
        out.append(i.notice)  # "mic lost" waits for the main flow's next line
        i.activity_started_at = time.monotonic() - 10  # an activity that began before the switch...
        i._send.send_nowait(_Switched(time.monotonic()))  # ...sees a (second) switch
        with pytest.raises(StaleInput):
            await i.listen(2, ("page", 9))

    out = await run_with(inputs, body)
    assert out == ["typed on the console", "mic_lost"]


def test_an_activity_takes_only_its_own_late_items(tmp_path):
    inputs = make(tmp_path, Stamped([]))
    inputs.late = [_Item("page", typed_utterance("/page 4"), ("offer", 1, 1)),
                   _Item("skip", typed_utterance("skip"), ("act", 7, "card.0")),
                   _Item("page", typed_utterance("/page 5"), ("act", 7, "card.1"))]
    mine = inputs.take_late(lambda o: o[:2] == ("act", 7))
    assert [it.u.text for it in mine] == ["skip", "/page 5"]
    assert [it.u.text for it in inputs.take_late()] == ["/page 4"]  # the boundary's, left for the boundary


@pytest.mark.parametrize("text, reply", [("yes", "yes"), ("Yes please!", "yes"), ("please", "yes"),
                                         ("no", "no"), ("No, thank you.", "no"), ("not now", "no"),
                                         ("skip", None), ("/page 5", None), ("/fix fox box", None),
                                         ("The fox ran home", None)])
def test_the_hint_offer_answers_only_yes_and_no(text, reply):
    """D21 / round 8 #5: anything else is handed back to read_listen's dispatch, never read as reading here."""
    assert _hint_reply(typed_utterance(text)) == reply
