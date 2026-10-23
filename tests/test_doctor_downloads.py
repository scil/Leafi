"""`doctor --download` fetches evaluation data only when it is named (plan M4.4a)."""

from __future__ import annotations

from leafi import doctor


def test_a_plain_download_never_fetches_evaluation_data(settings, monkeypatch):
    called = []
    monkeypatch.setattr(doctor, "DOWNLOADS", [("asr", lambda s: called.append("asr") or "present")])
    monkeypatch.setattr(doctor, "OPTIONAL_DOWNLOADS",
                        [("speechocean762", lambda s: called.append("so762") or "downloaded")])
    doctor.download(settings)
    assert called == ["asr"]
    called.clear()
    doctor.download(settings, {"speechocean762"})
    assert called == ["so762"]


def test_speechocean762_counts_as_present_once_extracted(settings):
    d = doctor.eval_dir(settings, "speechocean762") / "resource"
    d.mkdir(parents=True)
    (d / "scores.json").write_text("{}", encoding="utf-8")
    assert doctor.download_speechocean762(settings) == "present"
