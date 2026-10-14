import sys, os, tempfile, shutil
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

CHUNK_SIZE = 250

def run_sam3_chunked(video_path, out_dir, prompt="person", chunk_size=CHUNK_SIZE):
    video_path = Path(video_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    print(f"[SAM3] Video has {total_frames} frames ({w}x{h} @ {fps:.1f} fps). Using chunk size = {chunk_size} frames.", flush=True)

    from sam3.model_builder import build_sam3_video_predictor
    print("[SAM3] Initializing SAM 3 Video Predictor on GPU...", flush=True)
    predictor = build_sam3_video_predictor()

    num_chunks = (total_frames + chunk_size - 1) // chunk_size
    temp_dir = Path(tempfile.mkdtemp(prefix="sam3_chunks_"))

    try:
        global_saved_count = 0
        for chunk_idx in range(num_chunks):
            start_frame = chunk_idx * chunk_size
            end_frame = min(start_frame + chunk_size, total_frames)
            chunk_len = end_frame - start_frame
            print(f"\n[SAM3] === Processing Chunk {chunk_idx + 1}/{num_chunks} (frames {start_frame}..{end_frame - 1}, len={chunk_len}) ===", flush=True)

            # Write chunk video
            tmp_video = temp_dir / f"chunk_{chunk_idx:03d}.mp4"
            cap = cv2.VideoCapture(str(video_path))
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            writer = cv2.VideoWriter(str(tmp_video), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
            
            for _ in range(chunk_len):
                ret, frame = cap.read()
                if not ret: break
                writer.write(frame)
            writer.release()
            cap.release()

            # Start tracking session for this chunk
            resp = predictor.handle_request(dict(
                type="start_session",
                resource_path=str(tmp_video),
                offload_video_to_cpu=True,
                offload_state_to_cpu=True
            ))
            session_id = resp["session_id"]
            
            try:
                # Add prompt on frame 0 of this chunk
                resp = predictor.handle_request(dict(
                    type="add_prompt",
                    session_id=session_id,
                    frame_index=0,
                    text=prompt
                ))

                init_masks = resp.get("outputs", {}).get("out_binary_masks")
                last_mask = None
                if init_masks is not None and len(init_masks) > 0:
                    if isinstance(init_masks, np.ndarray):
                        last_mask = (np.any(init_masks, axis=0)).astype(np.uint8) * 255
                    else:
                        import torch
                        if isinstance(init_masks, torch.Tensor):
                            last_mask = (init_masks.any(dim=0).cpu().numpy().astype(np.uint8)) * 255
                
                if last_mask is not None:
                    Image.fromarray(last_mask).save(out_dir / f"mask_{start_frame:04d}.png")

                # Propagate in this chunk
                chunk_tracked = 0
                for stream_resp in predictor.handle_stream_request(dict(
                    type="propagate_in_video",
                    session_id=session_id
                )):
                    local_idx = stream_resp["frame_index"]
                    global_idx = start_frame + local_idx
                    outputs = stream_resp.get("outputs", {})
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
                        last_mask = combined
                    elif last_mask is not None:
                        combined = last_mask
                    else:
                        combined = np.zeros((h, w), dtype=np.uint8)

                    Image.fromarray(combined).save(out_dir / f"mask_{global_idx:04d}.png")
                    chunk_tracked += 1
                    global_saved_count += 1
                    
                    if chunk_tracked % 50 == 0:
                        print(f"[SAM3] Chunk {chunk_idx + 1}: Tracked {chunk_tracked}/{chunk_len} frames (Overall: {global_saved_count}/{total_frames})...", flush=True)

                print(f"[SAM3] Chunk {chunk_idx + 1} finished: generated {chunk_tracked} masks.", flush=True)
            finally:
                try:
                    predictor.handle_request(dict(type="close_session", session_id=session_id))
                except Exception:
                    pass
                if tmp_video.exists():
                    tmp_video.unlink()

        # Check total masks
        final_count = len(list(out_dir.glob("mask_*.png")))
        print(f"[SAM3] Total masks generated: {final_count}/{total_frames} in {out_dir}", flush=True)
        return final_count > 0
    finally:
        try:
            predictor.shutdown()
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)

def main():
    if len(sys.argv) < 3:
        print("Usage: python segment_sam3.py <video_path> <output_dir> [prompt]")
        sys.exit(1)
        
    video = sys.argv[1]
    out = sys.argv[2]
    prompt = sys.argv[3] if len(sys.argv) > 3 else "person"

    try:
        success = run_sam3_chunked(video, out, prompt)
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        import traceback
        print(f"[SAM3 Error] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(2)

if __name__ == '__main__':
    main()
