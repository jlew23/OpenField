"""RapQuest: songs, beats and persona remixes that land on the new beat."""
import shutil, uuid
from pathlib import Path

from . import db, flow, llm, lyrics, personas, beat

_beats_dir: Path | None = None
AUDIO_EXT = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.webm', '.mp4'}


def set_beats_dir(path):
    global _beats_dir
    _beats_dir = Path(path)
    _beats_dir.mkdir(parents=True, exist_ok=True)


def beat_path(name):
    if not _beats_dir or not name or '/' in name or '\\' in name or name.startswith('.'):
        return None
    p = _beats_dir / name
    return p if p.exists() else None


def save_beat(upload_file, filename, hint_bpm=None):
    ext = Path(filename or '').suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError('Upload an audio file (wav, mp3, m4a, flac, ogg).')
    name = uuid.uuid4().hex + ext
    with (_beats_dir / name).open('wb') as out:
        shutil.copyfileobj(upload_file, out)
    try:
        analysis = beat.analyze(_beats_dir / name, hint_bpm=hint_bpm)
    except Exception as e:  # keep the file, report the analysis problem
        analysis = {'error': f'Could not analyse audio: {type(e).__name__}'}
    return name, analysis


def create_song(title, text, bpm=None, notes=''):
    hint = lyrics.tempo_hint(text)
    sid = db.create_song({'title': title or 'Untitled', 'lyrics': text, 'bpm': float(bpm or hint or 90), 'notes': notes})
    db.log_event('rapquest', 'song', f'New song: {title}', {'id': sid})
    return sid


def song_view(sid, bpm=None, feel='normal', persona_id=None):
    s = db.get_song(sid)
    if not s:
        return None
    p = personas.get(persona_id) if persona_id else None
    s['analysis'] = flow.analyze(s['lyrics'], bpm or s['bpm'], s['beats_per_bar'], feel, personas.pocket(p) if p else None)
    s['remixes'] = db.list_remixes(sid)
    return s


def fit(sid, bpm, feel=None, persona_id=None):
    s = db.get_song(sid)
    if not s:
        raise ValueError('Song not found')
    p = personas.get(persona_id) if persona_id else None
    return flow.compare(s['lyrics'], s['bpm'], bpm, s['beats_per_bar'], feel, personas.pocket(p) if p else None)


def remix(sid, persona_id, bpm, feel=None, direction='', beat_file='', beat_analysis=None):
    """Ask a persona to rewrite the song so it lands on the new beat."""
    s = db.get_song(sid)
    p = personas.get(persona_id)
    if not s or not p:
        raise ValueError('Song or persona not found')
    pocket = personas.pocket(p)
    cmp = flow.compare(s['lyrics'], s['bpm'], bpm, s['beats_per_bar'], feel, pocket)
    feel = cmp['feel']
    sec = cmp['after']['seconds_per_bar']
    lo, hi = pocket
    budget = flow.budget_sheet(cmp['after'])
    system = personas.system_prompt(p, extra='You are remixing a song for a new beat in the RapQuest flow lab.')
    user = (
        f"Original song \"{s['title']}\" was written at {s['bpm']:g} BPM. The new beat is {bpm:g} BPM"
        f"{' in a half-time feel' if feel == 'half' else ' in double-time' if feel == 'double' else ''}, so each bar lasts {sec:.2f}s. "
        f"Your pocket is {lo:g}-{hi:g} syllables per second, which means about {round(lo * sec)}-{round(hi * sec)} syllables per bar.\n\n"
        f"Here is the original, bar by bar, with how each one lands on the new beat:\n{budget}\n\n"
        f"{('Direction from the artist: ' + direction) if direction else ''}\n\n"
        "Rewrite it as YOUR remix:\n"
        "- Same number of bars, same order of story beats, same speakers.\n"
        "- Hit each bar's syllable target for the new tempo; fix every CROWDED or SPARSE bar.\n"
        "- Re-rhyme on vowel chains in your style; keep an end rhyme per couplet and add internals where your pocket allows.\n"
        "- Original words: do not copy lines verbatim (titles and hook ideas may stay).\n"
        "Output ONLY the lyric sheet: section headings as '### Name', speaker lines as '**NAME:**', one bar per line.")
    text = llm.complete([{'role': 'user', 'content': user}], system, temperature=0.85, max_tokens=4000).strip()
    text = text.strip('`').replace('```markdown', '').replace('```', '').strip()
    rid = db.create_remix(sid, {'persona_id': persona_id, 'title': f"{s['title']} ({p.get('handle') or p['name']} remix)",
                                'bpm': float(bpm), 'feel': feel, 'lyrics': text, 'direction': direction,
                                'beat_file': beat_file, 'beat_analysis': beat_analysis or {}, 'status': 'draft'})
    db.log_event('rapquest', 'remix', f"Remix drafted: {s['title']} by {p.get('name')} @ {bpm:g} BPM", {'id': rid, 'song': sid})
    return remix_view(rid)


def remix_view(rid):
    r = db.get_remix(rid)
    if not r:
        return None
    s = db.get_song(r['song_id'])
    p = personas.get(r['persona_id'])
    r['comparison'] = flow.compare(s['lyrics'], s['bpm'], r['bpm'], s['beats_per_bar'], r['feel'],
                                   personas.pocket(p) if p else None, new_text=r['lyrics'])
    r['song'] = {k: s[k] for k in ('id', 'title', 'bpm', 'beat_file', 'beat_analysis')}
    return r
