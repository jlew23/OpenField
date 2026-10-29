"""Jarvis at the helm: live station context, the action protocol, and the War Room board."""
import importlib.util, json, os, re, shutil, threading, time
from pathlib import Path

from . import db, llm, personas, academy, forge, lab, bible, rapquest, flow

_runs: Path | None = None
_sys_cache = {}

TONES = {
    'gentle': 'Tone dial: GENTLE. Keep the wit warm and light; encourage more than you tease.',
    'dry': 'Tone dial: DRY. Classic deadpan British sarcasm, polite and pointed.',
    'roast': 'Tone dial: ROAST. The user asked to be roasted: sharper sarcasm about their ideas (never their worth), still helpful.',
}

ACTION_RE = re.compile(r'```action\s*(\{.*?\})\s*```', re.S)


def set_runs(path):
    global _runs
    _runs = Path(path)


# ------------------------------------------------------------------ live state

def video_jobs(limit=8):
    if not _runs or not _runs.exists():
        return []
    jobs = []
    for d in _runs.iterdir():
        if d.is_dir() and len(d.name) == 32 and (d / 'status.json').exists():
            try:
                s = json.loads((d / 'status.json').read_text())
            except (ValueError, OSError):
                continue
            jobs.append({'id': d.name, 'state': s.get('state'), 'status': s.get('status'),
                         'updated': (d / 'status.json').stat().st_mtime,
                         'has_final': (d / 'final-preview.mp4').exists()})
    return sorted(jobs, key=lambda j: -j['updated'])[:limit]


def systems():
    """Cheap health checks (cached 30s); never spends tokens or money."""
    if _sys_cache.get('t', 0) > time.time() - 30:
        return _sys_cache['data']
    from config import setting
    def key_ok(name):
        v = setting(name).strip()
        return bool(v) and not any(x in v.lower() for x in ('your_key', 'your_api', 'replace_me', 'placeholder'))
    data = {
        'llm': llm.status(),
        'ffmpeg': bool(shutil.which('ffmpeg')),
        'rubberband': bool(shutil.which('rubberband')),
        'demucs': bool(shutil.which('demucs')),
        'torch': importlib.util.find_spec('torch') is not None,
        'cmudict': importlib.util.find_spec('pronouncing') is not None,
        'enhancor_key': key_ok('ENHANCOR_API_KEY'),
        'replicate_key': key_ok('REPLICATE_API_TOKEN'),
        'spotify': lab.spotify_config()['connected'],
        'bible': bible.source_path() is not None,
    }
    _sys_cache.update(t=time.time(), data=data)
    return data


def board():
    """Everything the War Room shows."""
    snap = academy.snapshot()
    return {
        'systems': systems(), 'db': db.stats(), 'jobs': video_jobs(), 'songs': db.list_songs()[:10],
        'remixes': db.list_remixes()[:10], 'events': db.events_after(0, 40), 'labs': lab.list_sessions(8),
        'academy': {k: snap[k] for k in ('xp', 'rank', 'level', 'rhythm', 'bars_written', 'submissions', 'radar', 'bosses_passed')},
        'forge': {k: v for k, v in forge.status().items() if k != 'trajectory'},
        'personas': [personas.public(p) for p in personas.all_personas()],
    }


def context_block():
    s = systems()
    snap = academy.snapshot()
    songs = db.list_songs()[:12]
    jobs = video_jobs(5)
    events = db.events_after(0, 8)
    lines = [
        f"LLM: {s['llm'].get('provider')} / {s['llm'].get('model') or '?'} ({'ok' if s['llm'].get('ok') else 'not reachable'})",
        f"Tools: ffmpeg {'yes' if s['ffmpeg'] else 'NO'}, rubberband {'yes' if s['rubberband'] else 'NO'}, demucs {'yes' if s['demucs'] else 'no'}, "
        f"GPU torch {'yes' if s['torch'] else 'no'}, Enhancor key {'set' if s['enhancor_key'] else 'missing'}, Spotify {'connected' if s['spotify'] else 'not connected'}, "
        f"Rap Bible {'loaded' if s['bible'] else 'NOT imported'}",
        f"Academy: rank {snap['rank']['name']} ({snap['xp']} XP), level {snap['level']}, "
        f"{snap['rhythm']['days_this_week']}/{snap['rhythm']['goal']} practice days this week, {snap['bars_written']} bars written, bosses passed {snap['bosses_passed'] or 'none'}",
        'Personas: ' + ', '.join(f"{p['id']} ({p.get('name')})" for p in personas.all_personas() if p['id'] != 'jarvis'),
        'Songs: ' + ('; '.join(f"#{x['id']} \"{x['title']}\" {x['bpm']:g} BPM, {x['remix_count']} remix(es)" for x in songs) or 'none yet'),
        'Video jobs: ' + ('; '.join(f"{j['id'][:8]} {j['state']}: {j['status']}" for j in jobs) or 'none'),
        'Recent events: ' + ('; '.join(e['message'] for e in events[-6:]) or 'quiet'),
    ]
    return 'LIVE STATION STATE\n' + '\n'.join('- ' + l for l in lines)


def system_prompt():
    p = personas.get('jarvis') or {}
    prof = academy.profile()
    title = prof.get('title') or llm.settings().get('user_title') or 'Sir'
    name = prof.get('name')
    extra = (f"The user's title: {title}.{' Their name: ' + name + '.' if name else ''}\n"
             f"{TONES.get(prof.get('jarvis_tone', 'dry'), TONES['dry'])}\n\n{context_block()}")
    return personas.system_prompt(p, extra=extra)


# ------------------------------------------------------------------ actions

def split_actions(text):
    actions = []
    for m in ACTION_RE.finditer(text):
        try:
            a = json.loads(m.group(1))
            if isinstance(a, dict) and a.get('do'):
                actions.append(a)
        except ValueError:
            continue
    return ACTION_RE.sub('', text).strip(), actions


NAV = {'rapquest': '/station/rapquest', 'academy': '/station/academy', 'warroom': '/station/warroom',
       'studio': '/', 'persona': '/station/persona', 'home': '/station'}


def execute(action):
    """Run one Jarvis action. Only safe, free or LLM-only actions are allowed."""
    kind = action.get('do')
    try:
        if kind == 'navigate':
            to = NAV.get(action.get('to'), '/station')
            ident = action.get('id')
            if action.get('to') == 'persona' and ident:
                to += '?id=' + str(ident)
            elif action.get('to') == 'rapquest' and ident:
                to += '?song=' + str(ident)
            return {'do': kind, 'ok': True, 'navigate': to, 'label': f'Open {action.get("to")}'}
        if kind == 'consult':
            pid = str(action.get('persona', ''))
            p = personas.get(pid)
            if not p or pid == 'jarvis':
                return {'do': kind, 'ok': False, 'label': f'No persona "{pid}"'}
            text = llm.complete([{'role': 'user', 'content': str(action.get('prompt', ''))[:2000]}], personas.system_prompt(p), max_tokens=900)
            forge.nudge_persona(pid, 0.1, 'consult')
            return {'do': kind, 'ok': True, 'persona': pid, 'name': p.get('name'), 'color': p.get('color'), 'text': text.strip(),
                    'label': f"{p.get('name')} answers"}
        if kind == 'fit':
            sid, bpm = int(action['song_id']), float(action['bpm'])
            cmp = rapquest.fit(sid, bpm)
            a, b = cmp['before']['summary'], cmp['after']['summary']
            return {'do': kind, 'ok': True, 'navigate': f'/station/rapquest?song={sid}&bpm={bpm:g}',
                    'label': f"Fit check @ {bpm:g} BPM ({cmp['feel']} feel)",
                    'text': f"{b['bars']} bars: {a['avg_sps']}/s before, {b['avg_sps']}/s after; {b['crowded']} crowded, {b['sparse']} sparse."}
        if kind == 'remix':
            sid, bpm = int(action['song_id']), float(action['bpm'])
            r = rapquest.remix(sid, str(action.get('persona', 'coach')), bpm, direction=str(action.get('direction', ''))[:500])
            forge.nudge_persona(str(action.get('persona')), 0.15, 'persona')
            return {'do': kind, 'ok': True, 'navigate': f"/station/rapquest?remix={r['id']}", 'label': f"Remix drafted: {r['title']}"}
        if kind == 'brief':
            b = board()
            s = b['systems']
            text = (f"LLM {'up' if s['llm']['ok'] else 'DOWN'} · {len(b['jobs'])} video job(s) · {b['db']['songs']} song(s), "
                    f"{b['db']['remixes']} remix(es) · Academy {b['academy']['rank']['name']} {b['academy']['xp']} XP · "
                    f"Forge {b['forge']['answered']}/{b['forge']['need_answers']} answers")
            return {'do': kind, 'ok': True, 'label': 'War Room brief', 'text': text, 'navigate': '/station/warroom'}
    except (KeyError, TypeError, ValueError) as e:
        return {'do': kind, 'ok': False, 'label': f'Bad action ({type(e).__name__})'}
    except llm.LLMError as e:
        return {'do': kind, 'ok': False, 'label': str(e)}
    return {'do': kind, 'ok': False, 'label': f'Unknown action "{kind}"'}
