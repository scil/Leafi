# Content-only egress E8–E10 rev 2 — codex (increment round)

Reviewer: codex-cli 0.155.0, `gpt-6-astra`, effort high, read-only sandbox, on `reviews/prompts/content-only-egress-rev2.md`, 2026-10-24. Output copied verbatim. Rev 3 answers findings 1–8 (cited as V*n*).

**Rev 2 still needs changes before implementation.** The table rebuild and proposed ownership predicates are sound, but the commit sequence, cache cleanup and several integration details remain incomplete. No files were edited.

Line references below refer to the [rev-2 design](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md).

1. **High — E8, lines 59–60: the specified migration edits miss two dependencies.**

   `SCHEMA_V5` still interpolates `_PROV` ten times. Deleting `_PROV` while preserving that frozen declaration makes importing `storage.py` raise `NameError`; I reproduced this by evaluating the declaration in memory.

   Also, today’s `version == 5` branch calls `_step(..., 6, ...)` without assigning `version = 6`. Simply appending the proposed `if version == 6` branch therefore leaves upgrades starting at 4 or 5 at version 6.

   **Fix:** retain `_PROV` exclusively for historical schemas, or inline its exact value there. Explicitly advance the local version after step 6. Preserve `_V5_COPY`. These are necessary alongside freezing `SCHEMA_V6`.

2. **High — E10, line 83: `legacy_prov` fixes column constraints, but commit 3 still cannot have the promised green suite.**

   After writers switch to `("system", "[]")`, existing assertions fail: `test_activity_status` expects learner-derived outcomes; `test_learner_store` expects encounter sources; `test_anki_single_path` expects derived card provenance. Tests also import `Provenance`, which commit 3 removes. E10 postpones these test changes until commit 4.

   The bridge also produces mixed forgetting behaviour: old rows retain source IDs and are purged, while new rows’ empty source lists survive. “No release between commits” limits exposure but does not make commit 3 internally consistent.

   **Fix:** combine commits 3 and 4, or explicitly move every affected import, assertion and forgetting expectation into commit 3 with the bridge. Do not describe all those test changes as commit-4-only work.

3. **High — E9, line 69, and E10: the stronger architecture rule expands implementation scope beyond the listed writers.**

   Applying the proposed “every INSERT or UPDATE” rule finds **20 existing raw UPDATE sites**, after retaining current exemptions. These include [Anki synchronization](E:/GitHub/scil/Leafi/leafi/study/anki.py:143), session finalization, recovery, `world.ensure_cycle`, and stale-session closure.

   Updating the architecture test alone therefore makes commit 4 fail. Routing everything mechanically through `update_named` is insufficient: its present interface updates one row, whereas recovery performs bulk updates; newly raised `LearnerUnavailable` also needs caller handling.

   **Fix:** inventory and convert these sites in commit 4, with refusal behaviour and bulk-update semantics specified. Alternatively, define narrowly justified exemptions for maintenance-only updates. Preserve the separately fenced adoption operation.

4. **Medium — E9, line 73: WAV-only cleanup leaves actual cached speech behind.**

   [EdgeTts writes `<key>.mp3`](E:/GitHub/scil/Leafi/leafi/services/tts/edge.py:44). Deleting `<key>.wav` and `<key>.json` leaves those MP3s orphaned, potentially permanently: a subsequent sidecar-driven sweep cannot discover them.

   **Fix:** delete supported audio formats, including MP3, and orphaned top-level cache audio. Validate sidecar paths against the configured cache directory and continue excluding `camera/`. Test WAV, MP3 and audio without a sidecar.

5. **Medium — E9, line 73: the “publish lock” does not yet define a working concurrency mechanism.**

   [TtsService has no publish lock](E:/GitHub/scil/Leafi/leafi/services/tts/__init__.py:83). Backends write directly to final audio paths, then the service writes JSON after awaiting synthesis.

   Concrete interleaving: M starts writing audio; forgetting N sees no sidecar being written; cleanup removes the audio; M subsequently publishes JSON or fails when accessing the deleted path. Retrying after a sidecar-only lock does not cover that interval. An in-process lock also cannot coordinate the separate `forget` CLI.

   **Fix:** specify a cross-process protocol covering audio creation and publication, including what happens to synthesis already underway and clips awaiting playback. Add a controlled in-flight synthesis test; the static cache-deletion test does not establish this guarantee.

6. **Medium — E9, line 71: preserving names needs collision and shared-term rules.**

   `household_terms_term` is case-insensitively unique. N with display name `Ada` and alias `ADA` makes two unconditional preservation inserts fail; I reproduced the constraint error. Existing household terms introduce the same collision.

   “Linked household terms” also includes school references through learner settings. Those rows already exist, can be shared by siblings, and carry meaningful `school`/`other` kinds. `pseudonym.load_lists` reads all household terms independently of whether N still exists.

   **Fix:** deduplicate display name and alias, make preservation idempotent, and define conflict handling. Retain existing shared terms in place with their kinds; specify when a person term receives `former_learner_id` rather than indiscriminately recreating or reclassifying linked rows. Test matching name/alias, existing terms, shared schools and reruns.

7. **Medium — E9’s accepted cost and E11: outside citations alone do not guarantee M’s note survives.**

   Input: a note owned by M has `session_id = N_session`, with citations to activities in both N’s and M’s sessions.

   `_delete_session_records` correctly retains it and removes N’s citation. But [the following deletion in `forget_learner`](E:/GitHub/scil/Leafi/leafi/study/records.py:287) deletes every note with that `session_id`. I reproduced both stages in memory.

   **Fix:** state that session attachment also determines deletion, and constrain the promised survival case accordingly; or explicitly preserve such notes by detaching their deleted session reference. Add this mixed-citation, cross-owner case to the regression tests.

8. **Medium — E9, line 68: the exclusion rationale for other session tables is false, and the architecture test cannot prove it.**

   `miscues.heard` contains learner text. [Generation reads it directly into request leaves](E:/GitHub/scil/Leafi/leafi/study/brain/generate.py:107); observations also store heard text. These tables therefore cannot be excluded because they contain no payload-bound text.

   The proposed three-table set correctly replaces the session-owned part of today’s provenance registry. It does **not** cover every session-owned text writer. Its architecture test would permit an unfenced `miscues.create` call while N is marked and N’s page read still exists.

   **Fix:** justify exclusions through the actual session-lifetime protection, with coverage of writer entry points and recovery paths, or extend fencing through their ownership joins. The current live-session refusal makes the exclusion plausible; the stated text-content rationale does not establish it.

The round-1 themes stand as follows:

| Theme | Status | Assessment |
|---|---|---|
| U1 | Partly closed | Frozen v6 target is correct; migration wiring needs finding 1. |
| U2 | Closed | Existing runner, exclusive lock, explicit migration and automatic backup are correctly identified. |
| U3 | Closed as a design decision | Cleanup timing, connection setting, rerun and observable completion are specified. Implementation details below remain essential. |
| U4 | Partly closed | Bridge satisfies NOT NULL columns; green commit boundaries remain unresolved in finding 2. |
| U5 | Partly closed | SQL predicates are sound; coverage and conversion scope need findings 3 and 8. |
| U6 | Partly closed | Cloud/Anki consequences and notices are corrected; note-survival qualification needs finding 7. |
| U7 | Partly closed | Alias preservation is explicit; conflict handling remains unspecified. |
| U8 | Closed | Catching refusal and returning lets both audit loops remove the pending row. |
| U9 | Partly closed | Cache path, camera exclusion and retryable failure are addressed; formats and synchronization remain incomplete. |
| U10 | Closed | Restore and pre-forget backup consequences are explicit. |
| U11 | Closed | Final by-owner sweep addresses the late `egress_log` row before learner deletion. |
| U12 | Closed | Both dependent designs and the active plan carry the overriding migration numbers. |

**What is sound:** I ran the existing `_step` against a populated, in-memory v7 target formed by removing the 20 columns. It rebuilt exactly `activities`, `brain_calls`, `utterances`, `encounters`, `learner_notes`, `book_notes` and `anki_outbox`. All shared-column rows, eight explicit indexes and six triggers survived; migrated and fresh schemas matched; integrity and foreign-key checks passed. This establishes preservation of the project-defined schema objects, not arbitrary extra user-created indexes or triggers.

The requested session-owned SQL can be written as:

```sql
INSERT INTO activities(session_id, kind, status, started_at)
SELECT :session_id, 'break', 'started', :now
WHERE EXISTS (
    SELECT 1
    FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id
    WHERE rs.id = :session_id AND l.forgetting = 0
);

UPDATE activities
SET outcome = :outcome
WHERE id = :id
  AND EXISTS (
      SELECT 1
      FROM reading_sessions rs JOIN learners l ON l.id = rs.learner_id
      WHERE rs.id = activities.session_id AND l.forgetting = 0
  );
```

Executing those statements against real in-memory SQLite produced:

| State | INSERT rows | UPDATE rows |
|---|---:|---:|
| N marked forgetting | 0 | 0 |
| N’s session and activity deleted | 0 | 0 |
| M active while N is forgetting | 1 | 1 |

Converting zero affected rows into `LearnerUnavailable` gives the intended behaviour without a separate owner read.

For cleanup, **today’s early return does not permit rerunning it**. Implementation must route both newly migrated and already-current files through cleanup before returning, and update the CLI’s current “already at schema” branch to report cleanup completion. Check the checkpoint’s returned busy flag—existing `_truncate` already does this—not merely whether execution raised. Keep cleanup under the exclusive `.users` lock: an open `Store` elsewhere must prevent this command from running, including on an already-v7 file.

Verification was limited to source inspection and in-memory probes; I did not run the filesystem-writing pytest suite.
