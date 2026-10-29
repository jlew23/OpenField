/* OpenField Station shared client: API, streaming, rewards, flow grid, markdown, settings, command palette, audio. */
(() => {
const S = window.Station = {};

/* ------------------------------------------------------------ api */
S.api = async (path, opts = {}) => {
  const o = { headers: {}, ...opts };
  if (o.body && !(o.body instanceof FormData) && typeof o.body !== 'string') {
    o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(o.body);
  }
  const r = await fetch(path, o);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) || (typeof data === 'string' ? data : r.statusText));
  return data;
};
S.get = p => S.api(p);
S.post = (p, body) => S.api(p, { method: 'POST', body: body || {} });
S.put = (p, body) => S.api(p, { method: 'PUT', body });
S.del = p => S.api(p, { method: 'DELETE' });

/* SSE over fetch (POST). handlers: {meta, delta, replace, action_start, action, done, error} */
S.stream = async (path, body, handlers) => {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail; } catch (_) {} handlers.error && handlers.error({ message: m }); return; }
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
  for (;;) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (!data) continue;
      try { handlers[ev] && handlers[ev](JSON.parse(data)); } catch (e) { console.error(e); }
    }
  }
};

/* ------------------------------------------------------------ dom helpers */
S.$ = (sel, root = document) => root.querySelector(sel);
S.$$ = (sel, root = document) => [...root.querySelectorAll(sel)];
S.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
S.h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
S.qs = k => new URLSearchParams(location.search).get(k);
S.debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
S.fmtAgo = ts => { const s = Date.now() / 1000 - ts; if (s < 60) return 'just now'; if (s < 3600) return Math.round(s / 60) + 'm ago'; if (s < 86400) return Math.round(s / 3600) + 'h ago'; return Math.round(s / 86400) + 'd ago'; };

/* ------------------------------------------------------------ shell */
const NAV = [['/station', 'Bridge'], ['/station/rapquest', 'RapQuest'], ['/station/academy', 'Academy'], ['/station/persona', 'Personas'], ['/station/warroom', 'War Room'], ['/', 'Studio']];
S.shell = (active) => {
  const bar = S.h(`<header class="topbar">
    <a class="brand" href="/station"><span class="mark">J</span><span><b>OPENFIELD STATION</b><small>JARVIS AT THE HELM</small></span></a>
    <nav class="nav">${NAV.map(([href, label]) => `<a href="${href}" class="${label === active ? 'on' : ''}">${label}</a>`).join('')}</nav>
    <div class="spacer"></div>
    <span class="pill" id="cmd-pill" title="Command palette">⌘K</span>
    <span class="pill" id="llm-pill" title="LLM settings"><span class="dot"></span><span id="llm-label">LLM…</span></span>
  </header>`);
  document.body.prepend(bar);
  document.body.insertAdjacentHTML('beforeend', `<div id="toasts"></div><canvas id="confetti"></canvas>`);
  S.$('#llm-pill').onclick = S.openSettings;
  S.$('#cmd-pill').onclick = S.openPalette;
  S.refreshLLM();
  S.initPalette();
};
S.refreshLLM = async () => {
  try {
    const st = await S.get('/api/llm/status');
    S.$('#llm-pill .dot').className = 'dot ' + (st.ok ? 'ok' : 'bad');
    S.$('#llm-label').textContent = `${st.provider}${st.model ? ' · ' + st.model : ''}`;
    S.llmStatus = st;
  } catch (e) { S.$('#llm-label').textContent = 'LLM offline'; }
};

/* ------------------------------------------------------------ rewards: toasts, confetti, sound */
S.prefs = { sounds: true };
let actx;
const ctx = () => (actx = actx || new (window.AudioContext || window.webkitAudioContext)());
S.tone = (notes, type = 'triangle', gap = 0.09, vol = 0.12) => {
  if (!S.prefs.sounds) return;
  try {
    const a = ctx(); const t0 = a.currentTime + 0.01;
    notes.forEach((f, i) => {
      const o = a.createOscillator(), g = a.createGain();
      o.type = type; o.frequency.value = f; o.connect(g); g.connect(a.destination);
      const t = t0 + i * gap; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.28); o.start(t); o.stop(t + 0.3);
    });
  } catch (_) {}
};
const SOUNDS = {
  xp: () => S.tone([880, 1320], 'sine', 0.06, 0.06),
  grade: () => S.tone([523, 659, 784], 'triangle', 0.07),
  quest: () => S.tone([659, 880, 1047], 'triangle', 0.08),
  achievement: () => S.tone([523, 659, 784, 1047, 1319], 'square', 0.07, 0.05),
  rank: () => S.tone([392, 523, 659, 784, 1047, 1319, 1568], 'sawtooth', 0.06, 0.05),
  chest: () => S.tone([1568, 1319, 1760, 2093], 'sine', 0.05, 0.08),
  card: () => S.tone([1047, 1568, 2093], 'sine', 0.07, 0.07),
  tier: () => S.tone([784, 988, 1175, 1568], 'triangle', 0.07),
  boss: () => S.tone([262, 330, 392, 523, 659, 784, 1047], 'sawtooth', 0.09, 0.07),
  star: () => S.tone([1175, 1568], 'triangle', 0.08),
  rhythm: () => S.tone([440, 660], 'sine', 0.08, 0.06),
  rung: () => S.tone([523, 784, 1047], 'square', 0.1, 0.05),
  unlock: () => S.tone([392, 784], 'triangle', 0.12),
};
S.toast = (label, kind = 'info', sub = '') => {
  const el = S.h(`<div class="toast ${kind}">${S.esc(label)}${sub ? `<small>${S.esc(sub)}</small>` : ''}</div>`);
  S.$('#toasts').appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity .4s, transform .4s'; el.style.opacity = 0; el.style.transform = 'translateX(30px)'; }, 4200);
  setTimeout(() => el.remove(), 4700);
};
S.banner = (text) => {
  const b = S.h(`<div class="banner"><div>${S.esc(text)}</div></div>`); document.body.appendChild(b); setTimeout(() => b.remove(), 1000);
};
S.confetti = (n = 140, colors = ['#EAFF00', '#00E5FF', '#00E676', '#FFD54F', '#B388FF', '#FF6D00']) => {
  const c = S.$('#confetti'); if (!c) return; const g = c.getContext('2d');
  c.width = innerWidth; c.height = innerHeight;
  const parts = Array.from({ length: n }, () => ({ x: innerWidth / 2 + (Math.random() - .5) * 200, y: innerHeight * .35, vx: (Math.random() - .5) * 14, vy: -Math.random() * 14 - 4, r: Math.random() * 6 + 3, c: colors[Math.floor(Math.random() * colors.length)], a: Math.random() * 6, va: (Math.random() - .5) * .3 }));
  let frame = 0;
  const step = () => {
    g.clearRect(0, 0, c.width, c.height); frame++;
    parts.forEach(p => { p.x += p.vx; p.y += p.vy; p.vy += .35; p.vx *= .99; p.a += p.va; g.save(); g.translate(p.x, p.y); g.rotate(p.a); g.fillStyle = p.c; g.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * .6); g.restore(); });
    if (frame < 160) requestAnimationFrame(step); else g.clearRect(0, 0, c.width, c.height);
  };
  step();
};
/* Turn server reward events into a little show, staggered so each one lands. */
S.celebrate = (events = []) => {
  let delay = 0; let big = false;
  for (const e of events) {
    setTimeout(() => {
      const k = e.type || 'info';
      S.toast(e.label, k, e.desc || e.reward || '');
      (SOUNDS[k] || SOUNDS.xp)();
      if (k === 'boss') { S.banner(e.label.replace(/^\W+/, '')); S.confetti(260); }
      else if (k === 'rank') { S.banner(e.rank || 'RANK UP'); S.confetti(200); }
      else if (k === 'achievement' || k === 'tier' || (k === 'grade' && e.score >= 90)) S.confetti(110);
      else if (k === 'chest' && e.rarity && e.rarity !== 'common') S.confetti(90, ['#B388FF', '#EAFF00', '#ffffff']);
    }, delay);
    delay += e.type === 'xp' ? 260 : 650;
    big = big || ['boss', 'rank'].includes(e.type);
  }
  return delay;
};

/* ------------------------------------------------------------ rhyme colours & flow grid */
S.PALETTE = ['#EAFF00', '#00E5FF', '#FF6D00', '#B388FF', '#00E676', '#FF4081', '#FFD54F', '#40C4FF', '#69F0AE', '#FF8A80', '#EA80FC', '#C6FF00'];
S.rcolor = f => (f === null || f === undefined) ? null : S.PALETTE[f % S.PALETTE.length];

/* Coloured lyric lines from an analysis: syllables grouped back into words. */
S.lyricHTML = (analysis) => (analysis?.bars || []).map(b => {
  let out = '', word = '';
  b.syllables.forEach((s, i) => {
    if (s.start && i > 0) { out += `<span class="w">${word}</span> `; word = ''; }
    const c = S.rcolor(s.rhyme);
    word += c ? `<span class="rh" style="background:${c}">${S.esc(s.text)}</span>` : S.esc(s.text);
  });
  out += `<span class="w">${word}</span>`;
  return `<div class="lyric-line">${out || '&nbsp;'}</div>`;
}).join('');

/* The 16-step bar grid (FL-style step sequencer for syllables). opts: {ghost, swing, playing} */
S.flowHTML = (analysis, opts = {}) => {
  if (!analysis || !analysis.bars?.length) return '<div class="empty">No bars yet. One line = one bar.</div>';
  const steps = analysis.steps || 16; const swing = opts.swing || 0;
  let lastSection = null, lastWho = null;
  return `<div class="flow">${analysis.bars.map((b, bi) => {
    let head = '';
    if (b.section && b.section !== lastSection) { lastSection = b.section; head += `<div class="tag" style="margin:8px 0 2px;align-self:flex-start;border-left:3px solid ${S.PALETTE[bi % 12]}">${S.esc(b.section)}</div>`; }
    const who = b.speaker && b.speaker !== lastWho ? (lastWho = b.speaker) : '';
    const cells = Array.from({ length: steps }, (_, i) => `<div class="cell ${i % (steps / 4) === 0 ? 'beat' : ''}" data-step="${i}"></div>`).join('');
    const w = 100 / steps;
    const syl = (b.syllables || []).map(s => {
      let pos = s.step ?? 0; if (swing && Math.floor(pos) % 2 === 1) pos += swing * 0.5;
      const c = S.rcolor(s.rhyme);
      return `<div class="syl ${s.stress > 0 ? 's1' : ''}" title="${S.esc(s.text)} · ${s.vowel || ''}" style="left:${pos * w}%;width:calc(${w}% - 2px);${c ? `background:${c};color:#000` : ''}">${S.esc(s.text)}</div>`;
    }).join('');
    const ghost = opts.ghost?.bars?.[bi] ? (opts.ghost.bars[bi].syllables || []).map(s => `<div class="syl" style="left:${(s.step ?? 0) * w}%;width:calc(${w}% - 2px);opacity:.18;background:#fff"></div>`).join('') : '';
    return `${head}<div class="flow-bar" data-bar="${bi}">
      <div class="n">${bi + 1}${who ? `<div class="who">${S.esc(who)}</div>` : ''}</div>
      <div><div class="steps16" style="grid-template-columns:repeat(${steps},1fr)">${cells}${ghost}${syl}</div>
        <div class="small mute" style="margin-top:3px;font-family:Inter">${S.esc(b.text)}</div></div>
      <div class="meta"><b class="verdict-${b.verdict || 'fits'}">${b.count} syl</b><br>${b.sps ?? ''}/s<br>${b.zone || ''}</div>
    </div>`;
  }).join('')}</div>`;
};
/* Highlight the bar/step under the playhead. */
S.flowPlayhead = (root, bar, step) => {
  S.$$('.flow-bar.now', root).forEach(e => e.classList.remove('now'));
  S.$$('.cell.lit', root).forEach(e => e.classList.remove('lit'));
  const el = S.$(`.flow-bar[data-bar="${bar}"]`, root); if (!el) return;
  el.classList.add('now');
  const cell = S.$(`.cell[data-step="${step}"]`, el); cell && cell.classList.add('lit');
};

/* ------------------------------------------------------------ transport: beat player, metronome, warp, tap */
S.Transport = class {
  constructor({ bpm = 90, offset = 0, beatsPerBar = 4, steps = 16, onTick } = {}) {
    Object.assign(this, { bpm, offset, beatsPerBar, steps, onTick, audio: null, sourceBpm: bpm, playing: false, metro: false, countIn: 0, loop: null });
  }
  load(url, sourceBpm) {
    this.audio = new Audio(url); this.audio.preload = 'auto'; this.sourceBpm = sourceBpm || this.bpm;
    this.audio.preservesPitch = true; this.audio.mozPreservesPitch = true; this.audio.webkitPreservesPitch = true;
    this.warp();
  }
  /* Ableton-style warp: play the beat at the target tempo, pitch preserved. */
  warp() { if (this.audio) this.audio.playbackRate = Math.max(0.5, Math.min(2, this.bpm / this.sourceBpm)); }
  setBpm(b) { this.bpm = b; this.warp(); }
  barSeconds() { return this.beatsPerBar * 60 / this.bpm; }
  /* Beats are counted on the source audio's own grid, so warping (playbackRate) never shifts the playhead. */
  position() {
    const beats = this.audio ? (this.audio.currentTime - this.offset) * this.sourceBpm / 60 : (ctx().currentTime - this.t0) * this.bpm / 60;
    const bar = Math.floor(beats / this.beatsPerBar);
    const inBar = ((beats % this.beatsPerBar) + this.beatsPerBar) % this.beatsPerBar;
    return { beats, bar, step: Math.floor(inBar / this.beatsPerBar * this.steps) };
  }
  seekBar(bar) {
    if (this.audio) this.audio.currentTime = Math.max(0, this.offset + bar * this.beatsPerBar * 60 / this.sourceBpm);
    else this.t0 = ctx().currentTime - bar * this.beatsPerBar * 60 / this.bpm;
  }
  async play() {
    this.playing = true; const a = ctx(); await a.resume();
    if (this.countIn) await this.click(this.countIn);
    if (this.audio) { await this.audio.play(); } else { this.t0 = a.currentTime; }
    let lastStep = -1;
    const loop = () => {
      if (!this.playing) return;
      const p = this.position();
      if (this.loop && p.bar > this.loop[1]) this.seekBar(this.loop[0]);
      const gs = p.bar * this.steps + p.step;
      if (gs !== lastStep) { lastStep = gs; if (this.metro && p.step % (this.steps / this.beatsPerBar) === 0) this.tick(p.step === 0); this.onTick && this.onTick(p); }
      requestAnimationFrame(loop);
    };
    loop();
  }
  stop() { this.playing = false; if (this.audio) { this.audio.pause(); } }
  rewind() { this.seekBar(0); }
  tick(accent) { S.tone([accent ? 1760 : 1175], 'square', 0, 0.06); }
  click(beats) { return new Promise(res => { let i = 0; const iv = setInterval(() => { this.tick(i % this.beatsPerBar === 0); if (++i >= beats) { clearInterval(iv); setTimeout(res, 60000 / this.bpm); } }, 60000 / this.bpm); }); }
};
S.tapTempo = (() => { let taps = []; return () => { const now = performance.now(); taps = taps.filter(t => now - t < 2500); taps.push(now); if (taps.length < 3) return null; const gaps = taps.slice(1).map((t, i) => t - taps[i]); return Math.round(60000 / (gaps.reduce((a, b) => a + b) / gaps.length)); }; })();

/* Mic recorder with optional retroactive capture buffer (Ableton Capture style). */
S.Recorder = class {
  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false } });
    this.chunks = []; this.rec = new MediaRecorder(this.stream); this.rec.ondataavailable = e => e.data.size && this.chunks.push(e.data);
    this.rec.start(250); this.started = performance.now();
  }
  async stop() {
    return new Promise(res => { this.rec.onstop = () => { this.stream.getTracks().forEach(t => t.stop()); res(new Blob(this.chunks, { type: this.rec.mimeType || 'audio/webm' })); }; this.rec.stop(); });
  }
};

/* ------------------------------------------------------------ markdown */
S.md = (src) => {
  const lines = String(src || '').replace(/\r/g, '').split('\n'); let html = '', i = 0;
  const inline = t => S.esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>').replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { let code = ''; i++; while (i < lines.length && !/^```/.test(lines[i])) code += lines[i++] + '\n'; i++; html += `<pre><code>${S.esc(code)}</code></pre>`; continue; }
    const h = l.match(/^(#{1,4})\s+(.*)/); if (h) { html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`; i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(l)) { html += '<hr>'; i++; continue; }
    if (/^>\s?/.test(l)) { let q = ''; while (i < lines.length && /^>\s?/.test(lines[i])) q += lines[i++].replace(/^>\s?/, '') + ' '; html += `<blockquote>${inline(q)}</blockquote>`; continue; }
    if (/^\|/.test(l)) { const rows = []; while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]); const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const body = rows.filter(r => !/^\|[\s:|-]+\|$/.test(r.trim())); html += '<table>' + body.map((r, ri) => `<tr>${cells(r).map(c => ri === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`).join('')}</tr>`).join('') + '</table>'; continue; }
    if (/^\s*([-*+]|\d+\.)\s+/.test(l)) { const ordered = /^\s*\d+\./.test(l); let items = ''; while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) items += `<li>${inline(lines[i++].replace(/^\s*([-*+]|\d+\.)\s+(\[.\]\s*)?/, ''))}</li>`; html += ordered ? `<ol>${items}</ol>` : `<ul>${items}</ul>`; continue; }
    if (!l.trim()) { i++; continue; }
    let p = ''; while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\||\s*([-*+]|\d+\.)\s)/.test(lines[i])) p += lines[i++] + ' ';
    html += `<p>${inline(p.trim())}</p>`;
  }
  return html;
};

/* ------------------------------------------------------------ settings drawer (LLM: local or BYOK) */
S.openSettings = async () => {
  let d = S.$('#settings-drawer');
  if (!d) {
    document.body.insertAdjacentHTML('beforeend', `<div class="drawer-bg" id="settings-bg"></div><aside class="drawer" id="settings-drawer"></aside>`);
    d = S.$('#settings-drawer'); S.$('#settings-bg').onclick = S.closeSettings;
  }
  const cfg = await S.get('/api/llm/settings');
  const presetOpts = Object.entries(cfg.presets).map(([k, v]) => `<option value="${k}" ${cfg.openai.preset === k ? 'selected' : ''}>${S.esc(v.label)}</option>`).join('');
  d.innerHTML = `<button class="btn small ghost x" onclick="Station.closeSettings()">✕</button>
    <div class="eyebrow">Brain</div><h2 style="margin:4px 0 6px">Who powers Jarvis & the crew</h2>
    <p class="dim small">Run a local model (free, private) or bring your own key. Keys stay on this machine and are never shown back.</p>
    <div class="row" style="margin:16px 0" id="prov-tabs">
      ${['ollama', 'openai', 'anthropic'].map(p => `<span class="chip click ${cfg.provider === p ? 'on' : ''}" data-p="${p}">${{ ollama: 'Ollama (local)', openai: 'OpenAI-compatible', anthropic: 'Anthropic Claude' }[p]}</span>`).join('')}
    </div>
    <div class="stack" data-sec="ollama">
      <label class="field">Ollama URL <input type="text" id="o-url" placeholder="auto-detect (incl. WSL → Windows host)" value="${S.esc(cfg.ollama.base_url)}"></label>
      <label class="field">Model <div class="row" style="flex-wrap:nowrap"><input type="text" id="o-model" placeholder="auto: first installed" value="${S.esc(cfg.ollama.model)}"><button class="btn small" data-list>List</button></div></label>
    </div>
    <div class="stack" data-sec="openai">
      <label class="field">Preset <select id="a-preset">${presetOpts}</select></label>
      <label class="field">Base URL <input type="url" id="a-url" value="${S.esc(cfg.openai.base_url)}"></label>
      <label class="field">Model <div class="row" style="flex-wrap:nowrap"><input type="text" id="a-model" value="${S.esc(cfg.openai.model)}" placeholder="e.g. qwen2.5-14b-instruct"><button class="btn small" data-list>List</button></div></label>
      <label class="field">API key ${cfg.openai.key_hint ? `<span class="mute">(${S.esc(cfg.openai.key_hint)})</span>` : ''}<input type="password" id="a-key" placeholder="${cfg.openai.key_set ? 'leave blank to keep' : 'not needed for local servers'}"></label>
    </div>
    <div class="stack" data-sec="anthropic">
      <label class="field">Model <select id="c-model">${cfg.anthropic_models.map(m => `<option ${cfg.anthropic.model === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
      <label class="field">API key ${cfg.anthropic.key_hint ? `<span class="mute">(${S.esc(cfg.anthropic.key_hint)})</span>` : ''}<input type="password" id="c-key" placeholder="${cfg.anthropic.key_set ? 'leave blank to keep' : 'sk-ant-…'}"></label>
      <p class="small mute">Uses the official Anthropic SDK with server-side refusal fallback on supported models.</p>
    </div>
    <hr class="sep">
    <div class="grid g2">
      <label class="field">Creativity (temperature) <input type="number" id="s-temp" min="0" max="2" step="0.1" value="${cfg.temperature}"></label>
      <label class="field">Max reply tokens <input type="number" id="s-max" min="64" max="64000" step="64" value="${cfg.max_tokens}"></label>
    </div>
    <label class="field" style="margin-top:10px">How Jarvis addresses you <input type="text" id="s-title" value="${S.esc(cfg.user_title)}"></label>
    <div class="row" style="margin-top:18px"><button class="btn primary" id="s-save">Save</button><button class="btn" id="s-test">Test connection</button><span id="s-msg" class="small dim"></span></div>
    <div id="s-models" class="row small" style="margin-top:12px"></div>`;
  let provider = cfg.provider;
  const show = () => { S.$$('[data-sec]', d).forEach(s => s.style.display = s.dataset.sec === provider ? 'flex' : 'none'); S.$$('#prov-tabs .chip', d).forEach(c => c.classList.toggle('on', c.dataset.p === provider)); };
  S.$$('#prov-tabs .chip', d).forEach(c => c.onclick = () => { provider = c.dataset.p; show(); });
  S.$('#a-preset', d).onchange = e => { const p = cfg.presets[e.target.value]; if (p && p.base_url) S.$('#a-url', d).value = p.base_url; };
  show();
  const collect = () => ({ provider, temperature: +S.$('#s-temp', d).value, max_tokens: +S.$('#s-max', d).value, user_title: S.$('#s-title', d).value,
    ollama: { base_url: S.$('#o-url', d).value.trim(), model: S.$('#o-model', d).value.trim() },
    openai: { preset: S.$('#a-preset', d).value, base_url: S.$('#a-url', d).value.trim(), model: S.$('#a-model', d).value.trim(), api_key: S.$('#a-key', d).value.trim() },
    anthropic: { model: S.$('#c-model', d).value, api_key: S.$('#c-key', d).value.trim() } });
  S.$('#s-save', d).onclick = async () => { try { await S.put('/api/llm/settings', collect()); S.$('#s-msg', d).textContent = 'Saved.'; S.refreshLLM(); } catch (e) { S.$('#s-msg', d).textContent = e.message; } };
  S.$('#s-test', d).onclick = async () => { S.$('#s-msg', d).textContent = 'Testing…'; try { await S.put('/api/llm/settings', collect()); const r = await S.post('/api/llm/test'); S.$('#s-msg', d).textContent = r.ok ? `✓ "${r.reply}" (${r.seconds}s)` : '✗ ' + r.error; S.refreshLLM(); } catch (e) { S.$('#s-msg', d).textContent = e.message; } };
  S.$$('[data-list]', d).forEach(b => b.onclick = async () => {
    try { await S.put('/api/llm/settings', collect()); const r = await S.get('/api/llm/models');
      S.$('#s-models', d).innerHTML = r.models.slice(0, 40).map(m => `<span class="chip click">${S.esc(m)}</span>`).join('') || '<span class="mute">No models found</span>';
      S.$$('#s-models .chip', d).forEach(c => c.onclick = () => { (provider === 'ollama' ? S.$('#o-model', d) : S.$('#a-model', d)).value = c.textContent; });
    } catch (e) { S.$('#s-models', d).textContent = e.message; } });
  S.$('#settings-bg').classList.add('open'); d.classList.add('open');
};
S.closeSettings = () => { S.$('#settings-bg')?.classList.remove('open'); S.$('#settings-drawer')?.classList.remove('open'); };

/* ------------------------------------------------------------ command palette (REAPER actions / Ableton search) */
S.commands = [];
S.addCommands = (cmds) => S.commands.push(...cmds);
S.initPalette = () => {
  S.addCommands([
    { label: 'Go: Bridge (Jarvis)', run: () => location.href = '/station' },
    { label: 'Go: RapQuest flow lab', run: () => location.href = '/station/rapquest' },
    { label: 'Go: Academy', run: () => location.href = '/station/academy' },
    { label: 'Go: Listening Lab', run: () => location.href = '/station/academy#lab' },
    { label: 'Go: Cypher / Battle', run: () => location.href = '/station/academy#cypher' },
    { label: 'Go: Rhyme Lab sandbox', run: () => location.href = '/station/academy#sandbox' },
    { label: 'Go: The Forge', run: () => location.href = '/station/academy#forge' },
    { label: 'Go: War Room', run: () => location.href = '/station/warroom' },
    { label: 'Ask Claude (War Room line)', run: () => location.href = '/station/warroom#claude' },
    { label: 'Go: Video Studio', run: () => location.href = '/' },
    { label: 'Settings: LLM provider & keys', run: S.openSettings },
  ]);
  S.get('/api/personas').then(ps => S.addCommands(ps.map(p => ({ label: `Persona: ${p.name}${p.handle ? ' (' + p.handle + ')' : ''}`, run: () => location.href = '/station/persona?id=' + p.id })))).catch(() => {});
  document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); S.openPalette(); } if (e.key === 'Escape') S.closePalette(); });
};
S.openPalette = () => {
  let m = S.$('#palette');
  if (!m) {
    document.body.insertAdjacentHTML('beforeend', `<div class="modal-bg" id="palette-bg"></div><div class="modal" id="palette" style="top:22%;padding:14px">
      <input type="text" id="palette-q" placeholder="Type a command, or ask Jarvis (Enter)…" autocomplete="off"><div id="palette-list" class="stack" style="margin-top:10px;gap:4px"></div></div>`);
    m = S.$('#palette'); S.$('#palette-bg').onclick = S.closePalette;
    const q = S.$('#palette-q'); let sel = 0;
    const render = () => {
      const t = q.value.toLowerCase(); const items = S.commands.filter(c => c.label.toLowerCase().includes(t)).slice(0, 12);
      if (t) items.push({ label: `Ask Jarvis: "${q.value}"`, run: () => { sessionStorage.setItem('jarvis-ask', q.value); location.href = '/station'; } });
      sel = Math.min(sel, items.length - 1);
      S.$('#palette-list').innerHTML = items.map((c, i) => `<div class="btn ghost" style="justify-content:flex-start;${i === sel ? 'border-color:var(--volt)' : 'border-color:transparent'}" data-i="${i}">${S.esc(c.label)}</div>`).join('');
      S.$$('#palette-list [data-i]').forEach(el => el.onclick = () => { S.closePalette(); items[+el.dataset.i].run(); });
      m._items = items; m._sel = () => sel;
    };
    q.oninput = () => { sel = 0; render(); };
    q.onkeydown = e => { if (e.key === 'ArrowDown') { sel++; render(); e.preventDefault(); } if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); render(); e.preventDefault(); } if (e.key === 'Enter') { const it = m._items[sel]; if (it) { S.closePalette(); it.run(); } } };
    m._render = render;
  }
  S.$('#palette-bg').classList.add('open'); m.classList.add('open'); S.$('#palette-q').value = ''; m._render(); setTimeout(() => S.$('#palette-q').focus(), 30);
};
S.closePalette = () => { S.$('#palette-bg')?.classList.remove('open'); S.$('#palette')?.classList.remove('open'); };

/* ------------------------------------------------------------ chat widget */
/* S.chatWidget(root, {persona, color, glyph, context, onAction, greeting}) */
S.chatWidget = (root, opts) => {
  root.innerHTML = `<div class="chat" data-chat></div>
    <div class="composer"><textarea data-in rows="1" placeholder="${S.esc(opts.placeholder || 'Talk to ' + (opts.name || 'them') + '…')}"></textarea><button class="btn primary" data-send>Send</button></div>`;
  const chat = S.$('[data-chat]', root), input = S.$('[data-in]', root), send = S.$('[data-send]', root);
  let cid = opts.conversationId || null; let busy = false;
  const add = (role, text, cls = '') => {
    const el = S.h(`<div class="msg ${role}"><div class="av" style="${role !== 'user' ? `background:${opts.color || 'var(--volt)'}` : ''}">${role === 'user' ? 'U' : S.esc(opts.glyph || 'J')}</div><div><div class="bubble ${cls}"></div></div></div>`);
    S.$('.bubble', el).textContent = text; chat.appendChild(el); chat.scrollTop = chat.scrollHeight; return el;
  };
  if (opts.greeting) add('bot', opts.greeting);
  const sendMsg = async (text) => {
    text = (text ?? input.value).trim(); if (!text || busy) return; busy = true; send.disabled = true; input.value = '';
    add('user', text);
    const el = add('bot', '', 'typing'); const bubble = S.$('.bubble', el); let acc = '';
    await S.stream('/api/chat', { persona_id: opts.persona, message: text, conversation_id: cid, context: opts.context || {} }, {
      meta: d => { cid = d.conversation_id; },
      delta: d => { acc += d.text; bubble.textContent = acc; chat.scrollTop = chat.scrollHeight; },
      replace: d => { bubble.textContent = d.text; },
      action_start: d => { bubble.insertAdjacentHTML('afterend', `<div class="action-card" data-pending><div class="t">Running ${S.esc(d.do)}…</div></div>`); },
      action: r => {
        const pend = S.$('[data-pending]', el); pend && pend.remove();
        const card = S.h(`<div class="action-card" style="border-left-color:${r.ok ? (r.color || 'var(--cyan)') : 'var(--red)'}"><div class="t">${S.esc(r.label || r.do)}</div>${r.text ? `<div style="white-space:pre-wrap">${S.esc(r.text)}</div>` : ''}${r.navigate ? `<a class="btn small" style="margin-top:6px" href="${r.navigate}">Open →</a>` : ''}</div>`);
        bubble.parentElement.appendChild(card); chat.scrollTop = chat.scrollHeight; opts.onAction && opts.onAction(r);
      },
      error: d => { bubble.classList.add('err'); bubble.textContent = (acc ? acc + '\n\n' : '') + '⚠ ' + d.message; },
      done: () => {},
    });
    bubble.classList.remove('typing'); busy = false; send.disabled = false; input.focus();
  };
  send.onclick = () => sendMsg();
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); } });
  return { send: sendMsg, add, get conversationId() { return cid; } };
};
})();
