"""The Claude line: Claude Code on your own machine, reachable from the War Room at any time.

It runs the Claude Code CLI headless (`claude -p ... --output-format stream-json`) inside your
jarvis-galaxy folder, so Claude picks up that folder's CLAUDE.md, settings, skills and agents. One
thread is kept going with `--resume`, so it remembers the conversation across messages and restarts.

Where things come from:
- Galaxy folder: the War Room setting, else JARVIS_GALAXY_DIR, else Documents/jarvis-galaxy next to
  Documents/openfield.
- Agents: Markdown files with front matter (Claude Code subagent format) in the galaxy's `sub*` folders
  (subagents/, sub-agents/, ...) and in .claude/agents/. Pick one and the message is routed to it.

Safety: by default Claude Code runs with its normal permission rules, so in headless mode anything that
would need an approval (edits, shell commands) is refused. Allow more in the War Room (allowed tools) if you
want it to act. The endpoints only answer requests from this machine unless you turn on LAN access.
"""
import json, os, re, shutil, subprocess, threading, time
from pathlib import Path

from . import db

_runs_root = None
TIMEOUT = 15 * 60


def set_runs(path):
    global _runs_root
    _runs_root = Path(path) if path else None


def config():
    c = db.get_setting('claude_line', {}) or {}
    return {'galaxy_dir': c.get('galaxy_dir', ''), 'allowed_tools': c.get('allowed_tools', ''),
            'model': c.get('model', ''), 'allow_lan': bool(c.get('allow_lan', False))}


def update_config(data):
    c = config()
    for k in ('galaxy_dir', 'allowed_tools', 'model'):
        if k in data:
            c[k] = str(data[k] or '').strip()
    if 'allow_lan' in data:
        c['allow_lan'] = bool(data['allow_lan'])
    db.set_setting('claude_line', c)
    return status()


def galaxy_dir():
    for cand in (config()['galaxy_dir'], os.getenv('JARVIS_GALAXY_DIR', '')):
        if cand and Path(cand).expanduser().is_dir():
            return Path(cand).expanduser()
    roots = []
    if _runs_root:
        roots.append(_runs_root.parent)  # Documents/openfield -> Documents
    if os.getenv('USERPROFILE'):
        roots.append(Path(os.environ['USERPROFILE']) / 'Documents')
    roots.append(Path.home() / 'Documents')
    for root in roots:
        for name in ('jarvis-galaxy', 'Jarvis-Galaxy', 'jarvis_galaxy', 'JarvisGalaxy'):
            if (root / name).is_dir():
                return root / name
    return None


def cli():
    for name in ('claude', 'claude.exe', 'claude.cmd'):
        p = shutil.which(name)
        if p:
            return p
    for p in (Path.home() / '.claude' / 'local' / 'claude', Path.home() / '.local' / 'bin' / 'claude'):
        if p.exists():
            return str(p)
    return None


def _front_matter(text):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.S)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(':')
        if sep and k.strip() and not k.startswith(' '):
            meta[k.strip()] = v.strip().strip('"\'')
    return meta


def agents(galaxy=None):
    galaxy = galaxy or galaxy_dir()
    if not galaxy:
        return [], []
    folders = sorted(p for p in galaxy.iterdir() if p.is_dir() and p.name.lower().startswith('sub'))
    claude_agents = galaxy / '.claude' / 'agents'
    if claude_agents.is_dir():
        folders.append(claude_agents)
    found, seen = [], set()
    for folder in folders:
        for f in sorted(folder.rglob('*.md'))[:200]:
            try:
                meta = _front_matter(f.read_text(encoding='utf-8', errors='replace')[:4000])
            except OSError:
                continue
            if not meta:
                continue
            name = meta.get('name') or f.stem
            if name in seen:
                continue
            seen.add(name)
            found.append({'name': name, 'description': meta.get('description', '')[:240],
                          'model': meta.get('model', ''), 'file': str(f.relative_to(galaxy))})
    summary = [{'folder': str(p.relative_to(galaxy)), 'files': sum(1 for _ in p.rglob('*') if _.is_file())} for p in folders]
    return found, summary


_status_cache = {}


def status():
    if _status_cache and time.time() - _status_cache['t'] < 20:
        return _status_cache['v']
    path, g = cli(), galaxy_dir()
    version = ''
    if path:
        try:
            version = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=10).stdout.strip()[:60]
        except (OSError, subprocess.SubprocessError):
            pass
    found, folders = agents(g)
    c = config()
    v = {'ok': bool(path and g), 'cli': bool(path), 'version': version, 'galaxy': str(g) if g else '',
         'agents': found, 'folders': folders, 'session': bool(db.get_setting('claude_line_session')),
         'allowed_tools': c['allowed_tools'], 'model': c['model'], 'allow_lan': c['allow_lan'],
         'detail': ('ready' if path and g else
                    'Install Claude Code and log in once: npm install -g @anthropic-ai/claude-code, then run `claude`.' if not path else
                    'jarvis-galaxy not found: set its folder in the War Room.')}
    _status_cache.update(v=v, t=time.time())
    return v


def thread_id():
    cid = db.get_setting('claude_line_thread')
    if not cid or not db.get_conversation(cid):
        cid = db.create_conversation('claude', 'Claude line')
        db.set_setting('claude_line_thread', cid)
    return cid


def new_thread():
    db.set_setting('claude_line_session', None)
    db.set_setting('claude_line_thread', None)
    _status_cache.clear()
    return {'thread': thread_id()}


_partial = {'ok': True}  # older CLIs lack --include-partial-messages


def command(message, agent=None, session=None):
    path, g = cli(), galaxy_dir()
    if not path:
        raise RuntimeError(status()['detail'])
    if not g:
        raise RuntimeError('jarvis-galaxy folder not found. Set it in the War Room.')
    c = config()
    prompt = f'Use the {agent} subagent for this.\n\n{message}' if agent else message
    cmd = [path, '-p', prompt, '--output-format', 'stream-json', '--verbose'] + \
          (['--include-partial-messages'] if _partial['ok'] else []) + ['--append-system-prompt', 'You are reachable from the OpenField Station War Room. The user is talking to you '
           'from that page; answers render as Markdown. Be direct.']
    if session:
        cmd += ['--resume', session]
    if c['allowed_tools']:
        cmd += ['--allowedTools', c['allowed_tools']]
    if c['model']:
        cmd += ['--model', c['model']]
    return cmd, g


def parse(line):
    """One stream-json line -> ('session'|'delta'|'text'|'tool'|'result'|'error', value) or None."""
    try:
        e = json.loads(line)
    except ValueError:
        return None
    t = e.get('type')
    if t == 'system' and e.get('subtype') == 'init':
        return 'session', e.get('session_id')
    if t == 'stream_event':
        ev = e.get('event') or {}
        d = ev.get('delta') or {}
        if ev.get('type') == 'content_block_delta' and d.get('type') == 'text_delta':
            return 'delta', d.get('text', '')
        return None
    if t == 'assistant':
        parts = (e.get('message') or {}).get('content') or []
        tools = [p.get('name') for p in parts if p.get('type') == 'tool_use']
        if tools:
            return 'tool', ', '.join(x for x in tools if x)
        text = ''.join(p.get('text', '') for p in parts if p.get('type') == 'text')
        return ('text', text) if text else None
    if t == 'result':
        if e.get('is_error') or e.get('subtype', 'success') != 'success':
            return 'error', e.get('result') or e.get('subtype') or 'Claude Code reported an error.'
        return 'result', {'text': e.get('result', ''), 'session': e.get('session_id'),
                          'cost': e.get('total_cost_usd'), 'turns': e.get('num_turns')}
    return None


def ask(message, agent=None):
    """Stream one turn. Yields (kind, value) with kind in delta|tool|done|error."""
    cid = thread_id()
    db.add_message(cid, 'user', message, {'agent': agent} if agent else None)
    db.log_event('claude', 'ask', (f'@{agent} ' if agent else '') + message[:90])
    for attempt in range(2):
        retry = False
        for kind, value in _run(cid, message, agent):
            if kind == 'retry':
                retry = True
                break
            yield kind, value
        if not retry:
            return


def _run(cid, message, agent):
    session = db.get_setting('claude_line_session')
    try:
        cmd, cwd = command(message, agent, session)
    except RuntimeError as e:
        yield 'error', str(e)
        return
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='replace', bufsize=1)
    timer = threading.Timer(TIMEOUT, proc.kill)
    timer.start()
    streamed, final, tools = [], None, []
    try:
        for line in proc.stdout:
            got = parse(line)
            if not got:
                continue
            kind, value = got
            if kind == 'session' and value:
                db.set_setting('claude_line_session', value)
            elif kind == 'delta':
                streamed.append(value)
                yield 'delta', value
            elif kind == 'text' and not streamed:  # CLI without partial messages: whole blocks
                streamed.append(value)
                yield 'delta', value
            elif kind == 'tool':
                tools.append(value)
                yield 'tool', value
            elif kind == 'result':
                final = value
            elif kind == 'error':
                yield 'error', str(value)[:600]
        proc.wait(timeout=30)
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
    if final is None:
        err = (proc.stderr.read() or '').strip()
        if _partial['ok'] and 'include-partial-messages' in err and not streamed:
            _partial['ok'] = False
            yield 'retry', None
            return
        if session and 'session' in err.lower():  # stale thread: start fresh next time
            db.set_setting('claude_line_session', None)
        yield 'error', (err[-600:] or f'Claude Code exited with code {proc.returncode}.')
        return
    if final.get('session'):
        db.set_setting('claude_line_session', final['session'])
    text = final.get('text') or ''.join(streamed)
    db.add_message(cid, 'assistant', text, {'agent': agent, 'tools': tools, 'cost': final.get('cost')})
    db.log_event('claude', 'reply', (f'@{agent}: ' if agent else '') + text.strip().replace('\n', ' ')[:90])
    yield 'done', {'text': text, 'cost': final.get('cost'), 'turns': final.get('turns')}


def history(limit=60):
    return db.get_messages(thread_id(), limit)
