# Local generation: the character swap on your own GPU

OpenField's paid path sends the prepared clip to Enhancor / Seedance. The **Local GPU** path runs the
same Higgsfield-style swap on your machine through ComfyUI, for free per render. It reuses everything
OpenField already makes: the normalized `original.mp4`, the SAM 3 `mask.mp4`, the `depth.mp4`
control video, your reference image, and the full original-audio restoration at the end.

```
OpenField prepare  ──► original.mp4 · mask.mp4 · depth.mp4 ──┐
your reference image ─────────────────────────────────────────┼──► ComfyUI workflow (Wan 2.2 Animate / VACE / …)
mask approval (same QA gate as paid) ─────────────────────────┘                │
                                                                               ▼
                                         local-result.mp4 ──► original audio restored ──► final-preview.mp4
```

## Recommended model: Wan 2.2 Animate (replacement / "mix" mode)

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
   approve the mask in step 02 as usual, and press **Create Draft**.

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

- **Wan VACE** (`OF_CONTROL` = depth.mp4, `OF_MASK` = mask.mp4): a general video-editing model. Use it when
  you want the depth composite to drive motion exactly as the paid path does.
- **Wan2GP**: a low-VRAM web UI (profiles down to ~6 GB) that packages Wan models. It is Gradio-based, so a
  future bridge could drive it through `gradio_client`, which OpenField already depends on.
- **LTX-2.x**: fast, with native audio and IC-LoRA pose/depth control, but it is not a character-swap model.
