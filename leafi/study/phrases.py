"""Static Coach-voice lines (coach and teammate: equal, funny, never scolding, never babyish).

Every immediate line comes from here; the Brain only enriches. Lines shown to the child pass `safe()`, a
short deny-list of shaming words; a Brain line that fails it falls back to the static phrase.
"""

from __future__ import annotations

import itertools
import re

DENY = re.compile(r"\b(wrong|stupid|dumb|lazy|bad|fail(ed|ure)?|terrible|silly|idiot|careless|mistake)\b",
                  re.IGNORECASE)

LINES: dict[str, list[str]] = {
    "hello": ["Hey teammate! Book open? Let's read.", "Ready when you are. Let's read together."],
    "ask_title": ["Which book are we reading today? Type its title."],
    "confirm_title": ["Is this \"{title}\"? (yes / no)"],
    "ask_page_text": ["I can't see the page. Type /page N --text <file> with the page text."],
    "page_ready": ["Page {page} is ready. Read it aloud whenever you like.", "Got page {page}. Off you go!"],
    "page_ready_text": ["Page {page} is ready. Type each sentence as you read it, then press Enter "
                        "(/stop to finish, /skip, /back, /fix OLD NEW, /explain WORD)."],
    "continue_offer": ["Last time we stopped on page {page}. Continue from there? (yes / no)"],
    "sentence_done": ["Nice!", "Smooth.", "Got it.", ""],
    "practice_intro": ["Let's try \"{word}\" together.", "Quick one: \"{word}\". Listen first."],
    "practice_retry": ["Your turn - say \"{word}\". (skip is fine too)"],
    "practice_again": ["Let's hear it once more.", "One more go?"],
    "practice_withdrawn": ["Yes, that's it!", "There it is!"],
    "practice_unsure": ["Okay, we'll come back to that one.", "No problem, moving on."],
    "practice_idle": ["We'll leave that one for later."],
    "unanchored": ["I lost my place - where are you reading?"],
    "reposition": ["Read me the first few words of your line, and I'll find it."],
    "line_skipped": ["Looks like we hopped over a line. That's okay."],
    "explain_wait": ["Good question! Let me think about \"{target}\"."],
    "explain_unavailable": ["I can't explain that one right now - let's keep reading, and I'll save it."],
    "correction_thanks": ["Thanks for fixing my reading! \"{new}\" it is.", "Good catch - I've got \"{new}\" now."],
    "correction_not_found": ["I couldn't find \"{old}\" near here. Can you read me that line?"],
    "correction_saved": ["I'll save that for your parent to check."],
    "check_intro": ["Page done! Quick question:"],
    "check_answer": ["{answer}"],
    "check_correct": ["Exactly!", "Spot on."],
    "after_check": ["Turn the page when you're ready (/page N), or say stop."],
    "review_intro": ["Before we start - {count} quick review card(s)."],
    "review_prompt": ["Remember this one? \"{front}\" (good / again)"],
    "noop": ["That doesn't do anything right now."],
    "idle": ["Let's take a break. See you next time!"],
    "bye": ["Great session, teammate. See you next time!"],
    "filler": ["Let me think.", "Hmm, one moment.", "Let me see."],  # a Brain call past 0.8 s (ADR-0017 §5)
    "degraded": ["Here is a short answer."],  # a `degraded` tier's answer (ADR-0017 §5.1)
    "lease_held": ["Another Leafi session is speaking right now."],
    "lease_lost": ["Another Leafi took over the speaker, so I'll stop here. Your reading is saved."],
    "mic_lost": ["I can't hear the microphone any more. Type what you read, or restart me when it's back."],
    "mic_lost_stop": ["I can't hear the microphone any more, and there's no keyboard here. Let's stop; "
                      "your reading is saved."],
    "eye_offline": ["I can't see the camera right now. Say \"next page\" when you turn the page."],
    "playback_stop_hint": ["Tip: type /stop any time, even while I'm talking."],
    # harness activities (ADR-0017 §3.1, §6.1)
    "hint_offer": ["Want a hint?"],
    "hint_word": ["It says \"{word}\"."],
    "encourage": ["You kept going on a tricky bit - nice work.", "You fixed that one yourself. Good reading."],
    "back_practice": ["Let's finish these words first, or say skip."],
    "back_no_page": ["To read the last page again, turn back to it."],
    "break_start": ["Short break - {seconds} seconds. Say skip to go on."],
    "wait_start": ["I'll wait a moment. Say what you'd like to do."],
    "read_aloud_intro": ["I'll read this one to you. Follow along."],
    "cards_added": ["I made {count} card(s) for you."],
    "quiz_intro": ["A few quick questions about what we read."],
    "quiz_answer": ["It was: {answer}."],
    "quiz_thanks": ["Thanks - nice thinking.", "I like that idea."],  # an open question: acknowledged only
    "questions_intro": ["Ask me anything about what we read. Say \"done\" when you're finished."],
    "questions_next": ["Another question? Or say \"done\"."],
    "questions_unavailable": ["I can't answer that one right now."],
    "questions_again": ["I didn't quite catch that. Can you ask again?"],
    "questions_child_only": ["The questions here come from the child."],  # Faces only: a panel line (design D8)
    "review_prompt_eases": ["Remember this one? \"{front}\" (again / hard / good / easy)"],
    "teach_intro": ["Let's learn {count} new word(s) from the story."],
    "teach_answer": ["The word was \"{word}\"."],
    "teach_known": ["Great, you know that one already."],
    "recall_intro": ["Let's remember {count} word(s) from before."],
    "recall_meaning": ["Which word means this: {explanation}?"],
    "recall_cloze": ["Which word fits here? {sentence}"],
}

_counters: dict[str, itertools.count] = {}


def safe(line: str) -> bool:
    return not DENY.search(line)


def say(key: str, **kw: object) -> str:
    """A static line, rotating through the variants deterministically."""
    variants = LINES[key]
    n = next(_counters.setdefault(key, itertools.count()))
    return variants[n % len(variants)].format(**kw)


def safe_or(line: str | None, key: str, **kw: object) -> str:
    return line if line and safe(line) else say(key, **kw)
