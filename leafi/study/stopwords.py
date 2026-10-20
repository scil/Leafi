"""Stop-word list for the CHECK partition (ADR-0013 → CHECK outcomes: content words = not in this list)."""

STOPWORDS = frozenset("""
a an the and or but if so of to in on at by for with from up down out over under about into onto
is are was were be been being am do does did done have has had having i you he she it we they me him her
us them my your his its our their this that these those there here what which who whom whose when where
why how not no yes yeah yep nope um uh oh ah well just very really too also then than as can could will
would shall should may might must i'm it's that's there's don't didn't doesn't isn't wasn't can't won't
think know guess maybe like some any all
""".split())
