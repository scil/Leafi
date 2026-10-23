# Lemma source for `WordInfo.lemmas` (reference collection)

Checked: 2026-10-22. Method: `tiered-research` (T1 = the owner's own docs, PyPI metadata, the project's repository; T2 = empirical studies; T3 = exemplar source files or local measurements read directly; T4 = secondary, "reported" only) and `gather-code-references`. Every claim below traces to a row of §6. Rows marked *(inferred)* were not confirmed against a primary source.

Decision it serves: plan `docs/plans/active/2026-10-22-ai-led-study.md` → M0.3. ADR-0013 v2 → Definitions (`WordInfo.lemmas(w)`) and Pair classes (`inflection`): a heard/expected pair is `inflection` when heard ≠ expected, both are `is_word`, and `lemmas(heard) ∩ lemmas(expected) ≠ ∅`. Examples from the ADR and its reviews: walked/walk, smiles/smiled, has/had are inflections; car/card, see/seed, ban/band, his/hid, bees/bed are not.

Constraints every candidate is checked against:

- **Single words, no sentence context.** One side is ASR output and the other a page token, so there is no part-of-speech tag. `lemmas(w)` must therefore be the union over every part of speech.
- **Offline**, Windows 11, Python 3.12.
- **Speed.** Answers are precomputed per word and cached, so about 1 ms per word is enough.
- **Inflections only, not derivations.** Plural, past, participle, -ing, -s, and adjective degree (bigger/big, better/good) count. Derivations (happily/happy, teacher/teach, kindness/kind) do not.
- **What an error costs** (ADR-0013 v2). A false `inflection` turns a real misreading into an observation, because `reading.inflections = observe`, so the misreading is missed. A missed inflection becomes a `substitute` and so a candidate, which spends the false-alarm budget. Recall protects the budget; precision protects against misses.

## 1. Candidates

| Candidate | Licence (code / data) | Latest release (date) | Default branch, last commit | Install (Windows / 3.12) | Context-free use | Notes |
|---|---|---|---|---|---|---|
| **lemminflect** | MIT (LS1, LS3). Data derived from the NIH SPECIALIST Lexicon (LS3): "open source", free of charge; redistribution must keep NLM's conditions, credit "SPECIALIST NLP Tools" with release number and date, and not use the NLM name to promote (LS4, LS5) | 0.2.3 (2022-10-02) (LS1) | `master` 2023-09-14, README/doc edits only since the release; no unreleased code (LS2) | `py3-none-any`, 0.8 MB; needs `numpy` only, which Leafi already has (2.5.1) (LS1, M) | `getAllLemmas(w)` returns `{upos: lemmas}` for every part of speech; `getAllLemmasOOV(w, upos)` applies rules to unknown words (LS3) | Dormant 3 years. Its README reports 95.6 % on 119k AGID inflections vs spaCy 3.5 84.7 % and NLTK 52.6 % (LS3; one benchmark, the author's own). `import lemminflect` **imports spaCy whenever spaCy is installed** and registers `Token._.lemma` / `_.inflect` (LS6). OOV models are pickles loaded from the package (LS6) |
| **spaCy** lemmatizer, `rule` or `lookup` mode | MIT (LS7); en tables in spacy-lookups-data, MIT, with WordNet 3.0 licence text for the English data (LS8, LS10) | spaCy 3.8.16 (2026-08-24); spacy-lookups-data 1.0.5 (**2023-07-28**) (LS7, LS8) | spaCy `master` 2026-09-30; lookups `master` 2025-06-04 (LS9) | cp312 `win_amd64` wheel. spaCy + thinc + blis ≈ 120 MB installed; spacy-lookups-data wheel **98 MB** (all languages). Alternatively, tables come with a pipeline package such as `en_core_web_sm` (M) | `rule` needs a POS: run once per POS on a hand-built `Doc(words=[w], pos=[p])`. `lookup` gives one lemma per word, no POS | Planned for Presidio (ADR-0018). Its lemmatizer needs either the 98 MB lookups wheel or a pipeline package |
| NLTK WordNet `morphy` | Apache-2.0 (LS11); WordNet 3.0 licence (permissive, notice required) | nltk 3.10.4 (2026-10-21) (LS11) | `develop` 2026-10-21 (LS9) | pure Python 1.7 MB wheel + `wordnet` corpus 10.3 MB, downloaded separately with `nltk.download` (M) | `wn._morphy(w, pos)` for n/v/a/r; union | `_morphy` is a private name. Morphy tries every suffix rule, so "hoping" yields both hope and hop (M) |
| simplemma | MIT (LS12) | 2.0.0 (2026-08-12) | `main` 2026-09-30 (LS9) | 18 MB wheel (all languages), no deps (LS12) | `lemmatize(w, lang="en")`, **one** lemma | Active; one lemma loses irregular and multi-POS cases (§3) |
| AGID (Automatically Generated Inflection Database) table | Permissive notice licence (Kevin Atkinson), plus WordNet 1.6 and UK Advanced Cryptics notices that must be reproduced (LS13) | 2016.01.19, "no longer maintained" (LS13, LS14) | `en-wl/wordlist` branch `v1`, `agid/` (LS14) | one 3.4 MB text file `infl.txt`; Leafi parses it | reverse table form → base words, all POS; variant and confidence marks per form | Strict parse: drop forms tagged `~ ! ?`, variant level ≥ 2, and POS-unknown entries (LS13 format) |
| Snowball stemmer, stem equality | BSD-3 (LS15) | snowballstemmer 3.1.1 (2026-06-03) | `main` 2026-10-17 (LS9) | 0.1 MB | `stem(a) == stem(b)` | Not a lemmatizer: no irregulars, and it conflates derivations |
| inflect | MIT (LS16) | 7.6.0 (2026-10-21) | `main` 2026-10-21 (LS9) | 0.04 MB | `singular_noun()` only | Nouns only. Not measured |
| pattern / pattern3 | BSD-3 (clips) | PyPI `pattern3` 3.0.0 (2017-03-13). The PyPI name `pattern` is an unrelated 0.0.1a0 package (LS17) | clips `master`: README edit 2026-08-05, code last 2018 (LS9) | sdist only; not attempted | — | Rejected: unmaintained |

## 2. Measurement

Script: the session scratchpad `measure/measure_lemmas.py`, not in the repository. It ran in a throwaway Python 3.12.9 venv on Windows 11 with lemminflect 0.2.3, spaCy 3.8.16 + spacy-lookups-data 1.0.5, nltk 3.10.4 + WordNet 3.0, simplemma 2.0.0, AGID 2016.01.19 and snowballstemmer 3.1.1.

Rule used for every source: `lemmas(w) = {w} ∪ <the source's lemmas for w over all POS>`, and `inflection = a ≠ b and lemmas(a) ∩ lemmas(b) ≠ ∅`. Snowball uses `{stem(w)}` instead.

Test set (248 distinct words):

- **71 inflection pairs** typical of children's books:
  - regular: walked/walk, cats/cat, stopped/stop, cried/cry, hopped/hop, hoping/hope, boxes/box;
  - irregular: ran/run, went/go, children/child, mice/mouse, feet/foot, geese/goose, wolves/wolf, saw/see, caught/catch, bit/bite, hid/hide;
  - be/have/do forms: has/had, is/was, been/be, does/did;
  - adjective degree, suppletives included: bigger/big, happier/happy, hotter/hot, better/good, worse/bad, best/good.
- **50 look-alike non-inflection pairs:**
  - the ADR's and the review's: car/card, see/seed, ban/band, kin/kind, bar/bard, his/hid, bees/bed, being/bed, bring/bred, has/hat, wit/with;
  - silent-e and doubled-consonant pairs: cap/cape, hop/hope, win/wine, plan/plane, tap/tape, hopping/hoping, hopped/hoped;
  - others: mad/made, at/ate, house/horse, mouse/mouth, sing/song, number/numb, liver/live, and more.
- **15 derivation pairs**, all counted as not-inflection: happily/happy, kindness/kind, unhappy/happy, teacher/teach, player/play, painter/paint, and others.

Precision is TP / (TP + FP on the 50 look-alikes). Derivation false positives are listed separately.

| Source | Recall (71) | False + (50) | Precision | Derivation false + (15) | Warm per word | Cold start (fresh process) | RSS added |
|---|---|---|---|---|---|---|---|
| **lemminflect** (dictionary) | **71/71 = 1.000** | 1 (number/numb) | **0.986** | **0** | 2.7 µs | 25 ms import + 67 ms first lookup (tables), numpy 115 ms more. **≈ 1.1 s when spaCy is installed**, from its spaCy hook | +95 MiB with numpy and spaCy imported |
| lemminflect + OOV rules | 1.000 | 1 | 0.986 | 0 | 3.5 µs | as above | — |
| NLTK WordNet morphy | 1.000 | 2 (hopping/hoping, hopped/hoped) | 0.973 | 0 | 2.7 µs | 1.8 s | +159 MiB |
| AGID strict table | 1.000 | 2 (number/numb, liver/live) | 0.973 | 1 (player/play) | 0.1 µs | 0.11 s parse | +22 MiB |
| AGID loose table | 1.000 | 4 (+ hopping/hoping, hopped/hoped) | 0.947 | 1 | 0.1 µs | 0.29 s | — |
| spaCy `rule`, 6 POS | 0.972 (missed better/good, hoping/hope) | 2 (hopping/hoping, hopped/hoped) | 0.972 | 2 (teacher/teach, painter/paint) | 27 µs | 1.1 s | +78 MiB |
| spaCy `lookup` | 0.915 (missed better, worse, best, leaves/leaf, dying/die, does/did) | 2 (number/numb, liver/live) | 0.970 | 0 | 3.0 µs | 1.0 s | +81 MiB |
| simplemma | 0.901 (missed bigger/big, hotter/hot, thought/think, leaves/leaf, worse/bad, bit/bite, going/gone) | 0 | 1.000 | 0 | 0.2 µs | 0.16 s | +24 MiB |
| Snowball stem equality | 0.239 (no irregular passes) | 1 (bath/bathe) | 0.944 | **8** (quickly/quick, kindness/kind, …) | 11 µs | 0.03 s | +3 MiB |

**Wider scan** (`measure/stress.py`, `stress2.py`, `stress3.py`):

- Vocabulary: the 20,000 most frequent lowercase alphabetic words of spacy-lookups-data `en_lexeme_prob`. It is web text heavy with internet slang, not a children's corpus.
- Pairs: 9,303 letter-sharing pairs, each `a`/`a+suffix` (suffix in e, d, s, n, t, y, r, er, ed, es, en, ing, est, ly) or a silent-e drop (hope/hoping), with both words in the vocabulary.
- Result: the five main sources agree on 5,844 pairs and disagree on 1,094.

Findings:

- **lemminflect never says "inflection" alone.** Every pair it accepts is accepted by at least one other source.
  - Questionable accepts it shares with the others: numb/number, fee/feed (it lists "feed" as a past of the verb "fee"), game/gamer, strange/stranger. These are comparatives or archaic forms that coincide with a common word.
  - Its misses (196 pairs the other two of the top three accept) are almost all regular plurals or past forms of words its dictionary lacks: cops, cafes, empires, calories, bots, americans.
  - Coverage: its dictionary has no entry for 4.5 % of the top 2,000 words and 13 % of the top 20,000. The top-2,000 gaps are function words (the, and, of, with, …) and slang. Function words need no lemma, because `{w}` is their answer.
- **lemminflect's OOV rules add noise.** They add 379 pairs, including be/bing, give/giver, east/easter and children/childrens.
- **WordNet morphy over-generates exactly the ADR's look-alike shape.** It accepts win/wines, rob/robes, tap/taping, strip/striped, mat/mates, cod/codes and broke/broker, because every suffix rule is tried and any result that is a WordNet lemma is kept.
- **AGID strict says "inflection" alone on 52 pairs.** Agent nouns are read as comparatives (own/owner, off/offer, open/opener, home/homer, play/player, east/easter, matter/matt, forest/fore, interest/inter).
- **lemminflect dictionary with an AGID strict fallback** for words lemminflect does not know adds 180 pairs, mostly correct (cop/cops, cafe/cafes, calorie/calories). A few are wrong (here/heres, she/shes, east/easter).

## 3. Failure cases worth keeping as regression tests

| Pair | Truth | Who gets it wrong | Why |
|---|---|---|---|
| number/numb | not inflection (for a reader) | lemminflect, AGID, spaCy lookup | "number" is the comparative of the adjective "numb" |
| liver/live | not | AGID, spaCy lookup | the same, for the adjective "live" |
| fee/feed | not | lemminflect, AGID, WordNet | archaic verb "fee" |
| hopping/hoping, hopped/hoped | not | WordNet, AGID loose, spaCy rule | silent-e rule tried in both directions |
| win/wines, rob/robes, tap/taping | not | WordNet (and spaCy rule on some) | the same |
| better/good, worse/bad | inflection | spaCy lookup and rule, simplemma | suppletive comparatives need an exception table |
| leaves/leaf, thought/think, bit/bite | inflection | simplemma, spaCy lookup | one lemma per word picks the other reading |
| teacher/teach, player/play | derivation | spaCy rule, AGID | ADJ `-er` rule; agent noun read as comparative |

## 4. Recommendation

Adopt **lemminflect 0.2.3, dictionary only** (`getAllLemmas`, no OOV), behind the `WordInfo` port. `lemmas(w) = {w} ∪ ⋃ getAllLemmas(w).values()`. Add a small versioned Leafi override table, `study/lemma_overrides.py`, that removes known look-alike links: number↛numb, liver↛live, fee↛feed, gamer↛game, stranger↛strange. Record the source in `page_reads.alignment_versions` as `lemminflect-0.2.3+overrides-<n>`.

- **Why lemminflect.**
  - It is the only candidate with recall 1.000 on the 71 children's-book inflections, and it has the highest precision on the look-alikes (0.986, one error).
  - It has zero derivation false positives.
  - It is never the sole "yes" in the 9,303-pair scan.
  - It takes about 3 µs per word warm and about 90 ms cold, far inside the budget.
  - Its single dependency, numpy, is already in `requirements-study.txt`.
- **Accepted risks.**
  1. **Dormant upstream.** No release since 2022-10-02 and no code commit since. English inflection is static data, so the risk is packaging (the pickled OOV models and numpy compatibility), and the dictionary path avoids it. If the package ever stops installing, export `getAllLemmas` for the M0.2 word list once to a JSON table. The `is_word` gate means only list or lexicon words ever reach `lemmas`, so that table would be complete for the list (*inferred* from ADR-0013's `inflection` test).
  2. **The spaCy hook.** Once Presidio brings spaCy (ADR-0018), `import lemminflect` imports spaCy (≈ 1 s) and registers `Token._.lemma`/`_.inflect`. Import it lazily inside the `WordInfo` adapter, and keep those extension names free.
  3. **Dictionary gaps** for modern regular plurals (cops, cafes). The answer `{w}` makes such a pair a `substitute`, a possible false alarm. These words are rare in children's books (*inferred*). The household lexicon can add entries to the override table.
  4. **Licence.** The MIT code notice, plus the SPECIALIST terms if Leafi ever redistributes the data (for example, an exported table): credit "SPECIALIST NLP Tools", release and date, and state modifications.
- **Runner-up: the AGID strict table** (permissive notice licence, one 3.4 MB file, 0.1 µs, no dependency). Same recall, and precision 0.973. Its agent-noun-as-comparative errors (own/owner, open/opener, home/homer) appear in children's books, so it would need a larger override list.
- **Rejected.**
  - spaCy, in either mode: lower recall on suppletives, derivation false positives, 98 MB of tables or a pipeline package, and 27 µs per word with a hand-built `Doc` per POS. Presidio's planned spaCy does not change this, because its pipeline lemmatizer needs a tagger and context.
  - WordNet morphy: the look-alike shape is exactly its failure mode; a private API; a separate corpus download.
  - simplemma: one lemma per word, recall 0.90.
  - Snowball: recall 0.24, and it conflates derivations.
  - inflect: nouns only.
  - pattern: unmaintained.

Provenance line (for `derive-project-plan` / the Decision Log): `WordInfo.lemmas` ← lemminflect 0.2.3 `getAllLemmas` union over POS (LS1–LS3, LS6), measured here (§2: recall 1.000, precision 0.986, 0 derivation FP, 2.7 µs/word) + Leafi override table (adapted: look-alike comparatives found in §3); licence MIT + SPECIALIST terms (LS4, LS5).

Regression tests to add with the port, under `tests/test_alignment.py` or the `WordInfo` adapter's own test:

- every pair in §2's three sets;
- the §3 cases, including number/numb after the override;
- `lemmas("with") == {"with"}`;
- `import` of the adapter does not import spaCy at module load.

## 5. Gaps

- No children's-book corpus frequency was used. The wider scan's vocabulary is web text, so the gap rates in §2 overstate the problem for picture books (*inferred*).
- The lemminflect accuracy table (LS3) is the author's own benchmark against AGID: one T1-reported study, not corroborated.
- The SPECIALIST Lexicon release page answered 403 to a direct licence-page fetch. Its terms were read from `LSG/Docs/termsAndConditions.html` (LS5).

## 6. Sources

All rows checked 2026-10-22. "Undated" = an undated living page or a file on a default branch. M = local measurement in the scratchpad venv (T3).

| id | tier | title / url | source-date | checked | supports |
|---|---|---|---|---|---|
| LS1 | T1 | PyPI lemminflect — https://pypi.org/pypi/lemminflect/json | 0.2.3, 2022-10-02 | 2026-10-22 | licence MIT, deps `numpy`, wheel `py3-none-any`, 0.8 MB |
| LS2 | T1 | GitHub API bjascob/LemmInflect commits and tags — https://api.github.com/repos/bjascob/LemmInflect/commits | last commit 2023-09-14 | 2026-10-22 | default branch activity; no unreleased code |
| LS3 | T1 | LemmInflect README — https://github.com/bjascob/LemmInflect/blob/master/README.md | undated (0.2.3) | 2026-10-22 | API, SPECIALIST data source, AGID benchmark table |
| LS4 | T1 | SPECIALIST Lexicon home — https://lhncbc.nlm.nih.gov/LSG/Projects/lexicon/current/web/index.html | 2027 release header; 2026 latest complete | 2026-10-22 | "open-source resource, subject to the applicable terms" |
| LS5 | T1 | Terms and Conditions for Use of the SPECIALIST NLP Tools — https://lhncbc.nlm.nih.gov/LSG/Docs/termsAndConditions.html | undated | 2026-10-22 | no charge; keep conditions on redistribution; attribution; no NLM endorsement |
| LS6 | T3 | lemminflect/__init__.py, utils/DataContainer.py (installed 0.2.3) | 0.2.3 | 2026-10-22 | spaCy import hook and Token extensions; pickle-loaded models |
| LS7 | T1 | PyPI spacy — https://pypi.org/pypi/spacy/json | 3.8.16, 2026-08-24 | 2026-10-22 | licence, deps, cp312 Windows wheel |
| LS8 | T1 | PyPI spacy-lookups-data — https://pypi.org/pypi/spacy-lookups-data/json | 1.0.5, 2023-07-28 | 2026-10-22 | MIT, 98 MB wheel |
| LS9 | T1 | GitHub API commits for explosion/spaCy, explosion/spacy-lookups-data, nltk/nltk, adbar/simplemma, snowballstem/snowball, jaraco/inflect, clips/pattern, en-wl/wordlist — https://api.github.com/repos/{owner}/{repo}/commits?per_page=1 | see §1 | 2026-10-22 | default-branch activity |
| LS10 | T3 | spacy_lookups_data/data/en_license.txt (installed 1.0.5) | 1.0.5 | 2026-10-22 | English tables under WordNet 3.0 licence |
| LS11 | T1 | PyPI nltk — https://pypi.org/pypi/nltk/json | 3.10.4, 2026-10-21 | 2026-10-22 | Apache-2.0, deps |
| LS12 | T1 | PyPI simplemma — https://pypi.org/pypi/simplemma/json | 2.0.0, 2026-08-12 | 2026-10-22 | MIT, size, no deps |
| LS13 | T1 | AGID README — https://raw.githubusercontent.com/en-wl/wordlist/v1/agid/README | 2016.01.19 | 2026-10-22 | format, variant marks, copyright notices |
| LS14 | T1 | SCOWL "other" page — http://wordlist.aspell.net/other/ | undated; AGID 2016.01.19 "no longer maintained" | 2026-10-22 | status |
| LS15 | T1 | PyPI snowballstemmer — https://pypi.org/pypi/snowballstemmer/json | 3.1.1, 2026-06-03 | 2026-10-22 | BSD-3 |
| LS16 | T1 | PyPI inflect — https://pypi.org/pypi/inflect/json | 7.6.0, 2026-10-21 | 2026-10-22 | MIT, noun singularisation only |
| LS17 | T1 | PyPI pattern3 / pattern — https://pypi.org/pypi/pattern3/json, https://pypi.org/pypi/pattern/json | 3.0.0, 2017-03-13; 0.0.1a0, 2024-12-23 | 2026-10-22 | unmaintained; name squat |
| M | T3 | Scratchpad `measure/measure_lemmas.py`, `stress.py`, `stress2.py`, `stress3.py`, `load.py` in a throwaway Python 3.12.9 venv, Windows 11 | 2026-10-22 | 2026-10-22 | every number in §2–§3 |
