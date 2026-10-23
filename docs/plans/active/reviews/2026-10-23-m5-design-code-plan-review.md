# M5 egress design — code-plan-review (round 1)

Reviewer: a fresh Claude agent running the `code-plan-review` skill on `docs/plans/active/2026-10-23-m5-egress-design.md` (prompt: `reviews/prompts/m5-design.md`), 2026-10-23. Independent of the codex and fresh-Claude rounds.

## Owner decisions raised

1. D5 `notify`: what the parent notification names — nobody (counts only, recommended), the surrogate, or the real name (needs an egress-table exemption).
2. `egress_log` CHECKs (G4.2): migration 6 (add `notify`, allow NULL learner for household-level study sends; recommended) or attribute those rows to `anonymous`.
3. When household `.env` privacy keys take effect for a running session or supervisor (J1.1): reread at session start and force a restart from the confirmation page (recommended).
4. CJK names (I2.3): require substring matching for CJK terms (recommended) or state non-detection as a Non-Goal.

## Most severe

1. G4.2 — `egress_log.purpose CHECK` (storage.py:344) has no `notify`; `CHECK((purpose='ops') = (learner_id IS NULL))` rejects any study send without a learner (TTS before `identify`, catalog outside a session, household notifications). Inserts fail at runtime. Decide before M5b.
2. I2.3 — "case-insensitive, whole-word" cannot match a Chinese name inside Chinese text (`\b` never falls between CJK characters); spaCy `en` detects nothing in Chinese. Real names reach edge-tts (zh voice) and the Brain. Substring matching for CJK terms, longest first; a canary test with a Chinese name in a zh line.
3. D10 / G5.1 — `HMAC mod N` over ~200 names collides (~5 % with five household names); the payload-dependent skip breaks "stable per person" and can map a reply back to the wrong child. Assign surrogates once, injectively, stored per term; resolve a payload clash per request in the token's mapping.
4. B1.2 — `O_EXCL` create of `egress.key` races: a second process may read an empty or short key. Write a temp file and `os.replace`; refuse any length but 32.
5. D3 / I1.3 — `lan` by host string and every port: a gateway on the same LAN host reached by its LAN IP passes without a grant. Make `lan` entries `(resolved address, port)`; compare resolved addresses.

## Other findings

- B1.2 — `REDACT_TERMS` → `household_terms` "once": no unique constraint, no owner of "once"; add a unique index on `lower(term)` and `ON CONFLICT DO NOTHING` inside a named step that clears the key. `household_terms.kind` CHECK is `name|school|other`: use `other`, not `term`.
- B4.1 — `egress_log` rows stuck in `sending` after cancellation or a crash: update in `finally` (cancelled → `unknown`); at startup mark old `sending` rows `unknown`.
- C2.1 — tokens keyed by `(host, H)` collide for identical bodies (the same TTS line, the same Brain request for two learners): carry the token id in a contextvar set by `prepare` and use the HMAC as a check, or a FIFO per key; test two identical concurrent sends.
- C3.2 — huggingface_hub reads `Location` / `X-Linked-*` from 3xx itself; pass the 3xx back for `huggingface` and check the next request's host against the hop list; name the real CDN hosts.
- F1.1 — does the detector run on `page` / `system` TTS lines? If so, book characters send every read-aloud line to Kokoro. State the classes (ADR: learner-derived text plus the lists) and test a page line naming a character.
- F1.1 — reverse-mapping "the school" / `[place]` and model-invented surrogates ("Robin" the bird): reverse-map only person surrogates in this request's mapping, never neutral tokens.
- H1.1 — Presidio's spaCy engine may call `spacy.cli.download` for a name that is not an installed package; the predefined-recognizer import pulls `tldextract`. Build `spacy.load(path)` yourself and pass it in; test the detector under `LEAFI_NO_NETWORK=1` in a subprocess. (Presidio source not verified.)
- H1.3 — huggingface_hub reads `HF_HUB_OFFLINE` at import; lift it before the first import in `doctor --download`, and test.
- H1.1 — aiohttp's `AsyncResolver` (if `aiodns` is ever installed) bypasses `loop.getaddrinfo`: pin `ThreadedResolver` in the adapter; `doctor` asserts `aiodns` absent in library mode.
- H1.1 — `claude.py`'s own two-attempt loop resubmits after a 403: up to 4 transmissions with re-`prepare`. Remove it in M5d; refusals never retried.
- J1.1 — `.env` read at process start while ADR §3 says the filter decides at send time (owner decision 3).
- J1.2 — say that a token's expiry gates connect and consumption only; a long download stream has its own read timeout.
- H5 — ADR §7.6 console buttons: no M5 step updates the console; add it to M5e with `check-console.js`.

## Outside the catalog

- The guard patches connect only: `socket.sendto` and `create_datagram_endpoint` (UDP) bypass it; `create_connection(sock=…)` passes because `_is_loopback(None)` is True. Add UDP refusals and a `sock=` test.
- Grants copied into tasks spawned inside the `with` (keep-alive, library background tasks) live until `expires`: keep expiries tight and say so.
- Entry points that build `Settings()` without `_settings()` (`cmd_timing`, cli.py:271) or `python -m leafi.<module>` get no guard: install in `leafi/__init__` or test every entry point.
- huggingface_hub's `snapshot_download` uses worker threads; contextvars do not flow into a `ThreadPoolExecutor`: set the grant inside the transport's `handle_request`, not an outer `with`.
- `lan` resolved once at install: a DHCP change needs a restart.

## Sound

Token consumption atomic under the lock (B1.1); single use and spent-token refusal (B2.3); one mediator retry (B3.3); positive controls planned (K2.2); the ADR's §9 provenance covers the mechanisms.
