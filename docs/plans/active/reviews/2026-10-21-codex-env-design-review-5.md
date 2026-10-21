# Codex design review, round 5 — confirming (gpt-6-astra, reasoning xhigh, read-only)

Run 2026-10-21 against rev 5. Prompt: prompts/env-round-5.md. Tally: rounds 3-5 rhyme on install/recovery edge cases; rev 6 removes the backup-copy fallback and replaces syntax-based recovery detection with a recovery marker.

## 1. Round-4 blocker and items

- **Save-outcome blocker — partially resolved:** the cited failure cases now have explicit results and regression tests; classification gaps remain below ([§2](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:87)).
- **Backup ordering — resolved:** stamps are unique and increasing under the lock ([§2 step 4](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:81)).
- **Cleanup details — resolved:** handles close before replacement; recovery artifacts survive; cleanup failures become warnings ([steps 5–7](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:82)).

## 2. Contradictions and repository-rule gaps

- **F1 — High: first-creation outcomes conflict.** If another writer creates the target, step 6 requires `Conflict`, while step 7’s “other bytes” requires `RecoveryRequired`; if creation fails and the target remains absent, the table also requires recovery despite preserving the original state and having no backup. Locations: [creation rule](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:84) ↔ [classification and recovery instruction](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:93).

- **F2 — High: byte restoration does not establish permission restoration.** The backup fallback copies bytes before `protect_like`; if protection then fails, matching old bytes still selects `RolledBack` and removes recovery artifacts, contrary to fail-closed permission handling. Ordinary Python copying does not preserve Windows ACLs ([Python documentation](https://docs.python.org/3.12/library/shutil.html#shutil.copyfile)). Locations: [fallback and classification](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:85) ↔ [protection contract](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:99).

- **F3 — Medium: the promised recovery alert is not guaranteed.** A failed fallback copy can leave an empty file or a prefix containing complete assignments: neither old nor new bytes, but still canonical, so `RecoveryRequired` occurs while `env-file` passes. Locations: [canonical grammar](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:38) ↔ [alert guarantee](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:93).

- **F4 — Medium: the new check’s integration is incomplete.** Adding its function alone omits the fixed down/up catalog sentences and Gatus endpoint required by existing checks tests. Locations: [proposed addition](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:93) ↔ [ADR-0016 catalog rule](/E:/GitHub/scil/Leafi/docs/adr/0016-supervision-and-alerting.md:140); enforced by [catalog coverage](/E:/GitHub/scil/Leafi/tests/test_checks.py:106) and [dashboard coverage](/E:/GitHub/scil/Leafi/tests/test_checks.py:181).

- **F5 — Medium: HTTP contracts disagree.** §2 defines a recovery-required 500 response, but §6’s response contract omits it and labels its failure responses “nothing written.” Locations: [§2 mapping](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:97) ↔ [§6 responses](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:156).

- **F6 — Low: two stale §1 contracts remain.** The `empty` operation says it writes `KEY=`, whereas the serializer preserves comments with `KEY=''` ([operation](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:63) ↔ [serializer](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:56)); agreement tests demand identical text from Settings classes, whereas Tests correctly separates raw parsing from typed validation ([§1](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:54) ↔ [Tests](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:180)).

No additional import-boundary or ADR-0011 conflict found; `.env` was not read.

## 3. Implementability

**Not quite: three decisions remain before coding.**

- **Blocker — F1:** Define classification precedence for first-creation conflicts and unchanged absence.
- **Blocker — F2:** Specify protected fallback restoration and the result when original bytes are restored but permissions cannot be verified.
- **Blocker — F3:** Decide how recovery-required state remains detectable independently of canonical syntax, or explicitly narrow the alert guarantee.
- **Implementer may decide — F4:** Complete the existing check, catalog, and dashboard registrations using ADR-0016’s established mechanism.
- **Implementer may decide — F5:** Carry §2’s explicit recovery response through §6 and the page’s error handling.
- **Implementer may decide — F6:** Follow the detailed serializer and Tests contracts when reconciling §1.

### Remaining blockers before coding

- F1: First-creation classification.
- F2: Permission-safe fallback restoration.
- F3: Recovery alert coverage.
