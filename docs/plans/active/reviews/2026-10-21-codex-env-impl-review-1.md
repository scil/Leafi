# Codex implementation review, round 1 — .env settings page and manifest (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 on 62e4b6c..cdacf13. Prompt: prompts/env-impl-round-1.md.

1. **High — [leafi/envedit.py:392](/E:/GitHub/scil/Leafi/leafi/envedit.py:392):** Change `BARK_URL` in the manifest to `type:"text"` and remove `secret`: agreement reports the protection violation, but `view()` still includes the existing secret in its response because mismatches only disable editing. Fix: suppress values on agreement failure or apply the protection floor independently when masking.

2. **High — [leafi/core/envfile.py:60](/E:/GitHub/scil/Leafi/leafi/core/envfile.py:60):** A noncanonical multiline value such as `CAM_PASSWORD='first\nSecretCanary\nlast'` exposes `SecretCanary` as a diagnostic `key`, which `/api/env` returns. Fix: recognize diagnostic keys only from unambiguous assignment syntax outside quoted continuations, otherwise report only the line and rule.

3. **Medium — [leafi/core/envfile.py:439](/E:/GitHub/scil/Leafi/leafi/core/envfile.py:439):** If replacement succeeds but reading `.env` back raises `PermissionError`, the exception escapes classification and `save()` reports an ordinary unsuccessful write despite the committed change; a POSIX replacement exception similarly bypasses classification and cleanup. Fix: route installation and readback failures through the outcome classifier, returning `RecoveryRequired` when the resulting state cannot be established.

4. **Medium — [leafi/core/envschema.py:89](/E:/GitHub/scil/Leafi/leafi/core/envschema.py:89):** Removing a group’s `title` produces an uncaught `KeyError`, so `/api/env` disconnects instead of returning the required read-only `manifest_error`; several other malformed shapes likewise escape as `TypeError` or `AttributeError`. Fix: validate container and field shapes before accessing them and report malformed manifests through sanitized `SchemaError`s.

5. **Medium — [tests/test_env_validators.py:54](/E:/GitHub/scil/Leafi/tests/test_env_validators.py:54):** Changing `WEEKLY_REPORT.validator.fn` to `agent.parsers:parse_schedule` leaves these hard-coded binding tests passing, while the editor now accepts `WEEKLY_REPORT=sun:not-a-time`, which the actual weekly-report consumer rejects. Fix: derive each spy and consumer invocation from the manifest entry and verify that the declared consumer uses the declared validator.

6. **Medium — [leafi/envedit.py:284](/E:/GitHub/scil/Leafi/leafi/envedit.py:284):** Set the active `ASR_BACKEND` example to `Sherpa` and regenerate `.env.example`: agreement and the generated-example validation test accept it because Settings treats it as a string, although it is outside the manifest’s options. Fix: validate active examples against manifest enum/list domains as well as Settings types, validators, and gates.

7. **Medium — [leafi/envedit.py:219](/E:/GitHub/scil/Leafi/leafi/envedit.py:219):** Adding `${CAM_PASSWORD}` to Gatus configuration passes this coverage check merely because the key has a `compose:frigate` reader, even though no `compose:gatus` reader supplies it. Fix: require each container configuration reference to have the corresponding service’s Compose reader.

8. **Medium — [agent/webui/index.html:525](/E:/GitHub/scil/Leafi/agent/webui/index.html:525):** Queue removal of an Unknown key, remove it externally, then save: the 409 reload retains the pending operation, but `keyInfo()` now returns `undefined` and rendering throws at `x.secret`. Fix: reconcile pending operations against the reloaded catalog before rendering the conflict comparison.

9. **Low — [agent/webui/index.html:434](/E:/GitHub/scil/Leafi/agent/webui/index.html:434):** With the shipped manifest, `PRON_AUTO_JUDGE=false` still presents `true` as a selectable option, despite the requirement that gated choices never be offered; saving it only produces a server rejection. Fix: expose gate-filtered boolean choices from the server and render those choices.
