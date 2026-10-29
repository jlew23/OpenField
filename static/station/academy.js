/* The Academy: the Rap Writing Bible, playable. */
const S = Station; S.shell('Academy');
const A = { snap: null, home: null };
const THEMES = { default: '#EAFF00', 'Midnight Neon': '#00E5FF', 'Gold Chain': '#FFD54F', 'Analog Tape': '#FF8A65', 'Arena Lights': '#B388FF', 'Vinyl Crackle': '#69F0AE', 'Hall of Fame': '#FFFFFF' };
const AXIS_NAMES = { temper: ['Calm', 'Chaos'], texture: ['Plain', 'Ornate'], lens: ['Confessional', 'Cinematic'], pocket: ['Laid-back', 'Rapid'], imagery: ['Street', 'Abstract'], tone: ['Humor', 'Gravity'] };
const $v = () => S.$('#view');

/* ------------------------------------------------------------ boot & HUD */
async function load() {
  A.snap = await S.get('/api/academy');
  const p = A.snap.profile;
  S.prefs.sounds = p.sounds !== false;
  document.documentElement.style.setProperty('--accent', THEMES[p.theme] || THEMES.default);
  renderHud(); renderSubnav();
}
function renderHud() {
  const s = A.snap, r = s.rank, rh = s.rhythm, p = s.profile;
  const pct = r.next_at ? Math.round(r.progress * 100) : 100;
  const dots = Array.from({ length: rh.goal }, (_, i) => `<i class="${i < rh.days_this_week ? 'on' : ''}"></i>`).join('');
  S.$('#hud').innerHTML = `<div class="hud">
    <div><div class="eyebrow">${S.esc(p.chosen_title || (p.name ? p.name : 'The Academy'))}</div><div class="rank">${S.esc(r.name)}</div></div>
    <div><div class="xpline"><span>${p.show_totals ? s.xp + ' XP' : 'Level ' + s.level}</span><span>${r.next ? (p.show_totals ? `${r.next_at - s.xp} XP to ${r.next}` : 'next: ' + r.next) : 'MAX RANK'}</span></div>
      <div class="bar-meter"><i style="width:${pct}%"></i></div></div>
    <div title="${rh.mode === 'daily' ? 'Daily streak' : 'Practice days this week'}"><div class="small mute mono" style="margin-bottom:4px">${rh.mode === 'daily' ? `🔥 ${rh.streak} day streak` : `🥁 ${rh.days_this_week}/${rh.goal} this week${rh.weeks ? ' · ' + rh.weeks + 'w run' : ''}`}</div><div class="rhythm-dots">${dots}</div></div>
  </div>`;
}
const TABS = [['home', 'Home'], ['map', 'Map'], ['lab', 'Listening Lab'], ['cypher', 'Cypher'], ['sandbox', 'Rhyme Lab'], ['matrix', 'Matrix'], ['forge', 'The Forge'], ['trophies', 'Trophies'], ['settings', 'Settings']];
function renderSubnav() {
  const cur = location.hash.slice(1).split('/')[0] || 'home';
  S.$('#subnav').innerHTML = TABS.map(([k, l]) => `<a href="#${k}" class="${cur === k ? 'on' : ''}">${l}${k === 'home' && A.snap.reviews_due ? ` <span class="tag" style="color:var(--volt)">${A.snap.reviews_due}</span>` : ''}</a>`).join('');
}
async function route() {
  if (!A.snap) await load();
  renderSubnav();
  if (!A.snap.has_bible) return importView();
  const [k, arg] = location.hash.slice(1).split('/');
  const fn = { home, map, chapter: () => chapter(arg), boss: () => boss(+arg), lab, cypher, sandbox, matrix, forge, trophies, settings, onebar }[k || 'home'] || home;
  window.scrollTo(0, 0);
  await fn();
}
window.addEventListener('hashchange', route);
async function refresh() { A.snap = await S.get('/api/academy'); renderHud(); renderSubnav(); }
const after = async (events) => { const d = S.celebrate(events || []); setTimeout(refresh, Math.min(d, 2500)); };

/* ------------------------------------------------------------ modal */
function modal(html) { S.$('#m').innerHTML = `<button class="btn small ghost x" id="m-x">✕</button>${html}`; S.$('#m-bg').classList.add('open'); S.$('#m').classList.add('open'); S.$('#m-x').onclick = closeModal; S.$('#m-bg').onclick = closeModal; }
function closeModal() { S.$('#m-bg').classList.remove('open'); S.$('#m').classList.remove('open'); }

/* ------------------------------------------------------------ import */
function importView() {
  $v().innerHTML = `<div class="panel glow" style="max-width:680px;margin:30px auto;text-align:center;padding:40px">
    <div class="eyebrow">First things first</div><h1 class="big" style="font-size:3rem;margin:8px 0">Load your Bible</h1>
    <p class="dim">Drop the markdown version of THE RAP WRITING BIBLE. It stays on this machine. The Academy turns its levels, chapters, drills and appendices into the game.</p>
    <label class="btn primary" style="margin-top:20px">Choose RAP-WRITING-BIBLE.md<input type="file" id="bible-file" accept=".md,.txt" hidden></label>
    <p class="small mute" id="imp-msg" style="margin-top:12px"></p></div>`;
  S.$('#bible-file').onchange = async e => {
    const fd = new FormData(); fd.append('file', e.target.files[0]);
    try { const r = await S.api('/api/academy/bible', { method: 'POST', body: fd }); S.$('#imp-msg').textContent = `Loaded ${r.levels} levels, ${r.chapters} chapters.`; S.confetti(); A.snap = null; setTimeout(route, 700); }
    catch (err) { S.$('#imp-msg').textContent = err.message; }
  };
}

/* ------------------------------------------------------------ home */
async function home() {
  const c = await S.post('/api/academy/checkin'); after(c.events);
  const s = A.snap, q = s.today.quests || [];
  const reviews = await S.get('/api/academy/reviews');
  const plan = c.session;
  $v().innerHTML = `<div class="grid" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr)">
    <div class="stack">
      <section class="panel glow"><div class="panel-head"><h2>How long have you got?</h2><span class="small mute">No guilt either way</span></div>
        <div class="session-pick">${[3, 10, 30].map(m => `<button data-min="${m}" class="${plan.minutes === m ? 'on' : ''}">${m}<small>MIN</small></button>`).join('')}</div>
        <div class="stack" id="plan" style="margin-top:14px"></div></section>
      ${reviews.length ? `<section class="panel"><div class="panel-head"><h3>🧠 Recall check · ${reviews.length} due</h3><span class="small mute">Spaced reviews lock patterns in</span></div><div id="review"></div></section>` : ''}
      <section class="panel"><div class="panel-head"><h3>Recent report cards</h3></div>${s.recent.length ? s.recent.slice(0, 6).map(r => `<div class="row small" style="padding:6px 0;border-bottom:1px solid var(--line)"><b style="width:40px;color:${r.passed ? 'var(--green)' : 'var(--orange)'}">${r.letter}</b><span style="flex:1">${S.esc(r.ref)}</span><span class="mute">${S.fmtAgo(r.created_at)}</span><a href="#" data-report="${r.id}">open</a></div>`).join('') : '<div class="empty">Your first drill is waiting on the map.</div>'}</section>
    </div>
    <div class="stack">
      <section class="panel"><div class="panel-head"><h3>Today's quests</h3><span class="small mute">${q.filter(x => x.done).length}/${q.length}${s.today.chest ? ' · chest opened 🎁' : ''}</span></div>
        <div class="stack" style="gap:6px">${q.map(x => `<div class="quest ${x.done ? 'done' : ''}"><span>${x.done ? '✅' : '⬜'}</span><span>${S.esc(x.label)}</span><span class="small mute mono">+${x.xp}</span></div>`).join('')}</div>
        <p class="small mute" style="margin-top:8px">Clear all three for a guaranteed chest.</p></section>
      <section class="panel"><div class="panel-head"><h3>Skill radar</h3><span class="small mute">from your last 30 submissions</span></div><div id="radar"></div></section>
      <section class="panel"><div class="panel-head"><h3>The Forge</h3><a href="#forge" class="small">open →</a></div>
        <div class="bar-meter"><i style="width:${Math.round(s.forge.progress * 100)}%"></i></div>
        <p class="small dim" style="margin-top:6px">${s.forge.answered}/${s.forge.need_answers} life questions · Level ${s.forge.need_level} boss ${s.bosses_passed.includes(s.forge.need_level) ? '✅' : 'pending'} → your own rapper persona.</p></section>
    </div></div>`;
  const drawPlan = (pl) => {
    S.$('#plan').innerHTML = pl.steps.map(st => `<div class="step-card"><div class="min">${st.minutes}<br>min</div><div><b>${S.esc(st.title)}</b><div class="small dim">${S.esc(st.text)}</div></div>
      <a class="btn small primary" href="${{ onebar: '#onebar', sandbox: '#sandbox', drill: st.chapter ? '#chapter/' + st.chapter : '#map', cypher: '#cypher', lab: '#lab', wrap: '#trophies' }[st.kind]}">Go</a></div>`).join('')
      + (pl.routine ? `<details class="small dim" style="margin-top:6px"><summary>The Bible's Level ${pl.level} routine: "${S.esc(pl.routine.title)}"</summary><ul style="margin:8px 0 0 18px">${pl.routine.steps.map(x => `<li>${x.minutes ? x.minutes + ' min · ' : ''}<b>${S.esc(x.title)}</b>: ${S.esc(x.text)}</li>`).join('')}</ul></details>` : '');
  };
  drawPlan(plan);
  S.$$('.session-pick button').forEach(b => b.onclick = async () => { S.$$('.session-pick button').forEach(x => x.classList.toggle('on', x === b)); await S.put('/api/academy/profile', { session: +b.dataset.min }); drawPlan(await S.get('/api/academy/session?minutes=' + b.dataset.min)); });
  S.$('#radar').innerHTML = radarSVG(s.radar);
  S.$$('[data-report]').forEach(a => a.onclick = e => { e.preventDefault(); openReport(+a.dataset.report); });
  if (reviews.length) reviewCard(reviews, 0);
}
function reviewCard(list, i) {
  const q = list[i]; if (!q) { S.$('#review').innerHTML = '<div class="small dim">All caught up. 🧠</div>'; return; }
  S.$('#review').innerHTML = `<p>Which vowel pattern does <b style="color:var(--volt)">"${S.esc(q.phrase)}"</b> ride?</p><div class="stack" style="gap:6px;margin-top:8px">${q.options.map(o => `<button class="btn ghost" data-o="${o.id}" style="justify-content:flex-start">${S.esc(o.label)}</button>`).join('')}</div>`;
  S.$$('#review [data-o]').forEach(b => b.onclick = async () => {
    const r = await S.post('/api/academy/reviews/' + q.item, { choice: b.dataset.o });
    b.style.borderColor = r.correct ? 'var(--green)' : 'var(--red)'; S.celebrate(r.events); setTimeout(() => reviewCard(list, i + 1), 900);
  });
}
function radarSVG(r) {
  const axes = Object.keys(r || {}); if (!axes.length) return '<div class="empty">Submit a drill to light up your radar.</div>';
  const cx = 140, cy = 120, R = 92, pt = (i, v) => { const a = -Math.PI / 2 + i * 2 * Math.PI / axes.length; return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v]; };
  const ring = f => axes.map((_, i) => pt(i, f).join(',')).join(' ');
  const poly = axes.map((k, i) => pt(i, Math.max(.04, (r[k] || 0) / 100)).join(',')).join(' ');
  return `<svg viewBox="0 0 280 245" width="100%"><g stroke="#262b37" fill="none">${[.25, .5, .75, 1].map(f => `<polygon points="${ring(f)}"/>`).join('')}${axes.map((_, i) => `<line x1="${cx}" y1="${cy}" x2="${pt(i, 1)[0]}" y2="${pt(i, 1)[1]}"/>`).join('')}</g>
    <polygon points="${poly}" fill="rgba(234,255,0,.22)" stroke="var(--accent)" stroke-width="2"/>
    ${axes.map((k, i) => { const [x, y] = pt(i, 1.2); return `<text x="${x}" y="${y}" text-anchor="middle">${k} ${r[k] || 0}</text>`; }).join('')}</svg>`;
}

/* ------------------------------------------------------------ map */
async function map() {
  const s = A.snap, cur = s.curriculum;
  const best = s.best;
  $v().innerHTML = `<div class="panel" style="margin-bottom:14px"><div class="row"><div style="flex:1"><div class="eyebrow">The One Law</div><h2 style="margin-top:4px">${S.esc(cur.one_law)}</h2></div>
      <div class="small dim" style="max-width:340px">Chapters ahead of you are open to peek (half XP). Only the boss certifies a level.</div></div></div>
    ${cur.levels.map(l => `<div class="level"><div class="row"><div style="flex:1"><div class="eyebrow">Level ${l.level} · ${S.esc(l.tier)}</div><h2>${S.esc(l.name)}</h2><div class="small dim">${S.esc(l.goal)}</div></div>
      ${s.bosses_passed.includes(l.level) ? '<span class="tag" style="color:var(--green)">CERTIFIED</span>' : ''}</div>
      <div class="nodes">${l.chapters.map(c => { const st = s.chapters[c.id] || 'peek', stars = s.stars[c.id] || 0;
        return `<a class="node ${st}" href="#chapter/${c.id}"><span class="num">CH ${c.number}${st === 'peek' ? ' · PEEK' : ''}</span><b>${S.esc(c.title)}</b><span class="stars">${'★'.repeat(stars)}<span class="mute">${'☆'.repeat(Math.max(0, 3 - stars))}</span></span></a>`; }).join('')}
        ${l.test ? `<a class="node boss ${s.bosses_passed.includes(l.level) ? 'done' : ''}" href="#boss/${l.level}"><span class="num">${l.test.ongoing ? 'MASTERY' : 'BOSS'}</span><b>${S.esc(l.test.title.replace(/\(.*\)/, ''))}</b><span class="small">${best['boss-' + l.level] ? 'best ' + best['boss-' + l.level].best : '⚔️ ' + l.test.parts.length + ' parts'}</span></a>` : ''}
      </div></div>`).join('')}
    <div class="grid g2"><section class="panel"><h3>The skill ladder</h3><p class="small dim" style="margin:4px 0 10px">Check a rung only when it is automatic: on a beat, out loud, without thinking.</p>
      ${cur.ladder.map(r => `<label class="row small" style="padding:6px 0;border-bottom:1px solid var(--line)"><input type="checkbox" data-rung="${r.rung}" ${s.profile.rungs.includes(r.rung) ? 'checked disabled' : ''}><b>Rung ${r.rung}</b><span style="flex:1">${S.esc(r.text)}</span><span class="mute">${S.esc(r.level)}</span></label>`).join('')}</section>
    <section class="panel"><h3>12-week roadmap</h3><div class="stack small" style="gap:6px;margin-top:8px">${cur.roadmap.map(w => `<div class="row"><span class="tag" style="width:62px;text-align:center">wk ${S.esc(w.weeks)}</span><span style="flex:1">${S.esc(w.focus)}</span><span class="mute">${S.esc(w.milestone)}</span></div>`).join('')}</div></section></div>`;
  S.$$('[data-rung]').forEach(cb => cb.onchange = async () => { if (!cb.checked) return; if (!confirm('Is this rung truly automatic for you?')) { cb.checked = false; return; } after((await S.post('/api/academy/rung', { rung: +cb.dataset.rung })).events); cb.disabled = true; });
}

/* ------------------------------------------------------------ forge question popup (every new page asks one) */
function forgeQuestion(q, page) {
  if (!q) return;
  setTimeout(() => {
    modal(`<div class="eyebrow">The Forge asks</div><h2 style="margin:6px 0 4px">${S.esc(q.prompt)}</h2><p class="small mute">${S.esc(q.category)} · Your answer becomes raw material for your own rapper persona. Stays on this machine. Skip anytime.</p>
      <div class="row" style="margin:12px 0" id="fq-chips">${q.chips.map(c => `<span class="chip click" data-c="${S.esc(c)}">${S.esc(c)}</span>`).join('')}</div>
      <textarea id="fq-text" placeholder="Tell the story. Names, smells, the exact words people said…" style="min-height:140px"></textarea>
      <div class="row" style="margin-top:12px"><button class="btn primary" id="fq-save">Lock it in</button><button class="btn ghost" id="fq-skip">Skip</button></div>`);
    let chip = '';
    S.$$('#fq-chips .chip').forEach(c => c.onclick = () => { chip = chip === c.dataset.c ? '' : c.dataset.c; S.$$('#fq-chips .chip').forEach(x => x.classList.toggle('on', x.dataset.c === chip)); });
    S.$('#fq-skip').onclick = async () => { await S.post('/api/forge/skip', { qid: q.id, page }); closeModal(); };
    S.$('#fq-save').onclick = async () => {
      try {
        const before = A.snap.forge;
        const r = await S.post('/api/forge/answer', { qid: q.id, text: S.$('#fq-text').value, chip });
        closeModal();
        const big = Object.entries(r.position).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
        S.toast(`🧬 Trajectory shifted`, 'card', big ? `${big[1] > 0 ? AXIS_NAMES[big[0]][1] : AXIS_NAMES[big[0]][0]} ${Math.round(Math.abs(big[1]) * 100)}%` : ''); S.tone([440, 554, 659]);
        after(r.events);
      } catch (e) { S.toast(e.message); }
    };
  }, 700);
}

/* ------------------------------------------------------------ chapter */
async function chapter(cid) {
  const ch = await S.get('/api/academy/chapter/' + cid);
  S.post('/api/academy/chapter/' + cid + '/read');
  $v().innerHTML = `<div class="row" style="margin-bottom:10px"><a href="#map" class="small dim">← Map</a><span class="tag">Level ${ch.level} · ${S.esc(ch.level_name)}</span>
      ${ch.state === 'peek' ? '<span class="tag" style="color:var(--orange)">PEEKING AHEAD · half XP</span>' : ''}<span class="tag">${'★'.repeat(ch.stars)}${'☆'.repeat(3 - ch.stars)}</span></div>
    <div class="grid" style="grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)">
      <div><div class="eyebrow">Chapter ${ch.number}</div><h1 class="big" style="font-size:clamp(1.8rem,4vw,3rem);margin:6px 0 14px">${S.esc(ch.title)}</h1>
        <article class="panel md">${S.md(ch.body.replace(/\*\*Drill [^\n]*(\n\d+\.[^\n]*)*/g, ''))}</article>
        <div id="drills"></div></div>
      <aside class="stack" style="position:sticky;top:80px;align-self:start">
        <section class="panel"><div class="panel-head"><h3>Ask the Coach about this page</h3></div><div id="coach"></div></section>
        ${ch.matrix?.length ? `<section class="panel"><h3>Multi-syllable matrix</h3><div class="stack small" style="max-height:280px;overflow:auto;margin-top:8px">${ch.matrix.map(p => `<details><summary><b>${S.esc(p.name)}</b> <span class="mute">${S.esc(p.sounds)}</span></summary><div class="dim" style="padding:6px 0">${Object.entries(p.rows).map(([k, v]) => `<div><b>${k}</b> ${v.slice(0, 10).map(S.esc).join(' · ')}</div>`).join('')}</div></details>`).join('')}</div></section>` : ''}
        ${ch.word_bank?.length ? `<section class="panel"><h3>Word bank</h3>${ch.word_bank.map(w => `<div class="small" style="padding:6px 0;border-bottom:1px solid var(--line)"><b>${S.esc(w.word)}</b> <span class="mute">ride ${S.esc(w.ride)}</span><div class="dim">${S.esc(w.seed)}</div><div class="mute">⚠ ${S.esc(w.avoid)}</div></div>`).join('')}</section>` : ''}
      </aside></div>`;
  S.chatWidget(S.$('#coach'), { persona: 'coach', name: 'Coach', glyph: 'C', color: 'var(--green)', context: { chapter_id: cid }, placeholder: 'Ask about this chapter, or paste bars for feedback…' });
  S.$('#drills').innerHTML = ch.drills.length ? '' : `<div class="drill"><b>No drill in this chapter.</b><p class="small dim">Reading it unlocks the next node. Bring a question to the Coach.</p></div>`;
  ch.drills.forEach(d => S.$('#drills').appendChild(drillCard(d, ch)));
  forgeQuestion(ch.question, 'chapter:' + cid);
}

const FORM_NAMES = { bars: 'Write bars', vowel: 'Vowel drill', skeleton: 'Double-stitch skeleton', idiom: 'Idiom flip', wordplay: 'Wordplay', story: 'Story verse', hook: 'Hook', cut: 'Cut the expensive bar', transcribe: 'Transcription', perform: 'Performance', reflection: 'Notebook', check: 'Checklist', text: 'Explain it' };
function drillCard(d, ch, opts = {}) {
  const el = S.h(`<div class="drill"><div class="head"><span class="tag">${opts.label || 'Drill ' + d.number}</span><span class="tag">${FORM_NAMES[d.form] || d.form}</span>${d.best ? `<span class="tag" style="color:${d.best.passed ? 'var(--green)' : 'var(--orange)'}">best ${d.best.best}</span>` : ''}${d.difficulty ? `<span class="tag">${d.difficulty > 0 ? '▲ stretch' : '▼ assist'}</span>` : ''}</div>
    <p style="white-space:pre-wrap">${S.esc(d.text)}</p>${d.stretch ? `<p class="small" style="color:var(--volt)">${S.esc(d.stretch)}</p>` : ''}<div class="form" style="margin-top:12px"></div>
    ${opts.noSubmit ? '' : `<div class="row" style="margin-top:12px"><button class="btn primary" data-submit>Submit for grading</button><label class="small dim"><input type="checkbox" data-coach ${S.llmStatus?.ok !== false ? 'checked' : ''}> Coach review (LLM)</label><span class="small mute" data-msg></span></div>`}</div>`);
  const api = buildForm(S.$('.form', el), d, ch);
  el._collect = api.collect;
  if (!opts.noSubmit) S.$('[data-submit]', el).onclick = async () => {
    const btn = S.$('[data-submit]', el); btn.disabled = true; S.$('[data-msg]', el).textContent = S.$('[data-coach]', el).checked ? 'Coach is reading every bar…' : 'Grading…';
    try { const r = await S.post('/api/academy/submit', { ref: d.id, content: api.collect(), coach: S.$('[data-coach]', el).checked }); showResult(r); }
    catch (e) { S.$('[data-msg]', el).textContent = e.message; }
    btn.disabled = false; S.$('[data-msg]', el).textContent = '';
  };
  return el;
}

/* Practice forms, one per technique. Returns {collect()}. */
function buildForm(root, d, ch) {
  const live = (ta, out, bpm = 90) => { const run = S.debounce(async () => { const a = await S.post('/api/flow/analyze', { text: ta.value, bpm }); out.innerHTML = a.bars.length ? S.lyricHTML(a) + `<div class="small mute" style="margin-top:4px">${a.summary.bars} bars · ${a.summary.avg_syllables} syl/bar · ${a.families} rhyme thread(s)</div>` : ''; }, 350); ta.addEventListener('input', run); };
  const barsBox = (ph, rows = 6) => { const w = S.h(`<div><textarea placeholder="${S.esc(ph)}" style="min-height:${rows * 26}px"></textarea><div class="panel" style="padding:10px;margin-top:8px;min-height:40px" data-preview><span class="small mute">Live rhyme colours appear here as you write.</span></div></div>`); live(S.$('textarea', w), S.$('[data-preview]', w)); return w; };
  const f = d.form;
  if (f === 'vowel') {
    root.innerHTML = `<div class="grid g2"><label class="field">Your 3-4 syllable phrase<input type="text" data-phrase placeholder="back of the club"></label>
      <div><div class="small dim">Vowel skeleton</div><div class="vowelchips" data-skel style="margin-top:6px"></div></div></div>
      <div class="row" style="margin:12px 0"><span class="timer" data-timer>05:00</span><button class="btn small" data-start>Start timer</button><span class="small dim">Goal: ${d.goal || 15} matches, no judging.</span></div>
      <label class="field">Matches (one per line)<textarea data-matches style="min-height:180px" placeholder="stackin' it up&#10;trapped in the mud"></textarea></label>
      <div data-scores class="stack" style="gap:2px;margin-top:8px"></div>
      <label class="field" style="margin-top:12px">Then: 4 bars using the best ones (optional)</label>`;
    const bb = barsBox('Four bars, image on every fragment', 4); root.appendChild(bb);
    let t0 = null, iv = null;
    const phrase = S.$('[data-phrase]', root), matches = S.$('[data-matches]', root);
    const score = S.debounce(async () => {
      const r = await S.post('/api/academy/sandbox', { phrase: phrase.value, candidates: matches.value.split('\n') });
      S.$('[data-skel]', root).innerHTML = r.vowels.map(v => `<span class="${v.stress ? 'st' : ''}" title="${S.esc(v.text)}">${v.vowel}</span>`).join('-');
      S.$('[data-scores]', root).innerHTML = r.scored.map(m => `<div class="match-line"><span>${m.score >= .75 ? '✅' : '▫️'}</span><span style="flex:1">${S.esc(m.text)}</span><span class="mute">${Math.round(m.score * 100)}%</span></div>`).join('') + (r.scored.length ? `<div class="small" style="color:var(--volt)">${r.verified}/${d.goal || 15} verified</div>` : '');
    }, 400);
    phrase.oninput = score; matches.oninput = score;
    S.$('[data-start]', root).onclick = () => { t0 = Date.now(); clearInterval(iv); iv = setInterval(() => { const left = 300 - Math.floor((Date.now() - t0) / 1000); S.$('[data-timer]', root).textContent = left >= 0 ? `0${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : `+${-left}s`; if (left === 0) S.tone([880, 660, 440]); }, 250); };
    return { collect: () => ({ phrase: phrase.value, matches: matches.value.split('\n'), text: S.$('textarea', bb).value, seconds: t0 ? Math.round((Date.now() - t0) / 1000) : 0, goal: d.goal || 15, limit: 300 }) };
  }
  if (f === 'idiom') {
    root.innerHTML = `<div class="row"><label class="field" style="flex:1">Idiom<input type="text" data-idiom placeholder="Bite the bullet"></label><button class="btn small" data-rand style="align-self:flex-end">🎲 Random from the bank</button></div>
      ${['exaggerate', 'literal', 'frame'].map((k, i) => `<label class="field" style="margin-top:10px">${['1 · Exaggerate it', '2 · Take it literally', '3 · Own the frame'][i]}<input type="text" data-flip="${k}"></label>`).join('')}`;
    S.$('[data-rand]', root).onclick = async () => { const c = await S.get('/api/academy/chapter/ch-13').catch(() => null); const bank = c?.idioms?.bank || []; if (bank.length) S.$('[data-idiom]', root).value = bank[Math.floor(Math.random() * bank.length)]; };
    return { collect: () => ({ idiom: S.$('[data-idiom]', root).value, flips: Object.fromEntries(S.$$('[data-flip]', root).map(i => [i.dataset.flip, i.value])) }) };
  }
  if (['reflection', 'perform', 'check', 'text'].includes(f)) {
    const items = d.text.split(/(?<=[.!?])\s+/).filter(x => x.length > 12).slice(0, 5);
    root.innerHTML = `${items.map((t, i) => `<label class="row small" style="padding:4px 0"><input type="checkbox" data-ck="${i}"> ${S.esc(t)}</label>`).join('')}
      <label class="field" style="margin-top:8px">Notes / evidence (what you did, what you noticed)<textarea data-notes style="min-height:110px"></textarea></label>
      ${f === 'perform' ? `<p class="small mute">Tip: run it in the <a href="/station/rapquest">Pocket Trainer</a> and paste your numbers here.</p>` : ''}`;
    return { collect: () => ({ checks: S.$$('[data-ck]', root).map(c => c.checked), text: S.$('[data-notes]', root).value }) };
  }
  // bar-based forms
  const extras = { story: `<div class="grid g2" style="margin-bottom:10px">${['protagonist', 'setting', 'objective', 'obstacle', 'turn'].map(k => `<label class="field">${k[0].toUpperCase() + k.slice(1)}<input type="text" data-core="${k}"></label>`).join('')}</div><p class="small dim" style="margin-bottom:8px">Answer the Core Five BEFORE bar one.</p>`,
    cut: `<div class="grid g2" style="margin-bottom:10px"><label class="field">The bar you cut<input type="text" data-cut></label><label class="field">Why it was expensive<input type="text" data-why></label></div>`,
    transcribe: `<label class="field" style="margin-bottom:10px">Song & artist<input type="text" data-song placeholder="Artist - Title"></label><p class="small dim" style="margin-bottom:8px">Transcribe for private study; the colours show the threads you are hearing.</p>`,
    skeleton: `<pre class="small mute" style="margin-bottom:8px">__ [INTERNAL] __ ______ [END]\n__ [INTERNAL] __ ______ [END]</pre>` }[f] || '';
  root.innerHTML = extras;
  const bb = barsBox(d.scheme ? `${d.bars} bars, ${d.scheme}` : `${d.bars} bar(s), one per line`, Math.min(16, Math.max(3, d.bars)));
  root.appendChild(bb);
  if (f === 'skeleton' && d.assist) S.$('textarea', bb).value = '___ [internal] ___ ___ [end]\n___ [internal] ___ ___ [end]';
  return { collect: () => {
    const out = { text: S.$('textarea', bb).value };
    if (f === 'story') out.core_five = Object.fromEntries(S.$$('[data-core]', root).map(i => [i.dataset.core, i.value]));
    if (f === 'cut') { out.cut_bar = S.$('[data-cut]', root).value; out.reason = S.$('[data-why]', root).value; }
    if (f === 'transcribe') out.song = S.$('[data-song]', root).value;
    return out;
  } };
}

function critHTML(c) { return `<div class="crit"><span>${S.esc(c.label)}</span><div class="bar-meter"><i style="width:${c.score}%;background:${c.score >= 80 ? 'var(--green)' : c.score >= 60 ? 'var(--volt)' : 'var(--orange)'}"></i></div><b class="mono">${c.score}</b><span class="note">${S.esc(c.note)}</span></div>`; }
function showResult(r) {
  const g = r.grade, coach = r.coach || {};
  modal(`<div class="row" style="align-items:flex-end;gap:18px"><div class="grade-big">${g.letter}</div><div><div class="eyebrow">${g.passed ? 'Passed' : 'Not yet · run it back'}${r.peek ? ' · peek' : ''}</div><h2>${g.score}/100</h2></div></div>
    ${coach.summary ? `<div class="panel" style="margin-top:14px"><div class="eyebrow">Coach</div><p style="margin-top:6px">${S.esc(coach.summary)}</p>
      ${(coach.highlights || []).map(h => `<p class="small" style="margin-top:6px">“${S.esc(h.quote)}” <span class="dim">${S.esc(h.note)}</span></p>`).join('')}
      ${coach.fix ? `<p class="small" style="margin-top:8px"><b>One fix:</b> ${S.esc(coach.fix)}</p>` : ''}${coach.assignment ? `<p class="small" style="color:var(--volt);margin-top:6px"><b>Next:</b> ${S.esc(coach.assignment)}</p>` : ''}</div>` : ''}
    <div style="margin-top:14px">${(r.criteria || r.parts?.flatMap(p => p.criteria) || []).map(critHTML).join('')}</div>
    ${r.analysis ? `<div class="panel" style="margin-top:14px">${S.lyricHTML(r.analysis)}</div>` : ''}
    <div class="row" style="margin-top:16px"><button class="btn primary" id="rc">📄 Report card</button><a class="btn" href="/api/academy/report/${r.submission_id}.md">Download .md</a><button class="btn ghost" onclick="location.reload()">Run it back</button></div>`);
  S.$('#rc').onclick = () => openReport(r.submission_id);
  after(r.events);
}
async function openReport(id) {
  const s = await S.get('/api/academy/submission/' + id);
  modal(`<div class="row no-print" style="margin-bottom:10px"><button class="btn small" onclick="window.print()">🖨 Print / PDF</button><a class="btn small" href="/api/academy/report/${id}.md">Download .md</a></div><article class="md">${S.md(s.report || '# Report not available').replace(/&lt;sub&gt;(\d+)&lt;\/sub&gt;/g, '<sub>$1</sub>')}</article>`);
}

/* ------------------------------------------------------------ boss */
async function boss(level) {
  const b = await S.get('/api/academy/boss/' + level);
  $v().innerHTML = `<a href="#map" class="small dim">← Map</a>
    <div class="panel" style="margin:10px 0 16px;background:linear-gradient(135deg,#2a0b12,var(--panel));border-color:rgba(255,23,68,.4)">
      <div class="eyebrow" style="color:var(--red)">${b.ongoing ? 'Mastery checks · this level never ends' : 'Boss fight'}</div><h1 class="big" style="font-size:clamp(2rem,5vw,3.4rem);margin:6px 0">${S.esc(b.title)}</h1>
      <p class="dim">${S.esc(b.goal)}</p>${b.best ? `<p class="small">Best: ${b.best.best}/100 ${b.best.passed ? '✅' : ''}</p>` : ''}
      <div style="margin-top:12px"><div class="small mono" style="color:var(--red)">BOSS HP</div><div class="bar-meter" style="height:14px"><i id="hp" style="width:100%;background:linear-gradient(90deg,#ff1744,#ff6d00)"></i></div></div>
      <p class="small mute" style="margin-top:8px">Pass: 75+ overall and every part 60+. Your work saves per part; take it in stages across sessions.</p></div>
    <div id="parts"></div>
    <div class="row" style="margin-top:16px"><button class="btn primary" id="fight">⚔️ Submit the fight</button><label class="small dim"><input type="checkbox" id="b-coach" checked> Coach review</label><span class="small mute" id="b-msg"></span></div>`;
  const cards = b.parts.map((p, i) => {
    const d = { ...p, id: p.id, number: i + 1, form: ['text', 'check'].includes(p.form) ? p.form : p.form };
    const el = drillCard(d, null, { label: `Part ${i + 1}`, noSubmit: true });
    const saved = JSON.parse(localStorage.getItem(`boss-${level}-${p.id}`) || 'null');
    if (saved?.text) { const ta = S.$('textarea', el); if (ta) { ta.value = saved.text; ta.dispatchEvent(new Event('input')); } }
    el.addEventListener('input', S.debounce(() => localStorage.setItem(`boss-${level}-${p.id}`, JSON.stringify(el._collect())), 500));
    S.$('#parts').appendChild(el); return [p.id, el];
  });
  S.$('#fight').onclick = async () => {
    S.$('#fight').disabled = true; S.$('#b-msg').textContent = 'The boss is reading every part…';
    try {
      const r = await S.post('/api/academy/submit', { ref: 'boss-' + level, parts: Object.fromEntries(cards.map(([id, el]) => [id, el._collect()])), coach: S.$('#b-coach').checked });
      let hp = 100; const per = 100 / r.parts.length;
      r.parts.forEach((p, i) => setTimeout(() => { hp -= per * Math.min(1, p.grade.score / 75); S.$('#hp').style.width = Math.max(0, hp) + '%'; S.tone([200 + i * 60], 'sawtooth', 0, .08); }, 400 + i * 450));
      setTimeout(() => showResult({ ...r, criteria: r.parts.flatMap(p => p.criteria.map(c => ({ ...c, label: 'P' + (r.parts.indexOf(p) + 1) + ' · ' + c.label }))) }), 600 + r.parts.length * 450);
    } catch (e) { S.$('#b-msg').textContent = e.message; }
    S.$('#fight').disabled = false; S.$('#b-msg').textContent = '';
  };
  forgeQuestion(b.question, 'boss:' + level);
}

/* ------------------------------------------------------------ one bar drop (3-minute session) */
async function onebar() {
  const w = await S.get('/api/academy/prompt');
  $v().innerHTML = `<div class="panel glow" style="max-width:720px;margin:0 auto;text-align:center;padding:30px">
    <div class="eyebrow">One Bar Drop · 3 minutes</div><h1 class="big" style="font-size:3rem;margin:10px 0">${S.esc(w.word)}</h1>
    <p class="dim">${w.pattern ? `Ride the ${S.esc(w.pattern)} pattern (${S.esc(w.sounds)}).` : w.ride ? `Ride ${S.esc(w.ride)}. ⚠ ${S.esc(w.avoid)}` : 'Write one or two bars around it.'}</p>
    <textarea id="ob" style="margin-top:16px;min-height:90px;text-align:center" placeholder="One or two bars"></textarea>
    <div id="ob-prev" style="margin-top:10px"></div>
    <div class="row" style="justify-content:center;margin-top:14px"><button class="btn primary" id="ob-go">Drop it</button><a class="btn ghost" href="#onebar" onclick="setTimeout(()=>location.reload(),10)">New word</a></div></div>`;
  S.$('#ob').oninput = S.debounce(async e => { const a = await S.post('/api/flow/analyze', { text: e.target.value }); S.$('#ob-prev').innerHTML = S.lyricHTML(a); }, 300);
  S.$('#ob-go').onclick = async () => {
    const bars = S.$('#ob').value.trim(); if (!bars) return;
    S.$('#ob-go').disabled = true;
    try { const crew = ['biggie', 'slim-shady', 'king-von', 'j-cole']; const r = await S.post('/api/cypher/riff', { persona: crew[Math.floor(Math.random() * crew.length)], bars, mode: 'crew' });
      S.$('#ob-prev').innerHTML = `${S.lyricHTML(r.you)}<hr class="sep"><div class="small" style="color:${r.color}">${S.esc(r.name)} answers</div>${S.lyricHTML(r.analysis)}<p class="small" style="margin-top:6px">🔊 ${S.esc(r.shoutout || '')}</p>`; after(r.events); }
    catch (e) { const sc = await S.post('/api/cypher/score', { text: bars }); S.$('#ob-prev').innerHTML = S.lyricHTML(sc.analysis) + `<p class="small dim">Score ${sc.total} · (crew offline: ${S.esc(e.message)})</p>`; }
    S.$('#ob-go').disabled = false;
  };
}

/* ------------------------------------------------------------ cypher & battle */
async function cypher() {
  const ps = (await S.get('/api/personas')).filter(p => ['rapper', 'coach'].includes(p.role));
  const elo = await S.get('/api/cypher/elo');
  const w = await S.get('/api/academy/prompt');
  $v().innerHTML = `<div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1.2fr)">
    <section class="panel"><div class="row" id="cy-mode">${['crew', 'battle', 'solo'].map(m => `<span class="chip click ${m === 'crew' ? 'on' : ''}" data-m="${m}">${{ crew: '🎤 Crew cypher', battle: '⚔️ Battle', solo: '🎧 Solo' }[m]}</span>`).join('')}</div>
      <div style="margin:14px 0"><div class="small dim">Prompt</div><h2 id="cy-word">${S.esc(w.word)}</h2><div class="small mute">${S.esc(w.pattern ? w.pattern + ' · ' + w.sounds : w.ride || '')}</div></div>
      <div id="cy-who"></div>
      <div class="row" style="margin:8px 0"><span class="timer" id="cy-timer" hidden>05:00</span></div>
      <textarea id="cy-bars" style="min-height:150px" placeholder="Your bars, one per line"></textarea>
      <div id="cy-prev" style="margin-top:8px"></div>
      <div class="row" style="margin-top:10px"><button class="btn primary" id="cy-go">Pass the mic</button><button class="btn ghost" id="cy-new">New prompt</button></div>
      <p class="small mute" style="margin-top:8px">Battle scoring is transparent: rhyme density, chain length, internals in slot, imagery, pocket. Elo: you ${elo.you || 1000}.</p></section>
    <section class="panel"><div id="cy-out" class="stack"><div class="empty">The crew is waiting.</div></div></section></div>`;
  let mode = 'crew', timer;
  const who = () => {
    S.$('#cy-who').innerHTML = mode === 'solo' ? '' : `<div class="small dim" style="margin-bottom:6px">${mode === 'battle' ? 'Opponent' : 'Who is in the cypher'}</div><div class="row">${ps.filter(p => p.id !== 'coach' || mode === 'crew').map((p, i) => `<label class="chip click"><input type="${mode === 'battle' ? 'radio' : 'checkbox'}" name="cyp" value="${p.id}" ${i < (mode === 'battle' ? 1 : 2) ? 'checked' : ''} style="margin-right:4px">${S.esc(p.handle || p.name)}${mode === 'battle' ? ` <span class="mute">${elo[p.id] || 1100}</span>` : ''}</label>`).join('')}</div>`;
    S.$('#cy-timer').hidden = mode !== 'battle';
  };
  who();
  S.$$('#cy-mode .chip').forEach(c => c.onclick = () => { mode = c.dataset.m; S.$$('#cy-mode .chip').forEach(x => x.classList.toggle('on', x === c)); who(); if (mode === 'battle') { const t0 = Date.now(); clearInterval(timer); timer = setInterval(() => { const l = 300 - Math.floor((Date.now() - t0) / 1000); S.$('#cy-timer').textContent = l >= 0 ? `0${Math.floor(l / 60)}:${String(l % 60).padStart(2, '0')}` : 'TIME'; }, 250); } });
  S.$('#cy-new').onclick = async () => { const n = await S.get('/api/academy/prompt'); S.$('#cy-word').textContent = n.word; };
  S.$('#cy-bars').oninput = S.debounce(async e => { const a = await S.post('/api/flow/analyze', { text: e.target.value }); S.$('#cy-prev').innerHTML = S.lyricHTML(a); }, 350);
  S.$('#cy-go').onclick = async () => {
    const bars = S.$('#cy-bars').value.trim(); if (!bars) return;
    const chosen = S.$$('[name=cyp]:checked').map(i => i.value); const out = S.$('#cy-out'); out.innerHTML = '';
    S.$('#cy-go').disabled = true;
    try {
      if (mode === 'solo') { const sc = await S.post('/api/cypher/score', { text: bars }); out.innerHTML = metricsHTML('You', sc) + S.lyricHTML(sc.analysis); }
      else if (mode === 'battle') {
        const r = await S.post('/api/cypher/battle', { persona: chosen[0], bars, word: S.$('#cy-word').textContent });
        clearInterval(timer);
        out.innerHTML = `<h2 style="color:${r.result === 'win' ? 'var(--green)' : r.result === 'draw' ? 'var(--volt)' : 'var(--red)'}">${r.result.toUpperCase()} · ${r.you.total} vs ${r.them.total}</h2><div class="small mute">Elo you ${r.elo.you} · ${S.esc(r.them.name)} ${r.elo[r.them.persona]}</div>
          <div class="grid g2" style="margin-top:12px"><div>${metricsHTML('You', r.you)}${S.lyricHTML(r.you.analysis)}</div><div>${metricsHTML(r.them.name, r.them)}${S.lyricHTML(r.them.analysis)}</div></div>`;
        if (r.result === 'win') { S.banner('VICTORY'); S.confetti(200); }
        after(r.events);
      } else {
        let first = true;
        for (const pid of chosen) {
          const slot = S.h('<div class="panel" style="padding:12px"><span class="small mute">…</span></div>'); out.appendChild(slot);
          try { const r = await S.post('/api/cypher/riff', { persona: pid, bars, mode: 'crew', first_of_round: first }); first = false;
            slot.innerHTML = `<div class="small" style="color:${r.color};font-weight:800">${S.esc(r.name)}</div>${S.lyricHTML(r.analysis)}${r.shoutout ? `<p class="small" style="margin-top:6px">🔊 ${S.esc(r.shoutout)}</p>` : ''}${r.note ? `<p class="small dim">📝 ${S.esc(r.note)}</p>` : ''}`;
            after(r.events); S.tone([330, 440]); }
          catch (e) { slot.innerHTML = `<span class="small" style="color:var(--red)">${S.esc(e.message)}</span>`; }
        }
      }
    } catch (e) { out.innerHTML = `<div class="bubble err">${S.esc(e.message)}</div>`; }
    S.$('#cy-go').disabled = false;
  };
}
function metricsHTML(name, sc) { return `<div class="small" style="font-weight:800;margin-bottom:6px">${S.esc(name)} · ${sc.total}</div>${Object.entries(sc.metrics || {}).map(([k, v]) => critHTML({ label: k, score: v, note: '' })).join('')}`; }

/* ------------------------------------------------------------ rhyme lab sandbox */
async function sandbox() {
  $v().innerHTML = `<div class="grid g2"><section class="panel glow"><div class="eyebrow">Rhyme Lab · ungraded, always open</div><h2 style="margin:4px 0 12px">Strip it to the vowels</h2>
      <input type="text" id="sb-p" placeholder="Any phrase: terrified, back of the club, midnight…" style="font-size:18px">
      <div class="vowelchips" id="sb-skel" style="margin:12px 0"></div>
      <label class="field">Your matches (one per line)<textarea id="sb-c" style="min-height:200px"></textarea></label>
      <div id="sb-s" class="stack" style="gap:2px;margin-top:8px"></div>
      <div class="row" style="margin-top:10px"><button class="btn primary" id="sb-bank">Bank verified finds</button><span class="small mute">Finds pay a little XP and reveal matrix patterns.</span></div></section>
    <section class="panel"><h3>Pattern this phrase rides</h3><div id="sb-pat" class="small dim" style="margin-top:8px">Type a phrase.</div></section></div>`;
  const run = S.debounce(async (commit = false) => {
    const r = await S.post('/api/academy/sandbox', { phrase: S.$('#sb-p').value, candidates: S.$('#sb-c').value.split('\n'), commit });
    S.$('#sb-skel').innerHTML = r.vowels.map(v => `<span class="${v.stress ? 'st' : ''}" title="${S.esc(v.text)}">${S.esc(v.text)} · ${v.vowel}</span>`).join('');
    S.$('#sb-s').innerHTML = r.scored.map(m => `<div class="match-line"><span>${m.score >= .75 ? '✅' : '▫️'}</span><span style="flex:1">${S.esc(m.text)}</span><span class="mute">${Math.round(m.score * 100)}%</span></div>`).join('');
    S.$('#sb-pat').innerHTML = r.pattern ? `<b style="color:var(--volt)">${S.esc(r.pattern.name)}</b> <span class="mute">(${S.esc(r.pattern.sounds)})</span>${Object.entries(r.pattern.rows).map(([k, v]) => `<div style="margin-top:8px"><b>${k}</b><div class="row" style="margin-top:4px">${v.map(x => `<span class="chip click" data-add="${S.esc(x)}">${S.esc(x)}</span>`).join('')}</div></div>`).join('')}` : 'No matrix pattern for this one. Maybe it is a discovery…';
    S.$$('[data-add]').forEach(c => c.onclick = () => { S.$('#sb-c').value += (S.$('#sb-c').value.trim() ? '\n' : '') + c.dataset.add; run(); });
    if (commit) after(r.events);
  }, 350);
  S.$('#sb-p').oninput = () => run(); S.$('#sb-c').oninput = () => run(); S.$('#sb-bank').onclick = () => run(true);
}

/* ------------------------------------------------------------ matrix map */
async function matrix() {
  const s = A.snap;
  $v().innerHTML = `<div class="panel" style="margin-bottom:14px"><h2>The Multi-Syllable Matrix</h2><p class="small dim">18 vowel patterns hide in the fog. Reveal them by landing them in your bars, the Rhyme Lab, chests or recall checks. 5 uses = bronze, 15 = silver, 30 = gold.</p></div>
    <div class="matrix">${s.matrix.map(m => `<div class="mcard ${m.tier}"><div class="small mono mute">${m.tier === 'hidden' ? '???' : m.tier.toUpperCase()}</div><b>${m.tier === 'hidden' ? '· · ·' : S.esc(m.name)}</b><div class="small dim">${m.tier === 'hidden' ? 'undiscovered' : S.esc(m.sounds)}</div>
      ${m.tier !== 'hidden' ? `<div class="bar-meter" style="margin-top:10px"><i style="width:${Math.min(100, m.count / 30 * 100)}%"></i></div><div class="small mute mono" style="margin-top:4px">${m.count} uses</div>` : ''}</div>`).join('')}</div>
    ${s.discoveries.length ? `<div class="panel" style="margin-top:14px"><h3>🧭 Off the map: your discoveries</h3><div class="row" style="margin-top:8px">${s.discoveries.map(d => `<span class="chip">${S.esc(d.id.slice(2).toUpperCase())} · ${d.count}</span>`).join('')}</div></div>` : ''}`;
}

/* ------------------------------------------------------------ trophies & loot */
async function trophies() {
  const s = A.snap;
  const got = s.achievements.filter(a => a.unlocked).length;
  $v().innerHTML = `<div class="grid g2" style="margin-bottom:14px">
    <section class="panel"><h3>Ranks</h3><div class="stack small" style="gap:4px;margin-top:8px">${s.ranks.map(([need, name]) => `<div class="row"><span style="width:20px">${s.xp >= need ? '✅' : '⬜'}</span><b style="flex:1;${s.rank.name === name ? 'color:var(--volt)' : ''}">${S.esc(name)}</b><span class="mono mute">${need}</span></div>`).join('')}</div></section>
    <section class="panel"><h3>Loot</h3><p class="small dim">Equip what you have earned.</p><div class="stack" style="margin-top:8px">${s.loot.length ? s.loot.map(l => `<div class="row small"><span class="tag">${l.kind}</span><b style="flex:1">${S.esc(l.name)}</b>${['theme', 'title'].includes(l.kind) ? `<button class="btn small" data-equip="${l.kind}" data-name="${S.esc(l.name)}">Equip</button>` : ''}</div>`).join('') : '<div class="empty">Chests and rank-ups drop themes and titles.</div>'}</div></section></div>
    <section class="panel"><div class="panel-head"><h3>Achievements · ${got}/${s.achievements.length}</h3></div><div class="ach">${s.achievements.map(a => `<div class="${a.unlocked ? '' : 'locked'}"><span class="ic">${a.icon}</span><div><b>${S.esc(a.name)}</b><div class="small dim">${S.esc(a.desc)}</div>${a.xp ? `<div class="small mono mute">+${a.xp} XP</div>` : ''}</div></div>`).join('')}</div></section>`;
  S.$$('[data-equip]').forEach(b => b.onclick = async () => { await S.put('/api/academy/profile', b.dataset.equip === 'theme' ? { theme: b.dataset.name } : { chosen_title: b.dataset.name }); A.snap = null; await load(); S.toast('Equipped ' + b.dataset.name, 'card'); });
}

/* ------------------------------------------------------------ settings */
async function settings() {
  const p = A.snap.profile;
  $v().innerHTML = `<section class="panel" style="max-width:760px"><h2>Your Academy</h2><div class="grid g2" style="margin-top:14px">
    <label class="field">Name<input type="text" id="st-name" value="${S.esc(p.name)}"></label>
    <label class="field">Title Jarvis uses<input type="text" id="st-title" value="${S.esc(p.title)}"></label>
    <label class="field">Practice rhythm<select id="st-mode"><option value="weekly" ${p.rhythm_mode === 'weekly' ? 'selected' : ''}>Weekly goal (recommended)</option><option value="daily" ${p.rhythm_mode === 'daily' ? 'selected' : ''}>Daily streak</option></select></label>
    <label class="field">Practice days per week<input type="number" id="st-goal" min="1" max="7" value="${p.weekly_goal}"></label>
    <label class="field">Default session<select id="st-sess">${[3, 10, 30].map(m => `<option ${p.session === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
    <label class="field">Jarvis tone<select id="st-tone">${['gentle', 'dry', 'roast'].map(t => `<option ${p.jarvis_tone === t ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
    <label class="field">Placement (start at level)<select id="st-place">${[1, 2, 3, 4].map(l => `<option ${p.placement === l ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>
    <div class="stack" style="margin-top:14px">${[['sounds', 'Reward sounds'], ['show_totals', 'Show XP totals (off = only today\'s gains)'], ['leaderboard', 'Lab leaderboard vs the crew']].map(([k, l]) => `<label class="row small"><input type="checkbox" data-t="${k}" ${p[k] ? 'checked' : ''}> ${l}</label>`).join('')}</div>
    <div class="row" style="margin-top:16px"><button class="btn primary" id="st-save">Save</button><label class="btn ghost">Re-import Bible<input type="file" id="st-bible" accept=".md,.txt" hidden></label></div></section>`;
  S.$('#st-save').onclick = async () => {
    await S.put('/api/academy/profile', { name: S.$('#st-name').value, title: S.$('#st-title').value, rhythm_mode: S.$('#st-mode').value, weekly_goal: +S.$('#st-goal').value, session: +S.$('#st-sess').value, jarvis_tone: S.$('#st-tone').value, ...Object.fromEntries(S.$$('[data-t]').map(c => [c.dataset.t, c.checked])) });
    await S.post('/api/academy/placement', { level: +S.$('#st-place').value }); A.snap = null; await load(); S.toast('Saved', 'quest');
  };
  S.$('#st-bible').onchange = async e => { const fd = new FormData(); fd.append('file', e.target.files[0]); try { await S.api('/api/academy/bible', { method: 'POST', body: fd }); S.toast('Bible re-imported'); } catch (err) { S.toast(err.message); } };
}

/* ------------------------------------------------------------ the forge */
async function forge() {
  const st = await S.get('/api/forge');
  const t = st.trajectory, pos = t.position;
  const W = 320, H = 320, px = v => (v + 1) / 2 * (W - 40) + 20, py = v => H - ((v + 1) / 2 * (H - 40) + 20);
  const path = t.path.map(pt => `${px(pt.x)},${py(pt.y)}`).join(' ');
  const qs = await S.get('/api/forge/question?page=forge:' + new Date().toISOString().slice(0, 10));
  $v().innerHTML = `<div class="grid g2">
    <section class="panel glow"><div class="eyebrow">The Forge</div><h2 style="margin:4px 0">Your trajectory</h2>
      <p class="small dim">Every choice drifts your path: answers, crews, your pocket, the patterns you favour. No two paths forge the same artist.</p>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="margin-top:10px;background:#0a0c10;border-radius:12px">
        <line x1="${W / 2}" y1="10" x2="${W / 2}" y2="${H - 10}" stroke="#262b37"/><line x1="10" y1="${H / 2}" x2="${W - 10}" y2="${H / 2}" stroke="#262b37"/>
        <text x="16" y="${H / 2 - 6}">CALM</text><text x="${W - 16}" y="${H / 2 - 6}" text-anchor="end">CHAOS</text><text x="${W / 2 + 6}" y="20">ORNATE</text><text x="${W / 2 + 6}" y="${H - 12}">PLAIN</text>
        ${path ? `<polyline points="${W / 2},${H / 2} ${path}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-opacity=".6"/>` : ''}
        <circle cx="${px(pos.temper)}" cy="${py(pos.texture)}" r="8" fill="var(--accent)"><animate attributeName="r" values="7;10;7" dur="2s" repeatCount="indefinite"/></circle></svg>
      <div class="stack small" style="margin-top:12px;gap:6px">${Object.entries(AXIS_NAMES).filter(([k]) => !['temper', 'texture'].includes(k)).map(([k, [lo, hi]]) => `<div class="row"><span style="width:96px;text-align:right" class="mute">${lo}</span><div class="bar-meter" style="flex:1;position:relative"><i style="width:${(pos[k] + 1) * 50}%"></i></div><span style="width:96px" class="mute">${hi}</span></div>`).join('')}</div>
      <p class="small mute" style="margin-top:8px">${t.choices} choices on the path${st.influences.length ? ' · influences: ' + st.influences.map(i => `${i.persona} ${Math.round(i.share * 100)}%`).join(', ') : ''}</p></section>
    <div class="stack">
      <section class="panel"><h3>Progress to your persona</h3><div class="bar-meter" style="margin:10px 0"><i style="width:${Math.round(st.progress * 100)}%"></i></div>
        <div class="small dim">${st.answered}/${st.need_answers} life questions · beat the Level ${st.need_level} boss</div>
        ${st.awarded ? `<p style="margin-top:12px">🔥 Forged: <a href="/station/persona?id=${st.awarded.persona_id}"><b>${S.esc(st.awarded.stage_name)}</b></a> · <a href="/api/forge/skill.md">download SKILL.md</a></p>` : ''}
        ${st.eligible && !st.awarded ? `<div class="row" style="margin-top:12px"><input type="text" id="fg-name" placeholder="Your stage name"><button class="btn primary" id="fg-go">Forge me</button></div>` : ''}</section>
      <section class="panel"><h3>🔮 Preview</h3>${st.preview ? `<p class="small dim" style="margin-top:6px">${S.esc(st.preview.read || '')}</p><div class="row" style="margin-top:8px">${(st.preview.stage_names || []).map(n => `<span class="chip">${S.esc(n)}</span>`).join('')}</div><div class="row" style="margin-top:8px">${(st.preview.themes || []).map(n => `<span class="tag">${S.esc(n)}</span>`).join('')}</div>` : ''}
        <button class="btn small" id="fg-prev" style="margin-top:10px" ${st.preview_ready ? '' : 'disabled'}>${st.preview_ready ? (st.preview ? 'Re-read me' : 'Read me') : `Unlocks at ${st.preview_at} answers`}</button></section>
      <section class="panel" id="fg-q"></section>
    </div></div>`;
  if (qs.question) { S.$('#fg-q').innerHTML = `<div class="qcard"><div class="eyebrow">Today's question</div><p style="margin:6px 0">${S.esc(qs.question.prompt)}</p><button class="btn small primary" id="fg-answer">Answer</button></div>`; S.$('#fg-answer').onclick = () => forgeQuestion(qs.question, 'forge:' + new Date().toISOString().slice(0, 10)); }
  else S.$('#fg-q').innerHTML = '<div class="small dim">Open new Academy pages to get more questions.</div>';
  S.$('#fg-prev').onclick = async () => { S.$('#fg-prev').disabled = true; S.$('#fg-prev').textContent = 'Reading you…'; try { await S.post('/api/forge/preview'); S.tone([523, 659, 784, 1047]); forge(); } catch (e) { S.toast(e.message); S.$('#fg-prev').disabled = false; } };
  if (S.$('#fg-go')) S.$('#fg-go').onclick = async () => { S.$('#fg-go').disabled = true; try { const r = await S.post('/api/forge/forge', { stage_name: S.$('#fg-name').value }); S.banner(r.persona.name); S.confetti(300); after(r.events); setTimeout(() => location.href = '/station/persona?id=' + r.persona.id, 2500); } catch (e) { S.toast(e.message); S.$('#fg-go').disabled = false; } };
}

/* ------------------------------------------------------------ listening lab */
async function lab() {
  const L = await S.get('/api/lab');
  const sp = L.spotify;
  const msg = S.qs('lab');
  $v().innerHTML = `<div class="grid" style="grid-template-columns:minmax(0,1fr) minmax(0,1.5fr)">
    <div class="stack">
      <section class="panel"><div class="panel-head"><h3>Spotify</h3><span class="tag" style="color:${sp.connected ? 'var(--green)' : 'var(--mute)'}">${sp.connected ? 'connected' + (sp.user ? ' · ' + S.esc(sp.user) : '') : 'not connected'}</span></div>
        ${msg ? `<p class="small" style="color:var(--volt)">${S.esc({ connected: 'Spotify connected ✓', 'spotify-denied': 'Spotify login cancelled', 'spotify-error': S.qs('msg') || 'Spotify error' }[msg] || msg)}</p>` : ''}
        ${sp.connected ? `<button class="btn small ghost" id="sp-off">Disconnect</button>` : `<p class="small dim">Create an app at developer.spotify.com, add this Redirect URI, paste the Client ID. No secret needed.</p>
          <code class="small" style="display:block;margin:8px 0;word-break:break-all">${S.esc(sp.redirect_uri)}</code>
          <div class="row" style="flex-wrap:nowrap"><input type="text" id="sp-id" placeholder="Client ID" value="${S.esc(sp.client_id)}"><button class="btn small primary" id="sp-go">Connect</button></div>
          <p class="small mute" style="margin-top:6px">Without Spotify, the Lab picks from the Bible's listening curriculum.</p>`}</section>
      <section class="panel"><h3>The algorithm picks</h3><p class="small dim">Rap from your top, saved and recent tracks, weighted toward your level's study list and away from songs you have already studied.</p>
        <div class="row" style="margin-top:10px"><button class="btn primary" id="lb-pick">🎲 Pick a track</button><label class="small dim"><input type="checkbox" id="lb-short"> Short lab (transcribe only)</label></div>
        <div id="lb-track" style="margin-top:12px"></div></section>
      <section class="panel"><h3>Past labs</h3>${L.sessions.length ? L.sessions.map(s => `<div class="row small" style="padding:5px 0;border-bottom:1px solid var(--line)"><span style="flex:1">${S.esc(s.track.artists.join(', '))} · ${S.esc(s.track.name)}</span><span class="mono">${s.results.total ? s.results.score + '/' + s.results.total : '—'}</span><a href="#" data-lab="${s.id}">open</a></div>`).join('') : '<div class="small mute">None yet.</div>'}</section>
    </div>
    <section class="panel" id="lb-main"><div class="empty">Pick a track to start the class.</div></section></div>`;
  if (S.$('#sp-go')) S.$('#sp-go').onclick = async () => { await S.put('/api/lab/spotify', { client_id: S.$('#sp-id').value }); location.href = '/api/spotify/login'; };
  if (S.$('#sp-off')) S.$('#sp-off').onclick = async () => { await S.post('/api/spotify/disconnect'); lab(); };
  S.$$('[data-lab]').forEach(a => a.onclick = async e => { e.preventDefault(); showLab(await S.get('/api/lab/' + a.dataset.lab)); });
  S.$('#lb-pick').onclick = async () => {
    try { const t = await S.get('/api/lab/pick'); A.track = t;
      S.$('#lb-track').innerHTML = `${t.embed ? `<iframe src="${t.embed}" width="100%" height="152" frameborder="0" allow="encrypted-media" style="border-radius:12px"></iframe>` : `<a class="btn small" target="_blank" href="${t.url}">Open on Spotify</a>`}
        <div class="small dim" style="margin-top:6px">${S.esc(t.artists.join(', '))} · <b>${S.esc(t.name)}</b> <span class="tag">${S.esc(t.source)}</span>${t.focus ? ` <span class="tag">${S.esc(t.focus)}</span>` : ''}</div>
        <div class="row" style="margin-top:8px"><button class="btn primary" id="lb-start">Start the class</button><button class="btn ghost" id="lb-re">Pick another</button></div>`;
      S.$('#lb-re').onclick = () => S.$('#lb-pick').click();
      S.$('#lb-start').onclick = async () => {
        if (S.$('#lb-short').checked) return showLab({ id: null, track: t, dissection: {}, short: true });
        S.$('#lb-main').innerHTML = '<div class="empty">The Coach is breaking down the track…</div>';
        try { showLab(await S.post('/api/lab/start', { track: t })); } catch (e) { S.$('#lb-main').innerHTML = `<div class="bubble err">${S.esc(e.message)}</div>`; }
      };
    } catch (e) { S.$('#lb-track').innerHTML = `<div class="bubble err">${S.esc(e.message)}</div>`; }
  };
}
function showLab(s) {
  const d = s.dissection || {}, t = s.track;
  S.$('#lb-main').innerHTML = `<div class="eyebrow">Listening Lab${s.short ? ' · short' : ''}</div><h2>${S.esc(t.artists.join(', '))} · ${S.esc(t.name)}</h2>
    ${d.known === false ? '<p class="small" style="color:var(--orange)">Coach does not know this exact song well; lesson built from the artist\'s style.</p>' : ''}
    ${d.overview ? `<p style="margin:10px 0">${S.esc(d.overview)}</p>` : ''}
    ${(d.techniques || []).length ? `<h3 style="margin-top:12px">Techniques</h3>${d.techniques.map(x => `<div class="small" style="padding:6px 0;border-bottom:1px solid var(--line)"><b>${S.esc(x.name)}</b> <span class="tag">ch ${S.esc(x.chapter || '?')}</span><div class="dim">${S.esc(x.where || '')} · ${S.esc(x.why_it_works || '')}</div></div>`).join('')}` : ''}
    ${(d.listen_for || []).length ? `<h3 style="margin-top:12px">Listen for</h3><ul class="small dim" style="margin-left:18px">${d.listen_for.map(x => `<li>${S.esc(x)}</li>`).join('')}</ul>` : ''}
    <h3 style="margin-top:14px">Transcribe ${s.short ? '4' : '4-8'} bars</h3><p class="small dim">${S.esc(d.transcribe_tip || 'Pick the densest section. One bar per line.')}</p>
    <textarea id="lb-tx" style="min-height:120px;margin-top:6px">${S.esc(s.transcription || '')}</textarea><div id="lb-txv" class="panel" style="padding:10px;margin-top:8px"></div>
    ${s.id ? '<button class="btn small" id="lb-txs" style="margin-top:8px">Save transcription</button>' : ''}
    ${(d.quiz || []).length ? `<h3 style="margin-top:16px">Class quiz</h3><div id="lb-quiz" class="stack">${d.quiz.map((q, i) => `<div class="panel" style="padding:12px"><b class="small">${i + 1}. ${S.esc(q.q)}</b><div class="stack" style="gap:4px;margin-top:6px">${q.options.map((o, j) => `<label class="small row"><input type="radio" name="q${i}" value="${j}"> ${S.esc(o)}</label>`).join('')}</div></div>`).join('')}</div>
      <button class="btn primary" id="lb-submit" style="margin-top:10px">Hand it in</button><div id="lb-res"></div>` : ''}
    ${(d.discussion || []).length ? `<h3 style="margin-top:16px">Discuss with the Coach</h3><div class="row">${d.discussion.map(x => `<span class="chip click" data-disc="${S.esc(x)}">${S.esc(x)}</span>`).join('')}</div><div id="lb-chat" style="margin-top:10px"></div>` : ''}`;
  const tx = S.$('#lb-tx');
  const draw = S.debounce(async () => { const a = await S.post('/api/flow/analyze', { text: tx.value }); S.$('#lb-txv').innerHTML = a.bars.length ? S.lyricHTML(a) + `<div class="small mute">${a.families} rhyme thread(s) running</div>` : '<span class="small mute">Colours appear as you transcribe.</span>'; }, 350);
  tx.oninput = draw; draw();
  if (S.$('#lb-txs')) S.$('#lb-txs').onclick = async () => { const r = await S.post(`/api/lab/${s.id}/transcribe`, { text: tx.value }); after(r.events); S.toast('Transcription saved'); };
  if (S.$('#lb-submit')) S.$('#lb-submit').onclick = async () => {
    const answers = Object.fromEntries(d.quiz.map((_, i) => [i, +(S.$(`[name=q${i}]:checked`)?.value ?? -1)]));
    const r = await S.post(`/api/lab/${s.id}/quiz`, { answers });
    r.dissection.quiz.forEach((q, i) => { S.$$(`[name=q${i}]`).forEach((inp, j) => { inp.disabled = true; inp.parentElement.style.color = j === q.answer ? 'var(--green)' : (+inp.checked && j !== q.answer ? 'var(--red)' : ''); }); const p = S.$$('#lb-quiz .panel')[i]; p.insertAdjacentHTML('beforeend', `<div class="small dim" style="margin-top:6px">${S.esc(q.explain)}</div>`); });
    const showBoard = A.snap.profile.leaderboard !== false;
    S.$('#lb-res').innerHTML = `<h2 style="margin-top:12px">${r.score}/${r.total}${showBoard ? ` · #${r.place} in class` : ''}</h2>
      ${showBoard ? r.board.map((b, i) => `<div class="board-row ${b.id === 'you' ? 'you' : ''}"><b>${i + 1}</b><span>${S.esc(b.name)}</span><span class="mono">${b.score}/${r.total}</span></div>`).join('') : ''}
      ${r.banter.map(b => `<p class="small" style="margin-top:4px"><b style="color:${b.color}">${S.esc(b.name)}:</b> ${S.esc(b.line)}</p>`).join('')}`;
    if (r.beat_all && showBoard) { S.banner('TOP OF THE CLASS'); S.confetti(220); }
    after(r.events);
  };
  if (S.$('#lb-chat')) { const ch = S.chatWidget(S.$('#lb-chat'), { persona: 'coach', name: 'Coach', glyph: 'C', color: 'var(--green)', placeholder: 'Discuss the track…' }); S.$$('[data-disc]').forEach(c => c.onclick = () => ch.send(`About ${t.artists.join(', ')} - "${t.name}": ${c.dataset.disc}`)); }
}

route();
