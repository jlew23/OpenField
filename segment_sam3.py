import sys, os
from pathlib import Path
import numpy as np
from PIL import Image

def run_sam3(video_path, out_dir, prompt="person"):
    video_path = Path(video_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    from config import setting
    hf_token = setting('HF_TOKEN') or os.getenv('HF_TOKEN')
    if hf_token:
        os.environ['HF_TOKEN'] = hf_token

    from sam3.model_builder import build_sam3_video_predictor
    print(f"[SAM3] Initializing SAM 3 Video Predictor on GPU...", flush=True)
    predictor = build_sam3_video_predictor()

    print(f"[SAM3] Starting video tracking session for {video_path.name}...", flush=True)
    resp = predictor.handle_request(dict(type="start_session", resource_path=str(video_path)))
    session_id = resp["session_id"]

    try:
        print(f"[SAM3] Prompting frame 0 with '{prompt}'...", flush=True)
        resp = predictor.handle_request(dict(
            type="add_prompt",
            session_id=session_id,
            frame_index=0,
            text=prompt
        ))

        frame_count = 0
        print(f"[SAM3] Propagating mask tracking across all video frames...", flush=True)
        for stream_resp in predictor.handle_stream_request(dict(
            type="propagate_in_video",
            session_id=session_id
        )):
            frame_idx = stream_resp["frame_index"]
            outputs = stream_resp["outputs"]
            binary_masks = outputs.get("out_binary_masks")
            
            combined = None
            if binary_masks is not None and len(binary_masks) > 0:
                if isinstance(binary_masks, np.ndarray):
                    combined = (np.any(binary_masks, axis=0)).astype(np.uint8) * 255
                else:
                    import torch
                    if isinstance(binary_masks, torch.Tensor):
                        combined = (binary_masks.any(dim=0).cpu().numpy().astype(np.uint8)) * 255

            if combined is not None:
                mask_img = Image.fromarray(combined)
                mask_img.save(out_dir / f"mask_{frame_idx:04d}.png")
            frame_count += 1

        print(f"[SAM3] Successfully generated {frame_count} masks using SAM 3 in {out_dir}", flush=True)
        return True
    finally:
        try:
            predictor.handle_request(dict(type="close_session", session_id=session_id))
            predictor.shutdown()
        except Exception:
            pass

def main():
    if len(sys.argv) < 3:
        print("Usage: python segment_sam3.py <video_path> <output_dir> [prompt]")
        sys.exit(1)
        
    video = sys.argv[1]
    out = sys.argv[2]
    prompt = sys.argv[3] if len(sys.argv) > 3 else "person"

    try:
        success = run_sam3(video, out, prompt)
        if success:
            sys.exit(0)
    except Exception as e:
        print(f"[SAM3 Error] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(2)

if __name__ == '__main__':
    main()
