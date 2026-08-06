"""会话状态机流程测试:mock 掉喇叭/通知/到场检测,验证状态与上报分支。"""
import agent.session as S
import agent.storage as storage


class Recorder:
    def __init__(self):
        self.said: list[str] = []
        self.sent: list[str] = []

    async def say(self, text):
        self.said.append(text)

    async def send(self, title, body, with_snapshot=False):
        self.sent.append(title)


def _wire(monkeypatch, tmp_path, present: list[bool]):
    rec = Recorder()
    monkeypatch.setattr(storage, "DB", tmp_path / "t.db")
    monkeypatch.setattr(S, "say", rec.say)
    monkeypatch.setattr(S, "send", rec.send)
    answers = iter(present)

    async def fake_wait(timeout_s):
        return next(answers)

    monkeypatch.setattr(S.presence, "wait_for_person", fake_wait)
    return rec


async def test_present_first_try(monkeypatch, tmp_path):
    rec = _wire(monkeypatch, tmp_path, [True])
    await S.run_task("brush_pm")
    assert any("🟢" in t for t in rec.sent)
    assert storage.week_stats()["done"] == 1


async def test_present_after_retry(monkeypatch, tmp_path):
    rec = _wire(monkeypatch, tmp_path, [False, True])
    await S.run_task("water")
    assert len(rec.said) >= 3  # opening + retry + arrived
    assert any("第二次提醒后" in t for t in rec.sent)


async def test_missed(monkeypatch, tmp_path):
    rec = _wire(monkeypatch, tmp_path, [False, False])
    await S.run_task("brush_am")
    assert any("超时未到场" in t for t in rec.sent)
    assert storage.week_stats()["missed"] == 1
