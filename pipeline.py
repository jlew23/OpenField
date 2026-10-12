from pathlib import Path
from fractions import Fraction
import os, shutil, json, time
import av, numpy as np, requests
from PIL import Image
from gradio_client import Client, handle_file

from config import load_env
load_env()

DEPTH='depth-anything/Video-Depth-Anything'
SAM='linoyts/SAM3-Video'
_depth_pipe = None

def frames(path):
    with av.open(str(path)) as c:
        for f in c.decode(video=0): yield f.to_ndarray(format='rgb24')

def writer(path,w,h):
    c=av.open(str(path),'w');s=c.add_stream('libx264',rate=24);s.width=w;s.height=h;s.pix_fmt='yuv420p';s.options={'crf':'18','preset':'fast'}
    return c,s

def put(c,s,a,i):
    f=av.VideoFrame.from_ndarray(a,format='rgb24');f.pts=i;f.time_base=Fraction(1,24)
    for p in s.encode(f):c.mux(p)

def finish(c,s):
    for p in s.encode():c.mux(p)
    c.close()

def normalize(src,dst):
    with av.open(str(src)) as inp:
        vs=inp.streams.video[0];rate=float(vs.average_rate or 24)
        dur=float(vs.duration*vs.time_base) if vs.duration else float(inp.duration/av.time_base)
        # no duration limit for local processing
        it=iter(inp.decode(video=0));cur=next(it);start=float(cur.time or 0);nxt=next(it,None)
        scale=min(1,960/max(cur.width,cur.height));w=max(2,int(cur.width*scale)//2*2);h=max(2,int(cur.height*scale)//2*2)
        out,stream=writer(dst,w,h);count=round(dur*24)
        for i in range(count):
            t=i/24+start
            while nxt is not None and float(nxt.time)<=t:cur=nxt;nxt=next(it,None)
            a=np.asarray(cur.to_image().resize((w,h),Image.Resampling.LANCZOS));put(out,stream,a,i)
        finish(out,stream)
    return {'frames':count,'fps':24,'width':w,'height':h,'duration':count/24}

def file_path(x):
    if isinstance(x,str):return x
    if isinstance(x,dict):return file_path(x.get('video') or x.get('path'))
    raise ValueError('Provider did not return a downloadable video.')

def get_local_depth_pipeline():
    global _depth_pipe
    if _depth_pipe is None:
        import torch
        from transformers import pipeline
        device = 0 if torch.cuda.is_available() else -1
        _depth_pipe = pipeline(task="depth-estimation", model="depth-anything/Depth-Anything-V2-Small-hf", device=device)
    return _depth_pipe

def depth_local(src, dst, status=print):
    import cv2
    status('Loading Depth-Anything-V2 model weights on CUDA...')
    pipe = get_local_depth_pipeline()
    out = s = None
    all_frames = list(frames(src))
    total = len(all_frames)
    status(f'Running depth estimation on {total} frames...')
    for i, a in enumerate(all_frames):
        if i % 15 == 0 or i == total - 1:
            status(f'Depth estimation: frame {i+1}/{total} ({(i+1)/total*100:.0f}%)')
        pil_im = Image.fromarray(a)
        res = pipe(pil_im)
        depth_np = np.array(res["predicted_depth"], dtype=np.float32)
        d_min, d_max = depth_np.min(), depth_np.max()
        if d_max > d_min:
            depth_norm = ((depth_np - d_min) / (d_max - d_min) * 255).astype(np.uint8)
        else:
            depth_norm = np.zeros_like(depth_np, dtype=np.uint8)
        depth_norm = cv2.resize(depth_norm, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_LINEAR)
        colored = cv2.applyColorMap(depth_norm, cv2.COLORMAP_INFERNO)
        colored_rgb = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
        if out is None:
            out, s = writer(dst, colored_rgb.shape[1], colored_rgb.shape[0])
        put(out, s, colored_rgb, i)
    if out is None:
        raise ValueError('Empty depth video')
    finish(out, s)
    status('Depth estimation finished successfully!')

def depth_hf(src,dst):
    c=Client(DEPTH,token=os.getenv('HF_TOKEN') or None,verbose=False)
    result=c.predict({'video':handle_file(str(src))},max_len=-1,target_fps=24,max_res=960,grayscale=False,api_name='/infer_video_depth')
    shutil.copy(file_path(result[1]),dst)

def depth_replicate(src,dst,model_name="lucataco/depth-anything-video"):
    token=os.getenv('REPLICATE_API_TOKEN')
    if not token:raise ValueError('Replicate fallback requires REPLICATE_API_TOKEN in the server environment.')
    headers={'Authorization':f'Bearer {token}'}
    r=requests.get('https://api.replicate.com/v1/models/'+model_name,headers=headers,timeout=30);r.raise_for_status();model=r.json();v=model['latest_version'];props=v['openapi_schema']['components']['schemas']['Input']['properties']
    key=next((k for k in props if 'video' in k and props[k].get('format')=='uri'),None)
    if not key:raise ValueError('Unable to identify Replicate video input in schema.')
    with open(src,'rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=headers,files={'content':f},timeout=120)
    r.raise_for_status();url=r.json()['urls']['get']
    r=requests.post('https://api.replicate.com/v1/predictions',headers=headers,json={'version':v['id'],'input':{key:url}},timeout=60);r.raise_for_status();j=r.json()
    for _ in range(180):
        if j['status'] in ['succeeded','failed','canceled']:break
        time.sleep(5);r=requests.get(j['urls']['get'],headers=headers,timeout=30);r.raise_for_status();j=r.json()
    if j['status']!='succeeded':raise RuntimeError(str(j.get('error') or j['status']))
    output=j['output'];url=output if isinstance(output,str) else output[0] if isinstance(output,list) else next(v for k,v in output.items() if 'depth' in k)
    r=requests.get(url,timeout=120);r.raise_for_status();Path(dst).write_bytes(r.content)

def composite(original,depth,seg,directory,audio_source=None):
    raw=Path(seg).is_dir()
    mask_files=sorted(Path(seg).glob('mask_*.png')) if raw else []
    counts=[sum(1 for _ in frames(p)) for p in [original,depth]]+[len(mask_files) if raw else sum(1 for _ in frames(seg))]
    if len(set(counts))!=1:raise ValueError(f'Frame alignment failed (original/depth/SAM): {counts}. No misaligned export produced.')
    if raw and [int(p.stem.split('_')[-1]) for p in mask_files]!=list(range(counts[0])):raise ValueError('Missing or shifted frame indices in raw masks.')
    outs={};area=0
    for i,(rgb,d,sam) in enumerate(zip(frames(original),frames(depth),(np.asarray(Image.open(p).convert('RGB')) for p in mask_files) if raw else frames(seg))):
        h,w=rgb.shape[:2]
        if raw:
            mask=(sam[:,:,0]>127).astype(np.uint8)*255
        else:
            base=np.asarray(Image.fromarray(d).resize((sam.shape[1],sam.shape[0]),Image.Resampling.BILINEAR)).astype(np.float32)
            marked=base*0.5+np.array([0,127.5,0],dtype=np.float32)
            observed=sam.astype(np.float32)
            unchanged_error=((observed-base)**2).sum(axis=2)
            marked_error=((observed-marked)**2).sum(axis=2)
            mask=((marked_error+100<unchanged_error)&(observed[:,:,1]-base[:,:,1]>12)).astype(np.uint8)*255
        mask=np.asarray(Image.fromarray(mask).resize((w,h),Image.Resampling.NEAREST));area+=np.count_nonzero(mask)
        d=np.asarray(Image.fromarray(d).resize((w,h),Image.Resampling.BILINEAR));alpha=(mask>127)[:,:,None]
        result=np.where(alpha,d,rgb).astype(np.uint8)
        for name,a in [('mask',np.repeat(mask[:,:,None],3,axis=2)),('composite-silent',result)]:
            if name not in outs:outs[name]=writer(directory/(name+'.mp4'),w,h)
            put(*outs[name],a,i)
    for c,s in outs.values():finish(c,s)
    if area==0:raise ValueError('Segmentation found no subject in the video. Try a different video or angle.')
    final=directory/'composite.mp4'
    with av.open(str(directory/'composite-silent.mp4')) as video, av.open(str(audio_source or original)) as aud, av.open(str(final),'w') as output:
        vs=output.add_stream_from_template(video.streams.video[0])
        astream=output.add_stream_from_template(aud.streams.audio[0]) if aud.streams.audio else None
        for packet in video.demux(video=0):
            if packet.dts is not None:packet.stream=vs;output.mux(packet)
        if aud.streams.audio:
            for packet in aud.demux(audio=0):
                if packet.dts is not None:packet.stream=astream;output.mux(packet)
    return counts[0]

def run(src,directory,prompt='person',provider='local',status=print):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    from audio_workflow import separate
    status('Extracting audio track and isolating vocal stems with Demucs...')
    separate(src,directory,status)
    status('Normalizing video to standard 24 fps...')
    meta=normalize(src,directory/'original.mp4')
    status(f'Video normalized: {meta["frames"]} frames at 24 fps ({meta["duration"]:.1f}s)')
    token = os.getenv('REPLICATE_API_TOKEN', '').strip()
    is_local = (provider=='local') or (not token) or any(x in token.lower() for x in ['your_key','your_api','replace_me','placeholder'])
    if is_local:
        status('Generating depth map locally using Depth-Anything-V2 on RTX 4070...')
        try:
            depth_local(directory/'original.mp4',directory/'depth-raw.mp4',status)
        except Exception as e:
            status(f'Local depth note ({e}), trying alternatives')
            if provider=='huggingface': depth_hf(directory/'original.mp4',directory/'depth-raw.mp4')
            else: depth_replicate(directory/'original.mp4',directory/'depth-raw.mp4')
    elif provider=='huggingface':
        status('Video Depth Anything · generating depth via Hugging Face')
        depth_hf(directory/'original.mp4',directory/'depth-raw.mp4')
    else:
        status('Video Depth Anything · generating depth via Replicate')
        depth_replicate(directory/'original.mp4',directory/'depth-raw.mp4', 'chenxwh/depth-any-video' if provider=='replicate-chenxwh' else 'lucataco/depth-anything-video')
    shutil.copyfile(directory/'depth-raw.mp4',directory/'depth.mp4')
    status('Segmenting person silhouette masks...')
    from raw_masks import segment_raw,clean_border_fragments
    raw_dir=clean_border_fragments(segment_raw(directory/'original.mp4',directory,prompt))
    status('Compositing depth subject over original background...')
    composite(directory/'original.mp4',directory/'depth.mp4',raw_dir,directory,src)
    from audio_workflow import prepare_seedance_video
    status('Pitching isolated vocals +3 semitones and embedding in prepared video...')
    prepare_seedance_video(directory)
    meta.update(prompt=prompt,depth_provider='local' if is_local else provider,sam_space=SAM,mask_method='Local Segmentation')
    (directory/'manifest.json').write_text(json.dumps(meta,indent=2))
    status('Finished! Prepared video and all stems are saved in your run folder.')
