"""Parse lyric sheets (markdown or plain text) into sections, speakers and bars.

One line of lyrics = one bar, the same rule the Rap Writing Bible teaches.
Recognised markup:
  ## / ### Heading            -> new section
  **BIGGIE:**  or  BIGGIE:    -> speaker change (line may also carry lyrics after the colon)
  *(stage direction)*         -> direction, not a bar
  Tempo: 90 BPM / 90 BPM      -> tempo hint
  ---, bullets, blank lines   -> ignored
"""
import re

_SPEAKER = re.compile(r"^\s*\*{0,2}([A-Z][A-Za-z0-9 .'&\-]{0,30}?)\*{0,2}\s*(\*\([^)]*\)\*)?\s*:\s*\*{0,2}\s*(.*)$")
_HEADING = re.compile(r'^\s*#{1,6}\s+(.*)$')
_DIRECTION = re.compile(r'^\s*\*?\(([^)]*)\)\*?\s*$')
_BPM = re.compile(r'(\d{2,3}(?:\.\d+)?)\s*BPM', re.I)
_MD = re.compile(r'(\*\*|__|\*|_|`|\\)')


def clean_text(text):
    text = _MD.sub('', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def tempo_hint(text):
    m = _BPM.search(text or '')
    return float(m.group(1)) if m else None


def _speaker_from(line):
    m = _SPEAKER.match(line)
    if not m:
        return None, None
    name = m.group(1).strip()
    # Require the name to look like a tag: mostly uppercase, or wrapped in bold.
    if not (name.isupper() or line.lstrip().startswith('**')):
        return None, None
    if len(name.split()) > 4:
        return None, None
    return name, m.group(3)


def parse(text):
    """Return {'sections': [{'title', 'lines': [{'speaker','text','kind','index'}]}], 'bars': n}."""
    sections = [{'title': 'Verse', 'lines': []}]
    speaker = ''
    bar_index = 0
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped in ('---', '***', '___'):
            continue
        h = _HEADING.match(stripped)
        if h:
            title = clean_text(h.group(1))
            if sections[-1]['lines'] or sections[-1]['title'] != 'Verse':
                sections.append({'title': title, 'lines': []})
            else:
                sections[-1]['title'] = title
            continue
        if stripped.startswith(('- ', '* ', '+ ')) and not stripped.startswith('*('):
            continue
        if stripped.startswith('>'):
            continue
        d = _DIRECTION.match(stripped)
        if d:
            sections[-1]['lines'].append({'speaker': speaker, 'text': clean_text(d.group(1)), 'kind': 'direction'})
            continue
        name, rest = _speaker_from(stripped)
        if name:
            speaker = name.upper()
            rest = (rest or '').strip()
            if not rest:
                continue
            stripped = rest
            dd = _DIRECTION.match(stripped)
            if dd:
                sections[-1]['lines'].append({'speaker': speaker, 'text': clean_text(dd.group(1)), 'kind': 'direction'})
                continue
        text_line = clean_text(stripped)
        # Inline leading direction such as "*(laughs)* That's chess"
        text_line = re.sub(r'^\(([^)]*)\)\s*', '', text_line)
        if not text_line:
            continue
        if text_line.lower().startswith(('setting:', 'starring:', 'tempo:', 'key:')):
            continue
        sections[-1]['lines'].append({'speaker': speaker, 'text': text_line, 'kind': 'bar', 'index': bar_index})
        bar_index += 1
    sections = [s for s in sections if s['lines']]
    return {'sections': sections, 'bars': bar_index}


def bars(text):
    """Flat list of bar dicts in order."""
    out = []
    for s in parse(text)['sections']:
        for line in s['lines']:
            if line['kind'] == 'bar':
                out.append({**line, 'section': s['title']})
    return out


def to_text(parsed):
    """Render a parsed sheet back to simple markdown."""
    chunks = []
    for s in parsed['sections']:
        chunks.append('### ' + s['title'])
        speaker = None
        for line in s['lines']:
            if line['speaker'] and line['speaker'] != speaker:
                speaker = line['speaker']
                chunks.append(f'**{speaker}:**')
            chunks.append(f"*({line['text']})*" if line['kind'] == 'direction' else line['text'])
        chunks.append('')
    return '\n'.join(chunks).strip() + '\n'
