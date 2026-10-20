# Domain docs

Single-context repo.

## Before exploring, read these

- `GLOSSARY.md` at the repo root.
- `docs/adr/`: read ADRs that touch the area you are about to work in.

## Use the glossary's vocabulary

When your output names a domain concept (issue title, test name, hypothesis), use the term as defined in `GLOSSARY.md`; do not drift to the synonyms it lists under _Avoid_. A concept missing from the glossary is a signal: either you are inventing language or there is a gap for `/domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, say so explicitly: _Contradicts ADR-0003 (local-first services), but worth reopening because…_
