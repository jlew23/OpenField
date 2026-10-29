"""FastAPI routes for OpenField Station."""
import json, time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, StreamingResponse

from . import (academy, beat, bible, cypher, db, flow, forge, grading, jarvis, lab, llm, lyrics,
               personas, rapquest)

router = APIRouter()
STATIC = Path(__file__).resolve().parent.parent / 'static' / 'station'
PAGES = {'': 'index.html', 'rapquest': 'rapquest.html', 'academy': 'academy.html', 'persona': 'persona.html',
         'warroom': 'warroom.html'}


def init(runs_root):
    root = Path(runs_root) / 'station'
    root.mkdir(parents=True, exist_ok=True)
    db.init(root / 'station.db')
    academy.init()
    forge.init()
    lab.init()
    bible.set_data_dir(root / 'knowledge')
    rapquest.set_beats_dir(root / 'beats')
    jarvis.set_runs(runs_root)


def _err(e, code=400):
    raise HTTPException(code, str(e))


def sse(event, data):
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'


# ------------------------------------------------------------------ pages

@router.get('/station')
@router.get('/station/{page}')
def station_page(page: str = ''):
    name = PAGES.get(page)
    if not name:
        raise HTTPException(404)
    return FileResponse(STATIC / name)


# ------------------------------------------------------------------ llm settings

@router.get('/api/llm/settings')
def llm_settings():
    return llm.public_settings()


@router.put('/api/llm/settings')
def llm_update(body: dict = Body(...)):
    try:
        out = llm.update_settings(body)
    except (llm.LLMError, ValueError, TypeError) as e:
        _err(e)
    jarvis._sys_cache.clear()
    return out


@router.get('/api/llm/models')
def llm_models():
    try:
        return {'models': llm.list_models()}
    except llm.LLMError as e:
        _err(e, 502)


@router.get('/api/llm/status')
def llm_status():
    return llm.status()


@router.post('/api/llm/test')
def llm_test():
    try:
        t0 = time.time()
        text = llm.complete([{'role': 'user', 'content': 'Reply with exactly: Systems nominal.'}],
                            'You are a connection test. Follow the instruction exactly.', max_tokens=20)
        return {'ok': True, 'reply': text.strip()[:200], 'seconds': round(time.time() - t0, 2)}
    except llm.LLMError as e:
        return {'ok': False, 'error': str(e)}


# ------------------------------------------------------------------ personas

@router.get('/api/personas')
def list_personas():
    return [personas.public(p) for p in personas.all_personas()]


@router.get('/api/personas/{pid}')
def get_persona(pid: str):
    p = personas.get(pid)
    if not p:
        raise HTTPException(404)
    out = personas.public(p)
    out['prompt'] = p.get('prompt', '')
    out['forged'] = p.get('forged')
    return out


@router.put('/api/personas/{pid}')
def save_persona(pid: str, body: dict = Body(...)):
    if pid == 'jarvis' and 'prompt' in body and not body.get('prompt', '').strip():
        _err('Jarvis needs a prompt.')
    keep = ('name', 'handle', 'role', 'color', 'accent', 'tagline', 'voice', 'pocket', 'mechanics', 'drills', 'prompt',
            'uses_doctrine', 'greeting', 'glyph', 'artist', 'signature')
    existing = {k: v for k, v in (personas.get(pid) or {}).items() if k in keep or k == 'forged'}
    data = {**existing, **{k: v for k, v in body.items() if k in keep}, 'id': pid}
    db.save_custom_persona(pid, data)
    return personas.public(personas.get(pid))


@router.delete('/api/personas/{pid}')
def delete_persona(pid: str):
    db.delete_custom_persona(pid)
    return {'ok': True, 'restored_builtin': personas.get(pid) is not None}


# ------------------------------------------------------------------ chat (SSE)

def _history(cid):
    out = []
    for m in db.get_messages(cid, 40):
        if m['role'] == 'action':
            out.append({'role': 'user', 'content': '[Station result] ' + m['content']})
        else:
            out.append({'role': m['role'], 'content': m['content']})
    return out


@router.post('/api/chat')
def chat(body: dict = Body(...)):
    pid = body.get('persona_id') or 'jarvis'
    p = personas.get(pid)
    if not p:
        raise HTTPException(404, 'Unknown persona')
    message = (body.get('message') or '').strip()
    if not message:
        raise HTTPException(400, 'Empty message')
    ephemeral = bool(body.get('ephemeral'))
    cid = body.get('conversation_id')
    if not ephemeral:
        if not cid or not db.get_conversation(cid):
            cid = db.create_conversation(pid)
        history = _history(cid)
        db.add_message(cid, 'user', message)
    else:
        history = [m for m in (body.get('history') or []) if m.get('role') in ('user', 'assistant')][-12:]
    messages = history + [{'role': 'user', 'content': message}]

    ctx = body.get('context') or {}
    if pid == 'jarvis':
        system = jarvis.system_prompt()
    else:
        extra = ''
        if ctx.get('chapter_id'):
            data = bible.load()
            ch = bible.find_chapter(data, ctx['chapter_id']) if data else None
            if ch:
                extra += f"The student is reading {ch['title']}. That chapter of their manual:\n{ch['body'][:6000]}"
        if ctx.get('song_id'):
            s = db.get_song(int(ctx['song_id']))
            if s:
                extra += f"\nThe student is working on the song \"{s['title']}\" ({s['bpm']:g} BPM):\n{s['lyrics'][:4000]}"
        system = personas.system_prompt(p, extra=extra)

    def gen():
        yield sse('meta', {'conversation_id': cid, 'persona': pid})
        full = []
        try:
            for chunk in llm.stream_chat(messages, system):
                full.append(chunk)
                yield sse('delta', {'text': chunk})
        except llm.LLMError as e:
            yield sse('error', {'message': str(e)})
            return
        except Exception as e:  # network hiccups mid-stream
            yield sse('error', {'message': f'Stream interrupted ({type(e).__name__}).'})
            return
        text = ''.join(full)
        if pid == 'jarvis':
            shown, actions = jarvis.split_actions(text)
            if not ephemeral:
                db.add_message(cid, 'assistant', shown)
            yield sse('replace', {'text': shown})
            for a in actions[:4]:
                yield sse('action_start', {'do': a.get('do')})
                result = jarvis.execute(a)
                if not ephemeral:
                    db.add_message(cid, 'action', json.dumps({k: v for k, v in result.items() if k != 'navigate'})[:3000], result)
                db.log_event('jarvis', 'action', result.get('label', a.get('do')))
                yield sse('action', result)
        else:
            if not ephemeral:
                db.add_message(cid, 'assistant', text)
            if p.get('role') == 'rapper':
                forge.nudge_persona(pid, 0.05, 'persona')
        yield sse('done', {'conversation_id': cid})

    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.get('/api/conversations')
def conversations(persona: str = ''):
    return db.list_conversations(persona or None)


@router.get('/api/conversations/{cid}')
def conversation(cid: int):
    c = db.get_conversation(cid)
    if not c:
        raise HTTPException(404)
    c['messages'] = db.get_messages(cid)
    return c


@router.delete('/api/conversations/{cid}')
def delete_conversation(cid: int):
    db.delete_conversation(cid)
    return {'ok': True}


# ------------------------------------------------------------------ flow lab & songs

@router.post('/api/flow/analyze')
def analyze(body: dict = Body(...)):
    p = personas.get(body.get('persona') or '')
    return flow.analyze(body.get('text', ''), float(body.get('bpm') or 90), int(body.get('beats_per_bar') or 4),
                        body.get('feel') or 'normal', personas.pocket(p) if p else None)


@router.get('/api/songs')
def songs():
    return db.list_songs()


@router.post('/api/songs')
def new_song(body: dict = Body(...)):
    text = body.get('lyrics', '')
    if not lyrics.bars(text):
        _err('Paste some lyrics first (one bar per line).')
    sid = rapquest.create_song(body.get('title', '').strip() or 'Untitled', text, body.get('bpm'), body.get('notes', ''))
    return rapquest.song_view(sid)


@router.get('/api/songs/{sid}')
def song(sid: int, bpm: float = 0, feel: str = 'normal', persona: str = ''):
    s = rapquest.song_view(sid, bpm or None, feel, persona or None)
    if not s:
        raise HTTPException(404)
    return s


@router.put('/api/songs/{sid}')
def update_song(sid: int, body: dict = Body(...)):
    if not db.get_song(sid):
        raise HTTPException(404)
    db.update_song(sid, {k: body[k] for k in ('title', 'bpm', 'lyrics', 'notes', 'beats_per_bar', 'song_key', 'beat_analysis') if k in body})
    return rapquest.song_view(sid)


@router.delete('/api/songs/{sid}')
def delete_song(sid: int):
    db.delete_song(sid)
    return {'ok': True}


@router.post('/api/songs/{sid}/beat')
def song_beat(sid: int, audio: UploadFile = File(...)):
    s = db.get_song(sid)
    if not s:
        raise HTTPException(404)
    try:
        name, analysis = rapquest.save_beat(audio.file, audio.filename, hint_bpm=s['bpm'])
    except ValueError as e:
        _err(e)
    db.update_song(sid, {'beat_file': name, 'beat_analysis': analysis})
    return {'beat_file': name, 'analysis': analysis}


@router.post('/api/beats')
def upload_beat(audio: UploadFile = File(...), hint_bpm: float = Form(0)):
    try:
        name, analysis = rapquest.save_beat(audio.file, audio.filename, hint_bpm=hint_bpm or None)
    except ValueError as e:
        _err(e)
    return {'beat_file': name, 'analysis': analysis}


@router.get('/api/beats/{name}')
def get_beat(name: str):
    p = rapquest.beat_path(name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


@router.get('/api/songs/{sid}/fit')
def song_fit(sid: int, bpm: float, feel: str = '', persona: str = ''):
    try:
        return rapquest.fit(sid, bpm, feel or None, persona or None)
    except ValueError as e:
        _err(e, 404)


@router.post('/api/songs/{sid}/remix')
def song_remix(sid: int, body: dict = Body(...)):
    pid = body.get('persona') or 'coach'
    try:
        bpm = float(body.get('bpm') or 0)
        if not 40 <= bpm <= 220:
            raise ValueError('Set the new BPM (40-220).')
        r = rapquest.remix(sid, pid, bpm, body.get('feel') or None, body.get('direction', '')[:800],
                           body.get('beat_file', ''), body.get('beat_analysis'))
    except (ValueError, llm.LLMError) as e:
        _err(e)
    forge.nudge_persona(pid, 0.15, 'persona')
    return r


@router.post('/api/songs/{sid}/comp')
def song_comp(sid: int, body: dict = Body(...)):
    """Save a comp (best take per bar, REAPER-style) as a new version of the song."""
    s = db.get_song(sid)
    if not s:
        raise HTTPException(404)
    text = body.get('lyrics', '').strip()
    if not lyrics.bars(text):
        _err('The comp is empty.')
    rid = db.create_remix(sid, {'persona_id': body.get('persona') or 'comp', 'title': body.get('title') or f"{s['title']} (comp)",
                                'bpm': float(body.get('bpm') or s['bpm']), 'feel': body.get('feel') or 'normal', 'lyrics': text,
                                'beat_file': body.get('beat_file', ''), 'beat_analysis': body.get('beat_analysis') or {}, 'status': 'comp'})
    db.log_event('rapquest', 'comp', f"Comp saved: {s['title']}", {'id': rid})
    return rapquest.remix_view(rid)


@router.post('/api/pocket')
def pocket_trainer(audio: UploadFile = File(...), bpm: float = Form(...), offset: float = Form(0), latency_ms: float = Form(0)):
    """Bible drill 5.2: are you ahead of, behind, or dead on the beat?"""
    import tempfile, os
    suffix = Path(audio.filename or 'take.webm').suffix or '.webm'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio.file.read())
        path = tmp.name
    try:
        res = beat.pocket(path, bpm, offset, latency_ms)
    except Exception as e:
        _err(f'Could not read the take ({type(e).__name__}). Is ffmpeg installed?')
    finally:
        os.unlink(path)
    if res.get('ok'):
        res['events'] = academy.record_activity('pocket', xp=15 + round(25 * res['tight']), label=f"Pocket take: {res['verdict']}")
        forge.nudge('pocket', res['verdict'], {'pocket': 0.1 if res['mean_ms'] < -12 else -0.1 if res['mean_ms'] > 12 else 0,
                                               'temper': 0.05 if res['spread_ms'] > 35 else -0.05})
    return res


@router.get('/api/remixes/{rid}')
def get_remix(rid: int):
    r = rapquest.remix_view(rid)
    if not r:
        raise HTTPException(404)
    return r


@router.put('/api/remixes/{rid}')
def update_remix(rid: int, body: dict = Body(...)):
    if not db.get_remix(rid):
        raise HTTPException(404)
    db.update_remix(rid, {k: body[k] for k in ('lyrics', 'status', 'title', 'bpm', 'feel', 'beat_file', 'beat_analysis') if k in body})
    return rapquest.remix_view(rid)


@router.delete('/api/remixes/{rid}')
def delete_remix(rid: int):
    db.delete_remix(rid)
    return {'ok': True}


# ------------------------------------------------------------------ academy

@router.get('/api/academy')
def academy_home():
    data = bible.load()
    snap = academy.snapshot()
    snap['curriculum'] = bible.outline(data) if data else None
    snap['reviews_due'] = len(academy.reviews_due(20))
    snap['forge'] = {k: v for k, v in forge.status().items() if k != 'trajectory'}
    return snap


@router.post('/api/academy/checkin')
def academy_checkin():
    return {'events': academy.checkin(), 'session': academy.session_plan()}


@router.put('/api/academy/profile')
def academy_profile(body: dict = Body(...)):
    before = academy.profile()
    p = academy.update_profile(body)
    if p['jarvis_tone'] != before['jarvis_tone']:
        forge.nudge('setting', f"jarvis tone {p['jarvis_tone']}",
                    {'roast': {'tone': -0.2, 'temper': 0.1}, 'gentle': {'temper': -0.1}, 'dry': {'texture': 0.05}}[p['jarvis_tone']])
    return p


@router.post('/api/academy/bible')
def upload_bible(file: UploadFile = File(...)):
    text = file.file.read().decode('utf-8', 'replace')
    data = bible.parse(text)
    if not data['levels']:
        _err('That does not look like the Rap Writing Bible (no "LEVEL" sections found). Upload the markdown version.')
    bible.save_source(text)
    db.log_event('academy', 'bible', f"Rap Bible imported: {len(bible.chapters(data))} chapters")
    return {'ok': True, 'levels': len(data['levels']), 'chapters': len(bible.chapters(data))}


def _require_bible():
    data = bible.load()
    if not data:
        raise HTTPException(409, 'Import your Rap Writing Bible first.')
    return data


@router.get('/api/academy/chapter/{cid}')
def academy_chapter(cid: str):
    data = _require_bible()
    ch = bible.find_chapter(data, cid)
    if not ch:
        raise HTTPException(404)
    states, stars = academy.chapter_states(data)
    best = academy.best_by_ref()
    out = {**ch, 'drills': [academy.tuned_drill(d) | {'best': best.get(d['id'])} for d in ch['drills']],
           'state': states.get(cid), 'stars': stars.get(cid, 0),
           'question': forge.question_for_page('chapter:' + cid)}
    lvl = next(l for l in data['levels'] if l['level'] == ch['level'])
    out['level_name'] = lvl['name']
    out['matrix'] = data['matrix'] if ch['number'] in ('6', '11') else []
    out['word_bank'] = data['word_bank'] if ch['number'] == '11' else []
    out['idioms'] = data['idioms'] if ch['number'] == '13' else None
    out['homophones'] = data['homophones'][:40] if ch['number'] == '12' else []
    out['meanings'] = data['meanings'] if ch['number'] == '12' else []
    return out


@router.post('/api/academy/chapter/{cid}/read')
def academy_read(cid: str):
    return {'events': academy.mark_read(cid)}


@router.get('/api/academy/boss/{level}')
def academy_boss(level: int):
    data = _require_bible()
    lvl = next((l for l in data['levels'] if l['level'] == level), None)
    if not lvl or not lvl['test']:
        raise HTTPException(404)
    return {**lvl['test'], 'level': level, 'level_name': lvl['name'], 'goal': lvl['goal'],
            'best': academy.best_by_ref().get(f'boss-{level}'), 'question': forge.question_for_page(f'boss:{level}')}


def _grade_one(form, content, target_bars, scheme, chapter, drill_text, use_coach, pocket=None):
    auto = grading.auto_grade(form, content, target_bars, scheme, pocket)
    coach = None
    if use_coach and form not in ('check',):
        try:
            coach = grading.coach_review(chapter, drill_text, form, content, auto)
        except llm.LLMError as e:
            coach = {'summary': f'Coach unavailable: {e}', 'overall': None, 'error': True}
    return auto, coach


def _light_analysis(analysis):
    if not analysis:
        return None
    return {'bars': [{'index': b['index'], 'text': b['text'], 'count': b['count'], 'sps': b['sps'], 'zone': b['zone'],
                      'verdict': b['verdict'], 'syllables': [{k: s.get(k) for k in ('text', 'vowel', 'stress', 'rhyme', 'step', 'start')}
                                                             for s in b['syllables']]} for b in analysis['bars']],
            'families': analysis['families'], 'summary': analysis['summary'], 'steps': analysis['steps']}


@router.post('/api/academy/submit')
def academy_submit(body: dict = Body(...)):
    data = _require_bible()
    ref = body.get('ref', '')
    use_coach = bool(body.get('coach', True))
    prof = academy.profile()
    rank = academy.rank_for(academy.total_xp())['name']
    if ref.startswith('boss-'):
        level = int(ref.split('-')[1])
        lvl = next((l for l in data['levels'] if l['level'] == level), None)
        if not lvl or not lvl['test']:
            raise HTTPException(404)
        parts = body.get('parts') or {}
        part_results, scores = [], []
        for part in lvl['test']['parts']:
            content = parts.get(part['id']) or {}
            form = part['form'] if part['form'] not in ('text', 'check') else 'reflection'
            auto, coach = _grade_one(form, content, part['bars'], part['scheme'], {'title': lvl['test']['title'], 'body': ''},
                                     part['text'], use_coach and form not in ('reflection',))
            g = grading.combine(auto, coach)
            scores.append(g['score'])
            part_results.append({'part': part['id'], 'text': part['text'], 'grade': g, 'criteria': auto['criteria'],
                                 'coach': coach, 'analysis': _light_analysis(auto.get('analysis')), 'facts': auto['facts']})
        total = round(sum(scores) / max(len(scores), 1))
        passed = total >= 75 and all(s >= 60 for s in scores)
        grade = {'score': total, 'letter': grading.letter(total), 'passed': passed}
        auto_all = {'score': total, 'criteria': [c for pr in part_results for c in pr['criteria']],
                    'facts': {'bars': sum(pr['facts'].get('bars', 0) for pr in part_results), 'parts': len(part_results)}}
        meta = {'title': lvl['test']['title'], 'student': prof['name'] or 'Student', 'rank': rank,
                'chapter_title': f"Level {level}: {lvl['name']}", 'drill_text': lvl['goal'], 'created_at': time.time()}

        def report_fn(events):
            chunks = [grading.report_markdown({**meta, 'title': f"{lvl['test']['title']} · {pr['text'][:60]}"},
                                              parts.get(pr['part']) or {}, {'criteria': pr['criteria'], 'facts': pr['facts'],
                                                                            'analysis': None}, pr['coach'], pr['grade'])
                      for pr in part_results]
            head = f"# {lvl['test']['title']}\n\n## Overall: {grade['letter']} ({total}/100) · {'PASSED' if passed else 'RETRY'}\n\n"
            return head + '\n\n---\n\n'.join(chunks) + '\n\n## Rewards\n\n' + '\n'.join(f"- {e['label']}" for e in events if e.get('label'))
        sid, events = academy.record_submission(ref, 'boss', 'boss', {'parts': parts}, auto_all, None, grade, report_fn)
        return {'submission_id': sid, 'grade': grade, 'parts': part_results, 'events': events}

    ch, drill = bible.find_drill(data, ref)
    if not drill:
        raise HTTPException(404, 'Unknown drill')
    drill = academy.tuned_drill(drill)
    content = body.get('content') or {}
    if drill['form'] == 'vowel':
        content.setdefault('goal', drill.get('goal', 15))
    states, _ = academy.chapter_states(data)
    peek = states.get(ch['id']) == 'peek'
    auto, coach = _grade_one(drill['form'], content, drill['bars'], drill['scheme'], ch, drill['text'], use_coach)
    grade = grading.combine(auto, coach)
    meta = {'title': f"Drill {drill['number']}", 'student': prof['name'] or 'Student', 'rank': rank,
            'chapter_title': f"Chapter {ch['number']}: {ch['title']}", 'drill_text': drill['text'], 'created_at': time.time()}
    sid, events = academy.record_submission(
        ref, 'drill', drill['form'], content, auto, coach, grade, peek=peek,
        report_fn=lambda ev: grading.report_markdown(meta, content, auto, coach, grade, ev))
    forge.nudge_from_analysis(auto.get('analysis'), 'drill')
    if peek:
        forge.nudge('choice', f"peeked {ch['id']}", {'imagery': 0.05, 'temper': 0.03})
    return {'submission_id': sid, 'grade': grade, 'criteria': auto['criteria'], 'facts': auto['facts'],
            'analysis': _light_analysis(auto.get('analysis')), 'coach': coach, 'events': events, 'peek': peek}


@router.get('/api/academy/submission/{sid}')
def academy_submission(sid: int):
    s = academy.submission(sid)
    if not s:
        raise HTTPException(404)
    return s


@router.get('/api/academy/report/{sid}.md')
def academy_report(sid: int):
    s = academy.submission(sid)
    if not s:
        raise HTTPException(404)
    return PlainTextResponse(s['report'] or '# Report not available', media_type='text/markdown',
                             headers={'Content-Disposition': f'attachment; filename="report-card-{sid}.md"'})


@router.get('/api/academy/history')
def academy_history(ref: str = ''):
    return academy.history(ref or None)


@router.post('/api/academy/rung')
def academy_rung(body: dict = Body(...)):
    return {'events': academy.confirm_rung(int(body.get('rung', 0)))}


@router.post('/api/academy/placement')
def academy_placement(body: dict = Body(...)):
    return academy.set_placement(int(body.get('level', 1)))


@router.get('/api/academy/session')
def academy_session(minutes: int = 0):
    return academy.session_plan(minutes or None)


@router.get('/api/academy/reviews')
def academy_reviews():
    return [q for q in (academy.review_question(r['item']) for r in academy.reviews_due(5)) if q]


@router.post('/api/academy/reviews/{item}')
def academy_review_answer(item: str, body: dict = Body(...)):
    return academy.answer_review(item, body.get('choice', ''))


@router.post('/api/academy/sandbox')
def academy_sandbox(body: dict = Body(...)):
    """Rhyme Lab: ungraded vowel stripping. Verified finds pay a little XP and reveal patterns."""
    phrase = (body.get('phrase') or '').strip()
    cands = [c.strip() for c in body.get('candidates', []) if c.strip()][:40]
    syl = flow.syllabify_line(phrase)
    scored = [{'text': c, 'score': round(grading.vowel_match(phrase, c), 2)} for c in cands]
    verified = [s for s in scored if s['score'] >= 0.75]
    data = bible.load() or {}
    pid = academy.card_for_phrase(phrase) if phrase else None
    pat = next((p for p in data.get('matrix', []) if p['id'] == pid), None)
    events = []
    if verified and body.get('commit'):
        events = academy.record_activity('sandbox', xp=academy.XP['sandbox'] * len(verified), stat='sandbox',
                                         stat_n=len(verified), label=f'Rhyme Lab: {len(verified)} verified')
        if pid:
            academy.collect_card(pid, events, uses=1)
    return {'phrase': phrase, 'vowels': [{'text': s['text'], 'vowel': s['vowel'], 'stress': s['stress']} for s in syl],
            'scored': scored, 'verified': len(verified), 'pattern': pat, 'events': events}


@router.get('/api/academy/prompt')
def academy_prompt(pattern: str = ''):
    if not pattern:
        snap = academy.snapshot()
        weak = [m for m in snap['matrix'] if m['tier'] in ('hidden', 'revealed')]
        pattern = weak[0]['id'] if weak else ''
    return cypher.prompt_word(pattern or None)


# ------------------------------------------------------------------ forge

@router.get('/api/forge')
def forge_status():
    st = forge.status()
    st['preview'] = db.get_setting('forge_preview', None)
    return st


@router.get('/api/forge/question')
def forge_question(page: str):
    return {'question': forge.question_for_page(page[:80])}


@router.post('/api/forge/answer')
def forge_answer(body: dict = Body(...)):
    try:
        st = forge.answer(body.get('qid', ''), body.get('text', ''), body.get('chip', ''))
    except ValueError as e:
        _err(e)
    events = []
    if st['answered'] >= 25:
        academy.unlock('open_book', events)
    if st['answered'] == forge.PREVIEW_ANSWERS:
        events.append({'type': 'unlock', 'label': '🔮 Forge preview unlocked: your first stage-name read is ready'})
    return {'status': {k: v for k, v in st.items() if k != 'trajectory'}, 'events': events,
            'position': st['trajectory']['position']}


@router.post('/api/forge/skip')
def forge_skip(body: dict = Body(...)):
    forge.skip(body.get('qid', ''), body.get('page', ''))
    return {'ok': True}


@router.get('/api/forge/trajectory')
def forge_trajectory():
    return forge.trajectory()


@router.post('/api/forge/preview')
def forge_preview():
    try:
        return forge.preview()
    except (ValueError, llm.LLMError) as e:
        _err(e)


@router.post('/api/forge/forge')
def forge_award(body: dict = Body(...)):
    try:
        out = forge.forge(body.get('stage_name', ''))
    except (ValueError, llm.LLMError) as e:
        _err(e)
    out['events'] = [{'type': 'boss', 'label': f"🔥 PERSONA FORGED: {out['persona']['name']}"}]
    return out


@router.get('/api/forge/skill.md')
def forge_skill():
    award = db.get_setting('forge_award')
    p = personas.get(award['persona_id']) if award else None
    if not p:
        raise HTTPException(404, 'No forged persona yet')
    return PlainTextResponse(forge.skill_md(p), media_type='text/markdown',
                             headers={'Content-Disposition': f'attachment; filename="{p["id"]}-SKILL.md"'})


# ------------------------------------------------------------------ cypher & battle

@router.post('/api/cypher/riff')
def cypher_riff(body: dict = Body(...)):
    bars = (body.get('bars') or '').strip()
    pid = body.get('persona', '')
    if not bars:
        _err('Drop some bars first.')
    try:
        out = cypher.riff(pid, bars, body.get('mode', 'crew'))
    except llm.LLMError as e:
        _err(e)
    analysis = flow.analyze(bars, 90)
    events = []
    if body.get('first_of_round', True):
        events = academy.record_activity('cypher', xp=academy.XP['cypher'], bars=len(lyrics.bars(bars)), stat='cyphers',
                                         achievements=['first_cypher'], analysis=analysis, label='Cypher')
        forge.nudge_from_analysis(analysis, 'cypher-bars')
    forge.nudge_persona(pid, 0.2, 'cypher')
    out['you'] = cypher._light(bars)
    out['events'] = events
    return out


@router.post('/api/cypher/battle')
def cypher_battle(body: dict = Body(...)):
    bars = (body.get('bars') or '').strip()
    if not bars:
        _err('Write your bars first.')
    try:
        out = cypher.battle_round(body.get('persona', ''), bars, body.get('word', ''))
    except llm.LLMError as e:
        _err(e)
    won = out['result'] == 'win'
    out['events'] = academy.record_activity('battle', xp=academy.XP['cypher'] + (academy.XP['battle_win'] if won else 0),
                                            bars=len(lyrics.bars(bars)), stat='cyphers',
                                            achievements=['first_cypher'] + (['giant_killer'] if won else []),
                                            analysis=flow.analyze(bars, 90), label='Battle ' + out['result'])
    forge.nudge_persona(body.get('persona', ''), 0.2, 'battle')
    forge.nudge('battle', out['result'], {'temper': 0.08})
    return out


@router.get('/api/cypher/elo')
def cypher_elo():
    return cypher.elo()


@router.post('/api/cypher/score')
def cypher_score(body: dict = Body(...)):
    return cypher.score(body.get('text', ''), float(body.get('bpm') or 90))


# ------------------------------------------------------------------ listening lab

@router.get('/api/lab')
def lab_home():
    return {'spotify': lab.spotify_config(), 'sessions': lab.list_sessions(), 'level': academy.current_level(),
            'leaderboard': academy.profile().get('leaderboard', True)}


@router.put('/api/lab/spotify')
def lab_spotify(body: dict = Body(...)):
    return lab.set_client_id(body.get('client_id', ''), body.get('redirect_uri', ''))


@router.get('/api/spotify/login')
def spotify_login():
    try:
        return RedirectResponse(lab.login_url())
    except llm.LLMError as e:
        _err(e)


@router.get('/api/spotify/callback')
def spotify_callback(code: str = '', state: str = '', error: str = ''):
    if error:
        return RedirectResponse('/station/academy?lab=spotify-denied#lab')
    try:
        lab.handle_callback(code, state)
    except llm.LLMError as e:
        return RedirectResponse('/station/academy?lab=spotify-error&msg=' + quote(str(e)[:120]) + '#lab')
    return RedirectResponse('/station/academy?lab=connected#lab')


@router.post('/api/spotify/disconnect')
def spotify_disconnect():
    lab.disconnect()
    return {'ok': True}


@router.get('/api/lab/pick')
def lab_pick(level: int = 0):
    try:
        return lab.pick(level or academy.current_level())
    except llm.LLMError as e:
        _err(e)


@router.post('/api/lab/start')
def lab_start(body: dict = Body(...)):
    try:
        return lab.start(int(body.get('level') or academy.current_level()), body.get('track'))
    except llm.LLMError as e:
        _err(e)


@router.get('/api/lab/{sid}')
def lab_get(sid: int):
    s = lab.get(sid, hide_answers=True)
    if not s:
        raise HTTPException(404)
    return s


@router.post('/api/lab/{sid}/quiz')
def lab_quiz(sid: int, body: dict = Body(...)):
    try:
        res = lab.grade_quiz(sid, body.get('answers') or {})
    except llm.LLMError as e:
        _err(e)
    ach = ['lab_rat']
    if res['total'] and res['score'] == res['total']:
        ach.append('quiz_ace')
    if res['beat_all']:
        ach.append('top_of_class')
    xp = academy.XP['lab'] + academy.XP['quiz_right'] * res['score'] + (academy.XP['quiz_perfect'] if 'quiz_ace' in ach else 0)
    res['events'] = academy.record_activity('lab', xp=xp, stat='labs', achievements=ach, label='Listening Lab')
    s = lab.get(sid)
    res['dissection'] = s['dissection']
    return res


@router.post('/api/lab/{sid}/transcribe')
def lab_transcribe(sid: int, body: dict = Body(...)):
    text = (body.get('text') or '').strip()
    if not lab.get(sid):
        raise HTTPException(404)
    lab.save_transcription(sid, text)
    analysis = flow.analyze(text, float(body.get('bpm') or 90))
    events = []
    if len(analysis['bars']) >= 2:
        events = academy.record_activity('transcribe', xp=academy.XP['transcribe'], bars=0, label='Transcription', analysis=None)
    return {'analysis': _light_analysis(analysis), 'events': events}


# ------------------------------------------------------------------ war room

@router.get('/api/warroom')
def warroom():
    return jarvis.board()


@router.get('/api/events')
def events(after: int = 0):
    return db.events_after(after, 100)


@router.get('/api/events/stream')
def events_stream(after: int = 0):
    def gen():
        last = after
        started = time.time()
        while time.time() - started < 300:  # client reconnects after 5 minutes
            new = db.events_after(last, 50)
            for e in new:
                last = e['id']
                yield sse('event', e)
            yield ': ping\n\n'
            time.sleep(1.5)
    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})
