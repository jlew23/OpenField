"""LLM plumbing for the Station: local models or bring-your-own-key.

Providers
  ollama     local Ollama server (native /api/chat streaming)
  openai     any OpenAI-compatible /chat/completions endpoint: LM Studio, llama.cpp
             server, vLLM, OpenRouter, Groq, Together, OpenAI ...
  anthropic  Claude through the official `anthropic` SDK

Settings live in the Station database. Keys are never sent back to the browser.
Environment variables fill anything left blank, so a populated .env also works.
"""
import json, os, re, time
import requests

from . import db
from config import setting as env_setting

DEFAULTS = {
    'provider': 'ollama',
    'temperature': 0.8,
    'max_tokens': 2048,
    'user_title': 'Sir',
    'ollama': {'base_url': '', 'model': ''},
    'openai': {'preset': 'lmstudio', 'base_url': 'http://127.0.0.1:1234/v1', 'model': '', 'api_key': ''},
    'anthropic': {'model': 'claude-opus-5-5', 'api_key': ''},
}

PRESETS = {
    'lmstudio': {'label': 'LM Studio (local)', 'base_url': 'http://127.0.0.1:1234/v1', 'needs_key': False},
    'llamacpp': {'label': 'llama.cpp server (local)', 'base_url': 'http://127.0.0.1:8080/v1', 'needs_key': False},
    'openrouter': {'label': 'OpenRouter', 'base_url': 'https://openrouter.ai/api/v1', 'needs_key': True},
    'openai': {'label': 'OpenAI', 'base_url': 'https://api.openai.com/v1', 'needs_key': True},
    'groq': {'label': 'Groq', 'base_url': 'https://api.groq.com/openai/v1', 'needs_key': True},
    'together': {'label': 'Together', 'base_url': 'https://api.together.xyz/v1', 'needs_key': True},
    'custom': {'label': 'Custom OpenAI-compatible', 'base_url': '', 'needs_key': False},
}

ANTHROPIC_MODELS = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1']
# Models that accept Anthropic's server-side refusal fallback ("default" routing).
FALLBACK_MODELS = {'claude-opus-5-5', 'claude-opus-5', 'claude-fable-5-1', 'claude-sonnet-5-5'}


class LLMError(Exception):
    """A provider problem worth showing to the user as-is."""


# ------------------------------------------------------------------ settings

def _merge(base, patch):
    out = json.loads(json.dumps(base))
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def settings():
    return _merge(DEFAULTS, db.get_setting('llm', {}))


def _mask(key):
    return ('••••' + key[-4:]) if key and len(key) > 8 else ('set' if key else '')


def _env_key(provider, cfg):
    if provider == 'anthropic':
        return env_setting('ANTHROPIC_API_KEY')
    preset = cfg['openai'].get('preset')
    names = {'openrouter': 'OPENROUTER_API_KEY', 'groq': 'GROQ_API_KEY', 'together': 'TOGETHER_API_KEY'}
    return env_setting(names.get(preset, 'OPENAI_API_KEY')) or (env_setting('OPENAI_API_KEY') if preset == 'openai' else '')


def public_settings():
    cfg = settings()
    out = json.loads(json.dumps(cfg))
    for p in ('openai', 'anthropic'):
        stored = cfg[p].get('api_key', '')
        out[p]['api_key'] = ''
        out[p]['key_hint'] = _mask(stored) or ('from .env' if _env_key(p, cfg) else '')
        out[p]['key_set'] = bool(stored or _env_key(p, cfg))
    out['presets'] = PRESETS
    out['anthropic_models'] = ANTHROPIC_MODELS
    return out


def update_settings(patch):
    """Apply a settings patch from the UI. Blank api_key means 'keep the stored key'."""
    cfg = settings()
    patch = json.loads(json.dumps(patch or {}))
    for p in ('openai', 'anthropic'):
        section = patch.get(p)
        if not isinstance(section, dict):
            continue
        new_key = (section.pop('api_key', '') or '').strip()
        if section.pop('clear_key', False):
            cfg[p]['api_key'] = ''
        # Changing where requests go invalidates the stored key, so a key can't be
        # silently redirected to a different server.
        if p == 'openai' and 'base_url' in section and section['base_url'].rstrip('/') != cfg['openai']['base_url'].rstrip('/'):
            cfg['openai']['api_key'] = ''
        if new_key:
            cfg[p]['api_key'] = new_key
        cfg[p].update({k: v for k, v in section.items() if k in DEFAULTS[p]})
    for k in ('provider', 'temperature', 'max_tokens', 'user_title'):
        if k in patch:
            cfg[k] = patch[k]
    if cfg['provider'] not in ('ollama', 'openai', 'anthropic'):
        raise LLMError('Unknown provider')
    cfg['temperature'] = max(0.0, min(2.0, float(cfg['temperature'])))
    cfg['max_tokens'] = max(64, min(64000, int(cfg['max_tokens'])))
    db.set_setting('llm', {k: v for k, v in cfg.items() if k in DEFAULTS})
    _ollama_cache.clear()
    return public_settings()


# ------------------------------------------------------------------ ollama

_ollama_cache = {}


def _wsl_host_candidates():
    """Windows host address when running under WSL (Ollama often lives on Windows)."""
    hosts = []
    try:
        with open('/proc/net/route') as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) > 2 and parts[1] == '00000000':
                    gw = int(parts[2], 16)
                    hosts.append('.'.join(str((gw >> (8 * i)) & 255) for i in range(4)))
    except OSError:
        pass
    try:
        with open('/etc/resolv.conf') as f:
            for line in f:
                if line.startswith('nameserver'):
                    hosts.append(line.split()[1])
    except OSError:
        pass
    return hosts


def ollama_base(cfg=None):
    cfg = cfg or settings()
    configured = (cfg['ollama'].get('base_url') or '').rstrip('/')
    if configured:
        return configured
    if 'base' in _ollama_cache and time.time() - _ollama_cache['t'] < 60:
        return _ollama_cache['base']
    env = (os.getenv('OLLAMA_API_BASE') or os.getenv('OLLAMA_HOST') or '').rstrip('/')
    cands = [env] if env else []
    cands += ['http://127.0.0.1:11434'] + [f'http://{h}:11434' for h in _wsl_host_candidates()]
    for base in cands:
        if not base.startswith('http'):
            base = 'http://' + base
        try:
            if requests.get(base + '/api/tags', timeout=1.5).ok:
                _ollama_cache.update(base=base, t=time.time())
                return base
        except requests.RequestException:
            continue
    return cands[0] if cands else 'http://127.0.0.1:11434'


def _ollama_models(cfg):
    r = requests.get(ollama_base(cfg) + '/api/tags', timeout=5)
    r.raise_for_status()
    return [m['name'] for m in r.json().get('models', [])]


def _ollama_model(cfg):
    model = cfg['ollama'].get('model')
    if model:
        return model
    try:
        names = _ollama_models(cfg)
    except requests.RequestException:
        names = []
    if not names:
        raise LLMError('No Ollama model found. Start Ollama and run e.g. `ollama pull qwen2.5:14b`, '
                       'or pick another provider in Station settings.')
    general = [n for n in names if 'coder' not in n and 'embed' not in n]
    return (general or names)[0]


def _stream_ollama(cfg, system, messages, temperature, max_tokens):
    base = ollama_base(cfg)
    model = _ollama_model(cfg)
    body = {'model': model, 'stream': True,
            'messages': [{'role': 'system', 'content': system}] + messages,
            'options': {'temperature': temperature, 'num_predict': max_tokens}}
    try:
        r = requests.post(base + '/api/chat', json=body, stream=True, timeout=(10, 600))
    except requests.RequestException as e:
        raise LLMError(f'Cannot reach Ollama at {base}. Is it running? ({type(e).__name__})')
    if r.status_code == 404:
        raise LLMError(f'Ollama does not have the model "{model}". Run: ollama pull {model}')
    if not r.ok:
        raise LLMError(f'Ollama error {r.status_code}: {r.text[:300]}')
    for line in r.iter_lines():
        if not line:
            continue
        data = json.loads(line)
        if data.get('error'):
            raise LLMError('Ollama: ' + data['error'])
        chunk = (data.get('message') or {}).get('content', '')
        if chunk:
            yield chunk
        if data.get('done'):
            break


# ------------------------------------------------------------------ openai-compatible

def _openai_key(cfg):
    return cfg['openai'].get('api_key') or _env_key('openai', cfg)


def _openai_headers(cfg):
    headers = {'Content-Type': 'application/json'}
    key = _openai_key(cfg)
    if key:
        headers['Authorization'] = 'Bearer ' + key
    if 'openrouter.ai' in cfg['openai'].get('base_url', ''):
        headers['HTTP-Referer'] = 'http://127.0.0.1'
        headers['X-Title'] = 'OpenField Station'
    return headers


def _openai_models(cfg):
    base = cfg['openai']['base_url'].rstrip('/')
    r = requests.get(base + '/models', headers=_openai_headers(cfg), timeout=8)
    r.raise_for_status()
    return sorted(m.get('id') for m in r.json().get('data', []) if m.get('id'))


def _stream_openai(cfg, system, messages, temperature, max_tokens):
    base = cfg['openai']['base_url'].rstrip('/')
    if not base:
        raise LLMError('Set a base URL for the OpenAI-compatible provider in Station settings.')
    preset = PRESETS.get(cfg['openai'].get('preset'), {})
    if preset.get('needs_key') and not _openai_key(cfg):
        raise LLMError(f"{preset.get('label', 'This provider')} needs an API key. Add it in Station settings.")
    model = cfg['openai'].get('model')
    if not model:
        try:
            models = _openai_models(cfg)
        except requests.RequestException:
            models = []
        if not models:
            raise LLMError('Pick a model for the OpenAI-compatible provider in Station settings.')
        model = models[0]
    body = {'model': model, 'stream': True, 'temperature': temperature, 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': system}] + messages}
    try:
        r = requests.post(base + '/chat/completions', json=body, headers=_openai_headers(cfg), stream=True, timeout=(10, 600))
    except requests.RequestException as e:
        raise LLMError(f'Cannot reach {base} ({type(e).__name__}).')
    if r.status_code in (401, 403):
        raise LLMError('The provider rejected the API key.')
    if not r.ok:
        raise LLMError(f'Provider error {r.status_code}: {r.text[:300]}')
    for raw in r.iter_lines():
        if not raw:
            continue
        line = raw.decode('utf-8', 'replace')
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            break
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if data.get('error'):
            raise LLMError(str(data['error'].get('message', data['error'])))
        for choice in data.get('choices', []):
            chunk = (choice.get('delta') or {}).get('content')
            if chunk:
                yield chunk


# ------------------------------------------------------------------ anthropic

def _anthropic_client(cfg):
    try:
        import anthropic
    except ImportError:
        raise LLMError('Install the Anthropic SDK to use Claude: pip install anthropic')
    key = cfg['anthropic'].get('api_key') or _env_key('anthropic', cfg)
    if not key:
        raise LLMError('Add your Anthropic API key in Station settings (or ANTHROPIC_API_KEY in .env).')
    return anthropic, anthropic.Anthropic(api_key=key)


def _stream_anthropic(cfg, system, messages, temperature, max_tokens):
    anthropic, client = _anthropic_client(cfg)
    model = cfg['anthropic'].get('model') or 'claude-opus-5-5'
    # Current Claude models reject sampling parameters, so temperature is not sent.
    kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
    try:
        if model in FALLBACK_MODELS:
            # Server-side fallback: if a safety classifier declines, the API re-runs
            # the request on Anthropic's recommended fallback model in the same call.
            ctx = client.beta.messages.stream(**kwargs, betas=['server-side-fallback-2026-07-01'], fallbacks='default')
        else:
            ctx = client.messages.stream(**kwargs)
        with ctx as stream:
            for text in stream.text_stream:
                yield text
            final = stream.get_final_message()
        if getattr(final, 'stop_reason', None) == 'refusal':
            yield '\n\n[The model declined this request.]'
        elif getattr(final, 'stop_reason', None) == 'max_tokens':
            yield '\n\n[Reply cut off at the max token limit. Raise it in Station settings.]'
    except anthropic.AuthenticationError:
        raise LLMError('Anthropic rejected the API key.')
    except anthropic.PermissionDeniedError as e:
        raise LLMError(f'Anthropic denied access: {e.message}')
    except anthropic.NotFoundError:
        raise LLMError(f'Anthropic does not know the model "{model}".')
    except anthropic.RateLimitError:
        raise LLMError('Anthropic rate limit hit. Wait a moment and try again.')
    except anthropic.APIStatusError as e:
        raise LLMError(f'Anthropic error {e.status_code}: {e.message}')
    except anthropic.APIConnectionError:
        raise LLMError('Cannot reach the Anthropic API. Check your connection.')


def _anthropic_models(cfg):
    try:
        _, client = _anthropic_client(cfg)
        return [m.id for m in client.models.list()]
    except Exception:
        return ANTHROPIC_MODELS


# ------------------------------------------------------------------ public API

def _normalise(messages):
    """Keep user/assistant turns, merge consecutive same-role turns, start with user."""
    out = []
    for m in messages:
        role = m.get('role')
        content = (m.get('content') or '').strip()
        if role not in ('user', 'assistant') or not content:
            continue
        if out and out[-1]['role'] == role:
            out[-1]['content'] += '\n\n' + content
        else:
            out.append({'role': role, 'content': content})
    while out and out[0]['role'] != 'user':
        out.pop(0)
    return out


def stream_chat(messages, system, temperature=None, max_tokens=None, cfg=None):
    """Yield text chunks from the configured provider."""
    cfg = cfg or settings()
    msgs = _normalise(messages)
    if not msgs:
        raise LLMError('Nothing to send.')
    temperature = cfg['temperature'] if temperature is None else temperature
    max_tokens = max_tokens or cfg['max_tokens']
    provider = cfg['provider']
    fn = {'ollama': _stream_ollama, 'openai': _stream_openai, 'anthropic': _stream_anthropic}[provider]
    yield from fn(cfg, system, msgs, temperature, max_tokens)


def complete(messages, system, **kw):
    return ''.join(stream_chat(messages, system, **kw))


def list_models(cfg=None):
    cfg = cfg or settings()
    try:
        if cfg['provider'] == 'ollama':
            return _ollama_models(cfg)
        if cfg['provider'] == 'openai':
            return _openai_models(cfg)
        return _anthropic_models(cfg)
    except requests.RequestException as e:
        raise LLMError(f'Could not list models ({type(e).__name__}).')


def status(cfg=None):
    """Cheap reachability check for the War Room board (no tokens spent)."""
    cfg = cfg or settings()
    p = cfg['provider']
    try:
        if p == 'ollama':
            base = ollama_base(cfg)
            names = _ollama_models(cfg)
            model = cfg['ollama'].get('model') or (names[0] if names else '')
            ok = bool(names) and (not cfg['ollama'].get('model') or cfg['ollama']['model'] in names)
            return {'provider': p, 'ok': ok, 'model': model, 'detail': f'{base} · {len(names)} model(s)'}
        if p == 'openai':
            preset = PRESETS.get(cfg['openai'].get('preset'), {})
            if preset.get('needs_key') and not _openai_key(cfg):
                return {'provider': p, 'ok': False, 'model': cfg['openai'].get('model'), 'detail': 'API key missing'}
            models = _openai_models(cfg)
            return {'provider': p, 'ok': True, 'model': cfg['openai'].get('model') or (models[0] if models else ''),
                    'detail': f"{preset.get('label', 'custom')} · {len(models)} model(s)"}
        key = cfg['anthropic'].get('api_key') or _env_key('anthropic', cfg)
        return {'provider': p, 'ok': bool(key), 'model': cfg['anthropic'].get('model'),
                'detail': 'key configured' if key else 'API key missing'}
    except (requests.RequestException, LLMError, ValueError) as e:
        return {'provider': p, 'ok': False, 'model': '', 'detail': str(e)[:200] or type(e).__name__}


def extract_json(text):
    """Best-effort JSON object extraction from a model reply."""
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    candidates = [m.group(1)] if m else []
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except ValueError:
            continue
    return None
