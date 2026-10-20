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
A capability that returns a still frame on demand or a frame stream. Images never leave the LAN.

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
A capability that pushes a message to a parent's phone.

## Model services

**Service**:
A model-backed function the agent calls: ASR, TTS, OCR, Pronunciation, Brain, Vision judge. Each has one or more backends and a `mock` backend for tests.
_Avoid_: engine, provider (xiaozhi's word), model

**Brain**:
The language-model service that writes what Leafi says and decides tutoring moves. Cloud by default (text only), local fallback.
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
The mapping of an Utterance onto a window of the current Page revision that yields Observations and a Committed cursor.

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
A Candidate miscue and its later status. Only confirmed Miscues count toward Difficulties.

**Practice**:
A Leafi-led repeat of a word after a Candidate miscue: model it, let the learner retry at most twice, offer skip, record the outcome.

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
The child using Leafi. Leafi never identifies a Learner from images; identity, when needed, comes from Frigate's local face labels or from configuration.
_Avoid_: user (the parent is also a user), student

**Coach voice**:
The persona of everything Leafi says to the Learner: coach and teammate, equal, funny, never scolding, never babyish.
_Avoid_: tone, persona

## Habits (first track)

**Task**:
A scheduled habit the agent reminds, waits for and verifies: brushing, drinking water. Defined in `config/tasks.yml`.
_Avoid_: job, routine

**Verifier**:
The strategy that confirms a Task happened: presence only, pose-and-dwell scoring, or a vision-judge burst.
