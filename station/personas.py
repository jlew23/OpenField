"""Persona registry. Built-ins are markdown files in station/personas/, custom ones live in the DB.

File format: a small front-matter block, then the system prompt body.

    ---
    id: biggie
    name: The Pragmatic Don
    pocket: 3.2-5.5
    mechanics: [Hyper-specific detail, Calm over chaos]
    ---
    You are ...
"""
import re
from pathlib import Path

from . import db

ROOT = Path(__file__).resolve().parent / 'personas'
_cache = {}


def _parse_value(v):
    v = v.strip()
    if v.startswith('[') and v.endswith(']'):
        items, depth, cur = [], 0, ''
        for ch in v[1:-1]:
            depth += ch == '('
            depth -= ch == ')'
            if ch == ',' and depth == 0:
                items.append(cur)
                cur = ''
            else:
                cur += ch
        items.append(cur)
        return [x.strip().strip('"\'') for x in items if x.strip()]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if re.fullmatch(r'-?\d+(\.\d+)?', v):
        return float(v) if '.' in v else int(v)
    if v.lower() in ('true', 'false'):
        return v.lower() == 'true'
    return v


def parse_file(text):
    meta, body = {}, text
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.S)
    if m:
        body = m.group(2)
        key = None
        for line in m.group(1).splitlines():
            if not line.strip():
                continue
            if line.lstrip().startswith('- ') and key:
                meta.setdefault(key, [])
                if not isinstance(meta[key], list):
                    meta[key] = [meta[key]] if meta[key] else []
                meta[key].append(_parse_value(line.strip()[2:]))
                continue
            k, sep, v = line.partition(':')
            if sep:
                key = k.strip()
                meta[key] = _parse_value(v) if v.strip() else []
    meta['prompt'] = body.strip()
    if isinstance(meta.get('pocket'), str) and '-' in meta['pocket']:
        lo, hi = meta['pocket'].split('-', 1)
        meta['pocket'] = [float(lo), float(hi)]
    return meta


def _builtins():
    files = sorted(ROOT.glob('*.md'))
    stamp = tuple((f.name, f.stat().st_mtime) for f in files)
    if _cache.get('stamp') != stamp:
        out = {}
        for f in files:
            if f.name.startswith('_'):
                continue
            p = parse_file(f.read_text(encoding='utf-8'))
            p.setdefault('id', f.stem)
            p['builtin'] = True
            out[p['id']] = p
        _cache.update(stamp=stamp, personas=out)
    return _cache['personas']


def doctrine():
    f = ROOT / '_doctrine.md'
    return f.read_text(encoding='utf-8').strip() if f.exists() else ''


def all_personas():
    out = dict(_builtins())
    for p in db.list_custom_personas():
        if p.get('id'):
            p['builtin'] = False
            out[p['id']] = {**out.get(p['id'], {}), **p}
    return sorted(out.values(), key=lambda p: (p.get('order', 50), p.get('name', '')))


def get(pid):
    for p in all_personas():
        if p['id'] == pid:
            return p
    return None


def public(p):
    keys = ('id', 'name', 'artist', 'handle', 'role', 'color', 'accent', 'tagline', 'voice', 'pocket', 'mechanics',
            'drills', 'signature', 'unlock', 'order', 'builtin', 'glyph', 'greeting')
    return {k: p.get(k) for k in keys if k in p}


def system_prompt(p, extra=''):
    parts = [p.get('prompt', '')]
    if p.get('uses_doctrine'):
        parts.append(doctrine())
    parts.append('Never quote or reproduce lyrics from real recorded songs. Write originals only.')
    if extra:
        parts.append(extra)
    return '\n\n'.join(x for x in parts if x)


def pocket(p):
    pk = (p or {}).get('pocket')
    if isinstance(pk, list) and len(pk) == 2:
        return float(pk[0]), float(pk[1])
    return 2.5, 8.0
