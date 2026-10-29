# Genjustsu — Video Subject Replacement & Depth Conditioning Pipeline

A local, open-source video processing pipeline designed to prepare videos for AI character replacement and diffusion video models (such as Seedance).

The pipeline extracts colored depth geometry with **Depth-Anything-V2**, tracks character silhouettes with **SAM 3** on local GPUs, composites the depth map strictly onto the character while preserving the original scene background, and pitches isolated vocals by **+3 semitones** for lip-sync and motion conditioning.

---

## Key Features

- **Local GPU SAM 3 Video Tracking:** Segment and track characters across video sequences using Meta's SAM 3. Features an automatic 250-frame chunking engine to keep GPU VRAM steady (~4 GB) and prevent out-of-memory crashes on long videos.
- **Background-Preserving Compositing:** Only the isolated character silhouette receives the Depth-Anything-V2 map. The original background, scenery, lighting, camera movement, and props remain 100% intact.
- **Lip-Sync & Motion Audio Guidance:** Uses Rubber Band CLI to shift isolated vocal frequencies +3 semitones while preserving exact clip duration and timing, providing optimal motion guidance for video generation.
- **Clean Mask Generation:** Generates binary silhouette mask videos (`mask.mp4`) and cleaned per-frame PNG masks with border noise removal.
- **Full Soundtrack Preservation:** Easily remuxes the original master audio track back onto final generation exports.

---

## Pipeline Overview

```
Input Video (original.mp4)
      │
      ├──> [Vocal Isolation] ────> Isolated Vocals ──> [Rubber Band (+3)] ──> Pitched Vocals
      │                                                                              │
      ├──> [Depth-Anything-V2] ──> Depth Map (depth.mp4)                             │
      │                                    │                                         │
      └──> [SAM 3 (Local GPU)] ──> Silhouette Mask (mask.mp4)                        │
                                           │                                         │
                                           ▼                                         ▼
                        [Composite: Depth over Background] ────────> [seedance-input.mp4]
                                                                             │
                                                                   [Diffusion Video Model]
                                                                             │
                                                                   [Audio Restoration]
                                                                             ▼
                                                                     Final Master Video
```

### Generated Files in Each Run

Each processing run outputs the following structured files:
- `original.mp4`: Normalized 24 fps source video.
- `depth.mp4`: Depth-Anything-V2 colored depth geometry.
- `mask.mp4`: Binary character silhouette mask across all frames.
- `composite.mp4`: Depth-Anything map applied to the character with the original background preserved.
- `seedance-input.mp4`: The composited video muxed with +3 pitched vocals, ready for generative video models.
- `raw-masks/` & `clean-masks/`: Frame-by-frame PNG silhouette masks.
- `status.json`: Real-time state and execution logs.

---

## Prerequisites

- **Operating System:** 
  - Windows 10/11 using **WSL2** (Ubuntu 22.04 or 24.04).
  - Linux (Ubuntu / Debian).
  - macOS (Apple Silicon or Intel).
- **Hardware:** NVIDIA GPU with 8GB+ VRAM recommended for local SAM 3 inference (e.g., RTX 3060, 4070, 4080, 4090).
- **System Packages:**
  - `ffmpeg`
  - `rubberband-cli` (or `rubberband`)
  - `python3` (3.12+) & `python3-venv`
  - `git`

---

## Installation

### 1. Install System Dependencies

#### On Ubuntu / Debian / WSL2:
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg rubberband-cli git curl
```

#### On macOS:
```bash
brew update
brew install python@3.12 ffmpeg rubberband
```

---

### 2. Set Up Python Virtual Environment

Navigate to the repository folder:
```bash
cd Genjustsu-Open-Source-Workflow-main
```

Create and activate the virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project dependencies:
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

---

### 3. Install PyTorch with CUDA for Local SAM 3

To run SAM 3 tracking locally on your NVIDIA GPU:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install timm huggingface_hub
```

> **Model Weights:** The repository builder (`sam3/sam3/model_builder.py`) is pre-configured to automatically download the official SAM 3 weights (`sam3.pt`) on first run without requiring a gated token login.

---

## Configuration (.env)

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Configure your environment settings:
```env
# Optional: Port configuration (default 8770)
PORT=8770

# Optional: Remote API keys if using hosted fallbacks
REPLICATE_API_TOKEN=your_token_here
```

---

## How to Run

### Option 1: Web Interface

Launch the local interactive UI:
```bash
./start.command
# Or:
bash start.command
```

Open your browser to:
```
http://127.0.0.1:8770
```

1. **Upload** your source video (`.mp4` or `.mov`).
2. Click **Prepare Video** to run depth estimation, SAM 3 character tracking, background compositing, and audio pitching.
3. Inspect the resulting mask and composited video preview in the UI.

---

### Option 2: Command Line (CLI)

#### Run Full Video Preparation:
```bash
.venv/bin/python workflow.py prepare path/to/video.mp4 --mode depth
```

#### Run Standalone SAM 3 Video Tracking:
Generate silhouette masks for any video using custom text prompts (e.g., `person`):
```bash
.venv/bin/python segment_sam3.py path/to/video.mp4 output_masks/ person
```

#### Check System Diagnostics:
```bash
.venv/bin/python doctor.py
```

---

---

## OpenField Station (audio · video · pen)

Open `http://127.0.0.1:8770/station`, or click **ENTER THE STATION** on the Studio page.

- **Jarvis at the helm**: an LLM-powered console that knows the station's live state and can act on it.
  Runs on a local model (Ollama, LM Studio, llama.cpp) or your own key (OpenAI-compatible, OpenRouter, Anthropic).
- **RapQuest**: lyric sheets on a 16-step bar grid, rhyme-vowel colouring, beat/BPM detection, persona remixes that
  fit a new tempo, REAPER-style takes & comping, and a Pocket Trainer that measures if you rap ahead of or behind the beat.
- **Personas**: the Bible Coach plus style studies (Biggie, Slim Shady, King Von, J. Cole), each with its own page.
- **The Academy**: the built-in Rap Writing Bible as a game, with drills, graded report cards, boss fights, Listening Labs
  from your Spotify, cypher battles, the vowel-pattern matrix, and **the Forge**, which builds your own rapper persona.
- **War Room**: systems board, live feed, persona council, briefings.
- **The Claude line**: the War Room talks to Claude Code on your PC inside `Documents/jarvis-galaxy`, with its agents, one ongoing thread, read-only by default.
- **Local GPU generation**: run the swap on your own GPU through ComfyUI. Ships a Wan 2.1 VACE video-to-video workflow, and **crew swap** gives each person in the clip (hotel lobby challenge, Oouuh challenge) their own reference, rendered in 5-second chunks for 15-20 s clips. See `docs/LOCAL-GENERATION.md`.

Full guide: [`docs/STATION.md`](docs/STATION.md).

## Architecture & Technical Details

### Memory-Safe Chunked Tracking
Standard video transformer tracking models accumulate attention and conditioning tokens across every frame, leading to GPU out-of-memory errors on clips longer than a few hundred frames. 

`segment_sam3.py` solves this by splitting the video into **250-frame segments**. Each chunk:
- Operates in ~1.8 GB of system RAM and ~4 GB of GPU VRAM.
- Sustains continuous processing speeds of **2.5+ frames/second**.
- Frees session state immediately upon segment completion before advancing.

### Depth & Background Compositing
The composite module combines the Depth-Anything-V2 colored depth video with the original source footage using normalized alpha masking:
```
Composite = (Depth * Mask) + (Original * (1 - Mask))
```
This guarantees the background scenery, lighting, camera pan, and hand-held props remain identical to the original recording while isolating the subject.

---

## License

This project is licensed under the [MIT License](LICENSE).
