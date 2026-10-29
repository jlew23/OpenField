"""The Academy game layer.

Design rules (from the persona-lens debate, see docs/STATION.md):
- XP is earned by writing. Showing up is free, but it pays nothing.
- A weekly rhythm (N practice days out of 7) by default; a strict daily streak is opt-in.
- Variable rewards (chests) only drop after you submit work, and never sell streak insurance.
- Soft gates: any chapter's drills can be "peeked" for half XP; bosses certify a level.
- Mastery is visible: three-star chapters, a skill radar, matrix tiers.

Every action returns reward events for the UI (toasts, confetti, sounds):
  {'type': 'xp'|'rank'|'achievement'|'rhythm'|'quest'|'chest'|'card'|'tier'|'unlock'|'boss'|'rung'|'grade'|'star', 'label': ...}
"""
import datetime as dt, hashlib, json, random

from . import db, bible

RANKS = [
    (0, 'Open Mic Rookie'), (150, 'Notebook Scribbler'), (400, 'Cypher Regular'), (800, 'Battle Tested'),
    (1400, 'Mixtape Hustler'), (2200, 'Studio Rat'), (3300, 'Featured Verse'), (4800, 'Headliner'),
    (6800, 'Platinum Pen'), (9500, 'Hall of Fame Pen'), (13000, 'GOAT Status'),
]

XP = {'submit': 15, 'pass': 30, 'grade_bonus': 50, 'first_try': 15, 'improve': 10, 'vowel_match': 2,
      'boss': 300, 'quiz_right': 8, 'quiz_perfect': 40, 'lab': 30, 'transcribe': 25, 'cypher': 20,
      'battle_win': 40, 'card': 10, 'tier': 40, 'rung': 100, 'star': 25, 'sandbox': 2}

ACHIEVEMENTS = {
    'first_blood': ('First Blood', 'Submit your first drill.', '🩸', 25),
    'first_pass': ('On The Board', 'Pass your first drill.', '✅', 40),
    'rhythm_1': ('In The Pocket', 'Hit your weekly practice goal.', '🥁', 50),
    'rhythm_4': ('Four On The Floor', 'Hit your weekly goal four weeks running.', '🎚️', 200),
    'streak_7': ('Seven Days Straight', '7-day daily streak (daily mode).', '📅', 100),
    'comeback': ('The Comeback', 'Come back after a week away and write.', '🔁', 40),
    'vowel_hunter': ('Vowel Hunter', 'Verify 100 vowel matches.', '🎯', 150),
    'double_stitch': ('Double-Stitched', 'Land an internal in the same slot with a held end rhyme.', '🧵', 120),
    'multi_monster': ('Multi Monster', 'Write a 5-syllable rhyme chain.', '👹', 150),
    'perfectionist': ('Perfectionist', 'Score 95 or higher on a drill.', '💎', 150),
    'rewrite_culture': ('Rewrite Culture', 'Improve the same drill three times in a row.', '♻️', 100),
    'idiom_flipper': ('Idiom Flipper', 'Flip 10 idioms.', '🙃', 100),
    'centurion': ('Centurion', 'Write 100 bars in the Academy.', '💯', 150),
    'thousand_bars': ('Thousand Bars', 'Write 1,000 bars.', '🏛️', 600),
    'night_owl': ('Night Owl', 'Submit work after midnight.', '🦉', 30),
    'early_bird': ('Early Bird', 'Submit work before 7am.', '🐦', 30),
    'side_door': ('Side Door', 'Peek ahead and pass a drill from a later chapter.', '🚪', 40),
    'explorer': ('Off The Map', 'Discover a rhyme pattern that is not in the matrix.', '🧭', 60),
    'lab_rat': ('Lab Rat', 'Finish your first Listening Lab.', '🧪', 50),
    'quiz_ace': ('Quiz Ace', 'Perfect score in a Lab quiz.', '🧠', 100),
    'top_of_class': ('Top Of The Class', 'Beat every classmate in a Lab quiz.', '👑', 150),
    'first_cypher': ('Pass The Mic', 'Run your first cypher.', '🎤', 30),
    'giant_killer': ('Giant Killer', 'Win a battle against a persona.', '⚔️', 120),
    'story_architect': ('Story Architect', 'Pass a story drill with all of the Core Five.', '🏗️', 120),
    'three_stars': ('Three Stars', 'Earn three stars on a chapter.', '⭐', 100),
    'tier_gold': ('Gold Pattern', 'Take a vowel pattern to gold.', '🥇', 120),
    'card_18': ('Full Matrix', 'Reveal all 18 vowel patterns.', '🌈', 400),
    'open_book': ('Open Book', 'Answer 25 Forge questions.', '📖', 100),
    'grad_1': ('Graduate: Foundations', 'Beat the Level 1 boss.', '🎓', 0),
    'grad_2': ('Graduate: Craft', 'Beat the Level 2 boss.', '🎓', 0),
    'grad_3': ('Graduate: Density', 'Beat the Level 3 boss.', '🎓', 0),
    'quests_7': ('Quest Grinder', 'Clear all daily quests on 7 days.', '🗡️', 150),
}

QUESTS = [  # every quest is something you write or study actively
    ('write_bars', 'Write {n} bars', [4, 8, 12, 16], 'bars'),
    ('pass_drill', 'Pass a drill with {n}+', [70, 75, 80, 85], 'pass_score'),
    ('vowels', 'Verify {n} vowel matches', [5, 10, 15, 15], 'vowel_verified'),
    ('cypher', 'Run a cypher', [1], 'cyphers'),
    ('lab', 'Finish a Listening Lab', [1], 'labs'),
    ('flip', 'Flip {n} idiom(s)', [1, 1, 2, 2], 'flips'),
    ('chain', 'Land a {n}-syllable rhyme chain', [2, 3, 4, 5], 'chain'),
    ('sandbox', 'Find {n} rhymes in the Rhyme Lab', [5, 8, 10, 12], 'sandbox'),
]

COSMETICS = [  # chest loot besides XP and cards
    ('theme', 'Midnight Neon'), ('theme', 'Gold Chain'), ('theme', 'Analog Tape'), ('theme', 'Arena Lights'),
    ('theme', 'Vinyl Crackle'), ('title', 'The Wordsmith'), ('title', 'Vowel Surgeon'), ('title', 'Slant King'),
    ('title', 'Scheme Weaver'), ('title', 'Bar Mechanic'), ('frame', 'Gold Frame'), ('frame', 'Neon Frame'),
]

RANK_UNLOCKS = {
    'Notebook Scribbler': ('theme', 'Midnight Neon'), 'Battle Tested': ('theme', 'Gold Chain'),
    'Mixtape Hustler': ('title', 'The Hustler'), 'Studio Rat': ('theme', 'Analog Tape'),
    'Featured Verse': ('feature', "Masters' challenge drills on every persona page"),
    'Headliner': ('theme', 'Arena Lights'), 'Platinum Pen': ('title', 'Platinum Pen'),
    'Hall of Fame Pen': ('theme', 'Hall of Fame'), 'GOAT Status': ('title', 'GOAT'),
}

TIERS = [(30, 'gold'), (15, 'silver'), (5, 'bronze'), (1, 'revealed')]

RADAR_AXES = {  # axis -> criteria ids that feed it
    'Image': ['image', 'opening'], 'Rhyme': ['rhyme', 'scheme', 'end', 'landings'], 'Internals': ['internal'],
    'Flow': ['pocket', 'variety'], 'Vowel ear': ['matches'], 'Story': ['core', 'hook', 'cut'],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS academy_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL, kind TEXT NOT NULL, form TEXT NOT NULL,
  content TEXT NOT NULL, auto TEXT NOT NULL DEFAULT '{}', coach TEXT NOT NULL DEFAULT '{}',
  score INTEGER NOT NULL DEFAULT 0, letter TEXT NOT NULL DEFAULT '', passed INTEGER NOT NULL DEFAULT 0,
  xp INTEGER NOT NULL DEFAULT 0, report TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_ref ON academy_submissions(ref, id);
CREATE TABLE IF NOT EXISTS academy_xp (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, day TEXT NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS academy_achievements (id TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS academy_cards (id TEXT PRIMARY KEY, ts REAL NOT NULL, count INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS academy_days (
  day TEXT PRIMARY KEY, checked_in INTEGER NOT NULL DEFAULT 0, practiced INTEGER NOT NULL DEFAULT 0,
  stats TEXT NOT NULL DEFAULT '{}', quests TEXT NOT NULL DEFAULT '[]', chest INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS academy_reads (chapter TEXT PRIMARY KEY, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS academy_loot (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS academy_reviews (
  item TEXT PRIMARY KEY, kind TEXT NOT NULL, due TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0, ts REAL NOT NULL
);
"""


def init():
    with db.connect() as con:
        con.executescript(SCHEMA)
        cols = {r[1] for r in con.execute('PRAGMA table_info(academy_days)').fetchall()}
        if 'practiced' not in cols:
            con.execute('ALTER TABLE academy_days ADD COLUMN practiced INTEGER NOT NULL DEFAULT 0')


def today():
    return dt.date.today().isoformat()


def week_key(day=None):
    d = dt.date.fromisoformat(day) if day else dt.date.today()
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


# ------------------------------------------------------------------ profile & preferences

DEFAULT_PROFILE = {
    'name': '', 'title': 'Sir', 'created': '', 'placement': 1, 'rungs': [],
    'theme': 'default', 'chosen_title': '', 'frame': '',
    'rhythm_mode': 'weekly', 'weekly_goal': 3, 'streak': 0, 'best_streak': 0, 'last_day': '',
    'rhythm_weeks': 0, 'best_rhythm': 0, 'last_rhythm_week': '',
    'session': 10, 'jarvis_tone': 'dry', 'show_totals': True, 'leaderboard': True, 'sounds': True,
}


def profile():
    return {**DEFAULT_PROFILE, **(db.get_setting('academy_profile', {}) or {})}


def save_profile(p):
    db.set_setting('academy_profile', p)


def update_profile(patch):
    p = profile()
    for k in ('name', 'title', 'theme', 'chosen_title', 'frame'):
        if k in patch:
            p[k] = str(patch[k])[:60]
    if patch.get('rhythm_mode') in ('weekly', 'daily'):
        p['rhythm_mode'] = patch['rhythm_mode']
    if 'weekly_goal' in patch:
        p['weekly_goal'] = max(1, min(7, int(patch['weekly_goal'])))
    if patch.get('session') in (3, 10, 30, '3', '10', '30'):
        p['session'] = int(patch['session'])
    if patch.get('jarvis_tone') in ('gentle', 'dry', 'roast'):
        p['jarvis_tone'] = patch['jarvis_tone']
    for k in ('show_totals', 'leaderboard', 'sounds'):
        if k in patch:
            p[k] = bool(patch[k])
    if not p['created']:
        p['created'] = today()
    save_profile(p)
    return p


def total_xp():
    with db.connect() as con:
        return con.execute('SELECT COALESCE(SUM(amount),0) FROM academy_xp').fetchone()[0]


def rank_for(xp):
    current, nxt = RANKS[0], None
    for i, (need, name) in enumerate(RANKS):
        if xp >= need:
            current = (need, name)
            nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
    progress = 1.0 if not nxt else (xp - current[0]) / (nxt[0] - current[0])
    return {'name': current[1], 'floor': current[0], 'next': nxt[1] if nxt else None,
            'next_at': nxt[0] if nxt else None, 'progress': round(progress, 3), 'index': RANKS.index(current)}


def _award(amount, reason, events):
    amount = int(round(amount))
    if amount <= 0:
        return
    before = total_xp()
    with db.connect() as con:
        con.execute('INSERT INTO academy_xp(ts,day,amount,reason) VALUES(?,?,?,?)', (db.now(), today(), amount, reason))
    events.append({'type': 'xp', 'amount': amount, 'label': f'+{amount} XP · {reason}'})
    r0, r1 = rank_for(before), rank_for(before + amount)
    if r1['name'] != r0['name']:
        reward = RANK_UNLOCKS.get(r1['name'])
        if reward and reward[0] in ('theme', 'title'):
            _grant_loot(reward[0], reward[1])
        events.append({'type': 'rank', 'label': f"Rank up: {r1['name']}", 'rank': r1['name'],
                       'reward': f'{reward[0].title()} unlocked: {reward[1]}' if reward else ''})
        db.log_event('academy', 'rank', f"Reached rank {r1['name']}")


def has_achievement(aid):
    with db.connect() as con:
        return con.execute('SELECT 1 FROM academy_achievements WHERE id=?', (aid,)).fetchone() is not None


def unlock(aid, events):
    if aid not in ACHIEVEMENTS or has_achievement(aid):
        return
    name, desc, icon, xp = ACHIEVEMENTS[aid]
    with db.connect() as con:
        con.execute('INSERT INTO academy_achievements(id,ts) VALUES(?,?)', (aid, db.now()))
    events.append({'type': 'achievement', 'id': aid, 'label': f'{icon} {name}', 'desc': desc, 'icon': icon})
    db.log_event('academy', 'achievement', f'Achievement unlocked: {name}')
    _award(xp, f'Achievement: {name}', events)


def _grant_loot(kind, name):
    lid = f'{kind}:{name}'
    with db.connect() as con:
        new = con.execute('SELECT 1 FROM academy_loot WHERE id=?', (lid,)).fetchone() is None
        if new:
            con.execute('INSERT INTO academy_loot(id,kind,name,ts) VALUES(?,?,?,?)', (lid, kind, name, db.now()))
    return new


def loot():
    with db.connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM academy_loot ORDER BY ts').fetchall()]


# ------------------------------------------------------------------ days, rhythm, quests

def _day(day=None):
    day = day or today()
    with db.connect() as con:
        r = con.execute('SELECT * FROM academy_days WHERE day=?', (day,)).fetchone()
        if r is None:
            con.execute('INSERT INTO academy_days(day) VALUES(?)', (day,))
            r = con.execute('SELECT * FROM academy_days WHERE day=?', (day,)).fetchone()
    out = dict(r)
    out['stats'] = json.loads(out['stats'] or '{}')
    out['quests'] = json.loads(out['quests'] or '[]')
    return out


def _save_day(d):
    with db.connect() as con:
        con.execute('UPDATE academy_days SET checked_in=?, practiced=?, stats=?, quests=?, chest=? WHERE day=?',
                    (d['checked_in'], d.get('practiced', 0), json.dumps(d['stats']), json.dumps(d['quests']), d['chest'], d['day']))


def _make_quests(day, level):
    seed = int(hashlib.sha256(f'{day}:{level}'.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    out = []
    for qid, label, amounts, stat in rng.sample(QUESTS, 3):
        n = amounts[min(len(amounts) - 1, max(0, level - 1))]
        out.append({'id': qid, 'label': label.format(n=n), 'stat': stat, 'need': n, 'done': False, 'xp': 25 + 10 * level})
    return out


def current_level():
    data = bible.load()
    passed = passed_bosses()
    lvl = max([profile().get('placement', 1)] + [b + 1 for b in passed])
    return min(lvl, len(data['levels']) if data and data['levels'] else 4)


def practice_days(week=None):
    week = week or week_key()
    with db.connect() as con:
        days = [r['day'] for r in con.execute('SELECT day FROM academy_days WHERE practiced=1').fetchall()]
    return sorted(d for d in days if week_key(d) == week)


def rhythm():
    p = profile()
    days = practice_days()
    return {'mode': p['rhythm_mode'], 'goal': p['weekly_goal'], 'days_this_week': len(days), 'days': days,
            'weeks': p['rhythm_weeks'], 'best_weeks': p['best_rhythm'], 'streak': p['streak'], 'best_streak': p['best_streak']}


def checkin():
    """Sign in. Free and guilt-free: sets up today's quests and greets you. No XP for showing up."""
    events = []
    p = profile()
    d = _day()
    if not d['quests']:
        d['quests'] = _make_quests(d['day'], current_level())
    if not d['checked_in']:
        d['checked_in'] = 1
        last = p.get('last_day')
        if last:
            gap = (dt.date.today() - dt.date.fromisoformat(last)).days
            if gap >= 7:
                events.append({'type': 'rhythm', 'label': '👋 Welcome back. Your next submission earns a comeback bonus.', 'comeback': True})
                p['comeback'] = True
        save_profile(p)
    _save_day(d)
    return events


def _mark_practiced(events):
    """First real work of the day: counts toward the weekly rhythm (or daily streak)."""
    p = profile()
    d = _day()
    if d.get('practiced'):
        return
    d['practiced'] = 1
    _save_day(d)
    last = p.get('last_day')
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    p['streak'] = p['streak'] + 1 if last == yesterday else 1
    p['best_streak'] = max(p['best_streak'], p['streak'])
    p['last_day'] = today()
    if p.pop('comeback', False):
        unlock('comeback', events)
        _award(30, 'Comeback bonus', events)
    days = len(practice_days())
    if p['rhythm_mode'] == 'daily':
        events.append({'type': 'rhythm', 'label': f"🔥 Day {p['streak']}", 'streak': p['streak']})
        if p['streak'] >= 7:
            unlock('streak_7', events)
    else:
        events.append({'type': 'rhythm', 'label': f"🥁 {days}/{p['weekly_goal']} practice days this week", 'days': days})
    wk = week_key()
    if days >= p['weekly_goal'] and p.get('last_rhythm_week') != wk:
        prev = week_key((dt.date.today() - dt.timedelta(days=7)).isoformat())
        p['rhythm_weeks'] = p['rhythm_weeks'] + 1 if p.get('last_rhythm_week') == prev else 1
        p['best_rhythm'] = max(p['best_rhythm'], p['rhythm_weeks'])
        p['last_rhythm_week'] = wk
        save_profile(p)
        events.append({'type': 'rhythm', 'label': f"✅ Weekly goal hit · {p['rhythm_weeks']} week(s) in the pocket", 'goal': True})
        unlock('rhythm_1', events)
        if p['rhythm_weeks'] >= 4:
            unlock('rhythm_4', events)
    save_profile(p)


def bump(stat, amount=1, events=None, mode='add'):
    """Record a daily stat and resolve quests that depend on it."""
    events = events if events is not None else []
    d = _day()
    if not d['quests']:
        d['quests'] = _make_quests(d['day'], current_level())
    if mode == 'max':
        d['stats'][stat] = max(d['stats'].get(stat, 0), amount)
    else:
        d['stats'][stat] = d['stats'].get(stat, 0) + amount
    newly = []
    for q in d['quests']:
        if not q['done'] and d['stats'].get(q['stat'], 0) >= q['need']:
            q['done'] = True
            newly.append(q)
    _save_day(d)
    for q in newly:
        events.append({'type': 'quest', 'label': f"Quest complete: {q['label']}"})
        _award(q['xp'], f"Quest: {q['label']}", events)
    d = _day()
    if d['quests'] and all(q['done'] for q in d['quests']) and not d['chest']:
        d['chest'] = 1
        _save_day(d)
        events.append({'type': 'chest', 'label': '🎁 All quests cleared: guaranteed chest', 'guaranteed': True})
        open_chest(events, guaranteed=True)
        with db.connect() as con:
            if con.execute('SELECT COUNT(*) FROM academy_days WHERE chest=1').fetchone()[0] >= 7:
                unlock('quests_7', events)
    return events


def open_chest(events, guaranteed=False):
    """Variable reward. Only ever called after real work."""
    rng = random.Random()
    roll = rng.random()
    data = bible.load() or {}
    hidden = [p for p in data.get('matrix', []) if p['id'] not in cards()]
    if roll < 0.12 or (guaranteed and roll < 0.25):
        owned = {l['id'] for l in loot()}
        options = [c for c in COSMETICS if f'{c[0]}:{c[1]}' not in owned]
        if options:
            kind, name = rng.choice(options)
            _grant_loot(kind, name)
            events.append({'type': 'chest', 'label': f'💜 EPIC drop: {kind} "{name}"', 'rarity': 'epic'})
            return
    if roll < 0.5 and hidden:
        card = rng.choice(hidden)
        events.append({'type': 'chest', 'label': f"🃏 Rare drop: vowel pattern {card['name']} revealed", 'rarity': 'rare'})
        collect_card(card['id'], events, uses=0)
        return
    amount = rng.choice([20, 30, 40, 60, 100] if not guaranteed else [60, 80, 100, 150])
    events.append({'type': 'chest', 'label': f'🎁 {amount} bonus XP', 'rarity': 'epic' if amount >= 100 else 'common'})
    _award(amount, 'Chest', events)


# ------------------------------------------------------------------ matrix map (cards + tiers)

def tier_for(count):
    for need, name in TIERS:
        if count >= need:
            return name
    return 'hidden'


def collect_card(card_id, events, uses=1):
    """Reveal a pattern and/or add verified uses, announcing tier climbs."""
    with db.connect() as con:
        r = con.execute('SELECT count FROM academy_cards WHERE id=?', (card_id,)).fetchone()
        before = r['count'] if r else None
        if r:
            con.execute('UPDATE academy_cards SET count=count+? WHERE id=?', (uses, card_id))
        else:
            con.execute('INSERT INTO academy_cards(id,ts,count) VALUES(?,?,?)', (card_id, db.now(), max(uses, 1)))
        after = con.execute('SELECT count FROM academy_cards WHERE id=?', (card_id,)).fetchone()['count']
        revealed = con.execute("SELECT COUNT(*) FROM academy_cards WHERE id NOT LIKE 'x-%'").fetchone()[0]
    if before is None:
        if not card_id.startswith('x-'):
            schedule_review(card_id, 'card')
        disc = card_id.startswith('x-')
        events.append({'type': 'card', 'id': card_id,
                       'label': (f'🧭 Discovery: new pattern {card_id[2:].upper()}' if disc else f'🃏 Pattern revealed: {card_id.upper()}')})
        _award(XP['card'] * (3 if disc else 1), 'Discovery' if disc else 'Pattern revealed', events)
        if disc:
            unlock('explorer', events)
        if revealed >= 18:
            unlock('card_18', events)
    t0, t1 = tier_for(before or 0), tier_for(after)
    if before is not None and t1 != t0 and t1 in ('bronze', 'silver', 'gold'):
        events.append({'type': 'tier', 'id': card_id, 'tier': t1, 'label': f'{ {"bronze": "🥉", "silver": "🥈", "gold": "🥇"}[t1] } {card_id.upper()} reached {t1}'})
        _award(XP['tier'], f'{t1.title()} tier', events)
        if t1 == 'gold':
            unlock('tier_gold', events)


def cards():
    with db.connect() as con:
        return {r['id']: r['count'] for r in con.execute('SELECT * FROM academy_cards').fetchall()}


SOUND_NAMES = {'ay': 'EY', 'eh': 'EH', 'oh': 'OW', 'eye': 'AY', 'ih': 'IH', 'ah': 'AA', 'ee': 'IY', 'uh': 'AH',
               'oo': 'UW', 'aw': 'AO', 'ow': 'AW', 'ah/aw': 'AA'}


def pattern_vowels(pat):
    if 'cat' in pat['sounds']:
        return ('AE', 'AE')
    parts = [x.strip().lower() for x in pat['sounds'].replace('–', '-').split('-')]
    want = tuple(SOUND_NAMES.get(x) for x in parts)
    return want if len(want) == 2 and None not in want else None


def pattern_for_vowels(v1, v2):
    data = bible.load() or {}
    near = {'AO': 'AA', 'AA': 'AO'}
    for pat in data.get('matrix', []):
        want = pattern_vowels(pat)
        if want and (want == (v1, v2) or want == (near.get(v1, v1), v2) or want == (v1, near.get(v2, v2))):
            return pat['id']
    return None


def card_for_phrase(phrase):
    from .grading import vowel_chain
    chain = [v for v in vowel_chain(phrase)]
    if len(chain) < 2:
        return None
    from . import flow
    syl = flow.syllabify_line(phrase)
    stressed = [s['vowel'] for s in syl if s['stress'] > 0]
    pair = (stressed[-2], stressed[-1]) if len(stressed) >= 2 else (chain[-2], chain[-1])
    return pattern_for_vowels(*pair) or pattern_for_vowels(chain[-2], chain[-1])


def harvest_patterns(analysis, events):
    """Credit matrix patterns (or discoveries) for the rhyme chains in submitted bars."""
    if not analysis:
        return
    seen = {}
    for b in analysis['bars']:
        fam_syl = {}
        for s in b['syllables']:
            if 'rhyme' in s:
                fam_syl.setdefault(s['rhyme'], []).append(s)
        for fam, syl in fam_syl.items():
            stressed = [s['vowel'] for s in syl if s['stress'] > 0] or [s['vowel'] for s in syl]
            if len(syl) >= 2 and len(stressed) >= 1:
                pair = (syl[-2]['vowel'], syl[-1]['vowel']) if len(stressed) < 2 else (stressed[-2], stressed[-1])
                seen[(fam, pair)] = True
    for (_, pair) in seen:
        pid = pattern_for_vowels(*pair)
        if pid:
            collect_card(pid, events, uses=1)
        elif pair[0] not in ('AH', 'IH') or pair[1] not in ('AH', 'IH'):
            collect_card(f'x-{pair[0].lower()}-{pair[1].lower()}', events, uses=1)


# ------------------------------------------------------------------ progress, stars, radar

def reads():
    with db.connect() as con:
        return {r['chapter'] for r in con.execute('SELECT chapter FROM academy_reads').fetchall()}


def mark_read(chapter_id):
    with db.connect() as con:
        if con.execute('SELECT 1 FROM academy_reads WHERE chapter=?', (chapter_id,)).fetchone() is None:
            con.execute('INSERT INTO academy_reads(chapter,ts) VALUES(?,?)', (chapter_id, db.now()))
    return []


def best_by_ref():
    with db.connect() as con:
        rs = con.execute('SELECT ref, MAX(score) AS best, MAX(passed) AS passed, COUNT(*) AS attempts '
                         'FROM academy_submissions GROUP BY ref').fetchall()
    return {r['ref']: {'best': r['best'], 'passed': bool(r['passed']), 'attempts': r['attempts']} for r in rs}


def passed_bosses():
    return sorted(int(k.split('-')[1]) for k, v in best_by_ref().items() if k.startswith('boss-') and v['passed'])


def chapter_stars(chapter, best):
    drills = chapter['drills']
    if not drills:
        return 0
    scores = [best.get(d['id'], {}).get('best') or 0 for d in drills]
    passed = all(best.get(d['id'], {}).get('passed') for d in drills)
    if not passed:
        return 0
    return 3 if min(scores) >= 95 else 2 if min(scores) >= 85 else 1


def chapter_states(data):
    """open / done / peek per chapter. 'peek' = ahead of you: playable for half XP."""
    best = best_by_ref()
    level_open = current_level()
    states, stars = {}, {}
    for lvl in data['levels']:
        prev_ok = True
        for c in lvl['chapters']:
            st = chapter_stars(c, best)
            stars[c['id']] = st
            if st:
                state = 'done'
            elif lvl['level'] <= level_open and prev_ok:
                state = 'open'
            else:
                state = 'peek'
            states[c['id']] = state
            prev_ok = bool(st) or (not c['drills'] and prev_ok)
    return states, stars


def radar():
    with db.connect() as con:
        rows = con.execute('SELECT auto FROM academy_submissions ORDER BY id DESC LIMIT 30').fetchall()
    sums = {k: [] for k in RADAR_AXES}
    for r in rows:
        try:
            crits = json.loads(r['auto']).get('criteria', [])
        except ValueError:
            continue
        for c in crits:
            for axis, ids in RADAR_AXES.items():
                if c.get('id') in ids:
                    sums[axis].append(c.get('score', 0))
    return {axis: (round(sum(v) / len(v)) if v else 0) for axis, v in sums.items()}


def session_plan(minutes=None):
    """A ready-made session sized to the time you have (3 / 10 / 30 minutes)."""
    p = profile()
    minutes = int(minutes or p['session'])
    data = bible.load()
    level = current_level()
    nxt = None
    if data:
        states, _ = chapter_states(data)
        for c in bible.chapters(data):
            if states.get(c['id']) == 'open':
                nxt = c
                break
    weakest = None
    r = radar()
    if any(r.values()):
        weakest = min((v, k) for k, v in r.items() if v)[1]
    steps = []
    if minutes <= 3:
        steps = [{'kind': 'onebar', 'minutes': 3, 'title': 'One Bar Drop',
                  'text': 'Jarvis hands you a word from your weakest pattern. Write one or two bars, see the colours, done.'}]
    elif minutes <= 10:
        steps = [{'kind': 'sandbox', 'minutes': 3, 'title': 'Rhyme Lab warm-up', 'text': 'Vowel-strip a phrase and find 5 matches.'},
                 {'kind': 'drill', 'minutes': 5, 'title': f"Drill: {nxt['title']}" if nxt else 'Drill', 'chapter': nxt['id'] if nxt else None,
                  'text': 'One drill from where you are in the book.'},
                 {'kind': 'cypher', 'minutes': 2, 'title': 'Pass the mic', 'text': 'Drop those bars in the cypher and hear the crew answer.'}]
    else:
        steps = [{'kind': 'sandbox', 'minutes': 5, 'title': 'Warm-up: the vowel drill', 'text': 'Strip a phrase and list 15 matches.'},
                 {'kind': 'drill', 'minutes': 10, 'title': f"Chapter drill: {nxt['title']}" if nxt else 'Chapter drill', 'chapter': nxt['id'] if nxt else None,
                  'text': 'Aim for three stars.'},
                 {'kind': 'lab', 'minutes': 8, 'title': 'Short Listening Lab', 'text': 'Transcribe and colour 4 bars of a track from your Spotify.'},
                 {'kind': 'cypher', 'minutes': 5, 'title': 'Cypher or Battle', 'text': 'Use your drill bars against the crew.'},
                 {'kind': 'wrap', 'minutes': 2, 'title': 'Wrap', 'text': 'Radar check, report card, chest.'}]
    return {'minutes': minutes, 'level': level, 'weakest': weakest, 'steps': steps,
            'routine': (data or {}).get('daily', {}).get(level)}


def snapshot():
    """Everything the Academy dashboard needs in one call."""
    data = bible.load()
    xp = total_xp()
    p = profile()
    d = _day()
    with db.connect() as con:
        ach = {r['id']: r['ts'] for r in con.execute('SELECT * FROM academy_achievements').fetchall()}
        bars_written = con.execute("SELECT COALESCE(SUM(json_extract(auto,'$.facts.bars')),0) FROM academy_submissions").fetchone()[0]
        subs = con.execute('SELECT COUNT(*) FROM academy_submissions').fetchone()[0]
        recent = db.rows(con.execute('SELECT id, ref, kind, form, score, letter, passed, xp, created_at FROM academy_submissions ORDER BY id DESC LIMIT 12').fetchall())
        by_day = db.rows(con.execute('SELECT day, SUM(amount) AS xp FROM academy_xp GROUP BY day ORDER BY day DESC LIMIT 28').fetchall())
    states, stars = chapter_states(data) if data else ({}, {})
    card_counts = cards()
    matrix = []
    for pat in (data or {}).get('matrix', []):
        n = card_counts.get(pat['id'])
        matrix.append({'id': pat['id'], 'name': pat['name'], 'sounds': pat['sounds'],
                       'count': n or 0, 'tier': tier_for(n) if n is not None else 'hidden'})
    discoveries = [{'id': k, 'count': v, 'tier': tier_for(v)} for k, v in card_counts.items() if k.startswith('x-')]
    return {
        'has_bible': bool(data), 'profile': p, 'xp': xp, 'rank': rank_for(xp), 'ranks': RANKS,
        'level': current_level(), 'today': d, 'rhythm': rhythm(), 'achievements': [
            {'id': k, 'name': v[0], 'desc': v[1], 'icon': v[2], 'xp': v[3], 'unlocked': k in ach, 'ts': ach.get(k)}
            for k, v in ACHIEVEMENTS.items()],
        'matrix': matrix, 'discoveries': discoveries, 'loot': loot(), 'best': best_by_ref(),
        'reads': sorted(reads()), 'chapters': states, 'stars': stars, 'bosses_passed': passed_bosses(),
        'bars_written': bars_written, 'submissions': subs, 'recent': recent, 'xp_by_day': by_day, 'radar': radar(),
    }


# ------------------------------------------------------------------ paying out work

def _common_payout(events, bars=0):
    """Rhythm + chest roll for any real work."""
    _mark_practiced(events)
    if bars:
        bump('bars', bars, events)
    hour = dt.datetime.now().hour
    if hour < 4:
        unlock('night_owl', events)
    elif 4 <= hour < 7:
        unlock('early_bird', events)


def record_submission(ref, kind, form, content, auto, coach, grade, report_fn=None, peek=False):
    """Store a graded attempt and pay out XP, achievements, quests and loot. Returns (id, events)."""
    events = []
    prior = best_by_ref().get(ref)
    facts = auto.get('facts', {})
    bars = facts.get('bars', 0) or 0
    xp = XP['submit']
    if grade['passed']:
        xp += XP['pass'] + XP['grade_bonus'] * grade['score'] / 100
        if not prior:
            xp += XP['first_try']
    if prior and grade['score'] > (prior['best'] or 0):
        xp += XP['improve']
    if peek:
        xp /= 2
    xp = int(round(xp))
    stored_auto = {k: v for k, v in auto.items() if k != 'analysis'}
    with db.connect() as con:
        cur = con.execute('INSERT INTO academy_submissions(ref,kind,form,content,auto,coach,score,letter,passed,xp,created_at) '
                          'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (ref, kind, form, json.dumps(content), json.dumps(stored_auto), json.dumps(coach or {}),
                           grade['score'], grade['letter'], int(grade['passed']), xp, db.now()))
        sid = cur.lastrowid
        n_pass = con.execute('SELECT COUNT(*) FROM academy_submissions WHERE passed=1').fetchone()[0]
        total_bars = con.execute("SELECT COALESCE(SUM(json_extract(auto,'$.facts.bars')),0) FROM academy_submissions").fetchone()[0]
        verified = con.execute("SELECT COALESCE(SUM(json_extract(auto,'$.facts.verified')),0) FROM academy_submissions").fetchone()[0]
        flips = con.execute("SELECT COUNT(*) FROM academy_submissions WHERE form='idiom' AND passed=1").fetchone()[0]
        attempts = [r['score'] for r in con.execute('SELECT score FROM academy_submissions WHERE ref=? ORDER BY id', (ref,)).fetchall()]
    label = f"{grade['letter']} · {grade['score']}/100"
    events.append({'type': 'grade', 'label': label, 'score': grade['score'], 'letter': grade['letter'], 'passed': grade['passed']})
    _award(xp, f"{'Passed' if grade['passed'] else 'Attempted'} {ref}{' (peek)' if peek else ''}", events)
    if facts.get('verified'):
        _award(XP['vowel_match'] * facts['verified'], 'Vowel matches verified', events)
    unlock('first_blood', events)
    if n_pass:
        unlock('first_pass', events)
    if grade['score'] >= 95:
        unlock('perfectionist', events)
    if total_bars >= 100:
        unlock('centurion', events)
    if total_bars >= 1000:
        unlock('thousand_bars', events)
    if verified >= 100:
        unlock('vowel_hunter', events)
    if flips >= 10:
        unlock('idiom_flipper', events)
    if (facts.get('longest_chain') or 0) >= 5:
        unlock('multi_monster', events)
    if any(p.get('internal') and p.get('end') for p in facts.get('pairs') or []):
        unlock('double_stitch', events)
    if peek and grade['passed']:
        unlock('side_door', events)
    if form == 'story' and grade['passed'] and all((content.get('core_five') or {}).get(k) for k in ('protagonist', 'setting', 'objective', 'obstacle', 'turn')):
        unlock('story_architect', events)
    if len(attempts) >= 3 and attempts[-1] > attempts[-2] > attempts[-3]:
        unlock('rewrite_culture', events)
    # stars
    data = bible.load()
    if data and kind == 'drill':
        ch, _ = bible.find_drill(data, ref)
        if ch:
            best = best_by_ref()
            new_st = chapter_stars(ch, best)
            old_best = dict(best)
            old_best[ref] = prior or {'best': 0, 'passed': False}
            old_st = chapter_stars(ch, old_best)
            if new_st > old_st:
                events.append({'type': 'star', 'label': f"{'⭐' * new_st} {ch['title']}", 'stars': new_st})
                _award(XP['star'] * (new_st - old_st), f'{new_st}-star chapter', events)
                if new_st == 3:
                    unlock('three_stars', events)
    # bosses
    if kind == 'boss' and grade['passed'] and not (prior and prior['passed']):
        lvl = int(ref.split('-')[1])
        events.append({'type': 'boss', 'label': f'🏆 LEVEL {lvl} BOSS DEFEATED', 'level': lvl})
        _award(XP['boss'], f'Level {lvl} graduation', events)
        unlock(f'grad_{lvl}', events)
        events.append({'type': 'unlock', 'label': f'🔓 Level {lvl + 1} certified open'})
        db.log_event('academy', 'boss', f'Level {lvl} graduation test passed')
    # matrix map
    if form == 'vowel' and facts.get('verified', 0) >= 3:
        cid = card_for_phrase(content.get('phrase', ''))
        if cid:
            collect_card(cid, events, uses=facts['verified'])
    harvest_patterns(auto.get('analysis'), events)
    # quests, rhythm, chest
    if facts.get('verified'):
        bump('vowel_verified', facts['verified'], events)
    if grade['passed']:
        bump('pass_score', grade['score'], events, mode='max')
    if form == 'idiom' and grade['passed']:
        bump('flips', 1, events)
    if facts.get('longest_chain'):
        bump('chain', facts['longest_chain'], events, mode='max')
    _common_payout(events, bars)
    if grade['passed'] and random.random() < 0.35:
        open_chest(events)
    if report_fn:
        report = report_fn(events)
        with db.connect() as con:
            con.execute('UPDATE academy_submissions SET report=? WHERE id=?', (report, sid))
    db.log_event('academy', 'submission', f"{ref}: {label}", {'id': sid})
    return sid, events


def record_activity(kind, xp=0, bars=0, stat=None, achievements=(), analysis=None, label='', stat_n=1):
    """Pay out for cyphers, battles, labs and sandbox finds."""
    events = []
    if xp:
        _award(xp, label or kind, events)
    for a in achievements:
        unlock(a, events)
    if stat:
        bump(stat, max(1, int(stat_n)), events)
    harvest_patterns(analysis, events)
    _common_payout(events, bars)
    if kind in ('cypher', 'battle', 'lab') and random.random() < 0.25:
        open_chest(events)
    return events


def confirm_rung(rung):
    events = []
    p = profile()
    if rung in p['rungs']:
        return events
    p['rungs'] = sorted(set(p['rungs']) | {rung})
    save_profile(p)
    events.append({'type': 'rung', 'label': f'🪜 Rung {rung} mastered', 'rung': rung})
    _award(XP['rung'], f'Rung {rung}', events)
    return events


def set_placement(level):
    p = profile()
    p['placement'] = max(1, min(4, int(level)))
    save_profile(p)
    return p


def submission(sid):
    with db.connect() as con:
        r = con.execute('SELECT * FROM academy_submissions WHERE id=?', (sid,)).fetchone()
    if not r:
        return None
    out = dict(r)
    for k in ('content', 'auto', 'coach'):
        out[k] = json.loads(out[k] or '{}')
    return out


def history(ref=None, limit=50):
    q = 'SELECT id, ref, kind, form, score, letter, passed, xp, created_at FROM academy_submissions'
    with db.connect() as con:
        if ref:
            rs = con.execute(q + ' WHERE ref=? ORDER BY id DESC LIMIT ?', (ref, limit)).fetchall()
        else:
            rs = con.execute(q + ' ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return db.rows(rs)


# ------------------------------------------------------------------ spaced retrieval + adaptive difficulty

REVIEW_STEPS = [1, 3, 7, 14, 30, 60]  # days


def schedule_review(item, kind, step=0):
    due = (dt.date.today() + dt.timedelta(days=REVIEW_STEPS[min(step, len(REVIEW_STEPS) - 1)])).isoformat()
    with db.connect() as con:
        con.execute('INSERT INTO academy_reviews(item,kind,due,step,ts) VALUES(?,?,?,?,?) '
                    'ON CONFLICT(item) DO UPDATE SET due=excluded.due, step=excluded.step, ts=excluded.ts',
                    (item, kind, due, step, db.now()))


def reviews_due(limit=5):
    with db.connect() as con:
        return [dict(r) for r in con.execute('SELECT * FROM academy_reviews WHERE due<=? ORDER BY due LIMIT ?',
                                             (today(), limit)).fetchall()]


def review_question(item):
    """A retrieval question for a vowel-pattern card: which pattern does this phrase ride?"""
    data = bible.load() or {}
    pats = data.get('matrix', [])
    pat = next((p for p in pats if p['id'] == item), None)
    if not pat:
        return None
    rng = random.Random(f'{item}:{today()}')
    phrases = [x for row in pat['rows'].values() for x in row]
    phrase = rng.choice(phrases) if phrases else pat['name']
    wrong = rng.sample([p for p in pats if p['id'] != item], min(3, len(pats) - 1))
    options = [pat] + wrong
    rng.shuffle(options)
    return {'item': item, 'phrase': phrase, 'options': [{'id': o['id'], 'label': f"{o['name']} ({o['sounds']})"} for o in options]}


def answer_review(item, choice):
    events = []
    with db.connect() as con:
        r = con.execute('SELECT * FROM academy_reviews WHERE item=?', (item,)).fetchone()
    if not r:
        return {'correct': False, 'events': events}
    correct = choice == item
    step = r['step'] + 1 if correct else max(0, r['step'] - 1)
    schedule_review(item, r['kind'], step)
    if correct:
        events.append({'type': 'xp', 'label': f'Recall locked in: {item.upper()} (next review in {REVIEW_STEPS[min(step, 5)]} days)', 'amount': 0})
        collect_card(item, events, uses=1)
        _mark_practiced(events)
    else:
        events.append({'type': 'rhythm', 'label': f'Not quite: that was {item.upper()}. It will come back tomorrow.'})
    return {'correct': correct, 'events': events}


def difficulty():
    """-1 easier / 0 / +1 harder, steering toward roughly 80-85% success (the 85% rule)."""
    with db.connect() as con:
        rows = con.execute("SELECT passed FROM academy_submissions WHERE kind='drill' ORDER BY id DESC LIMIT 10").fetchall()
    if len(rows) < 4:
        return 0
    rate = sum(r['passed'] for r in rows) / len(rows)
    return 1 if rate > 0.9 else -1 if rate < 0.65 else 0


def tuned_drill(drill):
    """Apply adaptive difficulty to a drill's targets."""
    d = difficulty()
    out = dict(drill)
    out['difficulty'] = d
    if drill['form'] == 'vowel':
        out['goal'] = max(8, 15 + 5 * d)
    if d > 0 and drill['form'] in ('bars', 'skeleton', 'wordplay') and drill['bars'] <= 4:
        out['stretch'] = 'Stretch goal: hold one vowel chain across every bar.'
    if d < 0 and drill['form'] == 'skeleton':
        out['assist'] = True  # UI pre-fills the skeleton slots
    return out
