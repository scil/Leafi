You are reviewing a software design before any code exists. Review it as a design, not as prose.

Repository: the current directory (Leafi). Read, in this order:
1. AGENTS.md, GLOSSARY.md
2. docs/product.md
3. docs/architecture/overview.md, c4-context.md, c4-container.md, data-model.md, config.md, flows/reading-session.md, flows/device-routing.md, deployment.md, quality-attributes/*.md
4. docs/adr/0001 … 0008
5. docs/plans/active/2026-10-19-leafi-book-study.md (the implementation plan an Opus agent will follow)
6. docs/research/2026-10-19-prior-art-book-study.md (evidence; skim)
7. The existing habit-track code in agent/ (session.py, speaker.py, presence.py, tasks.py, storage.py) to judge whether the migration path is realistic.

Context: a 10-year-old learns English from physical books. A Xiaomi camera (through a patched host go2rtc) is the eye and speaker; a PC may supply mic/speaker/terminal; an ESP32 box may come later; zero speakers must still work (text output). Privacy red lines: images/faces/poses never leave the LAN; the child's voice stays local by default; cloud LLM gets text only.

Answer these, concretely, with file/section references:
A. What will be hard to get right, and what will keep going wrong? (interfaces, state machine, alignment, device routing, data model, failure modes, latency)
B. Where is the design under-specified such that an implementer would have to invent something important? Name each gap and propose the decision.
C. Where is it over-built for v1? What should be cut or deferred?
D. Contradictions between documents (ADRs vs plan vs product vs data-model vs glossary).
E. Risks in the chosen stack on Windows/RTX 50-series (sherpa-onnx Parakeet, kokoro-onnx, rapidocr, openpronounce/wav2vec2, anthropic 0.120 SDK, sounddevice, go2rtc audio) and what to prototype first.
F. Test plan weaknesses: which seams are untested or tested at the wrong level.
G. Anything a child-safety / privacy reviewer would flag.

Output: a Markdown report with sections A–G, each a numbered list of findings. Each finding: severity (high/medium/low), location, the problem in two sentences, a concrete suggested change to the design. End with a "Top 5 to fix before coding" list. Do not rewrite the documents. Do not comment on prose style.
