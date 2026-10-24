"""The privacy primitives of M5a (design D8, D10, D12): the egress key, the learner privacy writer and the school
answer, the version snapshot and the `.env` policy fingerprint. Real SQLite and real files."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from leafi.core import learner_store
from leafi.core.storage import Store
from leafi.privacy import secret, versions
from leafi.privacy import settings as privacy
from leafi.study.harness import settings as harness_settings


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "leafi.db") as s:
        yield s


@pytest.fixture(autouse=True)
def _fresh_key_cache():
    secret._forget_cache()
    yield
    secret._forget_cache()


# ---------------------------------------------------------------- the key


def test_the_key_is_made_once_and_read_back(tmp_path):
    k = secret.load(tmp_path)
    assert len(k) == 32 and secret.key_path(tmp_path).read_bytes() == k
    secret._forget_cache()
    assert secret.load(tmp_path) == k
    assert [p.name for p in tmp_path.iterdir()] == ["egress.key"]  # no temporary file left


def test_racing_processes_agree_on_one_key(tmp_path):
    script = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(__import__("pathlib").Path.cwd())!r})
        from pathlib import Path
        from leafi.privacy import secret
        print(secret.load(Path({str(tmp_path)!r})).hex())
    """)
    procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True) for _ in range(6)]
    keys = {p.communicate(timeout=60)[0].strip() for p in procs}
    assert len(keys) == 1 and bytes.fromhex(keys.pop()) == secret.key_path(tmp_path).read_bytes()


def test_a_short_key_fails_closed(tmp_path):
    secret.key_path(tmp_path).write_bytes(b"short")
    with pytest.raises(secret.KeyFileInvalid, match="5 bytes"):
        secret.load(tmp_path)


def test_backup_carries_the_key(settings, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    Store(settings.db_path).close()
    key = secret.load(settings.data_dir)
    assert cli.main(["backup"]) == 0
    (copy,) = (settings.data_dir / "backups").glob("leafi-*.db")
    assert copy.with_suffix(".key").read_bytes() == key


# ---------------------------------------------------------------- learner keys


def test_defaults_and_guests(store):
    mia = learner_store.create(store, "Mia")
    guest = learner_store.create(store, "guest", kind="guest", settings={"cloud.text": True})
    p = privacy.read(store, mia)
    assert (p.cloud_text, p.media, p.school, p.version) == (True, "ask", None, 0)
    assert p.cloud_text_allowed  # no school answer yet, which no longer gates (owner, 2026-10-24)
    g = privacy.read(store, guest)
    assert (g.cloud_text, g.media) == (False, "never") and not g.cloud_text_allowed
    assert privacy.read(store, 404).kind is None


def test_write_bumps_the_version_and_records_cloud_text_consent(store):
    mia = learner_store.create(store, "Mia")
    privacy.set_school(store, mia, None)
    p = privacy.write(store, mia, "cloud.text", False)
    assert (p.cloud_text, p.school, p.version) == (False, "none", 2)
    p = privacy.write(store, mia, "cloud.text", True)
    assert p.cloud_text_allowed and p.version == 3
    rows = [tuple(r) for r in store.all("SELECT purpose, status, indicated_by FROM consents ORDER BY id")]
    assert rows == [("cloud_text", "withdrawn", "household_setting"), ("cloud_text", "granted", "household_setting")]


def test_write_refuses_bad_values_guests_and_the_forgotten(store):
    mia = learner_store.create(store, "Mia")
    guest = learner_store.create(store, "g", kind="guest")
    for key, value in [("cloud.text", "yes"), ("privacy.media", "always"), ("privacy.school", 99), ("x", 1)]:
        with pytest.raises(privacy.InvalidPrivacySetting):
            privacy.write(store, mia, key, value)
    with pytest.raises(privacy.InvalidPrivacySetting):
        privacy.write(store, guest, "cloud.text", True)
    store.execute("UPDATE learners SET forgetting=1 WHERE id=?", (mia,))
    with pytest.raises(privacy.InvalidPrivacySetting):
        privacy.write(store, mia, "cloud.text", False)


def test_the_harness_writer_refuses_privacy_keys_and_keeps_them(store):
    mia = learner_store.create(store, "Mia")
    privacy.write(store, mia, "cloud.text", False)
    with pytest.raises(harness_settings.InvalidSetting):
        harness_settings.save(store, mia, {"cloud.text": True})
    harness_settings.save(store, mia, {"bands.ask": 2})
    assert privacy.read(store, mia).cloud_text is False  # a harness save merges, never drops them


def test_school_names_are_shared_and_an_imported_term_is_upgraded(store):
    mia, leo = learner_store.create(store, "Mia"), learner_store.create(store, "Leo")
    store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Oakwood Primary', 'name', 't')")
    a = privacy.set_school(store, mia, "oakwood primary")
    b = privacy.set_school(store, leo, "Oakwood Primary")
    assert a.school == b.school
    assert [tuple(r) for r in store.all("SELECT term, kind FROM household_terms")] == [("Oakwood Primary", "school")]
    assert privacy.school_name(store, a) == "Oakwood Primary"
    assert privacy.missing_school(store) == []


def test_missing_school_lists_unanswered_learners(store):
    mia, leo = learner_store.create(store, "Mia"), learner_store.create(store, "Leo")
    privacy.set_school(store, leo, None)
    assert privacy.missing_school(store) == [(mia, "Mia")]


def test_privacy_command_sets_a_school_only_with_yes(settings, monkeypatch, capsys):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with Store(settings.db_path) as store:
        learner_store.create(store, "Mia")
        learner_store.create(store, "Leo")
    assert cli.main(["privacy", "schools"]) == 0
    assert "Mia: NOT ANSWERED" in capsys.readouterr().out
    assert cli.main(["privacy", "learner", "mia", "school", "Oakwood"]) == 1
    assert "would set the school of learner #1 mia to 'Oakwood'" in capsys.readouterr().out
    assert cli.main(["privacy", "learner", "mia", "school", "Oakwood", "--yes"]) == 0
    assert cli.main(["privacy", "learner", "Leo", "school", "none", "--yes"]) == 0
    assert cli.main(["privacy", "learner", "Zed", "school", "none", "--yes"]) == 1
    capsys.readouterr()
    assert cli.main(["privacy", "schools"]) == 0
    out = capsys.readouterr().out
    assert "Mia: 'Oakwood'" in out and "Leo: no school" in out


def test_doctor_names_learners_without_a_school(settings):
    from leafi import doctor

    assert "no learners yet" in doctor.schools_line(settings)
    with Store(settings.db_path) as store:
        mia = learner_store.create(store, "Mia")
        learner_store.create(store, "Leo")
        privacy.set_school(store, mia, "Oakwood")
    line = doctor.schools_line(settings)
    assert "not answered" in line and "Leo" in line and "Mia" not in line


def test_terms_add_change_kind_and_remove_unlinking_a_school(store):
    mia = learner_store.create(store, "Mia")
    privacy.set_school(store, mia, "Oakwood")
    tid = privacy.add_term(store, "Grandma Lu")
    assert privacy.add_term(store, "grandma lu", "other") == tid  # same term, kind changed
    assert [(t, k) for _, t, k, _ in privacy.terms(store)] == [("Oakwood", "school"), ("Grandma Lu", "other")]
    with pytest.raises(privacy.InvalidPrivacySetting):
        privacy.add_term(store, "x", "planet")
    effects = privacy.remove_term(store, "oakwood")
    assert effects == [f"learner #{mia} Mia has no school answer now"]
    assert privacy.read(store, mia).school is None and privacy.read(store, mia).cloud_text_allowed
    with pytest.raises(privacy.InvalidPrivacySetting, match="no household term"):
        privacy.remove_term(store, "Oakwood")


def test_privacy_terms_command_and_the_legacy_import(settings, monkeypatch, capsys, tmp_path):
    from leafi import cli

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"REDACT_TERMS='Grandma Lu,Maple Street'\n")  # as `setup --redact` wrote it
    Store(settings.db_path).close()
    assert cli.main(["privacy", "terms"]) == 0
    assert "no household terms" in capsys.readouterr().out
    assert cli.main(["privacy", "terms", "add", "Uncle Bo"]) == 1  # without --yes only shows
    assert cli.main(["privacy", "terms", "add", "Uncle Bo", "--yes"]) == 0
    assert cli.main(["privacy", "terms", "import"]) == 1
    assert "would import 2" in capsys.readouterr().out
    assert cli.main(["privacy", "terms", "import", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "imported 2 term(s)" in out and "REDACT_TERMS removed from .env" in out
    assert b"# REDACT_TERMS=" in (tmp_path / ".env").read_bytes()
    assert cli.main(["privacy", "terms", "remove", "Uncle Bo", "--yes"]) == 0
    capsys.readouterr()
    assert cli.main(["privacy", "terms"]) == 0
    out = capsys.readouterr().out
    assert "Grandma Lu" in out and "Maple Street" in out and "Uncle Bo" not in out


def test_setup_prints_the_steps_and_the_anki_notice(settings, monkeypatch, capsys):
    from leafi import cli
    from leafi.study.anki import NOTICE

    monkeypatch.setattr(cli, "_settings", lambda: settings)
    with Store(settings.db_path) as store:
        learner_store.create(store, "Mia")
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert 'python -m leafi privacy learner "Mia" school' in out and NOTICE in out and "<" not in out


@pytest.mark.parametrize("value", ["<孩子的名字>", "<name>", "{name}", "[school]", "YOUR_NAME", "name",
                                   "孩子的名字", "Your Name"])
def test_placeholder_shaped_names_schools_and_terms_are_refused(store, value):
    with pytest.raises(ValueError, match="type the child's own first name"):
        learner_store.create(store, value)
    mia = learner_store.create(store, "Mia")
    with pytest.raises(privacy.InvalidPrivacySetting, match="not a school"):
        privacy.set_school(store, mia, value)
    with pytest.raises(privacy.InvalidPrivacySetting, match="not a term"):
        privacy.add_term(store, value)


@pytest.mark.parametrize("value", ["Rocco", "Anne-Marie", "O'Brien", "小明", "James McKinney Elementary School",
                                   "Name Ng"])
def test_real_names_pass_the_placeholder_check(value):
    from leafi.core.text import placeholder_reason

    assert placeholder_reason(value) is None


def test_migrate_refuses_a_placeholder_as_the_first_learner(tmp_path):
    from leafi.core import storage
    from tests.test_migration_5 import _version, v4_file

    path = tmp_path / "leafi.db"
    v4_file(path)
    with pytest.raises(ValueError, match="not a learner's name"):
        storage.migrate_file(path, "<孩子的名字>")
    assert _version(path) == 4  # refused before the backup and before any step
    assert not (tmp_path / "backups").exists()
    hint = storage._migrate_hint(path, 4)
    assert "<" not in hint and "first name of the child" in hint


# ---------------------------------------------------------------- versions


def test_snapshot_goes_stale_on_every_relevant_change(store):
    mia = learner_store.create(store, "Mia")
    privacy.set_school(store, mia, None)
    before = versions.snapshot(store.conn, [mia])
    assert versions.stale(before, versions.snapshot(store.conn, [mia])) is None
    privacy.write(store, mia, "cloud.text", False)
    assert "privacy settings" in versions.stale(before, versions.snapshot(store.conn, [mia]))
    before = versions.snapshot(store.conn, [mia])
    store.execute("INSERT INTO household_terms(term, kind, created_at) VALUES('Rose', 'name', 't')")
    assert versions.stale(before, versions.snapshot(store.conn, [mia])) == "protected names changed"
    before = versions.snapshot(store.conn, [mia, 404])
    assert "404 is gone" in versions.stale(before, versions.snapshot(store.conn, [mia, 404]))


def test_harness_settings_do_not_stale_a_snapshot(store):
    mia = learner_store.create(store, "Mia")
    before = versions.snapshot(store.conn, [mia])
    harness_settings.save(store, mia, {"bands.ask": 2})
    assert versions.stale(before, versions.snapshot(store.conn, [mia])) is None


def test_the_policy_fingerprint_follows_the_file_and_the_environment(tmp_path):
    env = tmp_path / ".env"
    env.write_text("CLOUD_PARENT_TEXT=true\nANKI_DECK=Leafi\n", encoding="utf-8")
    watch = versions.PolicyWatch(b"k" * 32, env, environ={})
    assert not watch.stale()
    env.write_text("CLOUD_PARENT_TEXT=true\nANKI_DECK=Other\n", encoding="utf-8")
    assert not watch.stale()  # not a privacy key
    env.write_text("CLOUD_PARENT_TEXT=false\nANKI_DECK=Other\n", encoding="utf-8")
    assert watch.stale()
    overridden = versions.PolicyWatch(b"k" * 32, env, environ={"cloud_parent_text": "true"})
    assert overridden.loaded == versions.fingerprint(b"k" * 32, {"CLOUD_PARENT_TEXT": "true"})
    assert versions.policy_values(tmp_path / "missing.env", environ={}) == {}
