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

**Global transitions (every state except WRAP):**
- `stop` (spoken ≤ 6 words matching the command grammar, typed `/stop`, or Face button) → WRAP. During playback, `stop` cancels the current `say()` first.
- `skip` → leaves PRACTICE/EXPLAIN/CHECK back to READ without recording a judgement.
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
    S->>A: align(window, utterance, committed_cursor)
    A-->>S: AlignResult(observations, provisional_cursor, committed_cursor)
    S->>S: store utterance, observations; candidate miscues for substituted/deleted
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
            S->>S: practices row; miscue → withdrawn | unsure | confirmed
        end
    end
    opt Brain enrichment (async, revision-guarded)
        S->>B: explanation / question request (redacted, ≤ 3 sentences)
        B-->>S: result or unavailable
        S->>S: apply only if (session, page_revision) unchanged
    end
```

The Brain is never on the path between the end of an utterance and the first spoken feedback (performance.md). Static phrases in the Coach voice cover every coach action; the Brain adds explanations, questions and better lines when it answers in time.

## Handling a correction (B5)

1. Utterance classified as `correction` (grammar: "the book says X not Y" / "it's X not Y" / typed `/fix Y X`); ambiguous cases ask once ("Do you mean the word is X?").
2. Locate `old_text` in the current revision near the cursor (nearest occurrence within the reread window); if not found, ask the learner to point at the line (read it) and retry once; else give up politely and record a `corrections` row with `char_start=null` for the parent.
3. One transaction (ADR-0010 §3): correction row, new revision with the span verified, lexicon update. Miscues whose token is inside the span → `invalidated (page_text_corrected)`.
4. Re-align the current sentence against the new revision; thank the learner in the Coach voice; continue.

## Handling "I don't understand" (B6)

1. Intent `explain(target)`; target = the word named, or the current sentence.
2. Immediate local response: Leafi shows/says the sentence and says it will explain. Brain request (redacted window ≤ 3 sentences, target, language order from the profile) → `{meaning_en, meaning_zh?, example, follow_up?}` validated against a strict schema and an allow-list of actions; `unavailable` → Leafi says it cannot explain this one now and moves on, recording the encounter with `explanation_en=null`.
3. `knowledge_items` upsert + `encounters` row.

## Comprehension check (B7)

At `CHECK`: Brain generates ≤ 2 questions with expected keywords from the page window; `unavailable` → skip CHECK silently (no Difficulty). Answers are judged by the Brain with the keywords; a missed answer records an `encounters` row (`trigger=check`), never a miscue. Page text is data: a page containing instructions ("ignore the previous…") is quoted inside a delimited block and the response is validated against the schema; `tests/test_prompt_injection.py` holds fixed scenarios.

## Wrap (B8, B9)

1. `summary` = counts (pages, tokens committed, candidates/confirmed/withdrawn, items learned, practices); parent notification text-only.
2. `anki_outbox` processed: dedupe by `leafi-id::<key>` tag, add/update, ack; failures stay `pending`.
3. Difficulties and lexicon rebuilt; session `ended_at` set; speech lease released.
