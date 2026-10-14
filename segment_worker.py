import sys
from pathlib import Path
import av, numpy as np, urllib.request
from PIL import Image
import mediapipe as mp

def main():
    if len(sys.argv) < 3:
        print("Usage: python segment_worker.py <video_path> <output_dir>")
        sys.exit(1)
        
    video_path = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = Path(__file__).resolve().parent / 'models' / 'selfie_segmenter.tflite'
    if not model_path.exists():
        model_path.parent.mkdir(exist_ok=True)
        url = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite'
        urllib.request.urlretrieve(url, str(model_path))
        
    BaseOptions = mp.tasks.BaseOptions
    ImageSegmenter = mp.tasks.vision.ImageSegmenter
    ImageSegmenterOptions = mp.tasks.vision.ImageSegmenterOptions
    VisionRunningMode = mp.tasks.vision.RunningMode
    
    options = ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=VisionRunningMode.VIDEO,
        output_category_mask=True,
        output_confidence_masks=True
    )
    
    frame_count = 0
    with ImageSegmenter.create_from_options(options) as segmenter, av.open(str(video_path)) as container:
        for i, frame in enumerate(container.decode(video=0)):
            rgb = frame.to_ndarray(format='rgb24')
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = segmenter.segment_for_video(mp_image, round(i * 1000 / 24))
            
            if result.confidence_masks and len(result.confidence_masks) > 0:
                conf = result.confidence_masks[0].numpy_view()
                binary_mask = (conf > 0.4).astype(np.uint8) * 255
            else:
                cat = result.category_mask.numpy_view()
                # 1 = person, 0 = background, 255 = unassigned
                binary_mask = ((cat == 1) & (cat != 255)).astype(np.uint8) * 255

            if binary_mask.ndim == 3 and binary_mask.shape[-1] == 1:
                binary_mask = binary_mask.squeeze(-1)
            Image.fromarray(binary_mask).save(out_dir / f'mask_{i:04d}.png')
            frame_count += 1
            
    print(f"Segmented {frame_count} frames to {out_dir}")

if __name__ == '__main__':
    main()
