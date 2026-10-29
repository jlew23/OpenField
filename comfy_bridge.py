"""Local generation through ComfyUI: the Higgsfield-style swap on your own GPU.

Any ComfyUI workflow works (Wan 2.2 Animate replacement, Wan VACE, LTX, ...):
export it with "Save (API Format)" into ./workflows/ and give the input nodes
these titles so OpenField knows where to plug its artifacts in:

  OF_REFERENCE  image loader      <- your character reference image
  OF_VIDEO      video loader      <- original.mp4 (the footage whose subject is replaced)
  OF_MASK       video/image load  <- mask.mp4 from SAM 3 (skip the in-graph segmenter, saves VRAM)
  OF_CONTROL    video loader      <- depth.mp4 (for depth-conditioned workflows such as VACE)
  OF_PROMPT     text encode       <- the generation prompt
  OF_NEGATIVE   text encode       <- negative prompt (optional)
  OF_SEED       sampler / seed    <- seed
  OF_FRAMES     frame count input <- number of frames to generate (optional)

Untagged graphs fall back to a best guess (first image loader, first video loader,
first positive text encode, first sampler seed).
"""
import json, random, time, uuid
from pathlib import Path
import requests

from config import ROOT, setting

WORKFLOWS = ROOT / 'workflows'
TAGS = ('OF_REFERENCE', 'OF_VIDEO', 'OF_MASK', 'OF_CONTROL', 'OF_PROMPT', 'OF_NEGATIVE', 'OF_SEED', 'OF_FRAMES')
VIDEO_EXT = ('.mp4', '.webm', '.mov', '.mkv', '.gif')
NEGATIVE = 'blurry, deformed hands, extra limbs, flicker, warped face, text, watermark, color shift, depth map colors'


def base_url():
    return (setting('COMFYUI_URL') or 'http://127.0.0.1:8188').rstrip('/')


def status():
    url = base_url()
    try:
        r = requests.get(url + '/system_stats', timeout=3)
        r.raise_for_status()
        stats = r.json()
        dev = (stats.get('devices') or [{}])[0]
        info = {'ok': True, 'url': url, 'device': dev.get('name', ''),
                'vram_gb': round(dev.get('vram_total', 0) / 1e9, 1) if dev.get('vram_total') else None}
    except (requests.RequestException, ValueError) as e:
        info = {'ok': False, 'url': url, 'error': f'ComfyUI not reachable ({type(e).__name__}). Start ComfyUI or set COMFYUI_URL.'}
    info['workflows'] = list_workflows()
    return info


def list_workflows():
    WORKFLOWS.mkdir(exist_ok=True)
    out = []
    for f in sorted(WORKFLOWS.glob('*.json')):
        try:
            wf = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        if not _is_api_format(wf):
            out.append({'name': f.name, 'ok': False, 'problem': 'Not API format. In ComfyUI use Workflow > Export (API).'})
            continue
        found = sorted({t for n in wf.values() for t in TAGS if _title(n) == t})
        out.append({'name': f.name, 'ok': True, 'tags': found})
    return out


def _is_api_format(wf):
    return isinstance(wf, dict) and wf and all(isinstance(v, dict) and 'class_type' in v for v in wf.values())


def _title(node):
    return ((node.get('_meta') or {}).get('title') or '').strip().upper()


def _first(wf, pred):
    for nid in sorted(wf, key=lambda k: int(k) if str(k).isdigit() else 0):
        if pred(wf[nid]):
            return nid
    return None


def locate(wf):
    """Map OF_* roles to node ids (explicit titles first, then best guesses)."""
    roles = {t: nid for nid, n in wf.items() for t in TAGS if _title(n) == t}
    ins = lambda n: n.get('inputs', {})
    if 'OF_REFERENCE' not in roles:
        roles['OF_REFERENCE'] = _first(wf, lambda n: n['class_type'] in ('LoadImage', 'LoadImageMask') and 'mask' not in _title(n).lower())
    if 'OF_VIDEO' not in roles:
        roles['OF_VIDEO'] = _first(wf, lambda n: ('video' in ins(n) or 'file' in ins(n)) and 'load' in n['class_type'].lower()
                                   and not any(w in _title(n).lower() for w in ('mask', 'depth', 'control')))
    if 'OF_PROMPT' not in roles:
        roles['OF_PROMPT'] = _first(wf, lambda n: 'text' in ins(n) and 'encode' in n['class_type'].lower()
                                    and 'neg' not in _title(n).lower())
    if 'OF_SEED' not in roles:
        roles['OF_SEED'] = _first(wf, lambda n: any(k in ins(n) for k in ('seed', 'noise_seed')) and not isinstance(ins(n).get('seed', ins(n).get('noise_seed')), list))
    return {k: v for k, v in roles.items() if v}


def _set(node, value, kind):
    inputs = node.setdefault('inputs', {})
    keys = {'image': ('image',), 'video': ('video', 'file', 'filename', 'path'),
            'text': ('text', 'prompt', 'positive_prompt', 'negative_prompt', 'string'),
            'seed': ('seed', 'noise_seed'), 'frames': ('frame_load_cap', 'length', 'num_frames', 'frames', 'value')}[kind]
    for k in keys:
        if k in inputs and not isinstance(inputs[k], list):  # a list means "wired from another node"
            inputs[k] = value
            return True
    return False


def upload(path):
    with open(path, 'rb') as fh:
        r = requests.post(base_url() + '/upload/image', files={'image': (Path(path).name, fh)},
                          data={'overwrite': 'true', 'type': 'input'}, timeout=300)
    if not r.ok:
        raise ValueError(f'ComfyUI upload failed ({r.status_code}): {r.text[:200]}')
    j = r.json()
    return (j.get('subfolder') + '/' if j.get('subfolder') else '') + j['name']


def _video_frames(path):
    try:
        import av
        with av.open(str(path)) as c:
            s = c.streams.video[0]
            return int(s.frames or round(float(c.duration / av.time_base) * float(s.average_rate)))
    except Exception:
        return 0


def submit(folder, prompt, reference, workflow, seed=None, status=print):
    """Patch the workflow with this job's artifacts and queue it. Returns the ComfyUI prompt id."""
    folder = Path(folder)
    from mask_review import require_approved
    require_approved(folder)  # same QA gate as paid generation
    wf_path = WORKFLOWS / Path(workflow).name
    if not wf_path.exists():
        raise ValueError('Pick a workflow from ./workflows (export it from ComfyUI in API format).')
    wf = json.loads(wf_path.read_text(encoding='utf-8'))
    if not _is_api_format(wf):
        raise ValueError(f'{wf_path.name} is not in ComfyUI API format.')
    roles = locate(wf)
    if 'OF_REFERENCE' not in roles or 'OF_VIDEO' not in roles:
        raise ValueError('The workflow needs an image loader titled OF_REFERENCE and a video loader titled OF_VIDEO.')
    source = folder / 'original.mp4' if (folder / 'original.mp4').exists() else folder / 'upload.mp4'
    status('Uploading reference, source video and masks to ComfyUI')
    plan = [('OF_REFERENCE', Path(reference), 'image'), ('OF_VIDEO', source, 'video'),
            ('OF_MASK', folder / 'mask.mp4', 'video'), ('OF_CONTROL', folder / 'depth.mp4', 'video')]
    used = {}
    for role, path, kind in plan:
        nid = roles.get(role)
        if not nid:
            continue
        if not path.exists():
            raise ValueError(f'{role} is wired in the workflow but {path.name} is missing from this job.')
        name = upload(path)
        node = wf[nid]
        if not (_set(node, name, kind) or _set(node, name, 'image' if kind == 'video' else 'video')):
            raise ValueError(f'Could not find a file input on node {nid} ({node["class_type"]}) for {role}.')
        used[role] = path.name
    if roles.get('OF_PROMPT'):
        _set(wf[roles['OF_PROMPT']], prompt, 'text')
    if roles.get('OF_NEGATIVE'):
        _set(wf[roles['OF_NEGATIVE']], NEGATIVE, 'text')
    seed = int(seed) if seed not in (None, '') else random.randint(1, 2 ** 31 - 1)
    if roles.get('OF_SEED'):
        _set(wf[roles['OF_SEED']], seed, 'seed')
    frames = _video_frames(source)
    if roles.get('OF_FRAMES') and frames:
        _set(wf[roles['OF_FRAMES']], frames, 'frames')
    client = uuid.uuid4().hex
    r = requests.post(base_url() + '/prompt', json={'prompt': wf, 'client_id': client}, timeout=60)
    if not r.ok:
        detail = r.text[:1500]
        (folder / 'local-error.json').write_text(detail)
        raise ValueError(f'ComfyUI rejected the workflow ({r.status_code}). Missing models or custom nodes? {detail[:400]}')
    pid = r.json().get('prompt_id')
    if not pid:
        raise ValueError('ComfyUI did not return a prompt id.')
    meta = {'prompt_id': pid, 'workflow': wf_path.name, 'seed': seed, 'inputs': used, 'roles': roles,
            'prompt': prompt, 'frames': frames, 'url': base_url(), 'submitted': time.time()}
    (folder / 'local-request.json').write_text(json.dumps(meta, indent=2))
    (folder / 'generation.json').write_text(json.dumps({'request_id': pid, 'prompt': prompt, 'video': 'local-result.mp4',
                                                        'mode': 'local:' + wf_path.stem}))
    status(f'Queued on local GPU · workflow {wf_path.name} · seed {seed}')
    return pid


def _outputs(entry):
    for node_out in (entry.get('outputs') or {}).values():
        for key in ('gifs', 'videos', 'images', 'files'):
            for item in node_out.get(key, []) or []:
                name = item.get('filename', '')
                if name.lower().endswith(VIDEO_EXT):
                    yield item


def wait_and_finish(folder, prompt_id, status=print, timeout=6 * 3600):
    folder = Path(folder)
    url = base_url()
    start = time.time()
    last = ''
    while time.time() - start < timeout:
        try:
            h = requests.get(f'{url}/history/{prompt_id}', timeout=20).json()
        except (requests.RequestException, ValueError):
            h = {}
        entry = h.get(prompt_id)
        if entry:
            st = entry.get('status') or {}
            if st.get('status_str') == 'error':
                msgs = [m for m in st.get('messages', []) if m and m[0] == 'execution_error']
                detail = msgs[0][1].get('exception_message', '') if msgs else 'unknown error'
                raise ValueError(f'ComfyUI run failed: {detail[:400]}')
            items = list(_outputs(entry))
            if items:
                item = items[-1]
                status('Downloading local render')
                r = requests.get(f'{url}/view', params={'filename': item['filename'], 'subfolder': item.get('subfolder', ''),
                                                       'type': item.get('type', 'output')}, timeout=600)
                r.raise_for_status()
                target = folder / 'local-result.mp4'
                target.write_bytes(r.content)
                status('Restoring entire original source audio · discarding generated audio')
                from audio_workflow import finish_preview
                finish_preview(target, folder)
                return target
            if st.get('completed'):
                raise ValueError('ComfyUI finished but the workflow saved no video. Add a Save Video / Video Combine node.')
        else:
            try:
                q = requests.get(f'{url}/queue', timeout=10).json()
                running = any(x[1] == prompt_id for x in q.get('queue_running', []))
                pending = [x[1] for x in q.get('queue_pending', [])]
                msg = 'Rendering on local GPU' if running else (f'Waiting in ComfyUI queue (position {pending.index(prompt_id) + 1})'
                                                                 if prompt_id in pending else 'Waiting for ComfyUI')
            except (requests.RequestException, ValueError):
                msg = 'Waiting for ComfyUI'
            mins = int((time.time() - start) // 60)
            msg = f'{msg} · {mins} min'
            if msg != last:
                status(msg)
                last = msg
        time.sleep(5)
    raise ValueError('Local render timed out.')
