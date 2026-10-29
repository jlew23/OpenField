# Local generation workflows (ComfyUI)

OpenField can run the character swap on your own GPU through [ComfyUI](https://github.com/comfyanonymous/ComfyUI).
Put workflows here in **API format** (in ComfyUI: Workflow → Export (API)).

Give the input nodes these titles (right-click a node → Title) so OpenField knows where
to plug in each job's files:

| Title | Node | OpenField sends |
|---|---|---|
| `OF_REFERENCE` | image loader | your character reference image |
| `OF_VIDEO` | video loader | `original.mp4` (the footage whose subject is replaced) |
| `OF_MASK` | video loader | `mask.mp4` from SAM 3 (step 02), so you can skip the in-graph segmenter |
| `OF_CONTROL` | video loader | `depth.mp4` (for depth-conditioned graphs such as Wan VACE) |
| `OF_PROMPT` | text encode | the generation prompt |
| `OF_NEGATIVE` | text encode | a negative prompt (optional) |
| `OF_SEED` | sampler | the seed |
| `OF_FRAMES` | int / frame cap | the clip's frame count (optional) |

Untagged graphs fall back to a best guess (first image loader, first video loader, first
positive text encode, first sampler seed). The output must come from a Save Video /
Video Combine node. See `docs/LOCAL-GENERATION.md` for the Wan 2.2 Animate setup.
