# Flow: a reading session

State machine in `leafi/study/session.py`. Every transition is logged; a crash leaves `reading_sessions.ended_at` null and the next start closes it. Semantics: ADR-0009 (observations, cursor, practice), ADR-0010 (page identity, revisions).

## States

```mermaid
stateDiagram-v2
    [*] --> IDENTIFY_BOOK
    IDENTIFY_BOOK --> FIND_PAGE: book confirmed (camera or learner)
    FIND_PAGE --> PAGE_UNCERTAIN: match below threshold or two candidates
    PAGE_UNCERTAIN --> FIND_PAGE: learner confirms / names the page
    FIND_PAGE --> REVIEW_DUE: first page and due cards exist
    REVIEW_DUE --> READ
    FIND_PAGE --> READ: page text ready (revision known)
    READ --> READ: utterance aligned
    READ --> PRACTICE: sentence end with candidate miscues
    READ --> CORRECT: control: "the book says …"
    READ --> EXPLAIN: control: "what does … mean" / "I don't understand"
    PRACTICE --> READ
    CORRECT --> READ
    EXPLAIN --> READ
    READ --> CHECK: committed cursor reaches page end
    CHECK --> FIND_PAGE: page turned
    CHECK --> WRAP: learner stops
    WRAP --> [*]
```

Additional states from ADR-0012: `REPOSITION` (no anchor after two unanchored utterances: Leafi asks for the first words of the learner's line; no assessment) and `LISTENER_LOST` (selected Ear gone; continue in text mode when the console exists).

**Input routing is by state** (ADR-0012 §7): READ → alignment; PRACTICE → retry match of the practised word; CHECK → local keyword comparison; REVIEW_DUE → `again`/`good` (`/again`, `/good`); EXPLAIN/CORRECT → that state's grammar. Controls apply everywhere; one that does not apply here is a spoken no-op ("not now").

**Global transitions (every state except WRAP):**
- `stop` (spoken ≤ 6 words matching the command grammar while listening; typed `/stop` or a Face key at any time, including during playback, which cancels the current `say()` first) → WRAP.
- `skip` → leaves PRACTICE/EXPLAIN/CHECK/REPOSITION back to READ without recording a judgement; bumps `turn_id` so pending async results are discarded.
- `page turned` (Eye frame-diff settles on a new page, or `/page N`, or spoken "page twelve") → FIND_PAGE; any provisional alignment is discarded, committed observations stay.
- `idle timeout` (`STUDY_IDLE_S`, default 180) → WRAP with `summary.idle=true`.
- `page uncertain` (camera lost, OCR failed, or a frame-diff without a confident match) → PAGE_UNCERTAIN; assessment is suspended; utterances are still stored with `kind=reading` but produce no observations until the page is confirmed.

## Sequence for one sentence

```mermaid
sequenceDiagram
    participant L as Learner
    participant Lis as Listener (Ear+VAD+ASR or typed)
    participant S as study.session
    participant A as alignment
    participant C as coach (local rules + static phrases)
    participant B as Brain (text only, off the fast path)
    participant H as Hub (say → Faces, TTS → Mouths)
    L->>Lis: reads
    Lis-->>S: Utterance(words, times, conf|None, audio_ref|None)
    S->>A: align(reading_state, utterance)
    A-->>S: AlignResult(new_state, observations, sentence_completed?)
    S->>S: store utterance, observations, reading_state; new candidates; withdraw reconciled candidates (self-correction, reread)
    alt sentence end reached and no candidates
        S->>H: say(local encouragement or nothing)
    else sentence end reached with candidates
        S->>C: practice_plan(candidates, difficulties)   — local, ≤ 50 ms
        C-->>S: words_to_practice (max 2), line from static phrases
        S->>H: say(line)
        loop each word (≤ 2 retries, skip always offered)
            S->>H: say(word, slow)
            L->>Lis: repeats
            Lis-->>S: Utterance
            S->>A: align([word], utterance)
            opt PRON_AUTO_JUDGE and audio_ref
                S->>S: pronunciation.score → evidence=acoustic
            end
            S->>S: practices row; after the sequence: matched → withdrawn; else unsure; confirmed only with acoustic evidence
        end
    end
    opt Brain enrichment (async, turn-guarded)
        S->>B: explanation / question request (redacted page window, target, intent enum)
        B-->>S: result or unavailable
        S->>S: apply only if (session, page_revision, turn_id) unchanged
    end
```

The Brain is never on the path between the end of an utterance and the first spoken feedback (performance.md). Static phrases in the Coach voice cover every coach action; the Brain adds explanations, questions and better lines when it answers in time.

## Handling a correction (B5)

1. Utterance classified as `correction` (grammar: "the book says X not Y" / "it's X not Y" / typed `/fix Y X`); ambiguous cases ask once ("Do you mean the word is X?").
2. Locate `old_text` in the current revision near the cursor (nearest occurrence within the reread window); if not found, ask the learner to point at the line (read it) and retry once; else give up politely and record a `corrections` row with `char_start=null` for the parent.
3. One transaction (ADR-0010 §3, §6): correction row; new revision with the span verified and the edit map; `spans_verified` and the reading state transformed through the map (tokens inside the edited span → `unattempted`); miscues inside the span → `invalidated (page_text_corrected)`; lexicon update; Difficulties recomputed.
4. The reading state now points at the new revision; the learner continues from the committed cursor; Leafi thanks them in the Coach voice.

## Handling "I don't understand" (B6)

1. Intent `explain(target)`; target = the word named, or the current sentence.
2. Immediate local response: Leafi shows/says the sentence and says it will explain. Brain request (redacted window ≤ 3 sentences, target, language order from the profile) → `{meaning_en, meaning_zh?, example, follow_up?}` validated against a strict schema and an allow-list of actions; `unavailable` → Leafi says it cannot explain this one now and moves on, recording the encounter with `explanation_en=null`.
3. `knowledge_items` upsert + `encounters` row.

## Comprehension check (B7)

At `CHECK`: the Brain generates ≤ 2 questions, each with acceptable answers as keyword sets, from the committed page window; `unavailable` → skip CHECK silently (no Difficulty). **The learner's answer stays local** (ADR-0011): it is normalised and compared with the keyword sets (all keywords of at least one acceptable answer present → correct); anything else is `uncertain` and Leafi gives the answer in the Coach voice without judgement; only a clear miss records an `encounters` row (`trigger=check`), never a miscue. Page text is data: a page containing instructions ("ignore the previous…") is quoted inside a delimited block and the response is validated against the schema; `tests/test_prompt_injection.py` holds fixed scenarios.

## Wrap (B8, B9)

1. `summary` = counts (pages, tokens committed, candidates/confirmed/withdrawn, items learned, practices); parent notification text-only.
2. `anki_outbox` processed: dedupe by `leafi-id::<key>` tag, add/update, ack; failures stay `pending`.
3. Difficulties and lexicon rebuilt; session `ended_at` set; speech lease released.
