from pathlib import Path
import os,json,time,zipfile,io,subprocess
import requests

ROOT = Path(__file__).resolve().parent

def segment_local(video, folder, prompt='person', status=print):
    folder = Path(folder)
    out = folder / 'raw-masks'
    out.mkdir(parents=True, exist_ok=True)
    worker_python = ROOT / '.venv/bin/python'
    if not worker_python.exists():
        worker_python = ROOT / '.venv-face/bin/python'
        
    # Priority 1: Local SAM 3
    sam3_script = ROOT / 'segment_sam3.py'
    if sam3_script.exists():
        status(f"Segmenting person silhouettes with local SAM 3 on GPU (prompt: '{prompt}')...")
        proc = subprocess.Popen(
            [str(worker_python), "-u", str(sam3_script), str(video), str(out), prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        for line in proc.stdout:
            l = line.strip()
            if l:
                print(l, flush=True)
                if l.startswith("[SAM3]"):
                    status(l)
        proc.wait()
        mask_count = len(list(out.glob('mask_*.png')))
        if mask_count > 0:
            status(f"Local SAM 3 generated {mask_count} masks successfully.")
            return out
        status("Local SAM 3 encountered an issue and produced no masks, falling back to secondary segmenter...")

    # Priority 2: Secondary segmenter (MediaPipe)
    status("Segmenting with secondary local segmenter...")
    script = ROOT / 'segment_worker.py'
    cmd = [str(worker_python), str(script), str(video), str(out)]
    subprocess.run(cmd, check=True)
    return out

def segment_raw(video, folder, prompt='person', status=print):
    token = os.environ.get('REPLICATE_API_TOKEN', '').strip()
    use_replicate = bool(token) and not any(x in token.lower() for x in ['your_key','your_api','replace_me','placeholder'])
    
    # Always prioritize local SAM 3
    try:
        return segment_local(video, folder, prompt, status=status)
    except Exception as e:
        if not use_replicate:
            raise
        status(f"Local segmentation error ({e}), attempting Replicate fallback...")

    folder=Path(folder);h={'Authorization':'Bearer '+token}
    try:
        with open(video,'rb') as f:r=requests.post('https://api.replicate.com/v1/files',headers=h,files={'content':f},timeout=120)
        r.raise_for_status();url=r.json()['urls']['get']
        payload={'version':'408f82fc20c300aac5d61d2e34ddb34cd0181e810e9f609d250aed14d5f81269','input':{'video':url,'prompt':prompt,'mask_only':True,'return_zip':True}}
        r=requests.post('https://api.replicate.com/v1/predictions',headers=h,json=payload,timeout=60);r.raise_for_status();j=r.json();(folder/'sam-raw-request.json').write_text(json.dumps(j,indent=2));status(f"SAM raw-mask cloud job: {j['id']}")
        for _ in range(180):
            if j['status'] in ['succeeded','failed','canceled']:break
            time.sleep(5);r=requests.get(j['urls']['get'],headers=h,timeout=30);r.raise_for_status();j=r.json()
        if j['status']!='succeeded':
            status(f"Replicate SAM failed, falling back to local: {j.get('error')}")
            return segment_local(video, folder, prompt, status=status)
        r=requests.get(j['output'],timeout=180);r.raise_for_status();(folder/'sam-masks.zip').write_bytes(r.content)
        out=folder/'raw-masks';out.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for name in z.namelist():
                base=Path(name).name
                if base.startswith('mask_') and base.endswith('.png'):(out/base).write_bytes(z.read(name))
        return out
    except Exception as e:
        status(f"Replicate error: {e}, falling back to local segmentation")
        return segment_local(video, folder, prompt, status=status)

def clean_border_fragments(folder):
    """Remove tiny, narrow disconnected edge fragments; preserve large edge subjects."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import label
    folder=Path(folder);output=folder.parent/'clean-masks';output.mkdir(exist_ok=True)
    report=[]
    for p in sorted(folder.glob('mask_*.png')):
        a=np.asarray(Image.open(p).convert('L'))>127;labels,_=label(a);h,w=a.shape;removed=0
        for ident in (set(labels[:,0])|set(labels[:,-1]))-{0}:
            y,x=np.where(labels==ident)
            if len(x)<h*w*.03 and x.max()-x.min()+1<=max(6,int(w*.05)):
                a[labels==ident]=False;removed+=len(x)
        Image.fromarray(a.astype(np.uint8)*255).save(output/p.name)
        report.append({'frame':p.stem,'removed_border_pixels':removed,'mask_pixels':int(a.sum()),'left_right_edge_pixels':int(a[:,0].sum()+a[:,-1].sum())})
    (folder.parent/'mask-cleanup-report.json').write_text(json.dumps(report,indent=2))
    return output
