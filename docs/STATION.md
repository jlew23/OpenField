# OpenField Station

An audio · video · pen workstation with **Jarvis at the helm**. Open `http://127.0.0.1:8770/station`
(or click **ENTER THE STATION** on the Studio page).

| Room | What it does |
|---|---|
| **The Bridge** `/station` | Jarvis console (streaming LLM chat that can operate the station), room tiles, roster, live feed |
| **RapQuest** `/station/rapquest` | Songs, beats, flow lab grid, persona remixes on a new tempo, takes & comp, Pocket Trainer |
| **Personas** `/station/persona` | One page per persona: chat, drills, quick cypher, pocket meter, editable prompt |
| **The Academy** `/station/academy` | The Rap Writing Bible as a game: chapters, drills, bosses, labs, cypher, Rhyme Lab, matrix, Forge |
| **War Room** `/station/warroom` | Claude line (Claude Code in jarvis-galaxy), systems board, live event feed, video jobs, persona council, Jarvis briefings |
| **Studio** `/` | The original OpenField video pipeline (now with a **Local GPU · ComfyUI** engine) |

Press **⌘K / Ctrl+K** anywhere for the command palette (every room, persona and action, or "Ask Jarvis").

## The brain: local model or bring your own key

Click the LLM pill (top right) to choose:

- **Ollama (local, default).** Auto-detected on `127.0.0.1:11434`, and from WSL on the Windows host
  (same trick as `jarvis.bat`). Model "auto" picks the first installed non-coder model.
- **OpenAI-compatible.** LM Studio, llama.cpp server, OpenRouter, OpenAI, Groq, Together, or any custom base URL.
- **Anthropic Claude.** Official `anthropic` SDK, default `claude-opus-5-5`, with server-side refusal fallback
  (`fallbacks: "default"`) on models that support it.

Keys are stored in the local Station database (`Documents/openfield/station/station.db`), never sent back to the
browser, and **cleared automatically if the base URL changes** so a key can't be redirected elsewhere.
Environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `OLLAMA_API_BASE`)
fill anything left blank.

### Jarvis actions

Jarvis gets the live station state (songs, jobs, Academy rank, LLM status, events) in his system prompt and can
answer with action blocks the server executes: `navigate`, `consult` (ask a persona), `fit` (tempo fit check),
`remix` (draft a persona remix), `brief` (War Room summary). He never starts paid video generation.
Personality, tone dial (gentle / dry / roast) and your title come from Academy settings.

## Personas

Built-ins live in `station/personas/*.md` (front matter + system prompt): Jarvis, the Bible Coach, and four
style studies built on craft mechanics (Biggie / The Pragmatic Don, Slim Shady / The Manic Chaos Demon,
King Von / The Eyewitness, J. Cole / The Confessional). All rap personas share `_doctrine.md` and are told to write
originals only. Each has a **pocket** (syllables per second) that drives the flow lab's verdicts. Create your own
from the roster page, or earn one in the Forge.

## RapQuest: the flow lab

- **Lyric sheets**: markdown with `### Section`, `**SPEAKER:**`, `*(directions)*`. One line = one bar.
- **Syllables & rhyme**: CMU dictionary (`pronouncing`) with a spelling fallback for slang. Every syllable gets a
  vowel sound; rhyme families are end-rhyme chains plus repeated internal vowel n-grams, coloured consistently.
- **Grid**: each bar on a 16-step grid (eighths when sparse, sixteenths, compressed "double-time" when over).
- **Tempo fit**: seconds per bar at the new BPM, syllables per second, verdict vs the persona's pocket
  (fits / crowded / sparse) and a per-bar syllable target. Half-time is suggested for big tempo jumps.
- **Remix**: a persona rewrites every bar to hit its target on the new beat, same story beats and speakers.
- **Beat analysis**: NumPy-only tempo and beat-grid detection (band-wise spectral flux, octave check, ½× / 2× alternatives).

Ideas lifted from DAWs:

| From | Station feature |
|---|---|
| Ableton warping | Original beat previewed at the remix tempo with pitch preserved |
| Ableton tap tempo / groove pool | Tap button, swing slider on the grid |
| Ableton Capture / FL score logger | Mic recorder used by the Pocket Trainer |
| FL step sequencer + ghost notes | 16-step syllable grid, original bar ghosted behind the remix |
| REAPER takes & swipe-comping | **Takes & Comp**: pick the best line per bar across every version, save as a comp |
| REAPER regions / `.rpp` | Sections as regions; import a `.rpp` to pull tempo and region names |
| REAPER actions list | ⌘K command palette |
| All three | Count-in, metronome, loop range, transport LCD, space = play/stop |

**Pocket Trainer** (Bible drill 5.2): record a take over the beat; onsets are measured against the 16th grid and
you get mean offset (ms ahead/behind), spread, and % within 30 ms.

## The Academy

The Rap Writing Bible ships built in (`station/bible/RAP-WRITING-BIBLE.md`); it is the Academy's methodology. You can
load a newer edition from Academy settings and go back to the built-in one at any time. The parser turns it into 4 levels, 21 chapters, the
drills (each mapped to a practice form: bars, vowel drill, double-stitch skeleton, idiom flip, wordplay, story with
the Core Five, hook, cut, transcription, performance/notebook), graduation **boss fights**, daily routines, the
skill ladder, the 12-week roadmap and the appendices (matrix, word bank, idioms, homophones, multi-meanings,
listening curriculum).

**Grading** = machine checks (bar count, scheme, rhyme density & chains, image check, syllable variety, pocket,
double-stitch slot alignment, vowel matches, Core Five, hook repetition) + an optional **Coach** review against the
actual chapter text. Each attempt produces a printable **report card** (markdown download or print to PDF).

### Why the game works the way it does

The design came from a structured debate (achiever, explorer, socializer, competitor and casual/anxious lenses)
checked against published research. Decisions and their evidence:

| Decision | Why |
|---|---|
| XP comes from **writing**, not logging in; XP labels say what you nailed | Rewards tied to merely showing up undermine intrinsic motivation; informational feedback strengthens it (Deci, Koestner & Ryan 1999) |
| Chests are **surprise** drops right **after** work, never streak insurance | Uncertain rewards increase repetition when resolved right after effort (Shen, Hsee & Talloen); unexpected rewards don't undermine motivation |
| **Weekly rhythm** (N of 7 days) by default; strict daily streak opt-in; no zero shown after a break | Broken streaks can make people quit; "emergency reserves" goals perform better (Silverman & Barasch 2023; Sharif & Shu 2017); missing a day doesn't hurt habit formation (Lally et al.) |
| **Soft gates**: peek any chapter at half XP; bosses certify | Autonomy predicts enjoyment and persistence (Ryan, Rigby & Przybylski 2006) |
| **Adaptive difficulty** steers toward ~85% success | The "eighty-five percent rule" for learning (Wilson et al. 2019) |
| **Spaced recall reviews** of matrix patterns (1, 3, 7, 14, 30, 60 days) | Practice testing and spaced practice are the high-utility techniques (Dunlosky et al. 2013; Cepeda et al. 2008) |
| Coach critiques **bars**, never the person | Over a third of feedback interventions hurt performance, mostly self-focused feedback (Kluger & DeNisi 1996) |
| Classmates are rivals **just above your level**; leaderboard opt-in | Leaderboards can backfire and depend on competitiveness (Hanus & Fox 2015; Mogavi et al. 2022) |
| Story (Jarvis, the crew, the Forge) and co-op + competition | Gamification works modestly; narrative and combined competition/collaboration did best (Sailer & Homner 2020) |
| Player types are **toggles**, not branches | Player typologies are weakly validated (Kirchner-Krath et al. 2024) |
| Sessions have a natural end (3 / 10 / 30 min); no infinite feed | Personalised short loops hold attention, but endless feeds correlate with worse attention (Su et al. 2021; Nguyen et al. 2025) |

The core loop: **write bars → instantly see what's inside them (colours, vowels, density) and hear the crew answer →
a skill map you care about moves → the next prompt is slightly harder.**

Game pieces: ranks (Open Mic Rookie → GOAT Status), 32 achievements, three daily quests + guaranteed chest,
three-star chapters, a skill radar, the Matrix map (18 hidden vowel patterns that go bronze/silver/gold, plus
"off the map" discoveries), loot (themes, titles), boss HP bars, confetti and synthesized sounds.

### Listening Lab

An algorithm picks a rap track from your Spotify (top, saved and recent; genre-filtered; weighted toward your
level's study list; avoids repeats), or from the Bible's listening curriculum without Spotify. The Coach dissects
the craft, you transcribe bars (colour-coded), and the class quizzes: you vs the personas. **Lyrics are never
fetched or reproduced**; you listen through the Spotify embed. Spotify uses PKCE, so only a Client ID is needed
(create an app at developer.spotify.com and add the redirect URI shown in the Lab).

### Cypher & Battle

Crew mode: drop bars, chosen personas answer with four bars on your vowel sound plus a shout-out and an honest
note. Battle mode: same word, 5-minute timer, scored on transparent metrics (rhyme density, longest chain,
internals in slot, imagery, pocket) with Elo ratings. Solo: score only.

## The Forge

Every new Academy page asks one life question ("Tell me about the craziest thing you ever did with your friends")
with optional flavour chips. Answers become a **story bank**. Every choice also nudges six style axes (calm↔chaos,
plain↔ornate, confessional↔cinematic, laid-back↔rapid, street↔abstract, humor↔gravity): the personas you cypher
with, your measured pocket and rhyme density, chapters you peek at, battles, Pocket Trainer verdicts, Jarvis's tone.
The path is fingerprinted, so a different order or one different choice lands somewhere else.

At 8 answers a **preview** reads you (stage-name ideas, themes). Beat the Level 3 boss with 20 answers and the
Forge synthesises **your own persona**: it joins the roster, remixes any song in RapQuest, and exports as a
`SKILL.md` you can use with Claude Code or other agent tools. Nothing leaves your machine except what your
chosen LLM sees.

## The Claude line (War Room)

The War Room has a permanent line to **Claude Code running on your own PC**, inside your `jarvis-galaxy`
folder, so Claude is reachable whenever the Station is open, with that folder's `CLAUDE.md`, settings, skills
and agents loaded.

- **Setup:** install Claude Code once and log in (`npm install -g @anthropic-ai/claude-code`, then run `claude`).
  The folder is found automatically at `Documents/jarvis-galaxy` (next to `Documents/openfield`); otherwise set
  it with ⚙ on the panel or `JARVIS_GALAXY_DIR`.
- **Agents:** Markdown agent files (front matter `name`, `description`) in the galaxy's `sub…` folders
  (`subagents/`, `sub-agents/`, …) and `.claude/agents/` show up in the picker; choosing one routes the message to it.
- **Memory:** one ongoing thread (Claude Code `--resume`), kept across restarts. **New thread** starts fresh.
  Every question and reply also lands in the live feed.
- **Permissions:** read-only by default (headless Claude Code refuses anything that needs approval). List the
  tools you want it to use under ⚙ → Allowed tools, e.g. `Read,Grep,Edit,Bash(git status)`.
- **Who can reach it:** only this computer by default. Tick "Answer other devices on my network" to use it
  from your phone; that setting can only be changed from this computer.
- Also in the ⌘K palette: **Ask Claude (War Room line)**.

## Privacy & safety notes

- All Station data lives in `Documents/openfield/station/` (SQLite DB, beats, any custom Bible edition).
- The app listens on `0.0.0.0:8770` (as before), so anyone on your network can open it and use your configured
  LLM. Run it on a trusted network.
- Spotify tokens are stored locally; disconnect from the Lab.
- Personas never quote real songs; the Lab never reproduces lyrics.

## What we took from other open-source "Higgsfield" projects

The best-known open alternative, Open-Higgsfield-AI (MIT), is a self-hosted studio front end over many hosted
models (image, video, lip-sync, multi-image references). Its strengths are breadth and presets; it relies on cloud
APIs. OpenField's strength is the opposite: a local, QA-gated preparation pipeline. Lessons applied or queued:

1. **Local engine**: done (ComfyUI bridge; Wan 2.1 VACE video-to-video shipped, Wan 2.2 Animate supported), plus **crew swap**: a different reference for each person in two-person challenge clips. See `docs/LOCAL-GENERATION.md`.
2. **Model routing per job**: the Studio now picks Seedance or a local workflow per draft; more workflows can be dropped into `workflows/`.
3. **Presets library** (camera moves, looks): next, as tagged workflow variants.
4. **Multi-reference identity**: next; workflows can already accept extra reference nodes.
5. **Generation history/gallery**: the War Room lists jobs; a gallery view is a natural follow-up.

## Testing

`python -m unittest discover -s tests` runs the original suite plus `tests/test_station.py` (flow engine, beat and
pocket analysis, Bible parsing, grading, game layer, Forge, LLM settings and streaming, Jarvis actions, ComfyUI
bridge). The web layer was exercised end to end against mock LLM and mock ComfyUI servers and every page was
driven in headless Chromium with no console errors.
