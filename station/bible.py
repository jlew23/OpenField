"""Turn THE RAP WRITING BIBLE (markdown) into a playable curriculum.

The Bible ships with OpenField (station/bible/RAP-WRITING-BIBLE.md): it is the
Academy's built-in rapper-builder methodology. A newer edition can be dropped
into the Station data folder (or station/knowledge/) and takes precedence.
Everything here is structure: levels, chapters, drills, tests, routines,
the skill ladder and the reference appendices.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLED = HERE / 'bible' / 'RAP-WRITING-BIBLE.md'
_cache = {}
_data_dir = None


def set_data_dir(path):
    global _data_dir
    _data_dir = Path(path)
    _data_dir.mkdir(parents=True, exist_ok=True)


def source_path():
    cands = []
    if _data_dir:
        cands.append(_data_dir / 'rap-bible.md')
    cands += sorted((HERE / 'knowledge').glob('*[Bb][Ii][Bb][Ll][Ee]*.md'))
    cands.append(BUNDLED)
    for c in cands:
        if c.exists():
            return c
    return None


def save_source(text):
    if not _data_dir:
        raise RuntimeError('Academy data folder is not set')
    (_data_dir / 'rap-bible.md').write_text(text, encoding='utf-8')
    _cache.clear()


def load():
    """Parsed curriculum, or None when no Bible has been imported yet."""
    path = source_path()
    if not path:
        return None
    stamp = (str(path), path.stat().st_mtime)
    if _cache.get('stamp') != stamp:
        _cache.update(stamp=stamp, data=parse(path.read_text(encoding='utf-8')))
    return _cache['data']


# ------------------------------------------------------------------ helpers

def _strip_md(s):
    return re.sub(r'(\*\*|\*|__|`)', '', s).strip()


def _blocks(text, level):
    """Split text on headings of exactly `level` hashes -> [(title, body)]."""
    pat = re.compile(r'^' + '#' * level + r'(?!#)\s+(.*)$', re.M)
    out, last, title = [], 0, None
    for m in pat.finditer(text):
        if title is not None:
            out.append((title, text[last:m.start()]))
        title, last = m.group(1).strip(), m.end()
    if title is not None:
        out.append((title, text[last:]))
    return out


def _numbered(body):
    items = []
    for line in body.splitlines():
        m = re.match(r'^\s*(\d+)\.\s+(.*)$', line)
        if m:
            items.append(_strip_md(m.group(2)))
    return items


def _bullets(body):
    return [_strip_md(m.group(1)) for m in re.finditer(r'^\s*[-*]\s+(.*)$', body, re.M)]


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')


# ------------------------------------------------------------------ drills

FORM_RULES = [
    ('transcribe', r'\btranscrib|color-code|colour-code'),
    ('vowel', r'vowel|strip it|strip to'),
    ('skeleton', r'skeleton|double-stitch|both threads|internal'),
    ('idiom', r'\bidiom'),
    ('wordplay', r'homophone|punchline|hidden words|appendix c|different senses|appendix b'),
    ('story', r'story|core five|architecture|point of view|first person|second person'),
    ('hook', r'\bhook\b'),
    ('cut', r'\bcut\b|expensive'),
    ('perform', r'\brecord\b|perform|hum |out loud .*times|three ways'),
    ('reflection', r'list of|notebook|count the bars|write down|play three songs'),
]


def form_for(text, chapter_no=''):
    low = text.lower()
    for form, pat in FORM_RULES:
        if re.search(pat, low):
            return form
    return 'bars'


def bar_target(text):
    low = text.lower()
    m = re.search(r'(\d+|one|two|three|four|eight|sixteen)[- ]bar', low)
    words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'eight': 8, 'sixteen': 16}
    if m:
        v = m.group(1)
        return int(words.get(v, v)) if not v.isdigit() else int(v)
    m = re.search(r'\b(\d+) bars\b|\b(four|two|eight) bars\b', low)
    if m:
        v = m.group(1) or m.group(2)
        return int(words.get(v, v)) if not str(v).isdigit() else int(v)
    if re.search(r'\ba (?:full )?16\b|\bone 16\b|your best 16|\b16\b', low):
        return 16
    if 'one bar' in low or 'one punchline' in low or 'one original punchline' in low:
        return 1
    return 4


def scheme_target(text):
    m = re.search(r'\b(AABB|ABAB|ABBA|AAAA)\b', text)
    return m.group(1) if m else ''


def _drills(chapter_no, body):
    out = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r'^\*\*Drill\s+([0-9A-Za-z.]+)\s*(\([^)]*\))?\s*:\*\*\s*(.*)$', lines[i].strip())
        if not m:
            i += 1
            continue
        num, label, text = m.group(1), (m.group(2) or '').strip('() '), m.group(3).strip()
        j = i + 1
        while j < len(lines) and re.match(r'^\s*(\d+\.|[-*])\s+', lines[j]):
            text += '\n' + lines[j].strip()
            j += 1
        clean = _strip_md(text)
        form = form_for(clean + ' ' + label, chapter_no)
        if chapter_no == '6':
            form = 'vowel'
        out.append({'id': f'drill-{num}', 'number': num, 'label': label, 'text': clean, 'form': form,
                    'bars': bar_target(clean), 'scheme': scheme_target(clean)})
        i = j
    return out


# ------------------------------------------------------------------ tests (bosses)

def _test_parts(items):
    parts = []
    for n, item in enumerate(items, 1):
        low = item.lower()
        specific = form_for(item)
        if specific in ('skeleton', 'wordplay', 'idiom', 'transcribe', 'cut', 'story', 'hook'):
            if specific == 'idiom' and 'punchline' in low:
                specific = 'wordplay'
            parts.append({'id': f'part-{n}', 'text': item, 'form': specific, 'bars': bar_target(item),
                          'scheme': scheme_target(item)})
            continue
        if 'vowel-strip' in low or 'vowel strip' in low or ('matches' in low and 'minute' in low):
            kind = 'vowel'
        elif re.search(r'write (an?|one) .*hook|\bhook\b', low):
            kind = 'hook'
        elif re.search(r'\bwrite\b.*(\d+-bar|16|verse|bars|skeleton)', low) or re.search(r'\b(16|8-bar)\b', low):
            kind = 'story' if 'story' in low else 'bars'
        elif re.search(r'explain|say what|summar', low):
            kind = 'text'
        else:
            kind = 'check'
        parts.append({'id': f'part-{n}', 'text': item, 'form': kind, 'bars': bar_target(item),
                      'scheme': scheme_target(item)})
    return parts


# ------------------------------------------------------------------ appendices

def _matrix(body):
    patterns = []
    for title, chunk in _blocks(body, 2):
        m = re.match(r'(.+?)\s*\((.+)\)', title)
        name, sounds = (m.group(1).strip(), m.group(2).strip()) if m else (title, '')
        rows = {}
        for label in ('2-Syl', '3-Syl', '4-Syl'):
            mm = re.search(r'\*\*' + label + r':\*\*\s*(.*)', chunk)
            if mm:
                rows[label] = [p.strip() for p in mm.group(1).split('·') if p.strip()]
        patterns.append({'id': slug(name), 'name': name, 'sounds': sounds, 'rows': rows})
    return patterns


def _word_bank(body):
    out = []
    for m in re.finditer(r'^-\s+\*\*([A-Z][A-Z ]+)\*\*\s+—\s+ride\s+\*([^*]+)\*\s+—\s+\*([^*]+)\*\s+—\s+⚠️\s*(.*)$', body, re.M):
        out.append({'word': m.group(1).title(), 'ride': m.group(2), 'seed': m.group(3).strip('"“”'), 'avoid': m.group(4).strip()})
    return out


def _idioms(body):
    raw = ''
    for title, chunk in _blocks(body, 2):
        if 'raw' in title.lower():
            raw = chunk
    bank = [x.strip() for x in re.split(r'·|\n', _strip_md(raw)) if x.strip() and len(x.strip()) < 60 and not x.strip().startswith('(')]
    worked = []
    for m in re.finditer(r'^\d+\.\s+"([^"]+)"\s+→\s+\*"?(.+?)"?\*\s*$', body, re.M):
        worked.append({'idiom': m.group(1), 'flip': m.group(2).strip('"')})
    return {'bank': bank, 'worked': worked}


def _homophones(body):
    out = []
    for m in re.finditer(r'^-\s+\*\*([^*]+)\*\*\s+—\s+"?(.+?)"?\s*$', body, re.M):
        out.append({'words': m.group(1).strip(), 'example': m.group(2).strip('"')})
    return out


def _multi_meanings(body):
    out = []
    for m in re.finditer(r'^-\s+\*\*([^*]+)\*\*\s+—\s+(.*)$', body, re.M):
        out.append({'word': m.group(1).strip(), 'senses': [s.strip() for s in m.group(2).split('/') if s.strip()]})
    return out


def _listening(body):
    levels = {}
    for title, chunk in _blocks(body, 2):
        m = re.match(r'Level\s+(\d)', title)
        if not m:
            continue
        songs = []
        for line in _bullets(chunk):
            mm = re.match(r'(.+?)\s+—\s+(.*)$', line)
            if not mm:
                continue
            artist, rest = mm.group(1).strip(), mm.group(2)
            for t in re.finditer(r'"([^"]+)"\s*(?:\(([^)]*)\))?', rest):
                songs.append({'artist': artist, 'title': t.group(1), 'focus': (t.group(2) or '').strip()})
            if not re.search(r'"', rest):
                note = re.search(r'\(([^)]*)\)', rest)
                songs.append({'artist': artist, 'title': re.sub(r'\s*\(.*', '', rest).strip(), 'focus': note.group(1) if note else ''})
        levels[int(m.group(1))] = {'title': title, 'songs': songs}
    return levels


def _daily(body):
    routines = {}
    for title, chunk in _blocks(body, 2):
        m = re.match(r'Level\s+(\d)\s+Daily\s*\(([^)]*)\)\s*—\s*"?([^"]+)"?', title)
        key = int(m.group(1)) if m else ('weekly' if 'weekly' in title.lower() else None)
        if key is None:
            continue
        steps = []
        for line in chunk.splitlines():
            mm = re.match(r'^\s*-\s+\*\*(?:(\d+)\s*min\s*—\s*)?([^:*]+):?\*\*:?\s*(.*)$', line)
            if mm:
                steps.append({'minutes': int(mm.group(1)) if mm.group(1) else 0, 'title': mm.group(2).strip(' :'),
                              'text': _strip_md(mm.group(3))})
        routines[key] = {'title': (m.group(3).strip() if m else title), 'steps': steps}
    return routines


# ------------------------------------------------------------------ main parse

def parse(text):
    data = {'title': 'The Rap Writing Bible', 'levels': [], 'ladder': [], 'one_law': '', 'daily': {},
            'roadmap': [], 'matrix': [], 'word_bank': [], 'idioms': {'bank': [], 'worked': []},
            'homophones': [], 'meanings': [], 'listening': {}, 'appendix_text': {}}
    m = re.search(r'^#\s+(.+)$', text, re.M)
    if m:
        data['title'] = _strip_md(m.group(1)).title()
    for title, body in _blocks(text, 1):
        t = title.upper()
        if 'SKILL LADDER' in t:
            for mm in re.finditer(r'\*\*Rung\s+(\d)\:\*\*\s*(.*?)(?:\*\((.*?)\)\*)?\s*$', body, re.M):
                data['ladder'].append({'rung': int(mm.group(1)), 'text': mm.group(2).strip(), 'level': (mm.group(3) or '').strip()})
        elif t.startswith('THE ONE LAW'):
            mm = re.search(r'\*\*(.+?)\*\*', body)
            data['one_law'] = mm.group(1) if mm else _strip_md(body.strip().splitlines()[0] if body.strip() else '')
        elif 'DAILY PRACTICE' in t:
            data['daily'] = _daily(body)
        elif 'ROADMAP' in t:
            for line in body.splitlines():
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                if len(cells) == 4 and not set(cells[0]) <= set('-: ') and cells[0].lower() != 'weeks':
                    data['roadmap'].append({'weeks': cells[0], 'focus': cells[1], 'routine': cells[2], 'milestone': cells[3]})
        elif re.search(r'LEVEL\s+\d', t) and '—' in title and 'APPENDIX' not in t:
            lm = re.search(r'LEVEL\s+(\d)\s+—\s+([A-Z ]+?)\s*(?:\((.*)\))?$', _strip_md(title).upper().replace('⬛', '').strip())
            num = int(lm.group(1)) if lm else len(data['levels']) + 1
            name = (lm.group(2).strip().title() if lm else title)
            goal = re.search(r'\*Goal:\s*(.+?)\*', body)
            level = {'level': num, 'name': name, 'tier': (lm.group(3) or '').title() if lm else '',
                     'goal': goal.group(1).strip() if goal else '', 'chapters': [], 'test': None}
            for ctitle, cbody in _blocks(body, 2):
                cm = re.match(r'Chapter\s+([0-9]+[A-Z]?)\s*:\s*(.*)$', _strip_md(ctitle))
                if cm:
                    no = cm.group(1)
                    level['chapters'].append({
                        'id': 'ch-' + no.lower(), 'number': no, 'title': cm.group(2).strip(' ★'),
                        'body': cbody.strip(), 'drills': _drills(no, cbody), 'level': num,
                    })
                elif 'GRADUATION' in ctitle.upper() or 'MASTERY' in ctitle.upper():
                    items = _numbered(cbody) or [re.sub(r'^\[.?\]\s*', '', b) for b in _bullets(cbody)]
                    reward = re.search(r'\*\*(.+?)\*\*\s*$', re.sub(r'(\s*-{3,}\s*)+$', '', cbody.strip()))
                    level['test'] = {'id': f'boss-{num}', 'title': _strip_md(ctitle).strip('✅ '),
                                     'parts': _test_parts(items), 'reward_text': reward.group(1) if reward else '',
                                     'ongoing': 'MASTERY' in ctitle.upper()}
            data['levels'].append(level)
        elif t.startswith('APPENDIX A'):
            data['matrix'] = _matrix(body)
        elif t.startswith('APPENDIX B'):
            data['homophones'] = _homophones(body)
            data['appendix_text']['B'] = body.strip()
        elif t.startswith('APPENDIX C'):
            data['meanings'] = _multi_meanings(body)
        elif t.startswith('APPENDIX D'):
            data['idioms'] = _idioms(body)
        elif t.startswith('APPENDIX E'):
            data['word_bank'] = _word_bank(body)
        elif t.startswith('APPENDIX F'):
            data['listening'] = _listening(body)
        elif t.startswith('APPENDIX H'):
            data['appendix_text']['H'] = body.strip()
    data['levels'].sort(key=lambda l: l['level'])
    return data


def chapters(data):
    return [c for lvl in data['levels'] for c in lvl['chapters']]


def find_chapter(data, cid):
    for c in chapters(data):
        if c['id'] == cid:
            return c
    return None


def find_drill(data, did):
    for c in chapters(data):
        for d in c['drills']:
            if d['id'] == did:
                return c, d
    return None, None


def outline(data):
    """Curriculum without chapter bodies (for listings)."""
    out = {k: v for k, v in data.items() if k not in ('levels', 'appendix_text')}
    out['levels'] = []
    for lvl in data['levels']:
        out['levels'].append({**{k: v for k, v in lvl.items() if k != 'chapters'},
                              'chapters': [{k: v for k, v in c.items() if k != 'body'} for c in lvl['chapters']]})
    return out


def edition():
    """Which copy is in use: 'built-in' or 'custom'."""
    p = source_path()
    return 'built-in' if p == BUNDLED else ('custom' if p else 'missing')


def reset_to_builtin():
    if _data_dir and (_data_dir / 'rap-bible.md').exists():
        (_data_dir / 'rap-bible.md').unlink()
    _cache.clear()
