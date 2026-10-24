"""ADR-0017 §2.1: every return is constructed and checked under the current epoch, or Reobserve; a skip heard
before an offer excludes nothing; at `bands.announce` a skip moves to the next candidate."""

from __future__ import annotations

from leafi.study.harness.menu import allowed
from leafi.study.harness.negotiate import REOBSERVE, negotiate
from leafi.study.harness.state import Facts
from tests.harness_helpers import make_session

READING = Facts(has_book=True, unread_current=True)


async def test_an_epoch_change_before_the_return_is_reobserve(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 9})
    stale = s.epoch()
    s.latch.epoch.bump()
    assert await negotiate(s, None, allowed(s), stale) is REOBSERVE


async def test_a_skip_posted_before_the_offer_excludes_nothing(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 9})
    s.latch.post_skip()
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert out.activity.kind == "read_listen" and not s.boundary.excluded


async def test_at_announce_a_skip_after_the_announcement_moves_to_the_next_candidate(tmp_path):
    s = make_session(tmp_path, facts=READING, values={"autonomy": 9})

    class SkipAfterFirst(type(s.talk)):
        async def say(self, text, **kw):
            await super().say(text, **kw)
            if len(self.said) == 1:
                s.latch.post_skip()

    s.talk = SkipAfterFirst([], s.latch)
    out = await negotiate(s, None, allowed(s), s.epoch())
    assert s.talk.said[:2] == ["Let's read the page.", "Let's listen to me read."]
    assert out.activity.kind == "read_aloud" and "read_listen" in s.boundary.excluded
