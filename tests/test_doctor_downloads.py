"""`doctor --download` fetches evaluation data and the YLE PDF only when named (plan M4.4a), the word lists
always (plan M0.2)."""

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


def test_a_plain_download_includes_the_word_lists_but_not_the_yle_pdf():
    plain = [label for label, _ in doctor.DOWNLOADS]
    optional = [label for label, _ in doctor.OPTIONAL_DOWNLOADS]
    assert "wordlists" in plain and "yle" in optional and "yle" not in plain


def test_word_lists_are_fetched_once_and_the_cyplex_extract_is_built_with_its_notice(settings, monkeypatch):
    fetched = []

    def fake_fetch(url, dest):
        fetched.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = "Word,Count\nGruffalo,5\nteh,1\n" if dest.suffix == ".csv" else "house\n"
        dest.write_text(body, encoding="utf-8")

    monkeypatch.setattr(doctor, "_fetch", fake_fetch)
    assert doctor.download_wordlists(settings).startswith("downloaded")
    d = doctor.wordlist_dir(settings)
    assert (d / "cyplex.txt").read_text(encoding="utf-8") == "gruffalo\n"
    assert "CC BY 4.0" in (d / "CYPLEX-NOTICE.txt").read_text(encoding="utf-8")
    assert (d / "SCOWL-COPYRIGHT.txt").exists()
    assert all(u.startswith(("https://raw.githubusercontent.com/en-wl/", "https://osf.io/download/")) for u in fetched)
    assert len(fetched) == 5
    assert doctor.download_wordlists(settings) == "present"
    assert len(fetched) == 5
    assert "wordlists" in doctor.wordlist_line(settings) and " ok " in doctor.wordlist_line(settings)


def test_speechocean762_counts_as_present_once_extracted(settings):
    d = doctor.eval_dir(settings, "speechocean762") / "resource"
    d.mkdir(parents=True)
    (d / "scores.json").write_text("{}", encoding="utf-8")
    assert doctor.download_speechocean762(settings) == "present"
