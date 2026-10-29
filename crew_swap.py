"""Crew swap: replace each person in a clip with their own reference, on your own GPU.

Made for two-person challenge videos (the hotel lobby challenge, the Oouuh challenge) of 15-20 seconds,
using Wan 2.1 VACE through ComfyUI (workflows/wan21-vace-swap.json).

How it works:

1. People. The prepared masks (SAM 3, or the fallback segmenter) are split into one track per person.
   SAM 3's per-object ids are used when present; otherwise connected blobs are tracked by overlap, and a
   blob that swallows two people (a hug, a shoulder bump) is split by distance to each person.
2. Passes. People are swapped one at a time. A pass repaints only that person's grown mask, with the
   depth silhouette inside it as the motion guide and the reference image for the look.
3. Chunks. VACE renders about five seconds (81 frames at 16 fps) per run, so the window is cut into
   overlapping chunks. Each chunk starts with the last second of the previous chunk's output, unmasked,
   so the new person carries across the cut, and the overlap is cross-faded. Finished chunks are cached,
   so a crashed or stopped render resumes where it left off.
4. Finish. The new people are pasted back into the full-resolution original with a feathered mask,
   timing goes back to 24 fps, and the original audio for the window is restored.

CLI:
    python crew_swap.py RUN_FOLDER --people
    python crew_swap.py RUN_FOLDER --ref 1=me.png --ref 2=friend.png --preset hotel-lobby
"""
import hashlib, json, math, shutil, subprocess, time
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image

GEN_FPS = 16
CHUNK = 81        # Wan's native clip length: 4n+1 frames, about five seconds at 16 fps
OVERLAP = 16      # one second of the previous chunk carried into the next
LONG_SIDE = 832   # 480p class, what VACE 1.3B was trained at
SRC_FPS = 24      # OpenField normalizes every upload to 24 fps
MIN_AREA = 0.004  # blobs under 0.4% of the frame are noise, not people

PRESETS = {
    'hotel-lobby': {'label': 'Hotel lobby challenge', 'seconds': 18, 'people': 2,
                    'prompt': 'a person dancing in a hotel lobby, the same person as the reference image, '
                              'natural skin, consistent outfit, sharp face, realistic indoor lighting'},
    'oouuh': {'label': 'Oouuh challenge (acoustic)', 'seconds': 15, 'people': 2,
              'prompt': 'a person performing to an acoustic song, the same person as the reference image, '
                        'natural skin, consistent outfit, sharp face, realistic lighting'},
    'custom': {'label': 'Custom', 'seconds': 20, 'people': 0,
               'prompt': 'the same person as the reference image, natural skin, consistent outfit, sharp face'},
}


# ---------------------------------------------------------------- video helpers

def _decode(path):
    import av
    with av.open(str(path)) as c:
        for f in c.decode(video=0):
            yield f.to_ndarray(format='rgb24')


def _info(path):
    import av
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        n = s.frames or sum(1 for _ in c.decode(video=0))
        return {'frames': int(n), 'width': s.codec_context.width, 'height': s.codec_context.height}


def _write(path, frames, fps, crf=12):
    import av
    frames = list(frames)
    h, w = frames[0].shape[:2]
    with av.open(str(path), 'w') as c:
        s = c.add_stream('libx264', rate=Fraction(fps).limit_denominator(1000))
        s.width, s.height, s.pix_fmt = w, h, 'yuv420p'
        s.options = {'crf': str(crf), 'preset': 'fast'}
        for i, a in enumerate(frames):
            f = av.VideoFrame.from_ndarray(np.ascontiguousarray(a), format='rgb24')
            f.pts = i
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)


def _resize(a, size, nearest=False):
    if a.shape[1] == size[0] and a.shape[0] == size[1]:
        return a
    import cv2
    return cv2.resize(a, size, interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_AREA)


def gen_size(w, h, long_side=LONG_SIDE):
    """Generation size: long side ~832, both sides multiples of 16 (VACE's step)."""
    s = long_side / max(w, h)
    return max(16, int(round(w * s / 16)) * 16), max(16, int(round(h * s / 16)) * 16)


def plan_chunks(n, chunk=CHUNK, overlap=OVERLAP):
    """[(start, end)] covering n frames; every chunk after the first begins `overlap` frames early."""
    if n <= chunk:
        return [(0, n)]
    out, a = [], 0
    while True:
        b = min(n, a + chunk)
        out.append((a, b))
        if b == n:
            return out
        a = b - overlap


def wan_length(n):
    """Smallest Wan-valid length (4k+1) that holds n frames."""
    return 4 * math.ceil(max(0, n - 1) / 4) + 1


def _grow(mask, r):
    if r <= 0 or not mask.any():
        return mask
    import cv2
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate(mask.astype(np.uint8), k) > 0


def _feather(mask, r):
    import cv2
    a = mask.astype(np.float32)
    if r > 0 and mask.any():
        a = cv2.GaussianBlur(a, (0, 0), max(1.0, r / 3))
        a = np.maximum(a, mask * 0.98)  # stay solid inside the repainted area
    return a


def _gray(depth_rgb):
    """Depth maps come colourised (inferno); VACE was trained on grey depth, so fold back to luminance."""
    g = (depth_rgb[..., 0] * 0.299 + depth_rgb[..., 1] * 0.587 + depth_rgb[..., 2] * 0.114).astype(np.uint8)
    return np.repeat(g[..., None], 3, axis=2)


# ---------------------------------------------------------------- people

def _mask_dir(folder):
    for name in ('clean-masks', 'raw-masks'):
        d = folder / name
        if d.exists() and any(d.glob('mask_*.png')):
            return d
    raise ValueError('Prepare the video first: no masks found for this job.')


def _components(frame_mask, labels=None):
    from scipy.ndimage import label, binary_closing
    total = frame_mask.size
    if labels is not None:
        return [labels == v for v in np.unique(labels) if v and (labels == v).sum() >= total * MIN_AREA]
    m = binary_closing(frame_mask, iterations=2)
    lab, k = label(m)
    if not k:
        return []
    sizes = np.bincount(lab.ravel())
    return [lab == i for i in range(1, k + 1) if sizes[i] >= total * MIN_AREA]


def _centroid(m):
    ys, xs = np.nonzero(m)
    return (ys.mean(), xs.mean()) if len(xs) else (0.0, 0.0)


def _color_bins(rgb):
    q = (rgb >> 4).astype(np.int32)
    return q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]


def _split_blob(comp, tracks, q, diag):
    """Split a blob that holds several touching people: each pixel goes to the person whose last outline is
    nearest and whose clothing colours match best, then the split is smoothed so it stays one piece each."""
    from scipy.ndimage import distance_transform_edt, uniform_filter
    ys, xs = np.nonzero(comp)
    pad = int(0.05 * diag)
    y0, y1 = max(0, ys.min() - pad), ys.max() + pad + 1
    x0, x1 = max(0, xs.min() - pad), xs.max() + pad + 1
    sub = comp[y0:y1, x0:x1]
    costs = []
    for t in tracks:
        dist = distance_transform_edt(~t['prev'][y0:y1, x0:x1]) / (0.03 * diag)
        cost = dist
        hist = t.get('hist')
        if q is not None and hist is not None and hist.sum() > 0:
            prob = (hist + 1) / (hist.sum() + 4096)
            cost = cost + 0.5 * -np.log(prob[q[y0:y1, x0:x1]])
        costs.append(cost)
    owner = np.argmin(np.stack(costs), axis=0)
    votes = np.stack([uniform_filter((owner == k).astype(np.float32), size=9) for k in range(len(tracks))])
    owner = votes.argmax(axis=0)
    out = {}
    for k in range(len(tracks)):
        part = np.zeros_like(comp)
        part[y0:y1, x0:x1] = sub & (owner == k)
        out[k] = part
    return out


def split_people(folder, max_people=4, status=print):
    """Write people/label_XXXX.png (0 = background, 1..N = person, left to right) and people.json."""
    folder = Path(folder)
    src = _mask_dir(folder)
    files = sorted(src.glob('mask_*.png'))
    objects = folder / 'raw-masks' / 'objects'
    use_objects = objects.exists() and any(objects.glob('label_*.png'))
    out = folder / 'people'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    status(f'Finding people in {len(files)} frames ({"SAM 3 object ids" if use_objects else "tracked silhouettes"})')
    tracks, labels_all, merged = [], [], 0
    h = w = None
    original = folder / 'original.mp4'
    rgb_frames = _decode(original) if original.exists() else iter(())
    for fi, p in enumerate(files):
        m = np.asarray(Image.open(p).convert('L')) > 127
        h, w = m.shape
        rgb = next(rgb_frames, None)
        q = _color_bins(_resize(rgb, (w, h))) if rgb is not None else None
        lp = objects / p.name.replace('mask_', 'label_')
        lab = None
        if use_objects and lp.exists():
            lab = np.asarray(Image.open(lp))
            lab = np.where(m, lab, 0) if lab.shape == m.shape else None  # respect the cleaned mask
        comps = _components(m, lab)
        if not tracks:
            comps.sort(key=lambda c: _centroid(c)[1])
        frame = np.zeros((h, w), np.uint8)
        claimed = {}
        diag = math.hypot(h, w)
        for comp in comps:
            hits = []
            for ti, t in enumerate(tracks):
                if t['prev'] is None:
                    continue
                inter = np.logical_and(comp, t['prev_grown']).sum()
                if inter > 0.15 * max(1, t['prev'].sum()):
                    hits.append(ti)
            if len(hits) >= 2:
                merged += 1
                for ti, part in _split_blob(comp, [tracks[ti] for ti in hits], q, diag).items():
                    claimed[hits[ti]] = claimed.get(hits[ti], np.zeros_like(comp)) | part
                continue
            if len(hits) == 1:
                ti = hits[0]
            else:
                c = _centroid(comp)
                free = [(math.hypot(c[0] - t['c'][0], c[1] - t['c'][1]), ti) for ti, t in enumerate(tracks) if ti not in claimed]
                near = min(free) if free else None
                if near and near[0] < 0.25 * diag:
                    ti = near[1]
                elif len(tracks) < max_people:
                    tracks.append({'prev': None, 'prev_grown': None, 'c': c, 'seen': 0, 'area': 0, 'best': (0, fi), 'first_x': c[1] / w})
                    ti = len(tracks) - 1
                else:
                    ti = min((math.hypot(c[0] - t['c'][0], c[1] - t['c'][1]), ti) for ti, t in enumerate(tracks))[1]
            claimed[ti] = claimed.get(ti, np.zeros_like(comp)) | comp
        for ti, cm in claimed.items():
            t = tracks[ti]
            t.update(prev=cm, prev_grown=_grow(cm, max(2, int(0.02 * max(h, w)))), c=_centroid(cm))
            if q is not None and len(claimed) == len(comps):  # learn clothing colours only when nobody is touching
                t['hist'] = t.get('hist', np.zeros(4096)) + np.bincount(q[cm], minlength=4096)
            area = int(cm.sum())
            t['seen'] += 1
            t['area'] += area
            if area > t['best'][0] and len(claimed) == len(comps):  # thumbnail from a frame where nobody touches
                t['best'] = (area, fi)
            frame[cm & (frame == 0)] = ti + 1
        labels_all.append(frame)
    n = len(files)
    # Keep real people (seen in at least 10% of frames), numbered left to right by where they first appear.
    keep = sorted([ti for ti, t in enumerate(tracks) if t['seen'] >= max(3, 0.1 * n)], key=lambda ti: tracks[ti]['first_x'])
    remap = np.zeros(len(tracks) + 1, np.uint8)
    for new, ti in enumerate(keep, 1):
        remap[ti + 1] = new
    for fi, frame in enumerate(labels_all):
        Image.fromarray(remap[frame]).save(out / f'label_{fi:04d}.png')
    # Thumbnails from the frame where each person is biggest.
    want = {tracks[ti]['best'][1]: [] for ti in keep}
    for new, ti in enumerate(keep, 1):
        want[tracks[ti]['best'][1]].append(new)
    people = []
    original = folder / 'original.mp4'
    if original.exists():
        for fi, rgb in enumerate(_decode(original)):
            for pid in want.get(fi, []):
                m = _resize((remap[labels_all[fi]] == pid).astype(np.uint8), (rgb.shape[1], rgb.shape[0]), nearest=True) > 0
                ys, xs = np.nonzero(m)
                pad = int(0.06 * max(rgb.shape[:2]))
                lit = np.where(m[..., None], rgb, (rgb * 0.3).astype(np.uint8))  # dim everyone else
                crop = lit[max(0, ys.min() - pad):ys.max() + pad, max(0, xs.min() - pad):xs.max() + pad]
                Image.fromarray(crop).save(out / f'person-{pid}.jpg', quality=88)
            if fi >= max(want, default=-1):
                break
    for new, ti in enumerate(keep, 1):
        t = tracks[ti]
        people.append({'id': new, 'visible': round(t['seen'] / n, 3), 'area': round(t['area'] / max(1, t['seen']) / (h * w), 4),
                       'thumb': f'people/person-{new}.jpg', 'first_x': round(t['first_x'], 3)})
    info = {'count': len(people), 'frames': n, 'source': 'sam3-objects' if use_objects else 'tracked-silhouettes',
            'merged_frames': merged, 'people': people, 'mask_size': [w, h]}
    (folder / 'people.json').write_text(json.dumps(info, indent=2))
    status(f'Found {len(people)} people' + (f' · split them apart in {merged} frames where they touch' if merged else ''))
    return info


def people(folder, status=print):
    """Saved people, recomputed only when the masks are newer than the last split."""
    folder = Path(folder)
    p = folder / 'people.json'
    if p.exists():
        try:
            src = _mask_dir(folder)
        except ValueError:
            src = None
        newest = max((f.stat().st_mtime for f in src.glob('mask_*.png')), default=0) if src else 0
        if newest <= p.stat().st_mtime:
            return json.loads(p.read_text())
    return split_people(folder, status=status)


def fit_reference(ref, size, target):
    """Pad the reference to the video's shape with its own background colour.

    WanVaceToVideo centre-crops the reference to width x height, which would cut the arms off a
    3:4 character sheet on a 9:16 clip; padding keeps the whole character."""
    im = Image.open(ref).convert('RGB')
    a = np.asarray(im)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = tuple(int(v) for v in np.median(border, axis=0))
    W, H = size
    s = min(W / im.width, H / im.height)
    w, h = max(1, round(im.width * s)), max(1, round(im.height * s))
    canvas = Image.new('RGB', (W, H), bg)
    canvas.paste(im.resize((w, h), Image.Resampling.LANCZOS), ((W - w) // 2, (H - h) // 2))
    canvas.save(target)
    return Path(target)


# ---------------------------------------------------------------- the swap

def _grab(path, indices, size, nearest=False):
    want = {}
    for k, i in enumerate(indices):
        want.setdefault(i, []).append(k)
    out = [None] * len(indices)
    last = max(indices)
    for i, a in enumerate(_decode(path)):
        if i in want:
            r = _resize(a, size, nearest)
            for k in want[i]:
                out[k] = r
        if i >= last:
            break
    for k in range(len(out)):  # a short file: hold its last frame
        if out[k] is None:
            out[k] = out[k - 1] if k else np.zeros((size[1], size[0], 3), np.uint8)
    return out


def _labels(folder, indices, size):
    d = Path(folder) / 'people'
    out = []
    for i in indices:
        p = d / f'label_{i:04d}.png'
        out.append(_resize(np.asarray(Image.open(p)), size, nearest=True) if p.exists() else np.zeros((size[1], size[0]), np.uint8))
    return out


def _person_masks(labels, pid, r):
    """Grown mask for one person that never reaches into anyone else (their own pass repaints them)."""
    out = []
    for lab in labels:
        own = lab > 0 if pid == 'all' else lab == int(pid)
        others = (lab > 0) & ~own
        out.append(_grow(own, r) & ~others)
    return out


def _digest(*parts):
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, Path) and p.exists():
            h.update(p.read_bytes())
        else:
            h.update(repr(p).encode())
    return h.hexdigest()[:12]


def run(folder, refs, workflow='wan21-vace-swap.json', prompt='', seed=None, start=0.0, seconds=None,
        preset='custom', grow=0.03, status=print, queue=None, fetch=None):
    """Swap every person in `refs` ({1: 'me.png', 2: 'friend.png'} or {'all': 'me.png'}). Returns crew-final.mp4."""
    import comfy_bridge
    from mask_review import require_approved
    folder = Path(folder)
    require_approved(folder)  # same QA gate as every other render
    queue = queue or comfy_bridge.queue
    fetch = fetch or comfy_bridge.fetch_frames
    if not refs:
        raise ValueError('Attach at least one reference image.')
    found = people(folder, status)
    ids = {p['id'] for p in found['people']}
    for pid in refs:
        if pid != 'all' and int(pid) not in ids:
            raise ValueError(f'Person {pid} was not found in this clip (found {found["count"]}).')
    cfg = PRESETS.get(preset, PRESETS['custom'])
    prompt = (prompt or '').strip() or cfg['prompt']
    seed = int(seed) if seed not in (None, '') else int(time.time()) % (2 ** 31 - 1)
    src = folder / 'original.mp4'
    meta = _info(src)
    total, w, h = meta['frames'], meta['width'], meta['height']
    dur = total / SRC_FPS
    start = max(0.0, min(float(start or 0), max(0.0, dur - 0.5)))
    seconds = float(seconds or cfg['seconds'] or dur)
    end = min(dur, start + seconds)
    n = max(1, int(round((end - start) * GEN_FPS)))
    idx = [min(total - 1, int(round((start + k / GEN_FPS) * SRC_FPS))) for k in range(n)]
    W, H = gen_size(w, h)
    chunks = plan_chunks(n)
    work = folder / 'crew'
    work.mkdir(exist_ok=True)
    order = sorted(refs, key=lambda p: (p == 'all', str(p)))
    labels = _labels(folder, idx, (W, H))
    status(f'Crew swap · {len(order)} {"person" if len(order) == 1 else "people"} · {end - start:.1f}s window · '
           f'{len(chunks)} chunk{"s" if len(chunks) > 1 else ""} each at {W}x{H}, {GEN_FPS} fps · seed {seed}')
    orig = _grab(src, idx, (W, H))
    depth = [_gray(d) for d in _grab(folder / 'depth.mp4', idx, (W, H))]
    current = [a.copy() for a in orig]
    r = max(2, int(grow * max(W, H)))
    swapped = [np.zeros((H, W), np.float32) for _ in range(n)]
    progress = {'state': 'running', 'passes': len(order), 'chunks': len(chunks), 'done': 0, 'seed': seed,
                'window': [round(start, 2), round(end, 2)], 'size': [W, H]}
    renders = len(order) * len(chunks)
    for pi, pid in enumerate(order):
        ref = Path(refs[pid])
        fitted = fit_reference(ref, (W, H), work / f'ref-{pid}.png')
        masks = _person_masks(labels, pid, r)
        others = [(lab > 0) & ~(lab > 0 if pid == 'all' else lab == int(pid)) for lab in labels]
        out = [None] * n
        pdir = work / f'p{pid}'
        pdir.mkdir(exist_ok=True)
        for ci, (a, b) in enumerate(chunks):
            label = f'Person {pid} · chunk {ci + 1}/{len(chunks)} · '
            key = _digest(ref, workflow, prompt, seed, a, b, W, H, grow, pi, [refs[p] for p in order[:pi]],
                          *[folder / 'people' / f'label_{i:04d}.png' for i in idx[a:b]])
            cache = pdir / f'chunk{ci:02d}-{key}.mp4'
            if cache.exists():
                res = list(_decode(cache))
                status(label + 'reusing finished render')
            else:
                ctrl, msk = [], []
                for j in range(a, b):
                    if ci and j < a + OVERLAP:  # context from the previous chunk: keep as is
                        ctrl.append(out[j])
                        msk.append(np.zeros((H, W, 3), np.uint8))
                    else:
                        m = masks[j][..., None]
                        ctrl.append(np.where(m, depth[j], current[j]))
                        msk.append(np.repeat(m.astype(np.uint8) * 255, 3, axis=2))
                length = wan_length(b - a)
                ctrl += [ctrl[-1]] * (length - len(ctrl))
                msk += [msk[-1]] * (length - len(msk))
                cpath, mpath = pdir / f'chunk{ci:02d}-control.mp4', pdir / f'chunk{ci:02d}-mask.mp4'
                _write(cpath, ctrl, GEN_FPS)
                _write(mpath, msk, GEN_FPS)
                status(label + 'queued')
                job = queue(workflow, {'OF_REFERENCE': fitted, 'OF_CONTROL': cpath, 'OF_MASK': mpath}, prompt, seed,
                            frames=length, size=(W, H))
                res = fetch(job, status, label)
                if len(res) < b - a:
                    raise ValueError(f'{label}the workflow returned {len(res)} frames, expected {b - a}.')
                res = [_resize(x, (W, H)) for x in res[:b - a]]
                _write(cache, res, GEN_FPS)
            for j in range(a, b):
                x = res[j - a]
                if out[j] is not None:  # overlap: cross-fade into the new chunk
                    t = (j - a + 1) / (OVERLAP + 1)
                    x = (out[j].astype(np.float32) * (1 - t) + x.astype(np.float32) * t).astype(np.uint8)
                out[j] = x
            progress['done'] += 1
            progress['status'] = f'{progress["done"]}/{renders} renders done'
            (work / 'progress.json').write_text(json.dumps(progress))
        for j in range(n):  # keep this person's new look, leave everything else untouched
            alpha = _feather(masks[j], r) * ~others[j]
            current[j] = (current[j] * (1 - alpha[..., None]) + out[j] * alpha[..., None]).astype(np.uint8)
            swapped[j] = np.maximum(swapped[j], alpha)
    status('Pasting the new crew into the full-resolution original')
    final = _paste_back(folder, current, swapped, start, end, (w, h))
    progress.update(state='done', status='done', video=final.name)
    (work / 'progress.json').write_text(json.dumps(progress))
    status('Crew swap ready · original audio restored')
    return final


def _paste_back(folder, gen, alpha, start, end, size):
    import av
    import cv2
    w, h = size
    n = len(gen)
    i0, i1 = int(round(start * SRC_FPS)), int(round(end * SRC_FPS))
    silent = folder / 'crew-silent.mp4'
    with av.open(str(silent), 'w') as c:
        s = c.add_stream('libx264', rate=SRC_FPS)
        s.width, s.height, s.pix_fmt, s.options = w, h, 'yuv420p', {'crf': '16', 'preset': 'fast'}
        k = 0
        for i, rgb in enumerate(_decode(folder / 'original.mp4')):
            if i < i0:
                continue
            if i >= i1:
                break
            t = min(n - 1.0, max(0.0, (i / SRC_FPS - start) * GEN_FPS))
            k0 = int(t)
            k1, f = min(k0 + 1, n - 1), t - int(t)
            g = gen[k0].astype(np.float32) * (1 - f) + gen[k1].astype(np.float32) * f
            a = alpha[k0] * (1 - f) + alpha[k1] * f
            g = cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
            a = cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)[..., None]
            frame = np.clip(rgb * (1 - a) + g * a, 0, 255).astype(np.uint8)
            vf = av.VideoFrame.from_ndarray(frame, format='rgb24')
            vf.pts = k
            k += 1
            for p in s.encode(vf):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    final = folder / 'crew-final.mp4'
    audio = folder / 'upload.mp4' if (folder / 'upload.mp4').exists() else folder / 'original.mp4'
    _mux_audio(silent, audio, start, end - start, final)
    return final


def _mux_audio(video, audio_src, start, seconds, target):
    """Original audio for exactly the swapped window; copies the video stream untouched."""
    ff = shutil.which('ffmpeg')
    if ff:
        r = subprocess.run([ff, '-y', '-loglevel', 'error', '-i', str(video), '-ss', f'{start:.3f}', '-t', f'{seconds:.3f}',
                            '-i', str(audio_src), '-map', '0:v:0', '-map', '1:a:0?', '-c:v', 'copy', '-c:a', 'aac',
                            '-b:a', '192k', '-shortest', str(target)], capture_output=True, text=True)
        if r.returncode == 0:
            return target
    import av
    with av.open(str(video)) as v, av.open(str(audio_src)) as a, av.open(str(target), 'w') as out:
        vs = out.add_stream_from_template(v.streams.video[0])
        for p in v.demux(video=0):
            if p.dts is not None:
                p.stream = vs
                out.mux(p)
        if a.streams.audio:
            ain = a.streams.audio[0]
            aout = out.add_stream('aac', rate=ain.codec_context.sample_rate or 48000)
            for fr in a.decode(audio=0):
                t = float(fr.pts * fr.time_base) if fr.pts is not None else 0
                if t < start:
                    continue
                if t >= start + seconds:
                    break
                fr.pts = None
                for p in aout.encode(fr):
                    out.mux(p)
            for p in aout.encode():
                out.mux(p)
    return target


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='Swap each person in a prepared OpenField run with their own reference.')
    ap.add_argument('folder', help='the run folder (Documents/openfield/<job id>)')
    ap.add_argument('--people', action='store_true', help='just find and number the people')
    ap.add_argument('--ref', action='append', default=[], help='PERSON=image, e.g. 1=me.png (or all=me.png)')
    ap.add_argument('--preset', default='hotel-lobby', choices=sorted(PRESETS))
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--seconds', type=float, default=None)
    ap.add_argument('--workflow', default='wan21-vace-swap.json')
    ap.add_argument('--prompt', default='')
    ap.add_argument('--seed', default=None)
    args = ap.parse_args(argv)
    if args.people:
        print(json.dumps(split_people(args.folder), indent=2))
        return
    refs = {}
    for item in args.ref:
        k, _, v = item.partition('=')
        refs['all' if k == 'all' else int(k)] = v
    print(run(args.folder, refs, args.workflow, args.prompt, args.seed, args.start, args.seconds, args.preset))


if __name__ == '__main__':
    main()
