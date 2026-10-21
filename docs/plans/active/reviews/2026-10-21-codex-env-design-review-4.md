# Codex design review, round 4 — .env settings page (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 against rev 4. Prompt: prompts/env-round-4.md. No parser counterexample remains under the canonical grammar; one blocker (truthful save outcomes).

## 1. Round-3 items

- **Empty-value/comment grammar and serialization — resolved.** Quoted empty values preserve comments correctly; the example-file correction and regression fixtures are specified.
- **Fail-closed ACL handling and protected backups/temps — resolved.** Flags `0` and protection before writing address the reported issues.
- **Partial Windows replacement recovery — partially resolved.** Normal recovery is specified; failed restoration still leaves `.env` missing.
- **Missing-file creation — resolved.** `"absent"`, no backup, and exclusive installation through `os.link` define the path.
- **`unset` validation — resolved.** String validation is skipped; candidate-model validation supplies defaults.
- **CLI confirmation — resolved.** The CLI constructs its confirmation.
- **Raw text versus typed agreement tests — resolved.** The Tests section distinguishes them.
- **Chronological backup ordering — partially resolved.** Nanosecond timestamps improve ordering but do not guarantee uniqueness or monotonicity.
- **Non-canonical problem-list-only behavior — resolved.**

## 2. Canonical parser agreement

**No counterexample found under the rev-4 grammar**, interpreting `<spaces>` as ASCII spaces and line endings as LF/CRLF.

I reproduced the relevant cases with installed python-dotenv **1.2.2** and traced the [Compose parser](https://raw.githubusercontent.com/compose-spec/compose-go/main/dotenv/parser.go): allowed bare values remain literal; allowed single-quoted contents remain literal; `KEY=` and `KEY=''  # note` both produce empty text. Compose was source-traced, not executed.

`.env` was not read.

## 3. §2 step 6 outcomes

Let **O** be the original bytes and **N** the candidate bytes. Assume cleanup succeeds unless stated. These states follow the [ReplaceFileW contract](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew).

| Outcome | Final `.env` | Final side file | Final temp file |
|---|---|---|---|
| Success | **N** | Removed | Absent: renamed to `.env` |
| `ERROR_UNABLE_TO_MOVE_REPLACEMENT` | **O** | Not explicitly guaranteed absent by the API; design performs no side cleanup | Removed |
| `ERROR_UNABLE_TO_MOVE_REPLACEMENT_2`, restoration succeeds | **O** | Absent: restored to `.env` | Removed |
| Same error, restoration fails | **Missing** | **O** retained | **N** remains unless additional cleanup runs; this branch does not specify it |
| `ERROR_UNABLE_TO_REMOVE_REPLACED` | **O** | Not explicitly guaranteed absent by the API; design performs no side cleanup | Removed |
| Other error | **O** | Absent | Removed |

**Flag:** failed restoration explicitly returns with `.env` missing. Keeping its bytes elsewhere preserves recoverability, but does not restore the live configuration.

**Additional flag:** after successful replacement, failure to remove `side` leaves `.env=N`, `side=O`, and no temp. If propagated as an ordinary failed save, that contradicts §6’s “nothing written.” The new creation path has the equivalent case: successful `os.link`, failed temp deletion, both names containing **N**.

## 4. Remaining defects and implementation decisions

- **Blocker — distinguish committed, rolled-back, and recovery-required outcomes.** Rev 4 introduces cleanup after installation without defining its effect on the result. Successful installation followed by cleanup failure should report committed success with a warning. Failed restoration needs an explicit recovery-required result, preserved recovery artifacts, and actionable recovery information; it cannot use the ordinary “nothing written” failure contract. Tests should exercise both cases, including real filesystem states behind injected API failures.

- **Implementer may decide — backup timestamp collisions and clock reversal.** `time.time_ns()` uses wall-clock time; nanosecond units guarantee neither nanosecond resolution nor forward-only movement. A collision currently aborts safely, but clock reversal can make rotation discard the newly created backup. Choose an ordered naming rule under the lock, such as `max(time.time_ns(), largest_existing_stamp + 1)`. [Python time documentation](https://docs.python.org/3.12/library/time.html#time.time_ns)

- **Implementer may decide — cleanup details.** Define temp retention after failed restoration and handling of any side artifact after other failures. Close the temp handle before replacement. Recovery artifacts must survive generic cleanup when restoration has failed.

### Remaining blockers before coding

- Define truthful save results and recovery behavior for failed restoration and post-install cleanup failure.
