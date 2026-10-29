"""The Forge: build the student's own rapper persona from every choice they make.

Two inputs feed it:
  1. Life questions, one per new Academy page. Each has a free-text story (the
     story bank your persona raps from) and optional flavour chips that nudge style.
  2. The trajectory: every meaningful choice in the station (persona you cypher
     with, your measured pocket and rhyme density, chapters you peek at, songs
     you study, the patterns you favour) shifts six style axes slightly.

At graduation the whole path is synthesised, seeded by its fingerprint, into a
persona and an exportable SKILL.md. Same answers in a different order, or one
different choice, lands somewhere else.
"""
import hashlib, json, math, random, re

from . import db, llm, personas

AXES = {
    'temper': ('Calm', 'Chaos'),
    'texture': ('Plain', 'Ornate'),
    'lens': ('Confessional', 'Cinematic'),
    'pocket': ('Laid-back', 'Rapid'),
    'imagery': ('Street', 'Abstract'),
    'tone': ('Humor', 'Gravity'),
}

# Persona influence vectors (where each master pulls you).
PULL = {
    'biggie': {'temper': -0.6, 'texture': -0.2, 'lens': 0.5, 'pocket': -0.6, 'imagery': -0.5, 'tone': 0.0},
    'slim-shady': {'temper': 0.9, 'texture': 0.8, 'lens': 0.3, 'pocket': 0.8, 'imagery': 0.2, 'tone': -0.5},
    'king-von': {'temper': -0.2, 'texture': -0.6, 'lens': 0.8, 'pocket': -0.1, 'imagery': -0.8, 'tone': 0.4},
    'j-cole': {'temper': -0.5, 'texture': -0.4, 'lens': -0.8, 'pocket': -0.2, 'imagery': -0.2, 'tone': 0.5},
    'coach': {'texture': 0.2},
}

# Life questions: id, category, prompt, chips [(label, deltas)]
QUESTIONS = [
    ('crazy-friends', 'Crew', 'Tell me about the craziest thing you ever did with your friends.',
     [('We should have been arrested', {'temper': .4, 'imagery': -.3}), ('Harmless chaos', {'tone': -.4}), ('It got deep', {'tone': .3, 'lens': -.2})]),
    ('first-chills', 'Taste', 'What is the first song that ever gave you chills, and where were you standing?',
     [('In a car', {'imagery': -.2}), ('Alone in my room', {'lens': -.3}), ('At a party or show', {'temper': .2})]),
    ('block', 'Origins', 'Describe the street you grew up on: one smell, one sound, one person.',
     [('Loud and busy', {'temper': .2, 'imagery': -.4}), ('Quiet and strange', {'imagery': .3}), ('Moved too much to say', {'lens': -.2, 'tone': .2})]),
    ('caught', 'Trouble', 'When is the last time you got caught doing something you should not have been doing?',
     [('Talked my way out', {'texture': .3, 'tone': -.2}), ('Took the L', {'lens': -.3}), ('Never got caught (yet)', {'temper': .2})]),
    ('worst-job', 'Hustle', 'What was your worst job and what did it teach you about people?',
     [('Customers are wild', {'tone': -.3}), ('Bosses are wild', {'temper': .2}), ('It taught me patience', {'temper': -.3})]),
    ('family-dinner', 'Family', 'Paint a family dinner (or the lack of one) at your house growing up.',
     [('Loud and loving', {'tone': -.2}), ('Tense', {'tone': .4}), ('Mostly alone', {'lens': -.4, 'tone': .3})]),
    ('lost-fight', 'Conflict', 'Tell me about a fight you lost, with fists, words or life.',
     [('Still mad about it', {'temper': .4}), ('Deserved it', {'lens': -.4}), ('It made me', {'tone': .3})]),
    ('conflict-style', 'Mind', 'When someone disrespects you, what do you actually do in the first ten seconds?',
     [('Go quiet and plot', {'temper': -.5}), ('Go loud', {'temper': .6}), ('Laugh it off', {'tone': -.5}), ('Walk away', {'temper': -.3, 'tone': .2})]),
    ('secret-skill', 'Identity', 'What is a skill you have that would surprise people who just met you?',
     [('Something nerdy', {'imagery': .4, 'texture': .2}), ('Something physical', {'imagery': -.3}), ('Something creative', {'texture': .3})]),
    ('money-first', 'Hustle', 'What did you buy with the first real money you ever made?',
     [('Something flashy', {'temper': .2, 'tone': -.2}), ('Something for family', {'lens': -.3, 'tone': .3}), ('Saved it', {'temper': -.4})]),
    ('night-out', 'Crew', 'Walk me through your best night out, from the first text to getting home.',
     [('Planned it like a heist', {'texture': .2, 'lens': .3}), ('Pure accident', {'temper': .3}), ('Ended somewhere unbelievable', {'lens': .4})]),
    ('fear', 'Mind', 'What are you genuinely afraid of that you rarely admit?',
     [('Failing publicly', {'lens': -.3, 'tone': .3}), ('Being ordinary', {'texture': .3}), ('Losing people', {'tone': .5})]),
    ('hero', 'Influences', 'Who did you want to be when you were twelve, and why?',
     [('A rapper', {'pocket': .2}), ('An athlete', {'imagery': -.3}), ('Someone in my family', {'lens': -.3}), ('A villain', {'temper': .4, 'tone': -.2})]),
    ('worst-advice', 'Mind', 'What is the worst advice anyone ever gave you, and did you take it?',
     [('Took it, regretted it', {'lens': -.3}), ('Ignored it, proved them wrong', {'temper': .2}), ('Still deciding', {'tone': .2})]),
    ('city-object', 'Imagery', 'If your city were one object on a kitchen table, what would it be and what condition is it in?',
     [('Something cracked', {'tone': .3, 'imagery': .2}), ('Something shiny', {'tone': -.2}), ('Something sticky', {'imagery': -.3})]),
    ('heartbreak', 'Love', 'Tell me about the first time your heart got properly broken.',
     [('I saw it coming', {'temper': -.3}), ('Blindsided', {'tone': .3}), ('I broke theirs first', {'temper': .3, 'tone': -.2})]),
    ('proudest', 'Identity', 'What is the thing you are proudest of that nobody gave you credit for?',
     [('Surviving something', {'tone': .4}), ('Building something', {'lens': .2}), ('Helping someone', {'lens': -.3})]),
    ('road-trip', 'Crew', 'Worst or best road trip of your life: who was in the car and what went wrong?',
     [('Car broke down', {'tone': -.3}), ('Somebody snapped', {'temper': .3}), ('Best talk of my life', {'lens': -.3})]),
    ('rule-broken', 'Values', 'What rule do you break on purpose, and what rule would you never break?',
     [('Break the law, never snitch', {'imagery': -.3, 'temper': .2}), ('Break etiquette, never lie', {'lens': -.3}), ('Break everything', {'temper': .5})]),
    ('morning', 'Life', 'What does your actual morning look like, minute by minute, on a bad day?',
     [('Chaos', {'pocket': .3, 'temper': .3}), ('Routine', {'temper': -.3}), ('Depressing', {'tone': .4})]),
    ('teacher', 'Influences', 'Which teacher, coach or older person changed your direction, for better or worse?',
     [('For better', {'tone': .2}), ('For worse', {'temper': .3}), ('It was the streets', {'imagery': -.5})]),
    ('regret-text', 'Love', 'What is the text you regret sending, or the one you wish you had sent?',
     [('Sent it drunk', {'tone': -.3, 'temper': .2}), ('Never sent it', {'lens': -.4, 'tone': .3}), ('Too proud', {'temper': .2})]),
    ('superstition', 'Mind', 'Do you have a superstition, ritual or lucky thing? Where did it come from?',
     [('Family thing', {'lens': -.2}), ('Sports thing', {'imagery': -.2}), ('I made it up', {'texture': .3, 'imagery': .3})]),
    ('cops', 'Trouble', 'Tell me about a run-in with authority (police, principal, landlord, manager).',
     [('Stayed calm', {'temper': -.4}), ('Lost it', {'temper': .5}), ('Comedy of errors', {'tone': -.4})]),
    ('weird-place', 'Imagery', 'What is the strangest place you have ever slept?',
     [('Outside', {'imagery': -.3}), ('Somewhere fancy by accident', {'tone': -.3}), ('Somewhere I should not have been', {'temper': .3})]),
    ('friend-lost', 'Crew', 'Tell me about a friend you lost touch with. What happened?',
     [('Drifted', {'tone': .2, 'lens': -.2}), ('Betrayal', {'temper': .4}), ('They are gone', {'tone': .6})]),
    ('food', 'Life', 'What meal would you rap about, and who makes it best?',
     [('Grandma', {'lens': -.3}), ('A spot on the corner', {'imagery': -.3}), ('Me', {'tone': -.2})]),
    ('decision', 'Mind', 'How do you make big decisions: gut, list, other people, or avoid them?',
     [('Gut', {'temper': .3, 'pocket': .2}), ('List', {'texture': .3, 'temper': -.3}), ('Ask around', {'lens': .2}), ('Avoid them', {'tone': .2})]),
    ('injustice', 'Values', 'What is something unfair that you have watched happen and could not stop?',
     [('Made me angry', {'temper': .4, 'tone': .3}), ('Made me quiet', {'temper': -.3, 'tone': .4}), ('Made me act', {'lens': .2})]),
    ('alter-ego', 'Identity', 'If you had an alter ego who does what you will not, what is their name and what do they do?',
     [('Pure menace', {'temper': .6, 'texture': .2}), ('A smooth operator', {'temper': -.4, 'tone': -.2}), ('A prophet', {'imagery': .5, 'tone': .4})]),
    ('room', 'Imagery', 'Describe the room you write in. Three objects you can see right now.',
     [('Messy', {'temper': .2}), ('Bare', {'texture': -.3}), ('Full of memorabilia', {'texture': .3})]),
    ('win', 'Identity', 'Tell me about a time you won when everybody expected you to lose.',
     [('Underdog story', {'lens': .3}), ('Pure luck', {'tone': -.3}), ('Revenge', {'temper': .4})]),
    ('slang', 'Voice', 'Give me five words or phrases only people from your circle say, and what they mean.',
     [('Regional slang', {'imagery': -.4}), ('Internet slang', {'imagery': .3, 'tone': -.2}), ('Inside jokes', {'tone': -.3})]),
    ('belief', 'Values', 'What do you believe that most people around you do not?',
     [('About money', {'imagery': -.2}), ('About god or fate', {'imagery': .5, 'tone': .3}), ('About people', {'lens': -.3})]),
    ('scar', 'Life', 'Tell me the story behind a scar, physical or otherwise.',
     [('Stupid accident', {'tone': -.4}), ('Someone did it', {'temper': .3, 'tone': .3}), ('I did it', {'lens': -.4})]),
    ('legacy', 'Values', 'What do you want people to say about you when you are not in the room?',
     [('He was funny', {'tone': -.4}), ('He was real', {'lens': -.4}), ('He was dangerous', {'temper': .4}), ('He was brilliant', {'texture': .4})]),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS forge_answers (
  qid TEXT PRIMARY KEY, answer TEXT NOT NULL, chip TEXT NOT NULL DEFAULT '', page TEXT NOT NULL DEFAULT '', ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS forge_trajectory (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, source TEXT NOT NULL, choice TEXT NOT NULL, deltas TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forge_pages (page TEXT PRIMARY KEY, qid TEXT NOT NULL, ts REAL NOT NULL);
"""

AWARD_LEVEL = 3          # beat this boss ...
AWARD_ANSWERS = 20       # ... and answer this many questions
PREVIEW_ANSWERS = 8      # a teaser of stage names unlocks here


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)


def _q(qid):
    for q in QUESTIONS:
        if q[0] == qid:
            return {'id': q[0], 'category': q[1], 'prompt': q[2], 'chips': [c[0] for c in q[3]]}
    return None


# ------------------------------------------------------------------ trajectory

def nudge(source, choice, deltas, scale=1.0):
    """Record a choice and how it moves the style axes."""
    d = {k: round(v * scale, 3) for k, v in (deltas or {}).items() if k in AXES and v}
    if not d:
        return
    with db.connect() as con:
        con.execute('INSERT INTO forge_trajectory(ts,source,choice,deltas) VALUES(?,?,?,?)',
                    (db.now(), source, str(choice)[:120], json.dumps(d)))


def nudge_persona(pid, weight=0.25, source='persona'):
    if pid in PULL:
        nudge(source, pid, PULL[pid], weight)


def nudge_from_analysis(analysis, source='bars'):
    """Your own bars tell us your pocket, density and imagery."""
    if not analysis or not analysis.get('bars'):
        return
    s = analysis['summary']
    sps = s.get('avg_sps', 4.5)
    syl = [x for b in analysis['bars'] for x in b['syllables']]
    density = sum(1 for x in syl if 'rhyme' in x) / max(len(syl), 1)
    from .grading import ABSTRACT
    words = [w.lower() for b in analysis['bars'] for w in re.findall(r"[A-Za-z']+", b['text'])]
    abstract = sum(1 for w in words if w in ABSTRACT) / max(len(words), 1)
    nudge(source, f"{s.get('bars')} bars @ {sps}/s", {
        'pocket': max(-1, min(1, (sps - 4.8) / 3)) * 0.3,
        'texture': max(-1, min(1, (density - 0.3) * 3)) * 0.25,
        'imagery': max(-1, min(1, (abstract - 0.03) * 20)) * 0.2,
    })


def trajectory(limit=400):
    with db.connect() as con:
        rows = con.execute('SELECT * FROM forge_trajectory ORDER BY id ASC').fetchall()
    pos = {k: 0.0 for k in AXES}
    path = []
    for r in rows[-limit:] if limit else rows:
        d = json.loads(r['deltas'])
        for k, v in d.items():
            # soft saturation keeps early choices meaningful but lets later ones still steer
            pos[k] = math.tanh(math.atanh(max(-0.999, min(0.999, pos[k]))) + v * 0.5)
        path.append({'ts': r['ts'], 'source': r['source'], 'choice': r['choice'],
                     'x': round(pos['temper'], 3), 'y': round(pos['texture'], 3)})
    return {'position': {k: round(v, 3) for k, v in pos.items()}, 'path': path, 'choices': len(rows)}


def fingerprint():
    with db.connect() as con:
        rows = con.execute('SELECT source, choice, deltas FROM forge_trajectory ORDER BY id').fetchall()
        ans = con.execute('SELECT qid, chip, answer FROM forge_answers ORDER BY ts').fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['source']}|{r['choice']}|{r['deltas']}\n".encode())
    for a in ans:
        h.update(f"{a['qid']}|{a['chip']}|{a['answer']}\n".encode())
    return h.hexdigest()


def influences():
    with db.connect() as con:
        rows = con.execute("SELECT choice, COUNT(*) AS n FROM forge_trajectory WHERE source IN ('persona','cypher','battle','consult') GROUP BY choice").fetchall()
    total = sum(r['n'] for r in rows) or 1
    return sorted([{'persona': r['choice'], 'share': round(r['n'] / total, 3), 'count': r['n']} for r in rows],
                  key=lambda x: -x['share'])


# ------------------------------------------------------------------ questions

def answers():
    with db.connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM forge_answers ORDER BY ts').fetchall()]


def question_for_page(page):
    """First visit to a page asks the next question. Revisits show the same one until answered or skipped."""
    with db.connect() as con:
        r = con.execute('SELECT qid FROM forge_pages WHERE page=?', (page,)).fetchone()
        answered = {a['qid'] for a in con.execute('SELECT qid FROM forge_answers').fetchall()}
        asked = {a['qid'] for a in con.execute('SELECT qid FROM forge_pages').fetchall()}
    if r:
        return None if r['qid'] in answered else _q(r['qid'])
    # balance categories: pick from the least-covered category, ordered by a per-user seed
    seen_cats = {}
    for q in QUESTIONS:
        if q[0] in answered:
            seen_cats[q[1]] = seen_cats.get(q[1], 0) + 1
    remaining = [q for q in QUESTIONS if q[0] not in answered and q[0] not in asked]
    if not remaining:
        return None
    seed = int(fingerprint()[:8], 16)
    rng = random.Random(seed)
    rng.shuffle(remaining)
    remaining.sort(key=lambda q: seen_cats.get(q[1], 0))
    pick = remaining[0]
    with db.connect() as con:
        con.execute('INSERT INTO forge_pages(page,qid,ts) VALUES(?,?,?)', (page, pick[0], db.now()))
    return _q(pick[0])


def answer(qid, text, chip=''):
    q = next((x for x in QUESTIONS if x[0] == qid), None)
    if not q:
        raise ValueError('Unknown question')
    text = (text or '').strip()
    if not text and not chip:
        raise ValueError('Write something or pick a chip (or skip).')
    with db.connect() as con:
        con.execute('INSERT INTO forge_answers(qid,answer,chip,ts) VALUES(?,?,?,?) '
                    'ON CONFLICT(qid) DO UPDATE SET answer=excluded.answer, chip=excluded.chip, ts=excluded.ts',
                    (qid, text[:4000], chip, db.now()))
    for label, deltas in q[3]:
        if label == chip:
            nudge('forge', f'{qid}:{chip}', deltas)
    if text:
        # longer, more detailed stories lean cinematic; first-person feelings lean confessional
        words = len(text.split())
        feels = len(re.findall(r"\b(i felt|i was scared|i cried|i hated|i loved|my fault|i regret)\b", text.lower()))
        nudge('forge-story', qid, {'lens': (0.15 if words > 80 else 0) - 0.15 * min(feels, 2)})
    return status()


def skip(qid, page=''):
    with db.connect() as con:
        con.execute('INSERT OR IGNORE INTO forge_answers(qid,answer,chip,page,ts) VALUES(?,?,?,?,?)',
                    (qid, '', 'skipped', page, db.now()))
    return status()


def status():
    a = [x for x in answers() if x['chip'] != 'skipped' or x['answer']]
    from . import academy
    bosses = academy.passed_bosses()
    awarded = db.get_setting('forge_award', None)
    return {
        'answered': len(a), 'total': len(QUESTIONS), 'need_answers': AWARD_ANSWERS, 'need_level': AWARD_LEVEL,
        'preview_at': PREVIEW_ANSWERS, 'preview_ready': len(a) >= PREVIEW_ANSWERS,
        'eligible': len(a) >= AWARD_ANSWERS and AWARD_LEVEL in bosses,
        'progress': round(min(1, len(a) / AWARD_ANSWERS) * 0.5 + (0.5 if AWARD_LEVEL in bosses else 0.5 * len([b for b in bosses if b <= AWARD_LEVEL]) / AWARD_LEVEL), 3),
        'awarded': awarded, 'trajectory': trajectory(), 'influences': influences(), 'axes': AXES,
    }


# ------------------------------------------------------------------ synthesis

def _signature_patterns():
    from . import academy
    counts = academy.cards()
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]


def _measured_pocket():
    traj = trajectory()['position']['pocket']
    centre = 4.8 + traj * 2.5
    return [round(max(2.5, centre - 1.2), 1), round(min(10, centre + 1.4), 1)]


def _style_words(pos):
    out = []
    for axis, (lo, hi) in AXES.items():
        v = pos.get(axis, 0)
        if abs(v) < 0.15:
            out.append(f'balanced between {lo.lower()} and {hi.lower()}')
        else:
            strength = 'leans' if abs(v) < 0.5 else 'is strongly'
            out.append(f"{strength} {(hi if v > 0 else lo).lower()} ({axis})")
    return out


def _brief():
    st = trajectory()
    pos = st['position']
    stories = [a for a in answers() if a['answer']]
    q_text = {q[0]: q[2] for q in QUESTIONS}
    bank = '\n'.join(f"- Q: {q_text.get(a['qid'], a['qid'])}\n  A: {a['answer'][:700]}" + (f" [{a['chip']}]" if a['chip'] else '') for a in stories)
    infl = ', '.join(f"{i['persona']} {int(i['share'] * 100)}%" for i in influences()[:4]) or 'none yet'
    return pos, (f"STYLE POSITION (each -1..1): {json.dumps(pos)}\nStyle in words: {'; '.join(_style_words(pos))}\n"
                 f"Persona influences: {infl}\nSignature vowel patterns: {', '.join(_signature_patterns()) or 'unknown'}\n"
                 f"Measured pocket (syllables/sec): {_measured_pocket()}\nChoices on the path: {st['choices']}\n\n"
                 f"STORY BANK (the student's own life, in their words):\n{bank or '(empty)'}")


def preview():
    """Teaser: stage-name ideas and a one-line read, unlocked early as a reward."""
    if not status()['preview_ready']:
        raise ValueError(f'Answer {PREVIEW_ANSWERS} Forge questions to unlock your first preview.')
    pos, brief = _brief()
    seed = fingerprint()[:12]
    system = ('You are the Forge, a perceptive (never clinical) character writer. You read a student rapper\'s life '
              'answers and style data and reflect who they are as an artist. No diagnoses, no psychology jargon, '
              'no judgement of the person: describe the artist.')
    user = (f"{brief}\n\nRandom seed for creative choices: {seed}\n\nReply ONLY with JSON: "
            '{"stage_names": ["5 original stage names that fit this specific person"], "read": "two sentences on the artist '
            'emerging here", "themes": ["4-6 recurring themes from their stories"]}')
    out = llm.extract_json(llm.complete([{'role': 'user', 'content': user}], system, temperature=0.9, max_tokens=800))
    if not isinstance(out, dict):
        raise llm.LLMError('The Forge could not read the model reply. Try again.')
    db.set_setting('forge_preview', {**out, 'fingerprint': seed})
    return out


def forge(stage_name):
    """Award the persona: synthesise the full trajectory into a persona + SKILL.md."""
    st = status()
    if not st['eligible'] and not db.get_setting('forge_award'):
        raise ValueError(f"Beat the Level {AWARD_LEVEL} boss and answer {AWARD_ANSWERS} Forge questions to earn your persona.")
    stage_name = re.sub(r'\s+', ' ', (stage_name or '').strip())[:40]
    if not stage_name:
        raise ValueError('Pick a stage name.')
    pos, brief = _brief()
    fp = fingerprint()
    system = ('You are the Forge. You turn a student rapper\'s life stories, style trajectory and measured craft into a '
              'writing persona that captures THEIR voice. Use their real details as raw material for imagery. No clinical '
              'or psychological labels. The persona writes original lyrics only and never quotes real songs.')
    user = (f"Stage name: {stage_name}\nPath fingerprint (use as the seed for every creative choice): {fp[:16]}\n\n{brief}\n\n"
            'Reply ONLY with JSON:\n{"tagline": "one line", "voice": "how they sound delivering", '
            '"mechanics": ["4-5 signature techniques"], "themes": ["recurring themes"], "imagery": ["8-12 concrete images from their life"], '
            '"vocabulary": ["slang/phrases they use"], "never": ["3 things this artist would never write"], '
            '"remix_method": "step by step: how this persona turns ANY song into their remix (keep the song\'s story beat per bar, '
            'swap in their imagery, re-rhyme on their signature vowels, fit their pocket)", '
            '"system_prompt": "the full persona system prompt, second person, 250-400 words"}')
    out = llm.extract_json(llm.complete([{'role': 'user', 'content': user}], system, temperature=0.8, max_tokens=3000))
    if not isinstance(out, dict) or not out.get('system_prompt'):
        raise llm.LLMError('The Forge could not build the persona from the model reply. Try again.')
    pid = 'you-' + re.sub(r'[^a-z0-9]+', '-', stage_name.lower()).strip('-')
    rng = random.Random(fp)
    hue = rng.randint(0, 359)
    persona = {
        'id': pid, 'name': stage_name, 'handle': stage_name.upper(), 'role': 'rapper', 'order': 5, 'glyph': stage_name[:1].upper(),
        'color': f'hsl({hue} 90% 60%)', 'accent': f'hsl({(hue + 150) % 360} 80% 55%)', 'uses_doctrine': True,
        'pocket': _measured_pocket(), 'tagline': out.get('tagline', ''), 'voice': out.get('voice', ''),
        'mechanics': out.get('mechanics', [])[:6], 'signature': (out.get('themes') or [''])[0],
        'greeting': f"{stage_name} in the building. Give me a song and I will make it mine.",
        'prompt': out['system_prompt'] + '\n\nREMIX METHOD\n' + out.get('remix_method', ''),
        'forged': {'fingerprint': fp, 'position': pos, 'imagery': out.get('imagery', []), 'vocabulary': out.get('vocabulary', []),
                   'never': out.get('never', []), 'themes': out.get('themes', [])},
    }
    db.save_custom_persona(pid, persona)
    award = {'persona_id': pid, 'stage_name': stage_name, 'fingerprint': fp, 'ts': db.now()}
    db.set_setting('forge_award', award)
    db.log_event('academy', 'forge', f'Persona forged: {stage_name}')
    return {'persona': personas.public(persona) | {'forged': persona['forged']}, 'skill_md': skill_md(persona)}


def skill_md(persona):
    """Exportable Agent Skill: turns any song into the student's remix."""
    f = persona.get('forged', {})
    lo, hi = persona.get('pocket', [3, 7])
    name = re.sub(r'[^a-z0-9-]+', '-', persona['name'].lower()).strip('-') or 'my-remix'
    lines = [
        '---', f'name: {name}-remix',
        f"description: Remix any song in the voice of {persona['name']}. Use when asked to rewrite, flip or remix lyrics as "
        f"{persona['name']}: keeps each bar's story beat, re-rhymes on signature vowels and fits a {lo}-{hi} syllables/sec pocket.",
        '---', '', f"# {persona['name']}", '', persona.get('tagline', ''), '',
        '## Voice', persona.get('voice', ''), '', '## Persona', persona.get('prompt', ''), '',
        '## Imagery bank (from real life)', *[f'- {x}' for x in f.get('imagery', [])], '',
        '## Vocabulary', *[f'- {x}' for x in f.get('vocabulary', [])], '',
        '## Never', *[f'- {x}' for x in f.get('never', [])], '',
        '## How to remix a song', '1. Split the source lyrics into bars (one line = one bar) and note each bar\'s story beat.',
        f'2. Keep the beat count. At the target BPM aim for {lo}-{hi} syllables per second per bar.',
        '3. Rewrite each bar with imagery from the bank above; keep the original meaning arc.',
        '4. Re-rhyme on vowel chains, not spellings; hold an end rhyme and add one internal in a matching slot.',
        '5. Never copy the original wording beyond the title or hook idea; the result must be original.',
        '', f"*Forged in OpenField Station · path {f.get('fingerprint', '')[:12]}*",
    ]
    return '\n'.join(lines)
