# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/` (gitignored, solo project; the GitHub remote exists but issues are not used for day-to-day work).

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is a `Status:` line near the top of each issue file
- Comments append under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path.

## Wayfinding operations

Map `.scratch/<effort>/map.md`; child tickets `.scratch/<effort>/issues/NN-<slug>.md` with `Type:`, `Status:` (`claimed`/`resolved`) and `Blocked by:` lines; frontier = open, unblocked, unclaimed, lowest number first.

PRs as a request surface: off.
