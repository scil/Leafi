# Implementation review, round 4 (fallback reviewer: a fresh Claude subagent, read-only)

Run 2026-10-21 on 22c07bd with the same prompt as the codex rounds (prompts/env-impl-round-4.md). Codex (gpt-6-astra) stopped mid-round on the account's usage limit and produced no findings; per the codex-review skill the fallback reviewer is a fresh agent that did not write the change. Claude verified the High finding by probe (python-dotenv reads `CAM_PASSWORD='x\\'` + newline + `SecretCanary: hidden'` as one value; the parser named `SecretCanary` as a key).

## 1. Round-3 findings

1. Partially resolved: the quoted assignment name is fixed; counting quotes still misreads an even run of backslashes before a quote.
2. Resolved: masked keys get `options: None`; agreement messages drop option details and quote gate values through `q()` for secret keys.
3. Resolved for agreement: `domain` only on enum/list, non-collection domains and non-callable validators reported, `_agreement` wrapped. A related crash remains in `view` (below).
4. Resolved: neither SchemaError message quotes the type value or the exception text.

## 2. Remaining findings

- High — leafi/core/envfile.py:145-149: `re.sub(r"\\.", "", ln)` pairs `\\`, python-dotenv's quoted-value regexes do not; `CAM_PASSWORD='x\\'` / `SecretCanary: hidden'` leaves line 2 reported with key `SecretCanary` in GET /api/env. Fix: any quote or backslash on a non-canonical line makes the rest of the file uncertain.
- Medium — leafi/envedit.py:426,431 via `typed`: a manifest key with no Settings field makes `gated`/`offered` raise KeyError in `view`, so GET /api/env crashes. Fix: skip both when agreement failed; `typed` tolerates a missing field.
- Low — agent/webui/__main__.py `_body`: `json.loads` of a deeply nested body raises RecursionError, not ValueError. Fix: catch it and answer 400.
- Low — agent/webui/__main__.py /api/tasks: a JSON body that is not an object raises AttributeError. Fix: require an object, answer 400.
- Low — leafi/core/envschema.py `load`: RecursionError on a deeply nested manifest escapes. Fix: catch it.

Not clean.
