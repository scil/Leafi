"""Fixed word lists of the reading algorithm (ADR-0013 v2). Versioned: a change bumps `VERSION`, which is
recorded in `page_reads.alignment_versions`. Not `stopwords.py`, which serves CHECK outcomes.
"""

from __future__ import annotations

VERSION = "1"

# Project LISTEN's 36 function words (prior-art RA3) plus common articles, auxiliaries, pronouns,
# prepositions, conjunctions and their contractions. Alignment never creates a candidate on these and never
# lets one anchor a spoken utterance alone. Directional particles (up, down, out, off, over, under) are left
# out: in children's text they carry the meaning ("the sun went down").
FUNCTION_WORDS = frozenset("""
a an the and or but if so of to in on at by for with from into onto about as than
then is are was were be been being am do does did have has had will would shall should can could may might must
i you he she it we they me him her us them my your his its our their this that these those there here
not no nor too very just also yet
i'm you're he's she's it's we're they're i've you've we've they've i'll you'll he'll she'll we'll they'll
i'd you'd he'd she'd we'd they'd isn't aren't wasn't weren't don't doesn't didn't can't won't
that's there's what's let's
""".split())

# One-word chatter that rule 4(d) never reads as a lone misreading (ADR-0013 v2 rev 3). The household's names
# are added by the caller.
INTERJECTIONS = frozenset("""
yeah yes yep no nope okay ok mum mom mummy mommy dad daddy wait look hey oh um uh hmm ah er
""".split())
