// UCL Edge model v2 (ESPN public feeds, no API key). Runs in a browser tab.
//
//   const M = await UCLM.build({today:'2026-10-21'});   // fetch, fit, backtest, predict
//
// Method
// 1. Domestic ratings: for every league ESPN carries box scores for, fit
//    multiplicative attack/defence ratings per stat (goals, shots, SOT,
//    corners, fouls, cards) with opponent adjustment, time decay
//    (half-life 150 days) and a 5-game prior toward league average.
// 2. Style vs strength: a team's domestic strength z = mean of its goal and
//    SOT log-ratios. Each stat rating is split into the part explained by
//    strength (pooled slope across leagues) and a style residual
//    (e.g. "Villa takes more corners than a team of its strength").
// 3. Cross-league strength comes from the market, not from domestic
//    ratings: the bookmaker 1X2 + total is converted to expected goals
//    (lambda_home, lambda_away). Supremacy S = ln(lh/la), tempo T = ln(lh+la).
// 4. UCL layer, fitted on UCL games since Aug 2025 with ESPN/DraftKings odds:
//      ln E[stat_home] = a_home + g*S + t*T + rho*(style_att_home + style_def_away)
//      ln E[stat_away] = a_away - g*S + t*T + rho*(style_att_away + style_def_home)
//    Poisson regression per stat; negative-binomial dispersion from residuals.
//    Offsides have no domestic feed, so they use the market terms only.
// 5. Backtest: fit on games before 2026-07-01, score the 2026-27 league phase.
(function (root) {
  'use strict';
  const BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/';
  const DOMESTIC = ['eng.1', 'esp.1', 'ita.1', 'ger.1', 'fra.1', 'por.1', 'ned.1', 'bel.1', 'tur.1', 'aut.1', 'nor.1', 'sco.1', 'gre.1', 'den.1', 'swe.1'];
  const DSTATS = ['Goals', 'Shots', 'Shots on Target', 'Corners', 'Fouls', 'Cards'];
  const USTATS = ['Shots', 'Shots on Target', 'Corners', 'Fouls', 'Cards', 'Offsides'];
  const SBKEY = { Shots: 'totalShots', 'Shots on Target': 'shotsOnTarget', Corners: 'wonCorners', Fouls: 'foulsCommitted' };
  const DAY = 864e5, HALF_LIFE = 150, WINDOW = 400, K_PRIOR = 5;
  const TRAIN_FROM = Date.parse('2025-08-01'), TEST_FROM = Date.parse('2026-07-01');

  async function getJSON(u) {
    for (let i = 0; i < 3; i++) {
      try { const r = await fetch(u); if (r.ok) return await r.json(); } catch (e) { /* retry */ }
      await new Promise(r => setTimeout(r, 400 * (i + 1)));
    }
    throw new Error('fetch failed ' + u);
  }
  async function pool(items, n, fn) {
    const out = new Array(items.length); let i = 0;
    await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) { const k = i++; try { out[k] = await fn(items[k]); } catch (e) { out[k] = null; } } }));
    return out;
  }

  // ---------- rows ----------
  function domesticRow(e, league) {
    const c = e.competitions && e.competitions[0];
    if (!c || !e.status || !e.status.type || !e.status.type.completed) return null;
    const S = {};
    for (const x of c.competitors) {
      const sm = {}; for (const s of x.statistics || []) sm[s.name] = +s.displayValue;
      const o = { id: String(x.team.id), name: x.team.displayName, Goals: +x.score, Cards: 0 };
      for (const [k, v] of Object.entries(SBKEY)) o[k] = Number.isFinite(sm[v]) ? sm[v] : null;
      S[x.homeAway] = o;
    }
    if (!S.home || !S.away) return null;
    let cardEvents = 0;
    for (const d of c.details || []) {
      const t = (d.type && d.type.text) || '';
      if (!/yellow card|red card/i.test(t)) continue;
      cardEvents++;
      const id = d.team && String(d.team.id);
      if (id === S.home.id) S.home.Cards++; else if (id === S.away.id) S.away.Cards++;
    }
    const has = S.home.Shots != null && S.away.Shots != null && S.home.Shots + S.away.Shots > 0;
    return { id: e.id, league, t: Date.parse(e.date), h: S.home, a: S.away, has, cardEvents };
  }

  const amToProb = m => (m == null || !isFinite(m) || m === 0) ? null : (m > 0 ? 100 / (m + 100) : -m / (-m + 100));
  function marketFromPick(pc) {
    if (!pc || !pc.homeTeamOdds || !pc.awayTeamOdds || !pc.drawOdds) return null;
    const raw = [amToProb(+pc.homeTeamOdds.moneyLine), amToProb(+pc.drawOdds.moneyLine), amToProb(+pc.awayTeamOdds.moneyLine)];
    if (raw.some(x => x == null)) return null;
    const s = raw[0] + raw[1] + raw[2];
    const m = { H: raw[0] / s, D: raw[1] / s, A: raw[2] / s, overround: s, provider: pc.provider && pc.provider.name, ml: [+pc.homeTeamOdds.moneyLine, +pc.drawOdds.moneyLine, +pc.awayTeamOdds.moneyLine] };
    const line = +pc.overUnder, po = amToProb(+pc.overOdds), pu = amToProb(+pc.underOdds);
    if (isFinite(line) && line % 1 === 0.5 && po && pu) { m.line = line; m.pOver = po / (po + pu); m.ouOdds = [+pc.overOdds, +pc.underOdds]; }
    return m;
  }

  function uclRow(e, sum) {
    const c = e.competitions[0], S = {};
    for (const x of c.competitors) S[x.homeAway] = { id: String(x.team.id), name: x.team.displayName, Goals: +x.score };
    for (const t of (sum && sum.boxscore && sum.boxscore.teams) || []) {
      const id = String(t.team.id), side = id === S.home.id ? 'home' : id === S.away.id ? 'away' : null;
      if (!side) continue;
      const sm = {}; for (const s of t.statistics || []) sm[s.name] = +s.displayValue;
      Object.assign(S[side], { Shots: sm.totalShots, 'Shots on Target': sm.shotsOnTarget, Corners: sm.wonCorners, Fouls: sm.foulsCommitted, Cards: (sm.yellowCards || 0) + (sm.redCards || 0), Offsides: sm.offsides });
    }
    const st = (e.status.type.name || '') + ' ' + (e.status.type.shortDetail || '');
    return { id: e.id, t: Date.parse(e.date), date: e.date, h: S.home, a: S.away, mkt: marketFromPick(((sum && sum.pickcenter) || [])[0]), extra: /AET|PEN|EXTRA|ET/i.test(st) && !/FULL_TIME/.test(st) };
  }

  // ---------- goals from market ----------
  function pois(l, n) { const p = [Math.exp(-l)]; for (let k = 1; k <= n; k++) p.push(p[k - 1] * l / k); return p; }
  function outcome(lh, la, line) {
    const ph = pois(lh, 14), pa = pois(la, 14); let H = 0, D = 0, A = 0, O = 0;
    for (let i = 0; i < ph.length; i++) for (let j = 0; j < pa.length; j++) {
      const p = ph[i] * pa[j];
      if (i > j) H += p; else if (i === j) D += p; else A += p;
      if (line != null && i + j > line) O += p;
    }
    return { H, D, A, O };
  }
  function solveLambda(m) {
    const line = m.line != null ? m.line : null, pOver = m.pOver != null ? m.pOver : null;
    const loss = (lh, la) => { const o = outcome(lh, la, line); let L = (o.H - m.H) ** 2 + (o.D - m.D) ** 2 + (o.A - m.A) ** 2; if (pOver != null) L += (o.O - pOver) ** 2; return L; };
    let best = null;
    for (let i = 3; i <= 90; i++) for (let j = 3; j <= 90; j++) { const lh = i * 0.05, la = j * 0.05, L = loss(lh, la); if (!best || L < best.L) best = { lh, la, L }; }
    for (const step of [0.01, 0.002]) {
      const b = { ...best };
      for (let i = -6; i <= 6; i++) for (let j = -6; j <= 6; j++) { const lh = b.lh + i * step, la = b.la + j * step; if (lh <= 0.05 || la <= 0.05) continue; const L = loss(lh, la); if (L < best.L) best = { lh, la, L }; }
    }
    return { lh: best.lh, la: best.la, fitErr: Math.sqrt(best.L / 4) };
  }

  // ---------- domestic ratings ----------
  function fitLeague(rows, T) {
    const R = rows.filter(r => r.has && r.t < T && r.t > T - WINDOW * DAY);
    if (R.length < 60) return null;
    const W = R.map(r => Math.pow(0.5, (T - r.t) / DAY / HALF_LIFE));
    const teams = [...new Set(R.flatMap(r => [r.h.id, r.a.id]))];
    const fit = { n: {}, names: {}, stats: {}, z: {}, nRows: R.length };
    R.forEach((r, k) => { for (const x of [r.h, r.a]) { fit.n[x.id] = (fit.n[x.id] || 0) + W[k]; fit.names[x.id] = x.name; } });
    const cardsOk = R.filter(r => r.cardEvents > 0).length / R.length > 0.6;
    for (const s of DSTATS) {
      if (s === 'Cards' && !cardsOk) continue;
      let sw = 0, sh = 0, sa = 0;
      R.forEach((r, k) => { sw += W[k]; sh += W[k] * r.h[s]; sa += W[k] * r.a[s]; });
      const mu = { home: sh / sw, away: sa / sw }, m = (mu.home + mu.away) / 2;
      const att = {}, def = {}; teams.forEach(t => { att[t] = 1; def[t] = 1; });
      for (let it = 0; it < 10; it++) {
        const na = {}, da = {}, nd = {}, dd = {};
        teams.forEach(t => { na[t] = da[t] = nd[t] = dd[t] = K_PRIOR * m; });
        R.forEach((r, k) => {
          const w = W[k], h = r.h.id, a = r.a.id;
          na[h] += w * r.h[s]; da[h] += w * mu.home * def[a];
          na[a] += w * r.a[s]; da[a] += w * mu.away * def[h];
          nd[h] += w * r.a[s]; dd[h] += w * mu.away * att[a];
          nd[a] += w * r.h[s]; dd[a] += w * mu.home * att[h];
        });
        teams.forEach(t => { att[t] = na[t] / da[t]; def[t] = nd[t] / dd[t]; });
        const ga = Math.exp(teams.reduce((x, t) => x + Math.log(att[t]), 0) / teams.length);
        const gd = Math.exp(teams.reduce((x, t) => x + Math.log(def[t]), 0) / teams.length);
        teams.forEach(t => { att[t] /= ga; def[t] /= gd; });
      }
      fit.stats[s] = { mu, att, def };
    }
    const G = fit.stats.Goals, O = fit.stats['Shots on Target'];
    teams.forEach(t => { fit.z[t] = 0.5 * ((Math.log(G.att[t]) - Math.log(G.def[t])) + (Math.log(O.att[t]) - Math.log(O.def[t]))); });
    return fit;
  }

  function styleSlopes(fits) {
    const out = {};
    for (const s of DSTATS) for (const side of ['att', 'def']) {
      let sxy = 0, sxx = 0;
      for (const f of fits) {
        if (!f || !f.stats[s]) continue;
        for (const t of Object.keys(f.z)) { const w = Math.min(f.n[t], 20), x = f.z[t]; sxy += w * x * Math.log(f.stats[s][side][t]); sxx += w * x * x; }
      }
      out[s + '|' + side] = sxx > 0 ? sxy / sxx : 0;
    }
    return out;
  }

  function style(fit, slopes, id, s) {
    if (!fit || !fit.stats[s] || fit.z[id] == null || (fit.n[id] || 0) < 3) return { att: 0, def: 0, ok: false };
    const z = fit.z[id];
    return { att: Math.log(fit.stats[s].att[id]) - slopes[s + '|att'] * z, def: Math.log(fit.stats[s].def[id]) - slopes[s + '|def'] * z, ok: true };
  }

  // ---------- Poisson regression + NB dispersion ----------
  function solve(A, b) {
    const n = b.length, M = A.map((r, i) => [...r, b[i]]);
    for (let i = 0; i < n; i++) {
      let p = i; for (let k = i + 1; k < n; k++) if (Math.abs(M[k][i]) > Math.abs(M[p][i])) p = k;
      [M[i], M[p]] = [M[p], M[i]];
      for (let k = i + 1; k < n; k++) { const f = M[k][i] / M[i][i]; for (let j = i; j <= n; j++) M[k][j] -= f * M[i][j]; }
    }
    const x = new Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) { let s = M[i][n]; for (let j = i + 1; j < n; j++) s -= M[i][j] * x[j]; x[i] = s / M[i][i]; }
    return x;
  }
  function poissonFit(X, y) {
    const p = X[0].length, ybar = y.reduce((a, b) => a + b, 0) / y.length;
    let b = new Array(p).fill(0); b[0] = b[1] = Math.log(Math.max(ybar, 0.1));
    for (let it = 0; it < 30; it++) {
      const A = Array.from({ length: p }, () => new Array(p).fill(0)), v = new Array(p).fill(0);
      for (let i = 0; i < y.length; i++) {
        const eta = X[i].reduce((s, x, j) => s + x * b[j], 0), mu = Math.exp(eta), z = eta + (y[i] - mu) / mu;
        for (let j = 0; j < p; j++) { v[j] += X[i][j] * mu * z; for (let k = 0; k < p; k++) A[j][k] += X[i][j] * mu * X[i][k]; }
      }
      for (let j = 0; j < p; j++) A[j][j] += 1e-6;
      const nb = solve(A, v), d = Math.max(...nb.map((x, j) => Math.abs(x - b[j])));
      b = nb; if (d < 1e-8) break;
    }
    return b;
  }
  const predict = (b, x) => Math.exp(x.reduce((s, v, j) => s + v * b[j], 0));
  function dispersion(mus, ys) {
    let num = 0, den = 0; mus.forEach((m, i) => { num += m * m; den += (ys[i] - m) ** 2 - m; });
    const r = num / den; return den > 0 && r < 400 ? r : null;
  }
  function lgamma(z) {
    const g = 7, c = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - lgamma(1 - z);
    z -= 1; let x = c[0]; for (let i = 1; i < g + 2; i++) x += c[i] / (z + i);
    const t = z + g + 0.5; return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
  }
  function nll(k, mu, r) {
    if (r == null) return mu - k * Math.log(mu) + lgamma(k + 1);
    const p = r / (r + mu);
    return -(lgamma(k + r) - lgamma(r) - lgamma(k + 1) + r * Math.log(p) + k * Math.log(1 - p));
  }

  // ---------- design ----------
  function features(s, lam, stH, stA, side, variant) {
    const S = Math.log(lam.lh / lam.la), T = Math.log(lam.lh + lam.la);
    const sgn = side === 'home' ? 1 : -1;
    const sty = side === 'home' ? stH.att + stA.def : stA.att + stH.def;
    const base = [side === 'home' ? 1 : 0, side === 'home' ? 0 : 1];
    if (variant === 0) return base;
    if (variant === 1 || s === 'Offsides') return [...base, sgn * S, T];
    return [...base, sgn * S, T, sty];
  }

  async function build(opts = {}) {
    const today = opts.today || new Date().toISOString().slice(0, 10);
    const log = opts.log || (() => {});
    const NOW = opts.asOf ? Date.parse(opts.asOf) : Date.now();
    // domestic
    const dom = {};
    await pool(DOMESTIC.flatMap(l => ['2025', '2026'].map(y => [l, y])), 6, async ([l, y]) => {
      const j = await getJSON(`${BASE}${l}/scoreboard?dates=${y}&limit=600`);
      const rows = (j.events || []).map(e => domesticRow(e, l)).filter(Boolean);
      (dom[l] = dom[l] || []).push(...rows);
    });
    const teamLeague = {};
    for (const [l, rows] of Object.entries(dom)) {
      const seen = {}; rows.sort((a, b) => a.t - b.t);
      for (const r of rows) for (const x of [r.h, r.a]) seen[x.id] = r.t;
      for (const [id, t] of Object.entries(seen)) if (!teamLeague[id] || teamLeague[id].t < t) teamLeague[id] = { league: l, t };
    }
    log('domestic rows ' + Object.values(dom).reduce((a, r) => a + r.length, 0));
    // UCL history
    const evs = [];
    for (const y of ['2025', '2026']) {
      const j = await getJSON(`${BASE}uefa.champions/scoreboard?dates=${y}&limit=600`);
      evs.push(...(j.events || []));
    }
    const done = evs.filter(e => e.status.type.completed && Date.parse(e.date) >= TRAIN_FROM && Date.parse(e.date) < NOW);
    const sums = await pool(done, 6, e => getJSON(`${BASE}uefa.champions/summary?event=${e.id}`));
    const ucl = done.map((e, i) => sums[i] ? uclRow(e, sums[i]) : null).filter(r => r && !r.extra && r.mkt && r.h.Shots != null && r.a.Shots != null);
    log('UCL rows with odds ' + ucl.length + ' of ' + done.length);
    // fixtures today
    const tj = await getJSON(`${BASE}uefa.champions/scoreboard?dates=${today.replace(/-/g, '')}`);
    const todayEv = (tj.events || []).filter(e => !e.status.type.completed);
    const tsums = await pool(todayEv, 6, e => getJSON(`${BASE}uefa.champions/summary?event=${e.id}`));

    // domestic fit cache
    const cache = {};
    const fitAt = (league, t) => { const d = Math.floor(t / DAY), k = league + '|' + d; if (!(k in cache)) cache[k] = fitLeague(dom[league] || [], d * DAY); return cache[k]; };
    const now = Date.parse(today + 'T00:00:00Z');
    const nowFits = DOMESTIC.map(l => fitAt(l, now));
    const slopes = styleSlopes(nowFits.filter(Boolean));
    const styleFor = (id, s, t) => { const tl = teamLeague[id]; if (!tl || s === 'Offsides') return { att: 0, def: 0, ok: false }; return style(fitAt(tl.league, t), slopes, id, s); };

    for (const r of ucl) { r.lam = solveLambda(r.mkt); }
    const fitStat = (rows, s, variant) => {
      const X = [], y = [];
      for (const r of rows) {
        if (r.h[s] == null || r.a[s] == null || !isFinite(r.h[s]) || !isFinite(r.a[s])) continue;
        const sh = styleFor(r.h.id, s, r.t), sa = styleFor(r.a.id, s, r.t);
        X.push(features(s, r.lam, sh, sa, 'home', variant)); y.push(r.h[s]);
        X.push(features(s, r.lam, sh, sa, 'away', variant)); y.push(r.a[s]);
      }
      return { X, y };
    };
    const coefs = {}, backtest = {};
    const train = ucl.filter(r => r.t < TEST_FROM), test = ucl.filter(r => r.t >= TEST_FROM);
    for (const s of USTATS) {
      backtest[s] = {};
      for (const v of [0, 1, 2]) {
        if (s === 'Offsides' && v === 2) continue;
        const tr = fitStat(train, s, v), te = fitStat(test, s, v);
        if (!tr.y.length || !te.y.length) continue;
        const b = poissonFit(tr.X, tr.y), mus = tr.X.map(x => predict(b, x)), r = dispersion(mus, tr.y);
        const pm = te.X.map(x => predict(b, x));
        backtest[s]['m' + v] = { nll: te.y.reduce((a, k, i) => a + nll(k, pm[i], r), 0) / te.y.length, bias: te.y.reduce((a, k) => a + k, 0) / pm.reduce((a, k) => a + k, 0), n: te.y.length / 2 };
      }
      const v = s === 'Offsides' ? 1 : 2, all = fitStat(ucl, s, v), b = poissonFit(all.X, all.y);
      coefs[s] = { b, r: dispersion(all.X.map(x => predict(b, x)), all.y), n: all.y.length / 2, variant: v };
    }
    // goals: market only; record calibration of market lambda on test set
    backtest.Goals = { mkt: test.reduce((a, r) => a + nll(r.h.Goals, r.lam.lh, null) + nll(r.a.Goals, r.lam.la, null), 0) / (2 * test.length), n: test.length };

    // predictions
    const fixtures = todayEv.map((e, i) => {
      const c = e.competitions[0], H = c.competitors.find(x => x.homeAway === 'home'), A = c.competitors.find(x => x.homeAway === 'away');
      const mkt = marketFromPick(((tsums[i] && tsums[i].pickcenter) || [])[0]);
      const hid = String(H.team.id), aid = String(A.team.id);
      const info = id => { const tl = teamLeague[id]; const f = tl && fitAt(tl.league, now); return { league: tl ? tl.league : null, games: f ? +(f.n[id] || 0).toFixed(1) : 0, z: f && f.z[id] != null ? +f.z[id].toFixed(3) : null }; };
      return { id: e.id, kickoff: e.date, home: H.team.displayName, away: A.team.displayName, homeId: hid, awayId: aid, homeAbbr: H.team.abbreviation, awayAbbr: A.team.abbreviation, venue: (c.venue || {}).fullName || '', dk: mkt, info: { home: info(hid), away: info(aid) },
        style: Object.fromEntries(USTATS.filter(s => s !== 'Offsides').map(s => { const a = styleFor(hid, s, now), b = styleFor(aid, s, now); return [s, { home: [+a.att.toFixed(3), +a.def.toFixed(3), a.ok], away: [+b.att.toFixed(3), +b.def.toFixed(3), b.ok] }]; })) };
    });
    return { meta: { built: new Date().toISOString(), today, version: 'ucl-edge-v2-espn', uclRows: ucl.length, train: train.length, test: test.length, domesticLeagues: DOMESTIC.filter(l => (dom[l] || []).length), halfLife: HALF_LIFE, kPrior: K_PRIOR }, coefs, slopes, backtest, fixtures };
  }

  // Means for one fixture given a market (lh, la). Used by the page and the builder.
  function means(model, fx, lam) {
    const out = { Goals: { home: lam.lh, away: lam.la, r: null } };
    for (const s of USTATS) {
      const c = model.coefs[s]; if (!c) continue;
      const st = fx.style[s] || { home: [0, 0], away: [0, 0] };
      const sh = { att: st.home[0], def: st.home[1] }, sa = { att: st.away[0], def: st.away[1] };
      out[s] = { home: predict(c.b, features(s, lam, sh, sa, 'home', c.variant)), away: predict(c.b, features(s, lam, sh, sa, 'away', c.variant)), r: c.r };
    }
    return out;
  }

  root.UCLM = { build, means, solveLambda, outcome, marketFromPick, fitLeague, nll };
})(typeof window !== 'undefined' ? window : globalThis);
