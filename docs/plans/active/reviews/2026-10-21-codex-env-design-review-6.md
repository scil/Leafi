# Codex design review, round 6 — confirming (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 against rev 6. Prompt: prompts/env-round-6.md.

## 1. F1–F6

- **F1 — resolved:** Conflict takes precedence; unchanged absence yields `RolledBack`.
- **F2 — resolved:** Copy fallback is removed; restoration uses one rename preserving the original ACL.
- **F3 — partially:** Markers detect recovery independently of syntax, but marker-creation failure remains unspecified.
- **F4 — resolved:** Check, alert catalog and Gatus registrations are explicit.
- **F5 — resolved:** §6 includes the recovery-required 500 response and page behavior.
- **F6 — resolved:** Empty-value serialization and raw-versus-typed agreement tests now agree.

## 2. New contradictions or defects introduced by rev 6

- **Medium — recovery detection depends on an unhandled write failure.** Creating the marker can fail, for example because storage is full. If `.env` contains other canonical bytes, recovery then has no marker and the check passes, contradicting the unconditional alert guarantee. Specify marker-write failure handling and add a regression case. Locations: [marker creation, §2:93](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:93) ↔ [alert guarantee, §2:95](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:95).

### Remaining blockers before coding

- Define behavior when the recovery marker cannot be created; preserve detection or explicitly narrow the guarantee.
## 1. F1–F6

- **F1 — resolved:** Conflict takes precedence; unchanged absence yields `RolledBack`.
- **F2 — resolved:** Copy fallback is removed; restoration uses one rename preserving the original ACL.
- **F3 — partially:** Markers detect recovery independently of syntax, but marker-creation failure remains unspecified.
- **F4 — resolved:** Check, alert catalog and Gatus registrations are explicit.
- **F5 — resolved:** §6 includes the recovery-required 500 response and page behavior.
- **F6 — resolved:** Empty-value serialization and raw-versus-typed agreement tests now agree.

## 2. New contradictions or defects introduced by rev 6

- **Medium — recovery detection depends on an unhandled write failure.** Creating the marker can fail, for example because storage is full. If `.env` contains other canonical bytes, recovery then has no marker and the check passes, contradicting the unconditional alert guarantee. Specify marker-write failure handling and add a regression case. Locations: [marker creation, §2:93](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:93) ↔ [alert guarantee, §2:95](/E:/GitHub/scil/Leafi/docs/plans/active/2026-10-21-env-settings-page.md:95).

### Remaining blockers before coding

- Define behavior when the recovery marker cannot be created; preserve detection or explicitly narrow the guarantee.
