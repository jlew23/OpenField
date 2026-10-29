"""Flow lab: syllables, rhyme-vowel chains, bar-grid placement and tempo fit.

Vowels carry the rhyme, so every syllable gets an ARPAbet-style vowel sound.
The CMU dictionary (`pronouncing` package) is used when installed; otherwise a
spelling heuristic keeps everything working, slang included.
"""
import re
from functools import lru_cache

from . import lyrics as lyr

try:  # optional, improves accuracy a lot
    import pronouncing as _pron
except Exception:  # pragma: no cover - depends on environment
    _pron = None

VOWELS = {'AA', 'AE', 'AH', 'AO', 'AW', 'AY', 'EH', 'ER', 'EY', 'IH', 'IY', 'OW', 'OY', 'UH', 'UW'}
WEAK = {'AH', 'IH', 'ER'}
FUNCTION_WORDS = {
    'a', 'an', 'the', 'to', 'of', 'and', 'in', 'on', 'at', 'my', 'your', 'you', 'i', 'it', 'is', 'for', 'as',
    'but', 'or', 'with', 'from', 'by', 'be', 'me', 'we', 'he', 'she', 'they', 'them', 'his', 'her', 'our',
    'that', 'this', 'so', 'if', 'up', 'just', 'like', 'was', 'are', 'am', 'do', 'got', 'get', 'im', "i'm",
    'yo', 'uh', 'ya', 'yall', "y'all", 'cause', "'cause", 'til', "'til", 'gon', "gon'", 'wanna', 'gonna'}

# Syllables-per-second zones, used for labels and colours in the UI.
ZONES = [(2.0, 'sparse'), (4.0, 'laid-back'), (6.0, 'mid'), (8.0, 'fast'), (10.0, 'rapid-fire'), (99, 'chopper')]


def zone(sps):
    for limit, name in ZONES:
        if sps < limit:
            return name
    return 'chopper'


# ---------------------------------------------------------------- numbers

_ONES = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
_TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()


def number_words(n):
    n = int(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ('' if n % 10 == 0 else ' ' + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + ' hundred' + ('' if n % 100 == 0 else ' ' + number_words(n % 100))
    for size, word in ((10 ** 9, 'billion'), (10 ** 6, 'million'), (1000, 'thousand')):
        if n >= size:
            rest = n % size
            return number_words(n // size) + ' ' + word + ('' if rest == 0 else ' ' + number_words(rest))
    return str(n)


def tokenize(text):
    """Split a lyric line into speakable words."""
    text = text.replace('&', ' and ').replace('%', ' percent ')
    text = re.sub(r'\$(\d[\d,]*)', lambda m: m.group(1).replace(',', '') + ' dollars', text)
    text = re.sub(r'(\d[\d,]*)', lambda m: ' ' + number_words(m.group(1).replace(',', '')) + ' ' if len(m.group(1).replace(',', '')) < 10 else m.group(1), text)
    words = re.findall(r"[A-Za-z][A-Za-z']*|'[A-Za-z]+", text.replace('-', ' ').replace('—', ' '))
    return [w for w in words if w.strip("'")]


# ---------------------------------------------------------------- phonetics

_HEURISTIC_VOWELS = [
    ('eau', 'OW'), ('igh', 'AY'), ('ough', 'AO'), ('augh', 'AO'),
    ('ai', 'EY'), ('ay', 'EY'), ('ei', 'EY'), ('ey', 'EY'), ('ee', 'IY'), ('ea', 'IY'), ('ie', 'AY'),
    ('oa', 'OW'), ('oe', 'OW'), ('oo', 'UW'), ('ou', 'AW'), ('ow', 'OW'), ('oi', 'OY'), ('oy', 'OY'),
    ('au', 'AO'), ('aw', 'AO'), ('ue', 'UW'), ('ui', 'UW'), ('ew', 'UW'),
    ('ar', 'AA'), ('or', 'AO'), ('er', 'ER'), ('ir', 'ER'), ('ur', 'ER'),
    ('a', 'AE'), ('e', 'EH'), ('i', 'IH'), ('o', 'AA'), ('u', 'AH'), ('y', 'IY'),
]
_LONG = {'a': 'EY', 'e': 'IY', 'i': 'AY', 'o': 'OW', 'u': 'UW'}


def _heuristic(word):
    """Approximate (vowel, stress) list from spelling."""
    w = word.lower().strip("'")
    w = re.sub(r"'", '', w)
    if not w:
        return []
    if w in ('i', 'im', 'ill', 'ive', 'id'):
        return [('AY', 1)]
    if w in ('a', 'of', 'the', 'uh'):
        return [('AH', 0)]
    if w in ('to', 'do', 'who', 'you'):
        return [('UW', 0 if w in ('to', 'you') else 1)]
    if w in ('in', 'it', 'is', 'if', 'with'):
        return [('IH', 0)]
    out = []
    i = 0
    n = len(w)
    while i < n:
        ch = w[i]
        if ch not in 'aeiouy' or (ch == 'y' and i == 0):
            i += 1
            continue
        # silent final e ("-le" endings get their own syllable below)
        if ch == 'e' and i == n - 1 and out:
            break
        if ch == 'e' and i == n - 1:
            out.append('IY')  # me, be, she
            break
        if ch == 'o' and i == n - 1:
            out.append('OW')  # yo, go, so
            break
        if ch == 'e' and i == n - 2 and w.endswith('es') and out and n > 3 and w[-3] not in 'sxzc':
            break
        if ch == 'e' and i == n - 2 and w.endswith('ed') and out and w[-3] not in 'td':
            break
        matched = None
        for pat, sound in _HEURISTIC_VOWELS:
            if not w.startswith(pat, i):
                continue
            after = i + len(pat)
            # r-controlled vowels only when the r closes the syllable (not "te-rri-fied")
            if pat.endswith('r') and after < n and w[after] in 'aeiouyr':
                continue
            if pat == 'ey' and after == n:
                sound = 'IY'  # money, honey
            matched = (pat, sound)
            break
        pat, sound = matched or (ch, 'AH')
        # magic e: vowel + single consonant + final e -> long vowel
        if len(pat) == 1 and ch in _LONG and i + 2 == n - 1 and w[-1] == 'e' and w[i + 1] not in 'aeiouy':
            sound = _LONG[ch]
        if ch == 'y':
            sound = 'AY' if (i == n - 1 and len(out) == 0) else 'IY'
            if i + 1 < n and w[i + 1] not in 'aeiou' and i != n - 1:
                sound = 'IH'
        out.append(sound)
        i += len(pat)
        # skip remaining vowels of a cluster we did not explicitly list
        while i < n and w[i] in 'aeiou' and not (w[i] == 'e' and i == n - 1):
            i += 1
    if w.endswith('le') and n > 2 and w[-3] not in 'aeiouy':
        out.append('AH')
    if not out:
        out = ['AH']
    stresses = [1] + [0] * (len(out) - 1)
    if len(out) == 1 and w in FUNCTION_WORDS:
        stresses = [0]
    return list(zip(out, stresses))


@lru_cache(maxsize=20000)
def phonemes(word):
    """List of (vowel, stress) for a word. Stress: 1 primary, 2 secondary, 0 none."""
    w = word.lower().strip("'")
    if _pron is not None:
        variants = _pron.phones_for_word(w) or _pron.phones_for_word(w.replace("'", ''))
        if not variants and w.endswith("in'"):
            variants = _pron.phones_for_word(w[:-1] + 'g')
        if not variants and w.endswith('in') and len(w) > 4:
            variants = _pron.phones_for_word(w + 'g')
        if variants:
            out = []
            for ph in variants[0].split():
                base, stress = ph[:-1], ph[-1:]
                if stress.isdigit() and base in VOWELS:
                    out.append((base, int(stress)))
            if out:
                if len(out) == 1 and w in FUNCTION_WORDS:
                    out = [(out[0][0], 0)]
                return tuple(out)
    return tuple(_heuristic(w))


def split_chunks(word, count):
    """Split the spelling of `word` into `count` display chunks (approximate syllables)."""
    if count <= 1 or len(word) <= count:
        return [word] if count <= 1 else (list(word) + [''] * (count - len(word)))[:count]
    groups = [m.span() for m in re.finditer(r'[aeiouyAEIOUY]+', word)]
    if len(groups) >= count:
        cuts = []
        for k in range(count - 1):
            end_v = groups[k][1]
            next_v = groups[k + 1][0]
            cons = next_v - end_v
            cuts.append(end_v + (cons // 2 if cons >= 2 else 0))
        pieces, start = [], 0
        for c in cuts:
            pieces.append(word[start:c])
            start = c
        pieces.append(word[start:])
        if all(pieces):
            return pieces
    size = len(word) / count
    return [word[round(i * size):round((i + 1) * size)] for i in range(count)]


def syllabify_line(text):
    """Return a list of syllable dicts for one bar."""
    out = []
    for wi, word in enumerate(tokenize(text)):
        ph = phonemes(word)
        chunks = split_chunks(word, len(ph))
        for si, ((vowel, stress), chunk) in enumerate(zip(ph, chunks)):
            out.append({'text': chunk, 'word': word, 'w': wi, 'vowel': vowel, 'stress': stress,
                        'end': si == len(ph) - 1, 'start': si == 0})
    return out


# ---------------------------------------------------------------- rhymes

def _strong(seq):
    return any(s['stress'] > 0 for s in seq) and not all(s['vowel'] in WEAK and s['stress'] == 0 for s in seq)


def mark_rhymes(bars_syllables, window=4):
    """Annotate syllables in-place with a `rhyme` family id (int) where rhyme chains exist.

    End rhymes: lines whose final vowel sounds match, extended backwards while
    the vowel chain keeps matching (multisyllabic landings).
    Internal chains: repeated vowel n-grams (2-4 syllables) inside a 4-bar window.
    """
    family_ids = {}

    def fid(key):
        if key not in family_ids:
            family_ids[key] = len(family_ids)
        return family_ids[key]

    # End rhymes
    for i, sy in enumerate(bars_syllables):
        if not sy:
            continue
        for j in range(i + 1, min(len(bars_syllables), i + window)):
            other = bars_syllables[j]
            if not other or sy[-1]['vowel'] != other[-1]['vowel']:
                continue
            depth = 0
            while depth < min(len(sy), len(other), 4) and sy[-1 - depth]['vowel'] == other[-1 - depth]['vowel']:
                depth += 1
            key = ('end',) + tuple(s['vowel'] for s in sy[len(sy) - depth:])
            # reuse an existing family if either side already landed on this vowel
            existing = sy[-1].get('rhyme', other[-1].get('rhyme'))
            f = existing if existing is not None else fid(key)
            for k in range(depth):
                sy[-1 - k].setdefault('rhyme', f)
                other[-1 - k].setdefault('rhyme', f)

    # Internal multi-syllable chains
    for start in range(0, len(bars_syllables), 2):
        block = bars_syllables[start:start + window]
        flat = [(bi, si, s) for bi, b in enumerate(block) for si, s in enumerate(b)]
        for n in (4, 3, 2):
            seen = {}
            for idx in range(len(flat) - n + 1):
                seg = flat[idx:idx + n]
                if len({bi for bi, _, _ in seg}) != 1:
                    continue
                syl = [s for _, _, s in seg]
                if any('rhyme' in s for s in syl) or not _strong(syl):
                    continue
                if n == 2 and not syl[-1]['end']:
                    continue
                seen.setdefault(tuple(s['vowel'] for s in syl), []).append(idx)
            for key, positions in seen.items():
                chosen = []
                for p in positions:
                    if all(abs(p - q) >= n for q in chosen):
                        chosen.append(p)
                if len(chosen) < 2:
                    continue
                f = fid(('chain',) + key)
                for p in chosen:
                    for _, _, s in flat[p:p + n]:
                        s.setdefault('rhyme', f)
    return len(family_ids)


# ---------------------------------------------------------------- grid placement

def place(syllables, steps=16):
    """Give each syllable a `step` position on a bar grid of `steps` slots.

    Up to half the grid: eighth-note delivery, landing the last syllable on beat 4.
    Up to the full grid: sixteenths, landing late in the bar.
    Beyond: compressed evenly (double-time / triplet territory), flagged.
    """
    n = len(syllables)
    if n == 0:
        return {'mode': 'rest', 'overflow': 0}
    beat4 = steps * 3 // 4
    if n * 2 <= steps:
        first = max(0, beat4 - (n - 1) * 2)
        for i, s in enumerate(syllables):
            s['step'] = first + i * 2
        return {'mode': 'eighths', 'overflow': 0}
    if n <= steps:
        last = min(steps - 1, beat4 + 2)
        first = max(0, last - (n - 1))
        for i, s in enumerate(syllables):
            s['step'] = first + i
        return {'mode': 'sixteenths', 'overflow': 0}
    size = steps / n
    for i, s in enumerate(syllables):
        s['step'] = round(i * size, 3)
    return {'mode': 'double-time', 'overflow': n - steps}


# ---------------------------------------------------------------- analysis

def seconds_per_bar(bpm, beats_per_bar=4, feel='normal'):
    sec = beats_per_bar * 60.0 / max(float(bpm), 1.0)
    return sec * 2 if feel == 'half' else sec


def grid_steps(feel='normal'):
    return 32 if feel == 'double' else 16


def analyze(text, bpm, beats_per_bar=4, feel='normal', pocket=None):
    """Full bar-by-bar analysis of a lyric sheet at a tempo."""
    bar_list = lyr.bars(text)
    sylls = [syllabify_line(b['text']) for b in bar_list]
    families = mark_rhymes(sylls)
    sec = seconds_per_bar(bpm, beats_per_bar, feel)
    steps = grid_steps(feel)
    lo, hi = (pocket or (2.5, 8.0))
    out_bars = []
    for b, sy in zip(bar_list, sylls):
        placement = place(sy, steps)
        count = len(sy)
        sps = count / sec
        if sps > hi:
            verdict = 'crowded'
        elif sps < lo:
            verdict = 'sparse'
        else:
            verdict = 'fits'
        target = max(1, round(min(max(count, lo * sec), hi * sec)))
        out_bars.append({
            'index': b['index'], 'section': b['section'], 'speaker': b['speaker'], 'text': b['text'],
            'syllables': sy, 'count': count, 'sps': round(sps, 2), 'zone': zone(sps),
            'verdict': verdict, 'target': target, 'placement': placement,
        })
    counts = [b['count'] for b in out_bars] or [0]
    crowded = sum(1 for b in out_bars if b['verdict'] == 'crowded')
    sparse = sum(1 for b in out_bars if b['verdict'] == 'sparse')
    avg = sum(counts) / max(len(counts), 1)
    return {
        'bpm': float(bpm), 'beats_per_bar': beats_per_bar, 'feel': feel, 'steps': steps,
        'seconds_per_bar': round(sec, 3), 'pocket': [lo, hi], 'families': families,
        'bars': out_bars, 'summary': {
            'bars': len(out_bars), 'avg_syllables': round(avg, 1), 'avg_sps': round(avg / sec, 2),
            'zone': zone(avg / sec), 'crowded': crowded, 'sparse': sparse,
            'fits': len(out_bars) - crowded - sparse,
            'dictionary': 'cmu' if _pron is not None else 'heuristic',
        },
    }


def suggest_feel(orig_bpm, new_bpm):
    ratio = float(new_bpm) / max(float(orig_bpm), 1.0)
    if ratio >= 1.45:
        return 'half'
    if ratio <= 0.69:
        return 'double'
    return 'normal'


def compare(text, orig_bpm, new_bpm, beats_per_bar=4, feel=None, pocket=None, new_text=None):
    """How a sheet written at orig_bpm lands on a beat at new_bpm (optionally with rewritten lyrics)."""
    feel = feel or suggest_feel(orig_bpm, new_bpm)
    before = analyze(text, orig_bpm, beats_per_bar, 'normal', pocket)
    after = analyze(new_text if new_text is not None else text, new_bpm, beats_per_bar, feel, pocket)
    deltas = []
    for i, b in enumerate(after['bars']):
        prev = before['bars'][i] if i < len(before['bars']) else None
        deltas.append({'index': i, 'sps_before': prev['sps'] if prev else None, 'sps_after': b['sps'],
                       'count_before': prev['count'] if prev else None, 'count_after': b['count'],
                       'verdict': b['verdict'], 'target': b['target']})
    return {'before': before, 'after': after, 'feel': feel, 'suggested_feel': suggest_feel(orig_bpm, new_bpm),
            'deltas': deltas}


def budget_sheet(analysis):
    """Compact per-bar syllable budget, used to brief an LLM before a rewrite."""
    lines = []
    for b in analysis['bars']:
        flag = '' if b['verdict'] == 'fits' else f" <- {b['verdict'].upper()}, aim for ~{b['target']}"
        who = f"[{b['speaker']}] " if b['speaker'] else ''
        lines.append(f"{b['index'] + 1:>2}. {who}{b['text']}  ({b['count']} syl, {b['sps']}/s){flag}")
    return '\n'.join(lines)
