/*
 * NationalBettingAssociation frontend. Plain JS, no build step.
 * anime.js 4 handles motion. If its CDN script doesn't load, or the viewer
 * prefers reduced motion, the page renders the same, just without animation.
 */
(() => {
  'use strict';

  const A = window.anime;
  const MOTION = Boolean(A && A.animate) && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------- helpers

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (x, d = 0) => `${(x * 100).toFixed(d)}%`;
  const signed = (x, d = 1) => `${x < 0 ? '−' : '+'}${Math.abs(x).toFixed(d)}`;
  const int = (v) => Math.round(v).toLocaleString();
  const num = (x, d) => x.toFixed(d).replace('-', '−');
  const flagPts = (t) => `${Math.round(t * 100)}-point`;

  const TEAM_COLORS = {
    ATL: '#e03a3e', BOS: '#1f9d55', BKN: '#a1a1a4', CHA: '#00a3b4', CHI: '#ce1141', CLE: '#b5304c',
    DAL: '#1e7fd8', DEN: '#fec524', DET: '#e0314b', GSW: '#ffc72c', HOU: '#ce1141', IND: '#fdbb30',
    LAC: '#2f6fe0', LAL: '#fdb927', MEM: '#6f8fcf', MIA: '#e03a50', MIL: '#3c9a5f', MIN: '#78be20',
    NOP: '#b4975a', NYK: '#f58426', OKC: '#2b8fe0', ORL: '#1a8fe0', PHI: '#2b7fd8', PHX: '#e56020',
    POR: '#e03a3e', SAC: '#8b5fbf', SAS: '#c4ced4', TOR: '#ce1141', UTA: '#f9a01b', WAS: '#e31837',
  };
  const BOOKS = { draftkings: 'DraftKings', fanduel: 'FanDuel', betmgm: 'BetMGM', bovada: 'Bovada', betrivers: 'BetRivers' };

  const colorOf = (abbr) => TEAM_COLORS[abbr] || '#808eef';
  const bookName = (key) => BOOKS[key] || key.replace(/(^|_)(\w)/g, (_, s, c) => (s ? ' ' : '') + c.toUpperCase());
  const nickname = (name) => (/Trail Blazers$/.test(name) ? 'Trail Blazers' : name.split(' ').pop());
  const shortName = (t) => `${t.abbr} ${nickname(t.team)}`;

  function fmtDate(iso) {
    const d = new Date(iso);
    const day = d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    return `${day} @ ${time}`;
  }
  const fmtDay = (iso) => new Date(iso).toLocaleDateString(undefined, { month: 'long', day: 'numeric' });

  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
    let body = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) throw new Error((body && body.detail) || `${res.status} ${res.statusText}`);
    return body;
  }

  const emptyHTML = (title, text) => `<div class="empty"><b>${esc(title)}</b>${esc(text)}</div>`;
  const errorHTML = (err) => `<div class="empty is-error"><b>Couldn't load this</b>${esc(err.message || err)}</div>`;

  // ---------------------------------------------------------------- motion

  function hide(els) {
    if (MOTION) els.forEach((el) => { el.style.opacity = '0'; });
  }

  function reveal(els, { y = 18, step = 60, start = 0, duration = 700, from = 'first' } = {}) {
    if (!MOTION || !els.length) return;
    hide(els);
    A.animate(els, {
      opacity: [0, 1],
      translateY: [y, 0],
      delay: A.stagger(step, { start, from }),
      duration,
      ease: 'outExpo',
      onComplete: () => els.forEach((el) => { el.style.opacity = ''; el.style.transform = ''; }),
    });
  }

  function countUp(el, to, fmt, { duration = 1200, delay = 0 } = {}) {
    if (!el) return;
    if (!MOTION || !Number.isFinite(to)) { el.textContent = fmt(to); return; }
    const state = { v: 0 };
    el.textContent = fmt(0);
    A.animate(state, {
      v: to,
      duration,
      delay,
      ease: 'outExpo',
      onUpdate: () => { el.textContent = fmt(state.v); },
      onComplete: () => { el.textContent = fmt(to); },
    });
  }

  function drawLines(els, start = 0) {
    if (!MOTION) return;
    els.forEach((el, i) => {
      const len = typeof el.getTotalLength === 'function' ? el.getTotalLength() : 240;
      el.style.strokeDasharray = `${len}`;
      el.style.strokeDashoffset = `${len}`;
      A.animate(el, { strokeDashoffset: [len, 0], duration: 900, delay: start + i * 140, ease: 'inOutQuart' });
    });
  }

  function whenVisible(el, fn) {
    if (!el) return;
    if (!('IntersectionObserver' in window)) { fn(); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); fn(); }
    }, { threshold: 0.12 });
    io.observe(el);
  }

  // ---------------------------------------------------------------- state

  const state = {
    games: [],
    model: null,
    teams: new Map(),
    heroGames: [],
    heroIndex: 0,
    heroHover: false,
    sort: 'gap',
    onlyFlagged: false,
    conversationId: null,
    busy: false,
    chatOpen: false,
  };
  const gameById = (id) => state.games.find((g) => g.game_id === id);

  // ---------------------------------------------------------------- under the hood

  const HOOD = {
    markets: {
      title: 'Stats vs. market, every game',
      tags: ['ES|QL', 'LOOKUP JOIN', 'EVAL', 'CASE'],
      why: "One row per team per bookmaker. LOOKUP JOIN attaches each team's season stats to its odds rows, and EVAL builds the raw score with the home-court bonus. The server pairs rows into games, strips the vig per book and runs the logistic from reference_model.py.",
    },
    teams: {
      title: 'Win-probability score, ranked',
      tags: ['ES|QL', 'EVAL', 'CASE'],
      why: 'The formula on its own: half the net rating plus 30 times the last-10 win rate. CASE handles a team with no last-10 games, scoring its form as average instead of dividing by zero.',
    },
    search: {
      title: 'Play-style search',
      tags: ['semantic_text', 'MATCH', 'ELSER on EIS'],
      why: "narrative is a semantic_text field that ELSER on the Elastic Inference Service embeds when a document is indexed. MATCH scores teams by meaning, and sorting on _score keeps that order instead of re-ranking by how good a team is.",
    },
    context: {
      title: 'League context',
      tags: ['ES|QL', 'STATS'],
      why: 'One row of aggregates over all 30 teams. The average net rating should come out at 0.00, since every point one team wins by is a point another team loses by. If it drifts, ingest double-counted a game.',
    },
    home_edge: {
      title: 'Measured home-court edge',
      tags: ['ES|QL', 'STATS', 'EVAL'],
      why: "Actual home and road win rates across the league. It's the number the model's flat +5 home bonus stands in for.",
    },
    tiers: {
      title: 'Teams by tier',
      tags: ['ES|QL', 'STATS … BY'],
      why: 'A grouped aggregation that buckets the league by net rating. Lopsided buckets would make narratives too similar for semantic search to separate.',
    },
    odds: {
      title: 'Odds coverage',
      tags: ['ES|QL', 'COUNT_DISTINCT', 'MAX'],
      why: 'How many games and books the page is working from, and when The Odds API was last pulled.',
    },
    chat: {
      title: 'Analyst chat',
      tags: ['Agent Builder', 'converse API', 'SSE'],
      why: "The chat panel streams Kibana's converse endpoint for the nba_value_finder agent. The agent picks its own tools, and each answer lists the ones that ran with the ES|QL they sent.",
    },
  };
  const HOOD_ORDER = ['markets', 'teams', 'search', 'context', 'home_edge', 'tiers', 'odds', 'chat'];
  const KEYWORDS = /\b(FROM|WHERE|EVAL|STATS|BY|KEEP|SORT|LIMIT|LOOKUP JOIN|ON|METADATA|MATCH|CASE|ROUND|AVG|MAX|MIN|COUNT_DISTINCT|COUNT|TO_DOUBLE|ASC|DESC|IS NOT NULL|AND|OR|POST|GET)\b/g;

  function highlight(query) {
    const text = query.includes('\n') ? query : query.replace(/\s*\|\s*/g, '\n| ');
    return esc(text.trim())
      .replace(/(&quot;[^\n]*?&quot;)/g, '<span class="str">$1</span>')
      .replace(KEYWORDS, '<span class="kw">$1</span>')
      .replace(/^(\s*)\|/gm, '$1<span class="pipe">|</span>')
      .replace(/(\?[a-z_]+)/g, '<span class="param">$1</span>');
  }

  function logQuery(key, { took, query, meta = '' }) {
    const def = HOOD[key];
    const grid = $('#hood-grid');
    if (!def || !grid) return;
    let card = $(`[data-hood="${key}"]`, grid);
    const fresh = !card;
    if (fresh) {
      card = document.createElement('article');
      card.className = 'q-card card';
      card.dataset.hood = key;
      card.innerHTML = `
        <header><h3>${esc(def.title)}</h3><span class="took"></span></header>
        <div class="tags">${def.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
        <p class="q-why">${esc(def.why)}</p>
        <span class="q-meta"></span>
        <pre class="code"><code></code></pre>`;
      const next = HOOD_ORDER.slice(HOOD_ORDER.indexOf(key) + 1).map((k) => $(`[data-hood="${k}"]`, grid)).find(Boolean);
      grid.insertBefore(card, next || null);
    }
    $('.took', card).textContent = took != null ? `${int(took)} ms` : '';
    $('.q-meta', card).textContent = meta;
    $('code', card).innerHTML = highlight(query);
    if (fresh) reveal([card], { y: 12, step: 0, duration: 600 });
    else if (MOTION) A.animate($('.took', card), { opacity: [0.2, 1], scale: [1.25, 1], duration: 700, ease: 'outBack' });
  }

  // ---------------------------------------------------------------- health

  async function loadHealth() {
    const pill = $('#status');
    const label = $('span', pill);
    try {
      const h = await api('/api/health');
      const es = h.elasticsearch;
      const kb = h.kibana;
      $('#agent-id').textContent = h.agent_id;
      let tone = 'ok';
      let text = `Elastic ${es.version || ''}`.trim();
      let title = es.counts ? Object.entries(es.counts).map(([k, v]) => `${k}: ${v}`).join(' · ') : '';
      if (!es.ok) { tone = 'bad'; text = 'Elasticsearch down'; title = es.error || ''; }
      else if (!kb.configured) { tone = 'warn'; text = 'Chat off: no KIBANA_URL'; }
      else if (!kb.ok) { tone = 'warn'; text = 'Kibana unreachable'; title = kb.error || ''; }
      else if (!kb.agent_registered) { tone = 'warn'; text = 'Agent not registered'; title = 'Run .venv/bin/python scripts/setup_agent.py'; }
      pill.dataset.tone = tone;
      label.textContent = text;
      pill.title = title;
      if (MOTION && tone === 'ok') {
        A.animate($('i', pill), { scale: [1, 1.7, 1], opacity: [1, 0.45, 1], duration: 2000, loop: true, ease: 'inOutSine' });
      }
    } catch (err) {
      pill.dataset.tone = 'bad';
      label.textContent = 'API offline';
      pill.title = err.message;
    }
  }

  // ---------------------------------------------------------------- markets

  function teamRowHTML(t) {
    return `
      <div class="trow">
        <div class="tname">
          <span class="tlabel">${esc(shortName(t))}</span>
          ${t.is_home ? '<span class="home-tag">Home</span>' : ''}
          <i class="uline" style="--c:${colorOf(t.abbr)};--w:${Math.max(6, t.model * 100).toFixed(1)}%"></i>
        </div>
        <span class="odds">${t.best_odds.toFixed(2)}x</span>
        <span class="chip chip-model" title="Stats model">${pct(t.model)}</span>
        <span class="chip" title="Books, vig removed">${pct(t.market)}</span>
      </div>`;
  }

  function cardHTML(g) {
    const edge = g[g.edge];
    return `
      <article class="market card" data-game="${esc(g.game_id)}" tabindex="0" aria-label="${esc(`${g.away.team} at ${g.home.team}`)}">
        <header class="market-head">
          <h3>${esc(shortName(g.away))} vs ${esc(shortName(g.home))}</h3>
          <div class="meta">${g.flagged ? '<span class="live">Flagged</span>' : ''}<span>${esc(fmtDate(g.date))}</span></div>
        </header>
        <div class="cols"><span></span><span>Odds</span><span>Model</span><span>Books</span></div>
        ${teamRowHTML(g.away)}
        ${teamRowHTML(g.home)}
        <footer class="market-foot">
          <span class="gap ${g.flagged ? 'is-flagged' : ''}">${signed(g.gap * 100)} pts on ${esc(nickname(edge.team))}</span>
          <span>${g.books.length} book${g.books.length === 1 ? '' : 's'}</span>
        </footer>
      </article>`;
  }

  function animateCards(grid) {
    const cards = $$('.market', grid);
    reveal(cards, { step: cards.length > 12 ? 22 : 55, y: 22 });
    if (MOTION) {
      const lines = $$('.uline', grid);
      lines.forEach((l) => { l.style.transform = 'scaleX(0)'; });
      A.animate(lines, { scaleX: [0, 1], duration: 900, ease: 'outExpo', delay: A.stagger(cards.length > 12 ? 11 : 28, { start: 250 }) });
    }
  }

  function renderMarkets(data) {
    state.games = data.games;
    state.model = data.model;
    logQuery('markets', { took: data.took_ms, query: data.query, meta: `${data.rows} rows in, ${data.games.length} games out${data.skipped.length ? `, ${data.skipped.length} skipped` : ''}` });

    if (!data.games.length) {
      $('#hero-body').innerHTML = emptyHTML('No priced games', 'Run ./ingest/refresh_all.sh to pull odds.');
      $('#gap-grid').innerHTML = '';
      $('#all-count').textContent = 'No odds indexed yet';
      return;
    }

    // Feature games that several books priced; one-book games make a thin chart.
    const byGap = [...data.games].sort((a, b) => b.gap - a.gap);
    const wellPriced = byGap.filter((g) => g.books.length >= 3);
    state.heroGames = [...wellPriced, ...byGap.filter((g) => g.books.length < 3)].slice(0, 5);

    const flagged = data.games.filter((g) => g.flagged).length;
    $('#all-count').textContent = `${data.games.length} games from ${data.rows} prices. ${flagged} clear the ${flagPts(data.model.threshold)} flag.`;

    renderHero(0, 1);
    renderGapGrid();
    renderAllGrid();
    startHeroTimer();
  }

  function renderGapGrid() {
    const grid = $('#gap-grid');
    const top = [...state.games].sort((a, b) => b.gap - a.gap).slice(0, 6);
    grid.innerHTML = top.map(cardHTML).join('');
    whenVisible(grid, () => animateCards(grid));
  }

  function renderAllGrid(animateNow = false) {
    const grid = $('#all-grid');
    let games = [...state.games];
    if (state.onlyFlagged) games = games.filter((g) => g.flagged);
    games.sort(state.sort === 'gap' ? (a, b) => b.gap - a.gap : (a, b) => new Date(a.date) - new Date(b.date));
    grid.innerHTML = games.length ? games.map(cardHTML).join('') : emptyHTML('Nothing flagged', 'No game clears the threshold right now.');
    if (animateNow) animateCards(grid);
    else whenVisible(grid, () => animateCards(grid));
  }

  // ---------------------------------------------------------------- hero

  function chartSVG(g) {
    const W = 520, H = 272, L = 96, R = 22, T = 58, B = 30;
    const values = [...g.books.map((b) => b.home_market), g.home.model].map((v) => v * 100);
    let lo = Math.floor((Math.min(...values) - 6) / 5) * 5;
    let hi = Math.ceil((Math.max(...values) + 6) / 5) * 5;
    if (hi - lo < 25) { const mid = (hi + lo) / 2; lo = mid - 12.5; hi = mid + 12.5; }
    lo = Math.max(0, lo);
    hi = Math.min(100, hi);
    const x = (p) => L + ((p * 100 - lo) / (hi - lo)) * (W - L - R);
    const rowH = (H - T - B) / g.books.length;
    const step = hi - lo > 45 ? 10 : 5;

    let grid = '';
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      const gx = x(v / 100).toFixed(1);
      grid += `<line class="grid-line" x1="${gx}" x2="${gx}" y1="${T - 8}" y2="${H - B}"/>`;
      grid += `<text class="axis" x="${gx}" y="${H - 10}" text-anchor="middle">${Math.round(v)}%</text>`;
    }

    const rows = g.books.map((b, i) => {
      const cy = (T + rowH * (i + 0.5)).toFixed(1);
      return `<text class="book" x="${L - 12}" y="${cy}" dy="4" text-anchor="end">${esc(bookName(b.bookmaker))}</text>
        <line class="row-line" x1="${L}" x2="${W - R}" y1="${cy}" y2="${cy}"/>`;
    }).join('');

    const dots = g.books.map((b, i) => {
      const cy = (T + rowH * (i + 0.5)).toFixed(1);
      return `<circle class="dot" cx="${x(b.home_market).toFixed(1)}" cy="${cy}" r="6"><title>${esc(bookName(b.bookmaker))}: ${pct(b.home_market, 1)} after vig</title></circle>`;
    }).join('');

    const xm = x(g.home.market);
    const xd = x(g.home.model);
    const clampX = (v) => Math.min(W - R - 44, Math.max(L + 44, v)).toFixed(1);
    return `
      <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${nickname(g.home.team)} win chance: model ${pct(g.home.model)}, books ${pct(g.home.market)}`)}">
        ${grid}${rows}
        <rect class="gap-band" x="${Math.min(xm, xd).toFixed(1)}" y="${T - 8}" width="${Math.abs(xd - xm).toFixed(1)}" height="${H - B - T + 8}" style="transform-origin:${xd >= xm ? 'left' : 'right'} center"/>
        <line class="line-market" data-draw x1="${xm.toFixed(1)}" x2="${xm.toFixed(1)}" y1="${T - 8}" y2="${H - B}"/>
        <line class="line-model" data-draw x1="${xd.toFixed(1)}" x2="${xd.toFixed(1)}" y1="${T - 8}" y2="${H - B}"/>
        ${dots}
        <text class="lbl lbl-model" x="${clampX(xd)}" y="${T - 34}" text-anchor="middle">Model ${pct(g.home.model)}</text>
        <text class="lbl lbl-market" x="${clampX(xm)}" y="${T - 16}" text-anchor="middle">Books ${pct(g.home.market)}</text>
      </svg>`;
  }

  function heroHTML(g, i) {
    const edge = g[g.edge];
    return `
      <div class="hero-left">
        <div class="crumbs"><span>NBA</span><i></i><span>${esc(fmtDate(g.date))}</span><i></i><span>Gap #${i + 1}</span></div>
        <h1 class="hero-title">${esc(shortName(g.away))} vs ${esc(shortName(g.home))}</h1>
        <div class="cols cols-hero"><span></span><span>Best odds</span><span>Model</span><span>Books</span></div>
        ${teamRowHTML(g.away)}
        ${teamRowHTML(g.home)}
        <div class="callout ${g.flagged ? 'is-flagged' : ''}">
          <div class="callout-num"><strong data-count="${(g.gap * 100).toFixed(2)}">0.0</strong><span>pts</span></div>
          <p>The model gives the ${esc(nickname(edge.team))} <b>${pct(edge.model, 1)}</b>. ${g.books.length === 1 ? 'The one book pricing this game has' : `${g.books.length} books average`} them at <b>${pct(edge.market, 1)}</b> once the vig comes out.</p>
        </div>
        <div class="hero-actions">
          <button class="btn-primary" type="button" data-ask="${esc(g.game_id)}">Ask the analyst</button>
          <button class="btn-ghost" type="button" data-open="${esc(g.game_id)}">Show the math</button>
        </div>
      </div>
      <div class="hero-right">
        <div class="chart-head">
          <span>${esc(nickname(g.home.team))} win chance, book by book</span>
          <span class="legend"><i class="lg-model"></i>Model<i class="lg-market"></i>Books avg</span>
        </div>
        ${chartSVG(g)}
      </div>`;
  }

  function animateHero(body) {
    const num = $('[data-count]', body);
    const target = Number(num.dataset.count);
    if (!MOTION) { num.textContent = target.toFixed(1); return; }

    const fades = $$('.crumbs, .hero-title, .cols-hero, .trow, .callout, .hero-actions, .chart-head, .grid-line, .axis, .book, .row-line, .lbl', body);
    hide(fades);
    $$('.uline', body).forEach((el) => { el.style.transform = 'scaleX(0)'; });
    const band = $('.gap-band', body);
    band.style.transform = 'scaleX(0)';
    $$('.dot', body).forEach((el) => el.setAttribute('r', '0'));

    const tl = A.createTimeline({ defaults: { ease: 'outExpo', duration: 700 } });
    tl.add($$('.crumbs, .hero-title, .cols-hero', body), { opacity: [0, 1], translateY: [14, 0], delay: A.stagger(70) }, 0)
      .add($$('.chart-head, .grid-line, .axis, .book, .row-line', body), { opacity: [0, 1], duration: 500, delay: A.stagger(14) }, 100)
      .add($$('.trow', body), { opacity: [0, 1], translateX: [-18, 0], delay: A.stagger(90) }, 200)
      .add($$('.uline', body), { scaleX: [0, 1], duration: 1000, delay: A.stagger(90) }, 380)
      .add($$('.callout, .hero-actions', body), { opacity: [0, 1], translateY: [12, 0], delay: A.stagger(90) }, 460)
      .add($$('.dot', body), { r: [0, 6], duration: 800, ease: 'outBack', delay: A.stagger(90) }, 520)
      .add(band, { scaleX: [0, 1], duration: 900, ease: 'outQuart' }, 820)
      .add($$('.lbl', body), { opacity: [0, 1], translateY: [6, 0], delay: A.stagger(90) }, 980);
    drawLines($$('[data-draw]', body), 420);
    countUp(num, target, (v) => v.toFixed(1), { duration: 1500, delay: 500 });
  }

  function renderDots() {
    const wrap = $('#hero-dots');
    if (wrap.children.length !== state.heroGames.length) {
      wrap.innerHTML = state.heroGames.map((_, i) => `<button class="hdot" type="button" data-i="${i}" aria-label="Show gap ${i + 1}"></button>`).join('');
    }
    $$('.hdot', wrap).forEach((dot, i) => {
      const on = i === state.heroIndex;
      dot.classList.toggle('on', on);
      dot.setAttribute('aria-current', on ? 'true' : 'false');
      if (MOTION) A.animate(dot, { width: on ? 32 : 6, opacity: on ? 1 : 0.45, duration: 450, ease: 'outExpo' });
    });
  }

  function renderHero(index, dir) {
    const games = state.heroGames;
    const body = $('#hero-body');
    if (!games.length) return;
    state.heroIndex = (index + games.length) % games.length;
    const paint = () => {
      body.innerHTML = heroHTML(games[state.heroIndex], state.heroIndex);
      renderDots();
      animateHero(body);
    };
    const current = $$('.hero-left, .hero-right', body);
    if (!MOTION || !current.length || $('.sk', body)) { paint(); return; }
    A.animate(current, { opacity: [1, 0], translateX: [0, -28 * dir], duration: 240, ease: 'inQuad', onComplete: paint });
  }

  let heroTimer = null;
  function startHeroTimer() {
    clearInterval(heroTimer);
    if (state.heroGames.length < 2) return;
    heroTimer = setInterval(() => {
      if (document.hidden || state.heroHover || state.chatOpen || !$('#modal').hidden) return;
      renderHero(state.heroIndex + 1, 1);
    }, 9000);
  }

  // ---------------------------------------------------------------- stats strip

  function renderStats(league) {
    const ctx = league.context.rows[0] || {};
    const home = league.home_edge.rows[0] || {};
    const odds = league.odds.rows[0] || {};
    logQuery('context', { took: league.context.took_ms, query: league.context.query });
    logQuery('home_edge', { took: league.home_edge.took_ms, query: league.home_edge.query, meta: `Home teams win ${pct(home.avg_home_win_pct || 0, 1)}, road teams ${pct(home.avg_away_win_pct || 0, 1)}` });
    logQuery('tiers', { took: league.tiers.took_ms, query: league.tiers.query, meta: league.tiers.rows.map((r) => `${r.tier.replace(/^\d\.\s*/, '')}: ${r.teams}`).join(' · ') });
    logQuery('odds', { took: league.odds.took_ms, query: league.odds.query, meta: odds.latest_fetch ? `Odds last pulled ${new Date(odds.latest_fetch).toLocaleString()}` : '' });

    const best = [...state.teams.values()].sort((a, b) => b.net_rating - a.net_rating)[0];
    const flagged = state.games.filter((g) => g.flagged).length;
    const tiles = [
      { label: 'Games priced', value: odds.games, fmt: int, note: `${odds.prices} prices from ${odds.books} books` },
      { label: 'Gaps of 8+ pts', value: flagged, fmt: int, note: `out of ${state.games.length} games` },
      { label: 'Home teams won', value: (home.avg_home_win_pct || 0) * 100, fmt: (v) => `${v.toFixed(1)}%`, note: `road teams ${pct(home.avg_away_win_pct || 0, 1)}` },
      { label: 'Best net rating', value: ctx.best_net_rating, fmt: (v) => signed(v), note: best ? best.team : 'across 30 teams' },
      { label: 'League avg net rating', value: ctx.avg_net_rating, fmt: (v) => signed(v, 2), note: 'zero-sum, should be 0.00' },
    ];
    const strip = $('#stats');
    strip.innerHTML = tiles.map((t) => `
      <div class="tile card">
        <span class="tile-label">${esc(t.label)}</span>
        <strong>${esc(t.fmt(t.value ?? 0))}</strong>
        <span class="tile-note" title="${esc(t.note)}">${esc(t.note)}</span>
      </div>`).join('');
    const tileEls = $$('.tile', strip);
    reveal(tileEls, { step: 70, y: 16 });
    tileEls.forEach((el, i) => countUp($('strong', el), tiles[i].value ?? 0, tiles[i].fmt, { duration: 1400, delay: 150 + i * 70 }));
  }

  // ---------------------------------------------------------------- rankings

  function renderTeams(data) {
    data.teams.forEach((t) => state.teams.set(t.team, t));
    logQuery('teams', { took: data.took_ms, query: data.query, meta: `${data.teams.length} teams` });
    const maxNet = Math.max(1, ...data.teams.map((t) => Math.abs(t.net_rating)));
    const body = $('#rankings-body');
    body.innerHTML = data.teams.map((t, i) => {
      const width = (Math.abs(t.net_rating) / maxNet) * 50;
      const squares = Array.from({ length: 10 }, (_, k) => `<i class="${k < t.last_10_wins ? 'w' : ''}"></i>`).join('');
      return `
        <tr>
          <td class="rank">${i + 1}</td>
          <td><div class="team-cell"><i style="--c:${colorOf(t.team_abbreviation)}"></i><b>${esc(t.team)}</b><span>${esc(t.team_abbreviation)}</span></div></td>
          <td class="num">${t.wins}-${t.losses}</td>
          <td><span class="net"><span class="net-bar ${t.net_rating >= 0 ? 'pos' : 'neg'}" style="width:${width.toFixed(1)}%"></span></span><span class="net-val">${signed(t.net_rating)}</span></td>
          <td><span class="l10" title="${t.last_10_wins}-${t.last_10_losses} over the last 10">${squares}</span></td>
          <td class="num score">${t.raw_score.toFixed(1)}</td>
        </tr>`;
    }).join('');

    const rows = $$('tr', body);
    const bars = $$('.net-bar', body);
    const wins = $$('.l10 i.w', body);
    if (MOTION) {
      hide(rows);
      bars.forEach((b) => { b.style.transform = 'scaleX(0)'; });
      wins.forEach((w) => { w.style.transform = 'scale(0)'; });
    }
    whenVisible($('#rankings'), () => {
      reveal(rows, { step: 26, y: 10 });
      if (!MOTION) return;
      A.animate(bars, { scaleX: [0, 1], duration: 900, ease: 'outExpo', delay: A.stagger(26, { start: 150 }) });
      A.animate(wins, { scale: [0, 1], duration: 450, ease: 'outBack', delay: A.stagger(5, { start: 250 }) });
    });
  }

  // ---------------------------------------------------------------- play-style search

  const STYLE_SUGGESTIONS = [
    'lockdown defense on a hot streak',
    'explosive offense but leaky defense',
    'struggling badly and losing at home',
    'finished the season in a slump',
  ];

  async function runStyleSearch(query) {
    const q = query.trim();
    if (q.length < 3) return;
    $('#style-q').value = q;
    const out = $('#style-results');
    out.classList.add('is-loading');
    out.setAttribute('aria-busy', 'true');
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
      logQuery('search', { took: data.took_ms, query: data.query, meta: `?description = "${q}"` });
      const scores = data.results.map((r) => r._score);
      const max = Math.max(...scores);
      const min = Math.min(...scores);
      const scale = (s) => (max === min ? 100 : 25 + (75 * (s - min)) / (max - min));
      $('#style-meta').textContent = data.results.length ? `${data.results.length} teams · ${data.took_ms} ms · ranked by _score` : '';
      out.innerHTML = data.results.length
        ? data.results.map((r, i) => `
          <article class="sres card">
            <span class="sres-rank">${i + 1}</span>
            <div class="sres-main">
              <div class="sres-top"><b>${esc(r.team)}</b><span>${esc(r.team_abbreviation)} · ${r.wins}-${r.losses} · net ${signed(r.net_rating)}</span></div>
              <p>${esc(r.narrative)}</p>
            </div>
            <div class="rel" title="_score ${r._score}">
              <span class="rel-track"><span class="rel-bar" style="width:${scale(r._score).toFixed(1)}%"></span></span>
              <span>${r._score.toFixed(2)}</span>
            </div>
          </article>`).join('')
        : emptyHTML('No matches', 'Try describing form, defense or scoring.');
      const cards = $$('.sres', out);
      reveal(cards, { step: 55, y: 14 });
      if (MOTION) {
        const bars = $$('.rel-bar', out);
        bars.forEach((b) => { b.style.transform = 'scaleX(0)'; });
        A.animate(bars, { scaleX: [0, 1], duration: 1000, ease: 'outExpo', delay: A.stagger(55, { start: 150 }) });
      }
    } catch (err) {
      out.innerHTML = errorHTML(err);
    } finally {
      out.classList.remove('is-loading');
      out.removeAttribute('aria-busy');
    }
  }

  function initStyleSearch() {
    $('#style-chips').innerHTML = STYLE_SUGGESTIONS.map((s) => `<button class="chip-btn" type="button">${esc(s)}</button>`).join('');
    $('#style-chips').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip-btn');
      if (chip) runStyleSearch(chip.textContent);
    });
    $('#style-form').addEventListener('submit', (e) => {
      e.preventDefault();
      runStyleSearch($('#style-q').value);
    });
  }

  function initNavSearch() {
    const input = $('#search');
    const box = $('#search-results');
    let timer = null;
    let seq = 0;

    const close = () => { box.hidden = true; };
    const goStyle = (q) => {
      close();
      input.blur();
      $('#style').scrollIntoView({ behavior: MOTION ? 'smooth' : 'auto' });
      runStyleSearch(q);
    };

    document.addEventListener('keydown', (e) => {
      const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
      if (e.key === '/' && !typing) { e.preventDefault(); input.focus(); }
      if (e.key === 'Escape') {
        if (!box.hidden) close();
        else if (!$('#modal').hidden) closeModal();
        else if (state.chatOpen) closeChat();
      }
    });

    input.addEventListener('input', () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 3) { close(); return; }
      timer = setTimeout(async () => {
        const mine = ++seq;
        box.hidden = false;
        box.innerHTML = '<div class="sr-empty">Searching team narratives…</div>';
        try {
          const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
          if (mine !== seq) return;
          logQuery('search', { took: data.took_ms, query: data.query, meta: `?description = "${q}"` });
          box.innerHTML = data.results.length
            ? data.results.slice(0, 5).map((r) => `
                <button class="sr-item" type="button" data-q="${esc(q)}">
                  <b>${esc(r.team)}</b><span>${esc(r.team_abbreviation)} · ${r.wins}-${r.losses}</span>
                  <p>${esc(r.narrative)}</p>
                </button>`).join('') + `<button class="sr-more" type="button" data-q="${esc(q)}">See every match</button>`
            : '<div class="sr-empty">No teams match that description.</div>';
          reveal($$('.sr-item', box), { step: 35, y: 8, duration: 450 });
        } catch (err) {
          box.innerHTML = `<div class="sr-empty">${esc(err.message)}</div>`;
        }
      }, 320);
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && input.value.trim().length >= 3) goStyle(input.value);
    });
    box.addEventListener('click', (e) => {
      const hit = e.target.closest('[data-q]');
      if (hit) goStyle(hit.dataset.q);
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.search')) close();
    });
  }

  // ---------------------------------------------------------------- tabs

  function initTabs() {
    const tabs = $$('#tabs a');
    const ink = $('#tab-ink');
    let current = tabs[0];

    const move = (tab, animated = true) => {
      current = tab;
      tabs.forEach((t) => t.classList.toggle('active', t === tab));
      const x = tab.offsetLeft;
      const w = tab.offsetWidth;
      if (MOTION && animated) A.animate(ink, { translateX: x, width: w, duration: 480, ease: 'outExpo' });
      else { ink.style.transform = `translateX(${x}px)`; ink.style.width = `${w}px`; }
    };

    move(tabs[0], false);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => move(current, false));
    window.addEventListener('resize', () => move(current, false));
    tabs.forEach((tab) => tab.addEventListener('click', () => move(tab)));

    const sections = tabs.map((t) => $(t.getAttribute('href')));
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const tab = tabs[sections.indexOf(entry.target)];
        if (tab && tab !== current) move(tab);
      });
    }, { rootMargin: '-35% 0px -60% 0px' });
    sections.forEach((s) => s && io.observe(s));
  }

  // ---------------------------------------------------------------- game modal

  function openGame(id) {
    const g = gameById(id);
    const m = state.model;
    if (!g || !m) return;

    const scoreRow = (t) => `
      <div class="math-row">
        <b>${esc(shortName(t))}</b>
        <code>${num(t.net_rating, 1)} × ${m.net_rating_weight} + ${t.last_10_win_pct.toFixed(2)} × ${m.recent_form_weight}${t.is_home ? ` + ${m.home_court_bonus} home` : ''} = <strong>${num(t.raw_score, 2)}</strong></code>
      </div>`;
    const avg = (key) => g.books.reduce((s, b) => s + b[key], 0) / g.books.length;
    const edge = g[g.edge];
    const narratives = [g.away, g.home]
      .map((t) => state.teams.get(t.team))
      .filter(Boolean)
      .map((t) => `<p><b>${esc(t.team)}:</b> ${esc(t.narrative)}</p>`)
      .join('');

    $('#modal-panel').innerHTML = `
      <header class="modal-head">
        <div>
          <div class="crumbs"><span>NBA</span><i></i><span>${esc(fmtDate(g.date))}</span><i></i><span>${g.books.length} book${g.books.length === 1 ? '' : 's'}</span></div>
          <h2 id="modal-title">${esc(shortName(g.away))} vs ${esc(shortName(g.home))}</h2>
        </div>
        <button class="icon-btn" type="button" data-close aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </header>
      <section>
        <h3>Step 1 · raw scores</h3>
        ${scoreRow(g.away)}${scoreRow(g.home)}
      </section>
      <section>
        <h3>Step 2 · scores to a probability</h3>
        <code class="math">P(${esc(g.home.abbr)}) = 1 / (1 + e^(−(${num(g.home.raw_score, 2)} − ${num(g.away.raw_score, 2)}) / ${m.logistic_scale})) = <strong>${pct(g.home.model, 1)}</strong></code>
      </section>
      <section>
        <h3>Step 3 · the books, vig removed</h3>
        <div class="table-wrap">
          <table class="books">
            <thead><tr><th>Book</th><th>${esc(g.away.abbr)} odds</th><th>${esc(g.home.abbr)} odds</th><th>${esc(g.away.abbr)}</th><th>${esc(g.home.abbr)}</th></tr></thead>
            <tbody>${g.books.map((b) => `<tr><td>${esc(bookName(b.bookmaker))}</td><td>${b.away_odds.toFixed(2)}</td><td>${b.home_odds.toFixed(2)}</td><td>${pct(b.away_market, 1)}</td><td>${pct(b.home_market, 1)}</td></tr>`).join('')}</tbody>
            <tfoot><tr><td>Average</td><td></td><td></td><td>${pct(avg('away_market'), 1)}</td><td>${pct(avg('home_market'), 1)}</td></tr></tfoot>
          </table>
        </div>
      </section>
      <section class="verdict ${g.flagged ? 'is-flagged' : ''}">
        <strong>${signed(g.gap * 100)} pts</strong>
        <p>The model has the ${esc(nickname(edge.team))} at ${pct(edge.model, 1)} against the books' ${pct(edge.market, 1)}. ${g.flagged ? `That clears the ${flagPts(m.threshold)} flag.` : `That's under the ${flagPts(m.threshold)} flag.`}</p>
      </section>
      ${narratives ? `<section class="narr"><h3>Team narratives (what semantic search reads)</h3>${narratives}</section>` : ''}
      <footer class="modal-foot">
        <button class="btn-primary" type="button" data-ask="${esc(g.game_id)}">Ask the analyst about this game</button>
      </footer>`;

    const modal = $('#modal');
    const scrim = $('#scrim');
    modal.hidden = false;
    scrim.hidden = false;
    document.body.style.overflow = 'hidden';
    if (MOTION) {
      A.animate(scrim, { opacity: [0, 1], duration: 260, ease: 'outQuad' });
      A.animate('#modal-panel', { opacity: [0, 1], scale: [0.96, 1], translateY: [14, 0], duration: 520, ease: 'outExpo' });
      const parts = $$('#modal-panel section, #modal-panel .modal-foot');
      reveal(parts, { step: 60, y: 10, start: 120, duration: 600 });
    }
    $('[data-close]', modal).focus();
  }

  function closeModal() {
    const modal = $('#modal');
    const scrim = $('#scrim');
    if (modal.hidden) return;
    const done = () => {
      modal.hidden = true;
      scrim.hidden = true;
      scrim.style.opacity = '';
      $('#modal-panel').style.transform = '';
      $('#modal-panel').style.opacity = '';
      document.body.style.overflow = '';
    };
    if (!MOTION) { done(); return; }
    A.animate('#modal-panel', { opacity: [1, 0], scale: [1, 0.97], duration: 200, ease: 'inQuad' });
    A.animate(scrim, { opacity: [1, 0], duration: 240, ease: 'inQuad', onComplete: done });
  }

  // ---------------------------------------------------------------- chat

  const CHAT_SUGGESTIONS = [
    'Which games have the biggest gap between the market and the stats model?',
    'Which teams are playing lockdown defense on a hot streak?',
    'How does your model turn team stats into a win probability?',
  ];

  function inline(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
      .replace(/(^|[\s(])_([^_\s][^_]*?)_(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
  }

  function markdown(src) {
    const out = [];
    let list = null;
    let code = null;
    let table = [];
    const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.join('')}</${list.tag}>`); list = null; } };
    const flushTable = () => {
      if (!table.length) return;
      const rows = table
        .filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r))
        .map((r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim())));
      const [head, ...body] = rows;
      out.push(`<table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      table = [];
    };
    for (const line of esc(src).split(/\r?\n/)) {
      if (/^\s*```/.test(line)) {
        if (code) { out.push(`<pre><code>${code.join('\n')}</code></pre>`); code = null; }
        else { flushList(); flushTable(); code = []; }
        continue;
      }
      if (code) { code.push(line); continue; }
      if (/^\s*\|.*\|\s*$/.test(line)) { flushList(); table.push(line); continue; }
      flushTable();
      const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (bullet || numbered) {
        const tag = bullet ? 'ul' : 'ol';
        if (!list || list.tag !== tag) { flushList(); list = { tag, items: [] }; }
        list.items.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        continue;
      }
      flushList();
      const heading = line.match(/^\s*#{1,6}\s+(.*)$/);
      if (heading) { out.push(`<h4>${inline(heading[1])}</h4>`); continue; }
      if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    if (code) out.push(`<pre><code>${code.join('\n')}</code></pre>`);
    flushList();
    flushTable();
    return out.join('');
  }

  function scrollChat() {
    const log = $('#chat-log');
    log.scrollTop = log.scrollHeight;
  }

  function appendMessage(html) {
    const log = $('#chat-log');
    log.insertAdjacentHTML('beforeend', html);
    const el = log.lastElementChild;
    if (MOTION) A.animate(el, { opacity: [0, 1], translateY: [12, 0], duration: 450, ease: 'outExpo' });
    scrollChat();
    return el;
  }

  function autosize(el) {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }

  function renderSuggestions() {
    const box = $('#chat-suggestions');
    box.innerHTML = CHAT_SUGGESTIONS.map((s) => `<button class="suggest" type="button">${esc(s)}</button>`).join('');
    box.hidden = false;
  }

  function toolHTML(call) {
    return `
      <details class="tool running" data-call="${esc(call.call_id || '')}">
        <summary><span class="tool-id">${esc(call.tool_id)}</span><span class="tool-meta">running</span></summary>
        <div class="tool-body">
          <span class="kv">params</span><pre>${esc(JSON.stringify(call.params || {}, null, 2))}</pre>
          <div class="tool-result"></div>
        </div>
      </details>`;
  }

  // One live agent bubble. Kibana events arrive through /api/chat/stream and
  // each handler below updates this bubble in place.
  function startAgentBubble() {
    const el = appendMessage(`
      <div class="msg msg-agent">
        <div class="trace" hidden><span class="trace-label">Tools</span></div>
        <div class="thinking">
          <span class="typing"><i></i><i></i><i></i></span>
          <span class="thinking-text">Sent to Agent Builder</span>
          <b class="elapsed">0s</b>
        </div>
        <div class="md"></div>
      </div>`);
    const started = performance.now();
    const trace = $('.trace', el);
    const thinking = $('.thinking', el);
    const md = $('.md', el);
    const elapsed = $('.elapsed', el);
    let text = '';
    let calls = 0;
    let frame = 0;

    const tick = setInterval(() => { elapsed.textContent = `${Math.round((performance.now() - started) / 1000)}s`; }, 500);
    const dots = MOTION ? A.animate($$('.typing i', el), { translateY: [0, -5, 0], opacity: [0.35, 1, 0.35], duration: 900, delay: A.stagger(140), loop: true, ease: 'inOutSine' }) : null;

    const stop = () => {
      clearInterval(tick);
      if (dots) dots.pause();
      thinking.remove();
    };

    return {
      reasoning({ text: step }) {
        const label = $('.thinking-text', el);
        if (!label) return;
        label.textContent = step;
        if (MOTION) A.animate(label, { opacity: [0.3, 1], translateX: [6, 0], duration: 400, ease: 'outQuad' });
      },
      toolCall(call) {
        calls += 1;
        trace.hidden = false;
        $('.trace-label', trace).textContent = `${calls} tool call${calls === 1 ? '' : 's'}`;
        trace.insertAdjacentHTML('beforeend', toolHTML(call));
        const item = trace.lastElementChild;
        if (MOTION) A.animate(item, { opacity: [0, 1], scale: [0.92, 1], duration: 500, ease: 'outBack' });
        const label = $('.thinking-text', el);
        if (label) label.textContent = `Running ${call.tool_id}`;
        scrollChat();
      },
      toolResult(result) {
        const item = $$('.tool.running', trace).find((t) => t.dataset.call === (result.call_id || '')) || $$('.tool.running', trace).pop();
        if (!item) return;
        item.classList.remove('running');
        $('.tool-meta', item).textContent = result.rows != null ? `${result.rows} row${result.rows === 1 ? '' : 's'}` : 'done';
        $('.tool-result', item).innerHTML = `
          ${result.query ? `<span class="kv">ES|QL</span><pre class="code">${highlight(result.query)}</pre>` : ''}
          <span class="kv">result</span><pre>${esc(result.preview)}</pre>`;
        if (MOTION) A.animate($('.tool-meta', item), { opacity: [0, 1], translateX: [8, 0], duration: 400, ease: 'outQuad' });
        const label = $('.thinking-text', el);
        if (label) label.textContent = 'Reading the results';
      },
      chunk({ text: piece }) {
        text += piece;
        if (thinking.isConnected) { stop(); }
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => { md.innerHTML = markdown(text); scrollChat(); });
      },
      done(final) {
        stop();
        cancelAnimationFrame(frame);
        md.innerHTML = markdown(final.message || text || '_No answer text came back._');
        const secs = (final.took_ms / 1000).toFixed(1);
        if (calls) $('.trace-label', trace).textContent = `${calls} tool call${calls === 1 ? '' : 's'} · ${secs}s`;
        scrollChat();
        return calls;
      },
      fail(detail) {
        stop();
        el.classList.remove('msg-agent');
        el.classList.add('msg-error');
        md.innerHTML = `<b>The analyst didn't answer.</b><p>${esc(detail)}</p>`;
        scrollChat();
      },
    };
  }

  async function streamChat(message, bubble) {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: state.conversationId }),
    });
    if (!res.ok || !res.body) {
      let detail = `${res.status} ${res.statusText}`;
      try { detail = (await res.json()).detail || detail; } catch { /* keep status text */ }
      throw new Error(detail);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let final = null;
    const handle = (event, data) => {
      if (event === 'reasoning') bubble.reasoning(data);
      else if (event === 'tool_call') bubble.toolCall(data);
      else if (event === 'tool_result') bubble.toolResult(data);
      else if (event === 'chunk') bubble.chunk(data);
      else if (event === 'conversation') state.conversationId = data.conversation_id || state.conversationId;
      else if (event === 'error') throw new Error(data.detail);
      else if (event === 'done') final = data;
    };

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let event = 'message';
        const data = [];
        block.split('\n').forEach((line) => {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) data.push(line.slice(5).trim());
        });
        if (!data.length) continue;
        let payload;
        try { payload = JSON.parse(data.join('\n')); } catch { continue; }
        handle(event, payload);
      }
    }
    if (!final) throw new Error('The stream closed before the agent finished.');
    return final;
  }

  async function send(text) {
    const message = text.trim();
    if (!message || state.busy) return;
    state.busy = true;
    const input = $('#chat-input');
    const sendBtn = $('#chat-send');
    input.value = '';
    autosize(input);
    sendBtn.disabled = true;
    $('#chat-suggestions').hidden = true;

    appendMessage(`<div class="msg msg-user"><p>${esc(message)}</p></div>`);
    const bubble = startAgentBubble();
    try {
      const final = await streamChat(message, bubble);
      state.conversationId = final.conversation_id || state.conversationId;
      const calls = bubble.done(final);
      const usage = final.model ? ` · ${final.model}` : '';
      logQuery('chat', {
        took: final.took_ms,
        query: `POST /api/agent_builder/converse/async\n${JSON.stringify({ agent_id: final.agent_id, conversation_id: final.conversation_id, input: message }, null, 2)}`,
        meta: `${calls} tool call${calls === 1 ? '' : 's'}${usage}`,
      });
    } catch (err) {
      bubble.fail(err.message);
    } finally {
      state.busy = false;
      sendBtn.disabled = false;
      if (state.chatOpen) input.focus();
    }
  }

  function openChat(prompt) {
    const panel = $('#chat');
    if (!state.chatOpen) {
      state.chatOpen = true;
      if (MOTION) panel.style.transform = 'translateX(100%)';
      panel.classList.add('open');
      panel.setAttribute('aria-hidden', 'false');
      if (MOTION) A.animate(panel, { translateX: ['100%', '0%'], duration: 560, ease: 'outExpo' });
    }
    if (prompt) send(prompt);
    else setTimeout(() => $('#chat-input').focus(), 150);
  }

  function closeChat() {
    if (!state.chatOpen) return;
    state.chatOpen = false;
    const panel = $('#chat');
    const done = () => {
      panel.classList.remove('open');
      panel.style.transform = '';
      panel.setAttribute('aria-hidden', 'true');
    };
    if (MOTION) A.animate(panel, { translateX: ['0%', '100%'], duration: 360, ease: 'inQuart', onComplete: done });
    else done();
  }

  function resetChat() {
    if (state.busy) return;
    state.conversationId = null;
    const log = $('#chat-log');
    $$('.msg:not(.intro)', log).forEach((m) => m.remove());
    renderSuggestions();
    reveal($$('.suggest'), { step: 60, y: 8 });
  }

  function askPrompt(g) {
    return `Is there a value mismatch in ${g.away.team} at ${g.home.team} on ${fmtDay(g.date)}? Show the math.`;
  }

  function initChat() {
    renderSuggestions();
    $('#open-chat').addEventListener('click', () => openChat());
    $('#chat-close').addEventListener('click', closeChat);
    $('#chat-new').addEventListener('click', resetChat);
    $('#chat-suggestions').addEventListener('click', (e) => {
      const btn = e.target.closest('.suggest');
      if (btn) send(btn.textContent);
    });
    const input = $('#chat-input');
    $('#chat-form').addEventListener('submit', (e) => { e.preventDefault(); send(input.value); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); }
    });
    input.addEventListener('input', () => autosize(input));
  }

  // ---------------------------------------------------------------- page wiring

  function initInteractions() {
    document.addEventListener('click', (e) => {
      const ask = e.target.closest('[data-ask]');
      if (ask) {
        const g = gameById(ask.dataset.ask);
        closeModal();
        if (g) openChat(askPrompt(g));
        return;
      }
      if (e.target.closest('[data-close]') || e.target.id === 'scrim' || e.target.id === 'modal') { closeModal(); return; }
      const open = e.target.closest('[data-open]');
      if (open) { openGame(open.dataset.open); return; }
      const card = e.target.closest('.market[data-game]');
      if (card) openGame(card.dataset.game);
    });
    document.addEventListener('keydown', (e) => {
      const card = e.target.closest && e.target.closest('.market[data-game]');
      if (card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openGame(card.dataset.game); }
    });

    $('#hero-prev').addEventListener('click', () => renderHero(state.heroIndex - 1, -1));
    $('#hero-next').addEventListener('click', () => renderHero(state.heroIndex + 1, 1));
    $('#hero-dots').addEventListener('click', (e) => {
      const dot = e.target.closest('.hdot');
      if (!dot) return;
      const i = Number(dot.dataset.i);
      if (i !== state.heroIndex) renderHero(i, i > state.heroIndex ? 1 : -1);
    });
    const hero = $('#hero');
    hero.addEventListener('mouseenter', () => { state.heroHover = true; });
    hero.addEventListener('mouseleave', () => { state.heroHover = false; });

    $('#sort').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-sort]');
      if (!btn || btn.dataset.sort === state.sort) return;
      state.sort = btn.dataset.sort;
      $$('#sort button').forEach((b) => b.classList.toggle('on', b === btn));
      renderAllGrid(true);
    });
    $('#flag-toggle').addEventListener('click', (e) => {
      state.onlyFlagged = !state.onlyFlagged;
      e.currentTarget.setAttribute('aria-pressed', String(state.onlyFlagged));
      renderAllGrid(true);
    });
  }

  function introNav() {
    if (!MOTION) return;
    const parts = $$('.brand, .search, .nav-actions > *, #tabs a');
    reveal(parts, { step: 45, y: -10, duration: 650 });
  }

  async function boot() {
    initTabs();
    initNavSearch();
    initStyleSearch();
    initChat();
    initInteractions();
    introNav();
    loadHealth();

    const teams = api('/api/teams').then(renderTeams).catch((err) => { $('#rankings-body').innerHTML = `<tr><td colspan="6">${errorHTML(err)}</td></tr>`; });
    const markets = api('/api/markets').then(renderMarkets).catch((err) => {
      $('#hero-body').innerHTML = errorHTML(err);
      $('#gap-grid').innerHTML = errorHTML(err);
      $('#all-count').textContent = 'Odds failed to load';
    });
    const league = api('/api/league');

    const [leagueResult] = await Promise.allSettled([league, teams, markets]);
    if (leagueResult.status === 'fulfilled') renderStats(leagueResult.value);
    else $('#stats').innerHTML = errorHTML(leagueResult.reason);

    runStyleSearch(STYLE_SUGGESTIONS[0]);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
