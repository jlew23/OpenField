"""Cypher and Battle: drop bars, the crew answers with bars; or go head to head on visible metrics."""
import json, random

from . import db, flow, grading, llm, personas, bible

RIFF_FORMAT = '''Reply ONLY with JSON:
{"bars": "exactly 4 original bars, one per line, riffing on their rhyme sound",
 "shoutout": "one short line naming the best fragment they wrote (quote at most 6 of their words)",
 "note": "one honest craft note on their weakest bar, or empty if none"}'''


def _vowel_hint(text):
    bars = [l for l in text.splitlines() if l.strip()]
    if not bars:
        return ''
    syl = flow.syllabify_line(bars[-1])
    return '-'.join(s['vowel'] for s in syl[-3:])


def riff(pid, student_bars, mode='crew'):
    """One persona's answer in the cypher."""
    p = personas.get(pid)
    if not p or p.get('role') not in ('rapper', 'coach'):
        raise llm.LLMError('That persona does not rap.')
    hint = _vowel_hint(student_bars)
    tone = {'crew': 'Be supportive but real: if you can out-rhyme them, do it.',
            'battle': 'This is a battle. Out-rhyme them on the same vowel sound. Playful, no slurs, no real people.'}.get(mode, '')
    system = personas.system_prompt(p, extra=f'You are in a cypher with the student. {tone}')
    user = (f"The student just dropped:\n{student_bars}\n\nTheir landing vowel chain is {hint or 'unknown'}. "
            f"Answer in character.\n\n{RIFF_FORMAT}")
    out = llm.extract_json(llm.complete([{'role': 'user', 'content': user}], system, max_tokens=700))
    if not isinstance(out, dict) or not out.get('bars'):
        raise llm.LLMError(f"{p.get('name', pid)} fumbled the mic (unreadable reply). Try again.")
    bars = '\n'.join(l.strip() for l in str(out['bars']).splitlines() if l.strip())[:800]
    return {'persona': pid, 'name': p.get('handle') or p['name'], 'color': p.get('color'), 'bars': bars,
            'shoutout': str(out.get('shoutout', ''))[:200], 'note': str(out.get('note', ''))[:300],
            'analysis': _light(bars)}


def _light(text):
    a = flow.analyze(text, 90)
    return {'bars': [{'text': b['text'], 'syllables': [{'text': s['text'], 'rhyme': s.get('rhyme'), 'start': s['start']}
                                                       for s in b['syllables']], 'count': b['count']} for b in a['bars']]}


def score(text, bpm=90):
    """Transparent battle metrics (0-100 each)."""
    a = flow.analyze(text, bpm)
    if not a['bars']:
        return {'total': 0, 'metrics': {}}
    dens = grading.rhyme_density(a)
    chain = grading.longest_chain(a)
    pairs = grading.internal_slot_pairs(a)
    internals = sum(p['internal'] for p in pairs) / max(len(pairs), 1)
    abstract = grading.image_check(a)
    crowded = a['summary']['crowded']
    metrics = {
        'Rhyme density': round(min(100, dens * 220)),
        'Longest chain': round(min(100, chain * 18)),
        'Internals in slot': round(internals * 100),
        'Imagery': max(0, 100 - 20 * len(abstract)),
        'Pocket': max(0, 100 - 20 * crowded),
    }
    weights = {'Rhyme density': 1.2, 'Longest chain': 1.0, 'Internals in slot': 1.0, 'Imagery': 0.8, 'Pocket': 0.6}
    total = round(sum(metrics[k] * w for k, w in weights.items()) / sum(weights.values()))
    return {'total': total, 'metrics': metrics, 'analysis': _light(text)}


def elo():
    return db.get_setting('elo', {}) or {}


def battle_round(pid, student_bars, prompt_word=''):
    p = personas.get(pid)
    if not p:
        raise llm.LLMError('Unknown persona')
    system = personas.system_prompt(p, extra='Battle round. Write exactly 4 original bars, one per line, on the given word. Nothing else.')
    word = prompt_word or 'midnight'
    theirs = llm.complete([{'role': 'user', 'content': f'Battle word: {word}. Your 4 bars:'}], system, max_tokens=400)
    theirs = '\n'.join(l.strip().strip('"') for l in theirs.splitlines() if l.strip() and not l.strip().startswith('```'))[:800]
    you, them = score(student_bars), score(theirs)
    ratings = elo()
    ra, rb = ratings.get('you', 1000), ratings.get(pid, 1100)
    expected = 1 / (1 + 10 ** ((rb - ra) / 400))
    result = 1 if you['total'] > them['total'] else 0.5 if you['total'] == them['total'] else 0
    k = 32
    ratings['you'] = round(ra + k * (result - expected))
    ratings[pid] = round(rb - k * (result - expected))
    db.set_setting('elo', ratings)
    return {'word': word, 'you': you, 'them': them | {'bars': theirs, 'persona': pid, 'name': p.get('handle') or p['name'],
                                                   'color': p.get('color')},
            'result': {1: 'win', 0.5: 'draw', 0: 'loss'}[result], 'elo': {'you': ratings['you'], pid: ratings[pid]}}


def prompt_word(weakest_pattern=None):
    """A word to write on: from the Bible's word bank, or a phrase from your weakest matrix pattern."""
    data = bible.load() or {}
    rng = random.Random()
    if weakest_pattern:
        pat = next((p for p in data.get('matrix', []) if p['id'] == weakest_pattern), None)
        if pat:
            pool = [x for row in pat['rows'].values() for x in row]
            if pool:
                return {'word': rng.choice(pool), 'pattern': pat['name'], 'sounds': pat['sounds']}
    bank = data.get('word_bank') or []
    if bank:
        w = rng.choice(bank)
        return {'word': w['word'], 'ride': w['ride'], 'avoid': w['avoid']}
    return {'word': rng.choice(['midnight', 'thunder', 'hollow', 'motion', 'rattle', 'horizon'])}
