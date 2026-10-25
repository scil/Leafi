# Content-only egress E8–E10 rev 3 — codex (confirming round)

Reviewer: codex-cli 0.155.0, `gpt-6-astra`, effort high, read-only sandbox, on `reviews/prompts/content-only-egress-rev3.md`, 2026-10-24. Output copied verbatim. Rev 4 answers findings 1–5 (cited as W*n*).

**Rev 3 still needs changes in E9.** E8’s migration wiring and E10’s merged commit boundary address the previous blockers. No files were edited.

| Previous finding | Status |
|---|---|
| V1 — migration dependencies | **Closed.** `_PROV`, frozen v6 schema, version advancement and cleanup retry are specified. |
| V2 — green commit boundaries | **Closed.** Removing the bridge and combining implementation with affected tests resolves the sequencing problem. |
| V3 — architecture-rule scope | **Partly closed.** Maintenance exceptions are explicit, but the text-column inventory is incomplete; finding 4 below. |
| V4 — MP3 and orphan cleanup | **Closed.** All top-level audio formats and orphans are covered. |
| V5 — cache concurrency | **Partly closed.** Deferral is useful, but the lease does not establish exclusive, quiescent cache access; findings 1–3. |
| V6 — name collisions/shared terms | **Closed.** Deduplication, idempotent inserts and preserving existing kinds match the implementation. |
| V7 — note attachment | **Closed.** Session attachment and citation-based deletion are now distinguished. |
| V8 — excluded session tables | **Partly closed.** Their text content is acknowledged, but the lifetime justification remains false; finding 5. |

1. **High — E9, [line 76](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:76): the study lease is not an exclusive cross-process lock.**

   [`lease.acquire`](E:/GitHub/scil/Leafi/leafi/core/lease.py:107) checks `holder()` and then writes a replacement file. Two processes can both observe an absent lease, then each successfully write and return a `Lease`. The shared `.tmp` filename also permits conflicting writes. Expiry can permit takeover while the original operation continues.

   **Failure:** a study process and `forget`, or two `forget` commands, start together → both believe they hold the lease → purging overlaps synthesis or another purge.

   **Fix:** specify atomic exclusion maintained throughout the protected operation, including acquisition, renewal and release. An OS-held lock is one option. Add a simultaneous-acquisition regression test; testing only an already-held lease misses this race.

2. **High — E9, line 76: even exclusive lease acquisition would not establish “nothing synthesises.”**

   Two existing paths invalidate that assumption:

   - [`KokoroTts.synthesize`](E:/GitHub/scil/Leafi/leafi/services/tts/kokoro.py:40) writes audio inside `run_in_executor`. Cancelling or timing out the awaiting coroutine does not stop that worker. Session cleanup releases the lease without draining these workers.
   - [`agent.speaker.say`](E:/GitHub/scil/Leafi/agent/speaker.py:24) merely checks whether the study lease is held before synthesising. The supervisor’s habit child writes into the same default `cache/tts` directory through [`agent/tts.py`](E:/GitHub/scil/Leafi/agent/tts.py:9), without holding that lease.

   **Failure:** Kokoro is still processing when a session ends → `forget` acquires the lease, clears the cache and reports completion → the worker subsequently writes the forgotten audio back. Separately, an already-running habit synthesis can lose its intermediate or output file during purging.

   **Fix:** coordinate actual cache writers through publication completion, including cancelled executor work. Either isolate the study cache from habit files or coordinate both tracks’ cache access. Cover delayed worker completion and already-running habit synthesis in regression tests.

3. **Medium — E9, line 76: the purge marker’s failure lifecycle and configured location are underspecified.**

   “Every regular file” includes `.purge`, yet the marker must survive unsuccessful cleanup.

   **Failure:** enumeration deletes `.purge` before an audio file → deleting that audio fails, or the process crashes → the next session sees no pending purge although audio remains. The design also names literal `cache/tts/.purge`, whereas the runner’s synthesizer uses [`Path(settings.cache_dir) / "tts"`](E:/GitHub/scil/Leafi/leafi/services/tts/__init__.py:122).

   **Fix:** derive the marker and deletion directory from the same configured path, and use `settings.lease_path`. Persist the request before irreversible forgetting steps; exclude the marker from ordinary deletion; remove it only after successful completion. Define retry/reporting behavior when the learner row has already gone. Test interruption, deletion failure and a non-default cache directory.

4. **Medium — E9, [line 72](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:72): the UPDATE fence omits text-bearing columns.**

   The schema includes `utterances.words`, `encounters.example`, and `book_notes.topic` / `characters`, none covered by the stated list. In particular, `example` belongs to the existing explanation provenance group and reaches card text.

   **Failure:** a raw `UPDATE encounters SET example=? WHERE id=?` targets a forgetting learner → an architecture test using the proposed list permits it → the write bypasses `update_named`.

   **Fix:** specify a complete table-to-column map, including text inside JSON fields, with explicit maintenance exceptions. Update the scanner to inspect assignment targets and add negative cases for these omitted columns. Today’s scanner detects none of the example, words or characters UPDATEs; simply retaining its provenance-name predicate cannot enforce the new rule.

5. **Medium — E9, [line 70](E:/GitHub/scil/Leafi/docs/plans/active/2026-10-24-content-only-egress-design.md:70): `post_done_at` does not exclude recovery writes.**

   [`run_session`](E:/GitHub/scil/Leafi/leafi/study/harness/loop.py:303) can fail finalization because the database is busy, then set `post_done_at` while `ended_at` remains null. [`rows.recover`](E:/GitHub/scil/Leafi/leafi/study/harness/rows.py:116) subsequently selects that session by `ended_at`, closes cycles, settles miscues and updates page reads.

   **Failure:** forgetting marks such a learner between deletion batches → another study launch recovers the unfinished session → recovery still writes its excluded tables. If difficulty recomputation encounters confirmed evidence, its fenced insert raises `LearnerUnavailable`, aborting startup before the new session begins.

   I reproduced both outcomes using real in-memory SQLite: recovery modified a cycle and miscue after `post_done_at`; marking the learner caused `LearnerUnavailable`.

   **Fix:** replace the blanket lifetime claim with explicit recovery and historical-update rules. Recovery should check ownership/forgetting within its write transaction and safely skip unavailable learners. Cover the failed-finalization state and recovery interleaved with forgetting.

The other requested checks pass:

- **Already-current migration:** an open supervisor or study `Store` prevents the exclusive `.users` lock. The CLI catches `DatabaseInUse`, prints the instruction to close all Leafi processes, and exits with code 2. Rev 3 correctly requires cleanup status on the successful already-current path.
- **Former names:** an in-memory probe confirmed that preserved display name and alias become `former:N` entries and share a surrogate. Existing household terms remain independently protected.
- **Commit 3:** no separate commit-order impossibility remains after merging the type, schema, writers and tests. Its implementation scope must include the concurrency and recovery fixes above, including session-start integration.

Verification used source inspection and in-memory probes. I did not run the filesystem-writing pytest suite.
