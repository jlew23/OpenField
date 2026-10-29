# Local generation: the character swap on your own GPU

OpenField's paid path sends the prepared clip to Enhancor / Seedance. The **Local GPU** path runs the
same Higgsfield-style swap on your machine through ComfyUI, for free per render. It reuses everything
OpenField already makes: the normalized `original.mp4`, the SAM 3 `mask.mp4`, the `depth.mp4`
control video, your reference image, and the full original-audio restoration at the end.

```
OpenField prepare  ──► original.mp4 · mask.mp4 · depth.mp4 ──┐
your reference image(s) ──────────────────────────────────────┼──► ComfyUI workflow (Wan 2.1 VACE / Wan 2.2 Animate / …)
mask approval (same QA gate as paid) ─────────────────────────┘                │
                                                                               ▼
                                         local-result.mp4 ──► original audio restored ──► final-preview.mp4
```

## Recommended for video-to-video: Wan 2.1 VACE (ships ready: `workflows/wan21-vace-swap.json`)

VACE ("All-in-one Video Creation and Editing", Alibaba Tongyi, Apache 2.0) is the Wan model built for
editing existing footage: it repaints only the masked area of a control video and keeps everything else,
with a reference image for the look. That is exactly OpenField's job, so it is the default local engine.
(There is no "Wan 1.1"; VACE comes in the Wan 2.1 family.)

OpenField feeds it a control video with the original background outside the mask and the grey depth
silhouette inside it, so the new person follows the original person's motion and body position.

| Model file (ComfyUI `models/diffusion_models/`) | VRAM | Notes |
|---|---|---|
| `wan2.1_vace_1.3B_fp16.safetensors` (4.3 GB) | 8-12 GB | **Default.** Good for an RTX 4070 at 480p (464x832 for vertical clips) |
| `wan2.1_vace_14B_fp16.safetensors` (34.7 GB) | 24 GB+ (or GGUF on 12 GB) | Better faces and hands; change `unet_name` in the workflow |

Also needed: `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` and `vae/wan_2.1_vae.safetensors`.
All three are in `Comfy-Org/Wan_2.1_ComfyUI_repackaged` on Hugging Face (`split_files/...`).

**Already have Wan 2.1 installed (another drive, other filenames, fp8 or GGUF)?** Nothing to download or rename.
Before each render OpenField asks ComfyUI which models it can see and points the workflow at your VACE model,
umT5 encoder and Wan 2.1 VAE (a VACE GGUF switches the loader to `UnetLoaderGGUF`). The Studio's Local
engine line shows which VACE file it found. If ComfyUI runs on Windows and OpenField in WSL, it is found
automatically on the Windows host; otherwise set `COMFYUI_URL`. Only VACE does the masked video-to-video swap:
a plain Wan 2.1 image-to-video or text-to-video model is not enough, and the Studio says so.

The workflow uses only core ComfyUI nodes (`LoadVideo`, `WanVaceToVideo`, `TrimVideoLatent`, `SaveImage`), so
it needs no custom nodes; update ComfyUI if `LoadVideo` or `WanVaceToVideo` is missing. It writes frames
(Save Image) and OpenField reassembles them, so there is no dependence on a video-save node.

### Crew swap: the hotel lobby challenge, the Oouuh challenge, any clip with two or more people

In the Studio (Local GPU engine) open **Crew swap**, pick the challenge, press **Find the people in my clip**,
and give each person their own photo (Person 1 defaults to Character 1, Person 2 to Character 2; leave a card
empty to keep that person). Or from a terminal:

```
python crew_swap.py "Documents/openfield/<job id>" --people
python crew_swap.py "Documents/openfield/<job id>" --ref 1=me.png --ref 2=friend.png --preset hotel-lobby --start 0 --seconds 18
```

What happens:

1. **People are numbered left to right.** SAM 3 now also saves per-person ids (`raw-masks/objects/`);
   older jobs fall back to tracking silhouettes. When two people touch, the blob is split by each person's
   previous outline and clothing colours (99%+ of pixels stay with the right person in testing).
2. **One pass per person.** Each pass repaints only that person's mask, grown a little so a bigger body fits,
   but never into the other person.
3. **Five-second chunks.** Wan renders 81 frames (about 5 s at 16 fps) at a time. An 18 s clip is 5 chunks per
   person. Each chunk starts with the last second of the previous one, so the new person carries across the
   cut, and the overlap is cross-faded. Finished chunks are cached in `crew/`, so a stopped or crashed render
   resumes where it left off.
4. **Paste back.** The new people are blended into the full-resolution original with a soft mask (background
   pixels stay original), timing goes back to 24 fps, and the original audio for the window is restored.
   Result: `crew-final.mp4`.

Rough time on an RTX 4070 with the 1.3B model at 480p and 20 steps: a few minutes per chunk, so an 18 s
two-person clip is 10 renders. Use the same seed to re-render one person with a different photo.

Tips: use clear, front-facing reference photos on a plain background, with an outfit you want to see; a
person with a very different build than the original may get clipped at the mask edge (raise `grow`).

## Also supported: Wan 2.2 Animate (replacement / "mix" mode)

Wan 2.2 Animate is an open-weights (Apache 2.0) 14B model from Alibaba's Tongyi Lab that swaps the
character in existing footage while keeping the background and camera move. ComfyUI ships official
templates for it (Workflow → Browse Templates → "Wan2.2 Animate"), and community workflows add automatic
masking. OpenField already produces a better-reviewed mask than the in-graph segmenter, so feed
`OF_MASK` and mute the graph's own segmentation nodes. That saves VRAM.

Rough VRAM guide (community reports, verify on your card):

| Setup | Resolution | Notes |
|---|---|---|
| fp8-scaled 14B | 720p | ~24 GB+ for a smooth run |
| GGUF Q4_K 14B + offloading | 480p | ~8-12 GB VRAM, ~32 GB system RAM, slower |
| Wan 2.2 TI2V-5B | 480-720p | fits 8 GB, but it is general image/text-to-video, not a swap model |

On an **RTX 4070 (12 GB)** start with the **GGUF Q4 build at 480p**, the 4-step lightx2v LoRA for drafts,
and clips of ~77 frames per segment (Animate extends in segments of about five seconds).

## Setup

1. Install ComfyUI and the nodes the template asks for (ComfyUI Manager → Install Missing Custom Nodes).
2. Download the models the template lists (diffusion model, umT5-XXL text encoder, Wan VAE, CLIP-vision,
   LoRAs). For 12 GB cards choose a GGUF diffusion model.
3. Open the template, confirm it renders once with ComfyUI's own inputs.
4. Retitle the input nodes: `OF_REFERENCE` (character image), `OF_VIDEO` (driving/source video),
   `OF_MASK` (character mask video), `OF_PROMPT`, `OF_SEED`, optionally `OF_FRAMES`, `OF_CONTROL`, `OF_NEGATIVE`.
5. Workflow → Export (API) → save into `openfield/workflows/` (see `workflows/README.md`).
6. Start ComfyUI (default `http://127.0.0.1:8188`; otherwise set `COMFYUI_URL` in `.env`).
7. In the Studio, step 03: choose **Local GPU · ComfyUI**, pick the workflow, attach the character image,
   approve the mask in step 02 as usual, and press **Create Draft** (one person), or use **Crew swap** (each person).
   A VACE workflow picked for a single swap runs the same chunked path with everyone in the mask.

The War Room shows ComfyUI status, the GPU name and VRAM. Progress (queue position, minutes rendering)
streams into the Studio status line.

## Behaviour and safety

- The mask-approval gate is identical to the paid path: no approval, no render.
- Nothing leaves your machine. No uploads, no API keys.
- The generated audio is always discarded and the entire original source audio is restored.
- If audio restoration fails (for example the model rendered fewer frames than the source), the raw
  render is kept as `local-result.mp4` so you can finish it manually in step 04.
- Wired inputs (inputs connected to other nodes) are never overwritten; only literal values are patched.

## Other local options worth knowing

- **Wan2GP**: a low-VRAM web UI (profiles down to ~6 GB) that packages Wan models. It is Gradio-based, so a
  future bridge could drive it through `gradio_client`, which OpenField already depends on.
- **LTX-2.x**: fast, with native audio and IC-LoRA pose/depth control, but it is not a character-swap model.
