"""Listening Lab: pick a rap track from the user's Spotify, dissect its craft, quiz the class.

Spotify uses the Authorization Code + PKCE flow, so only a Client ID is needed
(create an app at developer.spotify.com, redirect URI below). Lyrics are never
fetched or reproduced: the student listens through the Spotify embed and
transcribes bars themselves (Bible drill 14.1).
"""
import base64, hashlib, json, os, random, secrets, time, urllib.parse
import requests

from . import db, llm, personas, bible

SCOPES = 'user-top-read user-library-read user-read-recently-played'
RAP_WORDS = ('hip hop', 'rap', 'trap', 'drill', 'grime', 'boom bap', 'horrorcore', 'g funk', 'gangster', 'conscious',
             'underground hip hop', 'southern hip hop', 'east coast', 'west coast')

SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  track TEXT NOT NULL,
  level INTEGER NOT NULL,
  dissection TEXT NOT NULL DEFAULT '{}',
  answers TEXT NOT NULL DEFAULT '{}',
  results TEXT NOT NULL DEFAULT '{}',
  transcription TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  finished_at REAL
);
"""

# Classmates: how often each persona gets a quiz question right, and what they say.
CLASSMATES = {
    'biggie': {'skill': 0.78, 'right': ['Easy. Next.', 'Told you. Specifics.', 'Uh. Correct.'],
               'wrong': ['Man, I was half asleep.', 'Run that back.']},
    'slim-shady': {'skill': 0.74, 'right': ['YES! Vowels never lie!', 'Too easy, gimme a hard one!'],
                   'wrong': ['That question was rigged!', 'I meant the OTHER answer!']},
    'king-von': {'skill': 0.7, 'right': ['Aight, that one was clear.', 'Saw that coming.'],
                 'wrong': ['Damn, they got me.', 'I skipped a step on that one.']},
    'j-cole': {'skill': 0.76, 'right': ['Felt that one.', 'The honest answer is usually right.'],
               'wrong': ['I overthought it.', 'Humbling, honestly.']},
}


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)


# ------------------------------------------------------------------ spotify auth

def redirect_uri():
    port = os.getenv('PORT', '8770')
    return db.get_setting('spotify_redirect', '') or f'http://127.0.0.1:{port}/api/spotify/callback'


def spotify_config():
    cfg = db.get_setting('spotify', {}) or {}
    tok = db.get_setting('spotify_tokens', {}) or {}
    return {'client_id': cfg.get('client_id', ''), 'connected': bool(tok.get('refresh_token')),
            'redirect_uri': redirect_uri(), 'user': tok.get('user', '')}


def set_client_id(client_id, redirect=''):
    db.set_setting('spotify', {'client_id': client_id.strip()})
    if redirect:
        db.set_setting('spotify_redirect', redirect.strip())
    return spotify_config()


def login_url():
    cfg = db.get_setting('spotify', {}) or {}
    if not cfg.get('client_id'):
        raise llm.LLMError('Add your Spotify Client ID first.')
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state = secrets.token_urlsafe(16)
    db.set_setting('spotify_pkce', {'verifier': verifier, 'state': state, 't': time.time()})
    q = {'client_id': cfg['client_id'], 'response_type': 'code', 'redirect_uri': redirect_uri(), 'scope': SCOPES,
         'code_challenge_method': 'S256', 'code_challenge': challenge, 'state': state}
    return 'https://accounts.spotify.com/authorize?' + urllib.parse.urlencode(q)


def handle_callback(code, state):
    pk = db.get_setting('spotify_pkce', {}) or {}
    if not pk or state != pk.get('state') or time.time() - pk.get('t', 0) > 900:
        raise llm.LLMError('Spotify login expired or did not match. Try connecting again.')
    cfg = db.get_setting('spotify', {}) or {}
    r = requests.post('https://accounts.spotify.com/api/token', timeout=15, data={
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri(),
        'client_id': cfg.get('client_id', ''), 'code_verifier': pk['verifier']})
    if not r.ok:
        raise llm.LLMError(f'Spotify token exchange failed: {r.text[:200]}')
    _store_tokens(r.json())
    db.set_setting('spotify_pkce', {})
    try:
        me = api('/me')
        tok = db.get_setting('spotify_tokens', {})
        tok['user'] = me.get('display_name') or me.get('id', '')
        db.set_setting('spotify_tokens', tok)
    except Exception:
        pass
    db.log_event('lab', 'spotify', 'Spotify connected')


def disconnect():
    db.set_setting('spotify_tokens', {})


def _store_tokens(data):
    tok = db.get_setting('spotify_tokens', {}) or {}
    tok['access_token'] = data['access_token']
    tok['expires_at'] = time.time() + int(data.get('expires_in', 3600)) - 60
    if data.get('refresh_token'):
        tok['refresh_token'] = data['refresh_token']
    db.set_setting('spotify_tokens', tok)


def _token():
    tok = db.get_setting('spotify_tokens', {}) or {}
    if not tok.get('refresh_token'):
        raise llm.LLMError('Spotify is not connected.')
    if time.time() < tok.get('expires_at', 0):
        return tok['access_token']
    cfg = db.get_setting('spotify', {}) or {}
    r = requests.post('https://accounts.spotify.com/api/token', timeout=15, data={
        'grant_type': 'refresh_token', 'refresh_token': tok['refresh_token'], 'client_id': cfg.get('client_id', '')})
    if not r.ok:
        raise llm.LLMError('Spotify session expired. Connect again.')
    _store_tokens(r.json())
    return db.get_setting('spotify_tokens', {})['access_token']


def api(path, params=None):
    r = requests.get('https://api.spotify.com/v1' + path, params=params or {}, timeout=15,
                     headers={'Authorization': 'Bearer ' + _token()})
    if r.status_code == 429:
        raise llm.LLMError('Spotify rate limit. Try again in a minute.')
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ picking a track

def _track(t, source):
    img = (t.get('album', {}).get('images') or [{}])
    return {'id': t['id'], 'name': t['name'], 'artists': [a['name'] for a in t.get('artists', [])],
            'artist_ids': [a['id'] for a in t.get('artists', []) if a.get('id')],
            'album': t.get('album', {}).get('name', ''), 'year': (t.get('album', {}).get('release_date') or '')[:4],
            'image': img[0].get('url', '') if img else '', 'source': source,
            'embed': f"https://open.spotify.com/embed/track/{t['id']}", 'url': t.get('external_urls', {}).get('spotify', '')}


def spotify_candidates():
    tracks = {}
    for path, params, source in (('/me/top/tracks', {'limit': 50, 'time_range': 'medium_term'}, 'top'),
                                 ('/me/top/tracks', {'limit': 50, 'time_range': 'short_term'}, 'top (recent)'),
                                 ('/me/tracks', {'limit': 50}, 'saved'),
                                 ('/me/player/recently-played', {'limit': 50}, 'recent')):
        try:
            data = api(path, params)
        except Exception:
            continue
        for item in data.get('items', []):
            t = item.get('track', item)
            if t and t.get('id') and t['id'] not in tracks:
                tracks[t['id']] = _track(t, source)
    # genre filter through artist lookups (50 per call); keep everything if genres are unavailable
    artist_ids = list({a for t in tracks.values() for a in t['artist_ids']})
    genres = {}
    for i in range(0, len(artist_ids), 50):
        try:
            for a in api('/artists', {'ids': ','.join(artist_ids[i:i + 50])}).get('artists', []):
                if a:
                    genres[a['id']] = a.get('genres') or []
        except Exception:
            break
    out = []
    for t in tracks.values():
        g = [x for a in t['artist_ids'] for x in genres.get(a, [])]
        t['genres'] = g[:6]
        t['rap'] = any(w in x for x in g for w in RAP_WORDS)
        out.append(t)
    rap = [t for t in out if t['rap']]
    return rap if rap else out


def _done_ids():
    with db.connect() as con:
        rows = con.execute('SELECT track FROM lab_sessions').fetchall()
    ids = set()
    for r in rows:
        try:
            t = json.loads(r['track'])
            ids.add(t.get('id') or (t.get('artist', '') + t.get('name', '')))
        except ValueError:
            pass
    return ids


def pick(level, exclude=None):
    """The algorithm: favour unstudied rap tracks from your listening, weighted toward the level's study list."""
    exclude = set(exclude or []) | _done_ids()
    data = bible.load() or {}
    study = (data.get('listening') or {}).get(level, {}).get('songs', [])
    focus_artists = {s['artist'].lower() for s in study}
    connected = spotify_config()['connected']
    pool = []
    if connected:
        try:
            pool = spotify_candidates()
        except llm.LLMError:
            pool = []
    weighted = []
    for t in pool:
        if t['id'] in exclude:
            continue
        w = 1.0
        if any(a.lower() in focus_artists for a in t['artists']):
            w *= 3
        if t['source'].startswith('top'):
            w *= 1.5
        if t['rap']:
            w *= 2
        weighted.append((w, t))
    if weighted:
        total = sum(w for w, _ in weighted)
        r = random.random() * total
        for w, t in weighted:
            r -= w
            if r <= 0:
                return t
        return weighted[-1][1]
    # Fallback: the Bible's listening curriculum for this level
    options = [s for s in study if (s['artist'] + s['title']) not in exclude] or study
    if not options:
        raise llm.LLMError('No tracks to pick from. Connect Spotify or import the Bible.')
    s = random.choice(options)
    return {'id': '', 'name': s['title'], 'artists': [s['artist']], 'album': '', 'year': '', 'image': '',
            'source': 'bible curriculum', 'focus': s.get('focus', ''), 'embed': '', 'url':
            'https://open.spotify.com/search/' + urllib.parse.quote(f"{s['artist']} {s['title']}"), 'genres': [], 'rap': True}


# ------------------------------------------------------------------ dissection + quiz

DISSECT_FORMAT = '''Reply with ONLY a JSON object:
{
  "known": true or false,                 // do you actually know this specific song well?
  "confidence": "high" | "medium" | "low",
  "overview": "2-3 sentences: what the song is doing as a piece of writing",
  "structure": [{"section": "Verse 1", "what_happens": "..."}],
  "techniques": [{"name": "e.g. multisyllabic chain / withheld fact / object POV", "chapter": "Bible chapter number", "where": "where in the song (describe, do not quote)", "why_it_works": "..."}],
  "listen_for": ["3-5 things to listen for on the next play"],
  "transcribe_tip": "which 4-8 bars are worth transcribing and why (describe, do not quote)",
  "discussion": ["3 open questions for the class"],
  "quiz": [{"q": "question about craft", "options": ["A","B","C","D"], "answer": 0-3, "explain": "why"}]
}
Write 6 quiz questions mixing: technique identification, structure, Bible concepts applied to this song, and one "what would you do" craft question.'''


def dissect(track, level):
    coach = personas.get('coach') or {}
    data = bible.load() or {}
    lvl = next((l for l in data.get('levels', []) if l['level'] == level), None)
    focus = f"The student is on Level {level}: {lvl['name']} ({lvl['goal']})." if lvl else ''
    system = personas.system_prompt(coach, extra=(
        'You are running a LISTENING LAB for a class. Copyright rule: never reproduce lyrics. You may refer to a phrase '
        'of at most five words when essential; otherwise describe. If you do not know this exact song, say so with '
        '"known": false and build the lesson from the artist\'s well-documented style, clearly labelled as general.'))
    user = (f"Song: {', '.join(track.get('artists', []))} - \"{track.get('name')}\""
            f"{' (' + track['year'] + ')' if track.get('year') else ''}. {focus}"
            f"{' Curriculum focus: ' + track['focus'] if track.get('focus') else ''}\n\n{DISSECT_FORMAT}")
    reply = llm.complete([{'role': 'user', 'content': user}], system, temperature=0.5, max_tokens=3000)
    out = llm.extract_json(reply)
    if not isinstance(out, dict):
        raise llm.LLMError('The coach did not return a usable lesson. Try again, or use a stronger model.')
    quiz = []
    for q in out.get('quiz') or []:
        try:
            opts = [str(o) for o in q['options']][:4]
            ans = int(q['answer'])
            if len(opts) >= 2 and 0 <= ans < len(opts):
                quiz.append({'q': str(q['q']), 'options': opts, 'answer': ans, 'explain': str(q.get('explain', ''))})
        except (KeyError, TypeError, ValueError):
            continue
    out['quiz'] = quiz[:8]
    return out


def start(level, track=None):
    track = track or pick(level)
    lesson = dissect(track, level)
    with db.connect() as con:
        cur = con.execute('INSERT INTO lab_sessions(track,level,dissection,created_at) VALUES(?,?,?,?)',
                          (json.dumps(track), level, json.dumps(lesson), db.now()))
        sid = cur.lastrowid
    db.log_event('lab', 'start', f"Listening Lab: {', '.join(track['artists'])} - {track['name']}", {'id': sid})
    return get(sid, hide_answers=True)


def get(sid, hide_answers=False):
    with db.connect() as con:
        r = con.execute('SELECT * FROM lab_sessions WHERE id=?', (sid,)).fetchone()
    if not r:
        return None
    out = dict(r)
    for k in ('track', 'dissection', 'answers', 'results'):
        out[k] = json.loads(out[k] or '{}')
    if hide_answers and not out['finished_at']:
        out['dissection']['quiz'] = [{k: v for k, v in q.items() if k not in ('answer', 'explain')} for q in out['dissection'].get('quiz', [])]
    return out


def list_sessions(limit=30):
    with db.connect() as con:
        rs = con.execute('SELECT id, track, level, results, created_at, finished_at FROM lab_sessions ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    out = []
    for r in rs:
        d = dict(r)
        d['track'] = json.loads(d['track'])
        d['results'] = json.loads(d['results'] or '{}')
        out.append(d)
    return out


def grade_quiz(sid, answers, seed=None):
    """Score the student, simulate the classmates, build the leaderboard."""
    s = get(sid)
    if not s:
        raise llm.LLMError('Lab not found')
    quiz = s['dissection'].get('quiz', [])
    rng = random.Random(seed if seed is not None else sid * 7919)
    # Classmates are rivals just above your level: tuned to your past quiz average.
    past = [x['results'] for x in list_sessions(50) if x['results'].get('total')]
    mine = (sum(r['score'] / r['total'] for r in past) / len(past)) if past else 0.65
    offsets = {'biggie': 0.06, 'slim-shady': 0.03, 'king-von': -0.03, 'j-cole': 0.05}
    skills = {pid: max(0.4, min(0.95, mine + offsets.get(pid, 0))) for pid in CLASSMATES}
    per_q = []
    student = 0
    class_scores = {pid: 0 for pid in CLASSMATES}
    lines = []
    for i, q in enumerate(quiz):
        pick_ = answers.get(str(i), answers.get(i))
        right = pick_ is not None and int(pick_) == q['answer']
        student += right
        mates = {}
        for pid, mate in CLASSMATES.items():
            ok = rng.random() < skills[pid]
            class_scores[pid] += ok
            mates[pid] = ok
        per_q.append({'index': i, 'picked': pick_, 'answer': q['answer'], 'right': right, 'explain': q['explain'],
                      'classmates': mates})
    for pid, mate in CLASSMATES.items():
        p = personas.get(pid) or {}
        good = class_scores[pid] >= len(quiz) * 0.6
        lines.append({'persona': pid, 'name': p.get('handle') or p.get('name', pid), 'color': p.get('color'),
                      'line': rng.choice(mate['right'] if good else mate['wrong'])})
    board = sorted([{'id': 'you', 'name': 'You', 'score': student}] +
                   [{'id': pid, 'name': (personas.get(pid) or {}).get('handle', pid), 'score': sc} for pid, sc in class_scores.items()],
                   key=lambda x: (-x['score'], x['id'] != 'you'))
    place = next(i for i, b in enumerate(board) if b['id'] == 'you') + 1
    results = {'score': student, 'total': len(quiz), 'per_question': per_q, 'board': board, 'place': place,
               'banter': lines, 'beat_all': all(student > sc for sc in class_scores.values())}
    with db.connect() as con:
        con.execute('UPDATE lab_sessions SET answers=?, results=?, finished_at=? WHERE id=?',
                    (json.dumps(answers), json.dumps(results), db.now(), sid))
    return results


def save_transcription(sid, text):
    with db.connect() as con:
        con.execute('UPDATE lab_sessions SET transcription=? WHERE id=?', (text, sid))
