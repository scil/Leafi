# Codex implementation review, round 3 (gpt-6-astra, reasoning high, read-only)

Run 2026-10-21 on 2472a87. Prompt: prompts/env-impl-round-3.md.

1. **Partially** — Escaped quotes are handled; quoted assignment names still allow multiline secret disclosure.
2. **Resolved** — Secret defaults are masked in empty notes and fallback diagnostics.
3. **Partially** — Non-string examples are rejected; other malformed manifest fields still crash agreement checking.
4. **Resolved** — Pending operations are reconciled before rendering after reload.
5. **Resolved** — Cleanup `PermissionError` preserves the established `Conflict`.
6. **Resolved** — Consumer tests now assert that distinguishable parser results reach their outputs.

Remaining findings, ranked by severity (`\n` denotes a line break):

- **High — [leafi/core/envfile.py:143](E:/GitHub/scil/Leafi/leafi/core/envfile.py:143):** Parsing `'CAM_PASSWORD'='first\nSecretCanary: hidden\nlast'` fails to recognize the quoted assignment name and exposes `SecretCanary` through `problems[].key`; recognize noncanonical assignment boundaries conservatively and suppress subsequent key names whenever boundaries are uncertain.
- **High — [leafi/envedit.py:412](E:/GitHub/scil/Leafi/leafi/envedit.py:412):** A `CAM_PASSWORD` manifest entry with `type:"enum"`, `domain:"leafi.core.envschema:TYPES"` and `options:["SecretCanary"]` returns the secret through `options` and the agreement diagnostic at line 269 despite being masked and read-only; suppress secret options and their diagnostic representations.
- **Medium — [leafi/envedit.py:268](E:/GitHub/scil/Leafi/leafi/envedit.py:268):** Adding `domain:"leafi.envedit:TYPE_ANNOTATIONS"` to an integer entry passes schema parsing but crashes on `set(None)`, while a validator referencing `leafi.core.envschema:TYPES` crashes at line 293 because the tuple is not callable; validate domain/type compatibility and validator callability before agreement checking and return sanitized errors.
- **Medium — [leafi/core/envschema.py:112](E:/GitHub/scil/Leafi/leafi/core/envschema.py:112):** Setting `CAM_PASSWORD.type` to `"SecretCanary"` copies that value into `SchemaError` and consequently the response’s `manifest_error`; report only the field and violated rule, without interpolating rejected values or raw exception messages.
