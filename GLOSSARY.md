# Leafi

A household AI agent that runs tasks for one family through whatever eyes, ears, mouths and screens the home happens to have. The first track was habit coaching (brushing, drinking water); the current focus is helping a child study physical books in English.

## Devices and capabilities

**Capability**:
One thing the agent can do with the physical world: see (Eye), hear (Ear), speak (Mouth), show (Face), know someone is there (Presence), or reach a parent (Notifier).
_Avoid_: role, port (reserved for the code-level interface), sensor

**Device**:
A physical or virtual unit that provides one or more capabilities. A camera with a speaker is one device providing Eye and Mouth; an ESP32 box provides Ear, Mouth and Face; the PC provides Ear, Mouth and Face.
_Avoid_: peripheral, endpoint, satellite (Home Assistant's word; use only when talking about Wyoming)

**Hub**:
The registry that loads the configured devices and hands a session the capabilities it asks for, applying the voice policy.
_Avoid_: device manager, bus

**Voice policy**:
The rule for where a spoken line goes: every Mouth, the primary Mouth only, or none. With no Mouth the line is shown on every Face and logged.
_Avoid_: output routing

**Eye**:
A capability that returns a still frame on demand or a frame stream. Images never leave the LAN, except an item a learner agreed to show the Remote teacher (ADR-0018 §4).

**Ear**:
A capability that yields raw audio from a microphone.

**Listener**:
The combination of an Ear, voice activity detection and ASR that yields Utterances. A typed-text Listener yields Utterances without audio, so the study loop runs with zero hardware.
_Avoid_: recognizer, mic

**Mouth**:
A capability that plays an audio clip. Text becomes a clip through the TTS service, never inside a Mouth.
_Avoid_: speaker (we keep that word for the physical part)

**Face**:
A capability that shows text or a short status to a person: a terminal, a web page, the subtitle line of an ESP32 screen.
_Avoid_: display, screen (hardware word)

**Presence**:
A capability that reports "a person is here" events, today from Frigate over MQTT.

**Notifier**:
A capability that pushes a message to a parent's phone: an operational alert, or the session's counts with the learner named by their Surrogate name.

## Model services

**Service**:
A model-backed function the agent calls: ASR, TTS, OCR, Pronunciation, Brain, Vision judge. Each has one or more backends and a `mock` backend for tests.
_Avoid_: engine, provider (xiaozhi's word), model

**Brain**:
The language-model service that writes what Leafi says and decides tutoring moves. Cloud by default (text only, through Egress, redacted by content), local fallback; every Learner's and guest's words reach it redacted (ADR-0021).
_Avoid_: LLM (in prose), coach (that is the behaviour, not the service)

**Vision judge**:
The local vision-language model that answers yes/no questions about frames (habit verification) and reads a page when OCR gives up.
_Avoid_: VLM (in prose)

## Book study

**Book**:
A physical book the learner owns, identified by title, optional ISBN and language.

**Page**:
One page of a Book, identified by its number when printed, otherwise by its text fingerprint.

**Page text**:
The text of a Page as Leafi believes it: OCR output until a Correction exists, then the corrected text. Corrected text always wins.
_Avoid_: ground truth, transcript (reserved for speech)

**Spread**:
Two facing Pages seen in one camera frame. Read as one Page until the page-OCR stage 2 design decides otherwise.

**Angle probe**:
A cheap first guess at how the frame must be turned before OCR: text detection once, then recognition of a few long line crops at two candidate angles. It only nominates an angle; a full read must confirm it.

**Remembered angle**:
The frame rotation of the last sure page read, kept in memory for the session and tried first, while the text still lies where the Book was.

**Correction**:
A user's statement that a span of Page text is wrong and what it should be. Corrections are kept forever and feed the Lexicon.

**Reading session**:
One sitting in which the learner reads one or more Pages aloud with Leafi listening.
_Avoid_: lesson, run

**Utterance**:
One stretch of speech (or typed text) from the learner, with words, timestamps and confidence when audio was involved.
_Avoid_: transcript (the Utterance holds a transcript; it is not one)

**Page revision**:
One immutable version of a Page's text; OCR makes the first, each Correction makes the next. Page text means the latest revision.

**Alignment**:
The mapping of an Utterance onto the current Page revision (a window around the cursors first, the whole page when that fails) that yields Observations and a Committed cursor (ADR-0013).

**Unaligned speech**:
An Utterance, or a run of three or more heard words inside one, that Alignment cannot anchor to the page; it changes nothing, is never a miscue, and is reported as "not tracked", never as a verdict on the learner.
_Avoid_: off-task (a verdict the alignment cannot make), noise, garbage

**Observation**:
What Alignment saw, with no judgement attached: a matched, substituted or deleted span of expected words, or an insertion between two expected words.
_Avoid_: verdict, result

**Committed cursor**:
The position in the Page text up to which reading is settled; everything after it is provisional and may be revised by the next Utterance. The provisional cursor is the furthest point reading has reached.

**Reading state**:
The per-page-read record of every expected token's status and the two cursors, kept across Utterances and persisted after each one.

**Unread**:
The status of expected tokens the learner never reached in a completed sentence or page; they are reported, never practised.

**Candidate miscue**:
A substituted or deleted Observation that may be a reading problem. It becomes confirmed, unsure or withdrawn through Practice or acoustic evidence, or invalidated by a Correction.
_Avoid_: error, mistake, wrong (in copy shown to the child)

**Miscue**:
A Candidate miscue and its later status (confirmed, unsure, withdrawn, invalidated). Confirmed Miscues count fully toward Difficulties; unsure ones only as low-weight "watch" evidence across several sessions (ADR-0013).

**Practice**:
A Leafi-led repeat of a word that was a Candidate miscue, run by the `practise_errors` Activity after reading, never during it: show the sentence, model the word, let the learner retry at most twice, offer skip, record the outcome.

**Speech lease**:
The lock a study session holds so that no other Leafi process speaks through the shared Mouths while it runs.

**Listening gate**:
The session-owned switch that pauses the Listener while any Mouth plays and reopens it after the Mouth's drain time.

**Knowledge item**:
A thing the learner met and should keep: a word, a phrase, a grammar point, a fact from the book, a pronunciation. It may become an Anki card.
_Avoid_: flashcard (that is the Anki rendering), concept

**Difficulty**:
A Knowledge item or Miscue that recurs for this learner; it raises the item's priority in Practice and Review.

**Review**:
Recall of Knowledge items on a schedule; Anki owns the schedule (FSRS), Leafi runs the review turn through its Faces and Mouths.

**Lexicon**:
The set of words and phrases from the learner's Books, used to bias ASR and to post-correct OCR.
_Avoid_: dictionary, vocabulary list

**Learner**:
A child of the household with their own records (items, Difficulties, deck, settings), enrolled by name; siblings are separate Learners on one Leafi. Leafi identifies a Learner by name or a console pick (recognition is M8), never from images sent anywhere.
_Avoid_: user (the parent is also a user), student

**Learner kind**:
`learner` (enrolled), `guest` (a session not yet, or never, tied to an enrolled Learner) or `anonymous` (the one row that keeps the counts of deleted guest sessions).

**Guest**:
A session's owner until identification adopts it into a Learner; a guest who declines or is never confirmed is kept for `GUEST_KEEP_DAYS`, then forgotten. A guest's words leave redacted like a Learner's (ADR-0021).

**Book field**:
A text that comes from the book — page text, a sentence, an expected word, a title — marked `book=True` on the `Text` or `Leaf` that carries it. The name detector skips it so the book's characters keep their names; the protected-name lists still apply (ADR-0021 E2).

**Provenance** (retired 2026-10-24):
Where a text came from (`page`, `system`, `parent`, `learner`, `derived_from_learner`). Egress, TTS routing and storage no longer track it: ADR-0021 redacts by content. Only Book field remains of it.
_Avoid_: as a current concept; say Book field or "redacted by content".

**Surrogate name**:
The stable stand-in first name that replaces a Learner's (or a protected person's) real name in everything that leaves the house; replies are mapped back for what was sent.
_Avoid_: alias (`learners.alias` is a nickname the Learner uses, protected like the name)

**Household terms**:
The protected names, schools and other terms of the household (`household_terms`), replaced before any text leaves; edited with `leafi privacy terms`.

**Egress**:
The one way anything in `leafi/` reaches a cloud service (`leafi.privacy.egress`): it prepares a request (redaction by content — the lists on everything, the detector on every non-Book field —, an attempt row) and its transport sends only that request; nothing is refused for its source (ADR-0021).

**Grant**:
A short permission from egress for one connection to one host and port; the socket guard refuses any connection without one to a cloud address or a Gateway port.

**Gateway port**:
The port of a local model server that receives study payloads (Ollama, magpie): loopback, yet guarded like a cloud address.

**Remote teacher**:
A person outside the house a Learner may show one item to (a page photo, a recording) under a consent used once (ADR-0018 §4; M9).

## Study session (ADR-0017)

**Study harness**:
The code around the Brain in a study session: observation, Menu, construction, execution and timing, the Ledger, records, routing, egress and fallback. The Brain proposes; the harness decides what is allowed and runs it.
_Avoid_: framework, agent loop

**Activity**:
One unit of a study session with a kind (`review_anki`, `read_listen`, `read_aloud`, `practise_errors`, `teach_items`, `recall_items`, `quiz`, `learner_questions`, `add_cards`, `break`, `end`), parameters, a status and a time cap.
_Avoid_: step, task (reserved for habits), exercise

**Boundary**:
The moment between two Activities, where the next one is chosen.

**Menu**:
The set of Activity kinds the harness allows at a Boundary, computed from the session's state and budgets; it always contains `end`.

**Sequencer**:
Who picks the next Activity in a session: the Brain, or the Default policy. Fixed for the whole session by its Arm.

**Default policy**:
The configurable ordered list of steps `{kind, when}` that picks Activities when the Brain does not (built-in: review, recall, practise, teach, cards, read, end).

**Content owner**:
Per Activity kind, who writes its text and chooses its material: code (from stored data) or the Brain. Selection fields may come from any Sequencer; content fields only from the owner.

**Autonomy**:
A per-learner setting, 0–10, for how much Leafi decides by itself at a Boundary: below its first band it offers a short list, in the middle it proposes and asks or argues, at the top it announces.

**Cycle**:
The record opened by a reading Activity chosen at a Boundary; it owns every Candidate miscue its reading creates, on any page, until the next boundary-chosen reading, the wrap or `stop` closes it and settles what is still open.

**Continuation**:
A `read_listen` the harness starts by itself after a page turn while the learner keeps reading; it stays in the same Cycle and is not chosen at a Boundary.

**Epoch**:
The tuple that identifies the session's current situation (session, learner, cycle, page read, revision, turn, settings versions); anything built under an older epoch is dropped instead of spoken, run or written.

**Ledger**:
The session's and the open Cycle's running counters and budgets (minutes, errors practised, new items, quiz questions, cards, Brain calls), updated in the same transaction as each step's effects.

**Soft deadline**, **hard deadline**:
From the soft deadline no new Activity starts; at the hard deadline (soft + grace) the running one is cut.

**Arm**:
Which Sequencer a session was randomly assigned (`brain` or `default`), recorded with its probability on every Activity so the two can be compared.

**Tier**:
A class of Brain backend by strength and cost (`fast`, `standard`, `deep`), chosen per call by purpose and difficulty.

**Mastery mode**:
The per-learner rule for when a Knowledge item counts as known: enough spaced retrievals in Leafi (`retrievals`), or Anki's schedule (`anki`).

**Coach voice**:
The persona of everything Leafi says to the Learner: coach and teammate, equal, funny, never scolding, never babyish.
_Avoid_: tone, persona

## Habits (first track)

**Task**:
A scheduled habit the agent reminds, waits for and verifies: brushing, drinking water. Defined in `config/tasks.yml`.
_Avoid_: job, routine

**Verifier**:
The strategy that confirms a Task happened: presence only, pose-and-dwell scoring, or a vision-judge burst.
