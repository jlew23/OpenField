"""Grading for Academy submissions: automatic craft checks + Coach (LLM) review + report card."""
import re, statistics, time

from . import flow, llm, personas

ABSTRACT = {'pain', 'struggle', 'struggles', 'life', 'love', 'hate', 'feel', 'feeling', 'feelings', 'emotion', 'emotions',
            'stuff', 'things', 'thing', 'success', 'happiness', 'sadness', 'dreams', 'hope', 'fear', 'truth', 'real',
            'everything', 'nothing', 'something', 'vibes', 'grind', 'hustle', 'journey', 'destiny', 'soul', 'heart'}
FILLER_ENDS = {'tonight', 'alright', 'aight', 'right', 'yeah', 'though', 'know', 'see', 'me', 'be', 'free'}
NEAR = [{'AA', 'AO'}, {'AH', 'UH'}, {'IH', 'IY'}, {'EH', 'AE'}, {'ER', 'AH'}, {'UW', 'UH'}]


def _near(a, b):
    return a == b or any(a in s and b in s for s in NEAR)


def letter(score):
    for cut, grade in ((97, 'A+'), (92, 'A'), (88, 'A-'), (84, 'B+'), (80, 'B'), (76, 'B-'), (72, 'C+'), (68, 'C'),
                       (64, 'C-'), (55, 'D'), (0, 'F')):
        if score >= cut:
            return grade
    return 'F'


def _crit(cid, label, score, note, weight=1.0):
    return {'id': cid, 'label': label, 'score': int(max(0, min(100, round(score)))), 'note': note, 'weight': weight}


# ------------------------------------------------------------------ building blocks

def vowel_chain(text):
    return [s['vowel'] for s in flow.syllabify_line(text)]


LOOSE = {'AH', 'IH', 'ER', 'UH', 'IY'}


def vowel_match(target, candidate):
    """0..1 similarity of the candidate's vowel tail against the target chain.

    Stressed vowels carry the rhyme and count extra; unstressed "uh / ih"
    sounds are loose, so they match each other (the Bible's AH-uh-uh-UH).
    """
    t = [(s['vowel'], s['stress']) for s in flow.syllabify_line(target)]
    c = [(s['vowel'], s['stress']) for s in flow.syllabify_line(candidate)]
    if not t or not c:
        return 0.0
    tail = c[-len(t):]
    score = total = 0.0
    for (a, sa), (b, sb) in zip(reversed(t), reversed(tail)):
        weight = 1.5 if sa > 0 else 1.0
        total += weight
        if a == b:
            score += weight
        elif sa == 0 and sb == 0 and a in LOOSE and b in LOOSE:
            score += 0.8 * weight
        elif _near(a, b):
            score += 0.5 * weight
    missing = len(t) - len(tail)
    total += missing
    return score / total if total else 0.0


def end_letters(analysis):
    """Assign scheme letters by final vowel (A, B, C ...)."""
    letters, keys = [], {}
    for b in analysis['bars']:
        v = b['syllables'][-1]['vowel'] if b['syllables'] else '-'
        if v not in keys:
            keys[v] = chr(ord('A') + len(keys))
        letters.append(keys[v])
    return letters


def scheme_score(letters, scheme):
    pairs = {'AABB': [(0, 1), (2, 3)], 'ABAB': [(0, 2), (1, 3)], 'ABBA': [(0, 3), (1, 2)],
             'AAAA': [(0, 1), (1, 2), (2, 3)]}.get(scheme)
    if not pairs:
        return None
    hits = total = 0
    for start in range(0, len(letters) - 3, 4):
        for a, b in pairs:
            total += 1
            hits += letters[start + a] == letters[start + b]
    return hits / total if total else 0


def image_check(analysis):
    flagged = []
    for b in analysis['bars']:
        words = [w.lower().strip("'") for w in flow.tokenize(b['text'])]
        hits = [w for w in words if w in ABSTRACT]
        if hits:
            flagged.append({'bar': b['index'] + 1, 'words': hits})
    return flagged


def rhyme_density(analysis):
    syl = [s for b in analysis['bars'] for s in b['syllables']]
    if not syl:
        return 0.0
    return sum(1 for s in syl if 'rhyme' in s) / len(syl)


def longest_chain(analysis):
    best = 0
    for b in analysis['bars']:
        run = 0
        for s in b['syllables']:
            run = run + 1 if 'rhyme' in s else 0
            best = max(best, run)
    return best


def internal_slot_pairs(analysis):
    """Double-stitch check per bar pair: internal vowel echo in the same slot + held end rhyme."""
    results = []
    bars = analysis['bars']
    for i in range(0, len(bars) - 1, 2):
        a, b = bars[i], bars[i + 1]
        if not a['syllables'] or not b['syllables']:
            continue
        end_ok = _near(a['syllables'][-1]['vowel'], b['syllables'][-1]['vowel'])
        best = None
        for sa in a['syllables'][:-2]:
            if sa['stress'] == 0:
                continue
            for sb in b['syllables'][:-2]:
                if sb['vowel'] == sa['vowel'] and abs(sa['step'] - sb['step']) <= 2:
                    best = (sa, sb)
                    break
            if best:
                break
        results.append({'bars': [i + 1, i + 2], 'end': end_ok,
                        'internal': bool(best), 'pair': [best[0]['word'], best[1]['word']] if best else None})
    return results


def repeated_phrases(text, n=3):
    lines = [l.lower() for l in text.splitlines() if l.strip()]
    grams = {}
    for li, line in enumerate(lines):
        words = re.findall(r"[a-z']+", line)
        for k in range(len(words) - n + 1):
            grams.setdefault(' '.join(words[k:k + n]), set()).add(li)
    return {g: len(ls) for g, ls in grams.items() if len(ls) > 1}


# ------------------------------------------------------------------ auto grading per form

def auto_grade(form, submission, target_bars=4, scheme='', pocket=None, bpm=90):
    text = submission.get('text', '') or ''
    crits, facts = [], {}
    analysis = flow.analyze(text, bpm, pocket=pocket) if text.strip() else None
    n_bars = analysis['summary']['bars'] if analysis else 0
    facts['bars'] = n_bars

    def bar_count(weight=1.0):
        if not target_bars:
            return
        ratio = min(n_bars / target_bars, 1.0) if target_bars else 1
        over = n_bars > target_bars * 1.5
        crits.append(_crit('length', f'Bar count ({target_bars} asked)', ratio * 100 - (10 if over else 0),
                           f'{n_bars} bar(s) written.', weight))

    def craft_basics():
        imgs = image_check(analysis)
        facts['abstract'] = imgs
        crits.append(_crit('image', 'Image on every fragment', 100 - 18 * len(imgs),
                           'No abstractions spotted.' if not imgs else
                           'Abstract words to turn into pictures: ' + '; '.join(f"bar {f['bar']}: {', '.join(f['words'])}" for f in imgs[:5])))
        counts = [b['count'] for b in analysis['bars']]
        if len(counts) >= 3:
            spread = statistics.pstdev(counts)
            same = spread < 0.6
            crits.append(_crit('variety', 'Syllable variety (no robot flow)', 60 if same else min(100, 70 + spread * 10),
                               f'Syllables per bar: {counts}. ' + ('Identical counts sound robotic.' if same else 'Counts move around naturally.'), 0.5))
        dens = rhyme_density(analysis)
        chain = longest_chain(analysis)
        facts.update(density=round(dens, 2), longest_chain=chain, families=analysis['families'])
        crits.append(_crit('rhyme', 'Rhyme threads', min(100, 40 + dens * 150 + chain * 6),
                           f"{round(dens * 100)}% of syllables sit in a rhyme thread; longest chain {chain} syllables; {analysis['families']} famil(ies)."))
        ends = [b['syllables'][-1]['word'].lower() for b in analysis['bars'] if b['syllables']]
        repeats = {w for w in ends if ends.count(w) > 1}
        lazy = [w for w in ends if w in FILLER_ENDS]
        if repeats or len(lazy) > 1:
            crits.append(_crit('landings', 'Fresh landings', 100 - 15 * len(repeats) - 8 * max(0, len(lazy) - 1),
                               'Repeated or filler end words: ' + ', '.join(sorted(repeats | set(lazy))), 0.5))
        crowded = analysis['summary']['crowded']
        crits.append(_crit('pocket', 'Fits the pocket', 100 - 15 * crowded,
                           f"{analysis['summary']['avg_sps']} syllables/sec at {bpm} BPM; {crowded} crowded bar(s).", 0.5))

    if form in ('bars', 'hook', 'cut', 'story', 'wordplay', 'transcribe', 'skeleton') and not analysis:
        return {'score': 0, 'criteria': [_crit('empty', 'Submission', 0, 'Nothing written yet.')], 'facts': facts, 'analysis': None}

    if form == 'vowel':
        phrase = submission.get('phrase', '').strip()
        matches = [m.strip() for m in submission.get('matches', []) if m.strip()]
        chain = vowel_chain(phrase)
        scored = [{'text': m, 'score': round(vowel_match(phrase, m), 2)} for m in matches]
        verified = [s for s in scored if s['score'] >= 0.75]
        facts.update(phrase_vowels=chain, matches=scored, verified=len(verified))
        goal = int(submission.get('goal') or 15)
        crits.append(_crit('matches', f'Vowel matches ({goal} asked)', min(1, len(verified) / goal) * 100,
                           f"{len(verified)} of {len(matches)} matches carry the vowel chain {'-'.join(chain) or '?'}."))
        secs = submission.get('seconds')
        if secs:
            limit = int(submission.get('limit') or 300)
            crits.append(_crit('speed', 'Speed', 100 if secs <= limit else max(40, 100 - (secs - limit) / 3),
                               f'{secs // 60}m {secs % 60}s (target {limit // 60} min).', 0.5))
        if text.strip():
            crits.append(_crit('bars', 'Bars built from the matches', min(100, n_bars / 4 * 100), f'{n_bars} bar(s).', 0.7))
            craft_basics()
    elif form == 'skeleton':
        bar_count(0.7)
        pairs = internal_slot_pairs(analysis)
        facts['pairs'] = pairs
        ok_int = sum(p['internal'] for p in pairs)
        ok_end = sum(p['end'] for p in pairs)
        total = max(len(pairs), 1)
        crits.append(_crit('internal', 'Internal in the same slot', ok_int / total * 100,
                           '; '.join(f"bars {p['bars'][0]}-{p['bars'][1]}: " + (f"'{p['pair'][0]}' / '{p['pair'][1]}' line up" if p['internal'] else 'no aligned internal found') for p in pairs), 1.5))
        crits.append(_crit('end', 'Held end rhyme', ok_end / total * 100, f'{ok_end}/{total} pair(s) hold the end vowel.', 1.2))
        craft_basics()
    elif form == 'idiom':
        flips = submission.get('flips', {}) or {}
        idiom = submission.get('idiom', '')
        moves = [('exaggerate', 'Exaggerate it'), ('literal', 'Take it literally'), ('frame', 'Own the frame')]
        key_words = {w for w in re.findall(r"[a-z']+", idiom.lower()) if len(w) > 3}
        for key, label in moves:
            v = (flips.get(key) or '').strip()
            keeps = bool(key_words & set(re.findall(r"[a-z']+", v.lower())))
            crits.append(_crit(key, label, (0 if not v else 70 + (20 if keeps else 0) + (10 if len(v.split()) >= 6 else 0)),
                               'missing' if not v else ('keeps the idiom recognisable' if keeps else 'idiom is hard to recognise')))
        facts['idiom'] = idiom
    elif form in ('reflection', 'perform', 'check', 'text'):
        checks = submission.get('checks') or []
        done = sum(1 for c in checks if c)
        words = len(re.findall(r'\w+', text))
        if checks:
            crits.append(_crit('checklist', 'Checklist', done / len(checks) * 100, f'{done}/{len(checks)} items done.'))
        crits.append(_crit('notes', 'Notes / evidence', min(100, words * 4), f'{words} words written.', 0.7))
    else:
        bar_count()
        craft_basics()
        if scheme:
            letters = end_letters(analysis)
            sc = scheme_score(letters, scheme)
            facts['letters'] = ''.join(letters)
            if sc is not None:
                crits.append(_crit('scheme', f'{scheme} scheme', sc * 100, f"End pattern heard: {''.join(letters)}.", 1.2))
        if form == 'hook':
            reps = repeated_phrases(text)
            facts['repeats'] = list(reps)[:5]
            crits.append(_crit('hook', 'One strong repeated phrase', 100 if reps else 30,
                               ('Repeated: "' + '", "'.join(list(reps)[:3]) + '"') if reps else 'No phrase repeats yet; a hook lives on repetition.', 1.3))
        if form == 'story':
            core = submission.get('core_five') or {}
            keys = ['protagonist', 'setting', 'objective', 'obstacle', 'turn']
            filled = [k for k in keys if (core.get(k) or '').strip()]
            crits.append(_crit('core', 'Core Five answered first', len(filled) / 5 * 100,
                               'Missing: ' + ', '.join(k for k in keys if k not in filled) if len(filled) < 5 else 'All five answered.', 1.3))
            setting_words = {w for w in re.findall(r"[a-z']+", (core.get('setting') or '').lower()) if len(w) > 3}
            opening = ' '.join(b['text'].lower() for b in analysis['bars'][:2])
            if setting_words:
                hit = bool(setting_words & set(re.findall(r"[a-z']+", opening)))
                crits.append(_crit('opening', 'Visual in bars 1-2', 100 if hit else 50,
                                   'Opening bars land in the setting.' if hit else 'Bars 1-2 do not show the setting yet.', 0.8))
        if form == 'cut':
            cut = (submission.get('cut_bar') or '').strip()
            why = (submission.get('reason') or '').strip()
            crits.append(_crit('cut', 'Cut the expensive bar', (60 if cut else 0) + (40 if why else 0),
                               ('Cut: "' + cut[:80] + '"' if cut else 'Name the bar you cut.') + (' Reason given.' if why else ' Say why it was expensive.'), 1.2))
        if form == 'transcribe':
            fam = analysis['families']
            crits.append(_crit('threads', 'Rhyme threads spotted', min(100, fam * 30),
                               f'{fam} rhyme thread(s) found in your transcription.', 1.2))
    total_w = sum(c['weight'] for c in crits) or 1
    score = sum(c['score'] * c['weight'] for c in crits) / total_w
    return {'score': round(score), 'criteria': crits, 'facts': facts, 'analysis': analysis}


# ------------------------------------------------------------------ coach review (LLM)

COACH_SCHEMA = '''Reply with ONLY a JSON object, no prose before or after:
{
  "scores": {"image": 0-100, "rhyme": 0-100, "flow": 0-100, "technique": 0-100, "story": 0-100},
  "overall": 0-100,
  "verdict": "pass" or "retry",
  "rung": 1-6,
  "summary": "two sentences, specific",
  "highlights": [{"quote": "exact fragment from the student", "note": "rule it nails or breaks"}],
  "fix": "one concrete fix, shown on one of their bars",
  "assignment": "a 2-4 bar micro-assignment"
}'''


def coach_review(chapter, drill_text, form, submission, auto):
    coach = personas.get('coach') or {}
    body = (chapter or {}).get('body', '')[:7000]
    system = personas.system_prompt(coach, extra=(
        f"You are grading a drill from {chapter.get('title', 'the Bible') if chapter else 'the Bible'}. "
        f"Here is that chapter of the student's manual; grade against IT:\n\n{body}"))
    facts = auto.get('facts', {})
    crit_lines = '\n'.join(f"- {c['label']}: {c['score']}/100 ({c['note']})" for c in auto.get('criteria', []))
    sub_text = submission.get('text', '')
    extra = ''
    if form == 'vowel':
        extra = f"Target phrase: {submission.get('phrase')}\nMatches: {submission.get('matches')}\n"
    if form == 'idiom':
        extra = f"Idiom: {submission.get('idiom')}\nFlips: {submission.get('flips')}\n"
    if form == 'story':
        extra = f"Core Five: {submission.get('core_five')}\n"
    if form == 'cut':
        extra = f"Cut bar: {submission.get('cut_bar')}\nReason: {submission.get('reason')}\n"
    user = (f"DRILL: {drill_text}\n\n{extra}STUDENT SUBMISSION:\n{sub_text}\n\n"
            f"AUTOMATIC CHECKS (machine-measured, trust the numbers, judge the meaning yourself):\n{crit_lines}\n"
            f"Facts: {facts if len(str(facts)) < 1500 else str(facts)[:1500]}\n\n{COACH_SCHEMA}")
    reply = llm.complete([{'role': 'user', 'content': user}], system, temperature=0.4, max_tokens=1600)
    data = llm.extract_json(reply)
    if not isinstance(data, dict):
        return {'summary': reply.strip()[:1200], 'overall': None, 'raw': True}
    try:
        data['overall'] = int(max(0, min(100, float(data.get('overall', 0)))))
    except (TypeError, ValueError):
        data['overall'] = None
    data['highlights'] = [h for h in (data.get('highlights') or []) if isinstance(h, dict)][:6]
    return data


def combine(auto, coach):
    a = auto.get('score', 0)
    c = (coach or {}).get('overall')
    score = round(0.4 * a + 0.6 * c) if isinstance(c, int) else a
    return {'score': score, 'letter': letter(score), 'passed': score >= 70}


# ------------------------------------------------------------------ report card

def _highlight_md(analysis):
    lines = []
    for b in (analysis or {}).get('bars', []):
        out, prev_word = [], None
        for s in b['syllables']:
            piece = s['text']
            if 'rhyme' in s:
                piece = f"**{piece}**<sub>{s['rhyme']}</sub>"
            if prev_word is not None and s['start']:
                out.append(' ')
            out.append(piece)
            prev_word = s['w']
        lines.append(f"{b['index'] + 1:>2}. {''.join(out)}  *({b['count']} syl · {b['zone']})*")
    return '\n'.join(lines)


def report_markdown(meta, submission, auto, coach, grade, rewards=None):
    """A printable, shareable graded document."""
    when = time.strftime('%B %d, %Y · %H:%M', time.localtime(meta.get('created_at', time.time())))
    out = [f"# Report Card · {meta.get('title', 'Drill')}",
           f"**{meta.get('student', 'Student')}** · {meta.get('rank', '')} · {when}",
           f"*{meta.get('chapter_title', '')}*", '',
           f"## Grade: {grade['letter']} ({grade['score']}/100) · {'PASSED' if grade['passed'] else 'RETRY'}", '',
           f"> {meta.get('drill_text', '')}", '']
    if submission.get('phrase'):
        out += [f"**Target phrase:** {submission['phrase']}  ·  vowels: {'-'.join(auto['facts'].get('phrase_vowels', []))}", '']
        for m in auto['facts'].get('matches', []):
            out.append(f"- {'✅' if m['score'] >= 0.75 else '▫️'} {m['text']} ({int(m['score'] * 100)}%)")
        out.append('')
    if submission.get('idiom'):
        out += [f"**Idiom:** {submission['idiom']}", '']
        for k, v in (submission.get('flips') or {}).items():
            out.append(f"- *{k}*: {v}")
        out.append('')
    if submission.get('core_five'):
        out += ['**Core Five**', ''] + [f"- **{k.title()}:** {v}" for k, v in submission['core_five'].items() if v] + ['']
    if auto.get('analysis'):
        out += ['## Your bars (rhyme threads in bold, family number below)', '', _highlight_md(auto['analysis']), '']
    out += ['## Machine checks', '', '| Check | Score | Notes |', '|---|---|---|']
    for c in auto.get('criteria', []):
        out.append(f"| {c['label']} | {c['score']} | {c['note'].replace('|', '/')} |")
    out.append('')
    if coach:
        out += ['## Coach notes', '']
        if coach.get('summary'):
            out += [coach['summary'], '']
        sc = coach.get('scores') or {}
        if sc:
            out += [' · '.join(f"{k.title()} {v}" for k, v in sc.items() if isinstance(v, (int, float))), '']
        for h in coach.get('highlights', []):
            out.append(f"- \"{h.get('quote', '')}\": {h.get('note', '')}")
        if coach.get('fix'):
            out += ['', f"**One fix:** {coach['fix']}"]
        if coach.get('assignment'):
            out += ['', f"**Micro-assignment:** {coach['assignment']}"]
        if coach.get('rung'):
            out += ['', f"Coach places you around **Rung {coach['rung']}**."]
        out.append('')
    if rewards:
        out += ['## Rewards', ''] + [f"- {r.get('label', '')}" for r in rewards if r.get('label')] + ['']
    out.append('*Generated by OpenField Station · The Academy*')
    return '\n'.join(out)
