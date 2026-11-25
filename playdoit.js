// Playdoit (Altenar widget API) lines for Liga MX and UCL, shared by index.html, ucl.html and
// the Node build (ucl/build_node.js). The API is public and CORS-open; no login or key.
//   const evs = await PD.events('ucl');  const e = PD.match(evs, 'Lille', 'Bayern Munich', kickoffIso);
//   const P = PD.parse(await PD.details(e.id));   // lines, 1X2, 1UP, BTTS
(function (root) {
  'use strict';
  const B = 'https://sb2frontend-altenar2.biahosted.com/api/widget/';
  const Q = 'culture=es-ES&timezoneOffset=360&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX';
  const CHAMP = { ligamx: 10009, ucl: 16808 };
  const cache = {};

  async function get(path, ttl) {
    const c = cache[path];
    if (c && Date.now() - c.t < (ttl || 120000)) return c.v;
    const r = await fetch(B + path + (path.includes('?') ? '&' : '?') + Q);
    if (!r.ok) throw new Error('Playdoit ' + r.status);
    const v = await r.json();
    cache[path] = { t: Date.now(), v };
    return v;
  }

  async function events(league) {
    const j = await get('GetEvents?eventCount=0&sportId=66&champIds=' + (CHAMP[league] || league), 180000);
    return (j.events || []).map(e => {
      const [home, away] = String(e.name || '').split(' vs. ');
      return { id: e.id, name: e.name, home, away, start: e.startDate };
    }).filter(e => e.home && e.away);
  }
  const details = id => get('GetEventDetails?eventId=' + id, 90000);

  // ---- team-name matching (ESPN / model names vs Playdoit names) ----
  const STOP = new Set(['real', 'fc', 'cf', 'fk', 'sk', 'ac', 'sc', 'club', 'de', 'del', 'the', 'cd', 'afc', 'kv', 'sv', 'vfb', 'vfl', 'fsv', 'ogc', 'losc', 'ss', 'us', 'ud', 'rc', 'rcd', 'calcio', 'bk', 'if', 'as']);
  const ALIAS = { munchen: 'munich', prague: 'praha', praga: 'praha', psg: 'paris saint germain', internazionale: 'inter', utd: 'united', man: 'manchester', atl: 'atletico', chivas: 'guadalajara', gallos: 'queretaro', rayados: 'monterrey', xolos: 'tijuana' };
  function toks(n) {
    const s = String(n || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ');
    const out = [];
    for (const w of s.split(/\s+/)) { if (!w || STOP.has(w)) continue; for (const x of (ALIAS[w] || w).split(' ')) out.push(x); }
    return out;
  }
  function sim(a, b) {
    const A = new Set(toks(a)), Bs = new Set(toks(b));
    if (!A.size || !Bs.size) return 0;
    let i = 0; for (const x of A) if (Bs.has(x)) i++;
    return i / Math.min(A.size, Bs.size);
  }
  function match(list, home, away, kickoff) {
    let best = null;
    for (const e of list) {
      const sh = sim(home, e.home), sa = sim(away, e.away);
      if (sh < 0.5 || sa < 0.5) continue;
      let sc = sh + sa;
      if (kickoff && e.start) { const dh = Math.abs(Date.parse(e.start) - Date.parse(kickoff)) / 36e5; if (dh > 30) continue; sc -= dh / 100; }
      if (!best || sc > best.sc) best = { ...e, sc };
    }
    return best;
  }

  // ---- parse an event's markets into lines ----
  const TOTAL = { 'total': 'Goals', 'remates totales': 'Shots', 'remates a puerta totales': 'Shots on Target', 'total tiros de esquina': 'Corners', 'total fueras de juego': 'Offsides', 'total de tarjetas': 'Cards', 'total de faltas': 'Fouls' };
  const TEAM = { 'total de goles': 'Goals', 'remates totales': 'Shots', 'remates a puerta totales': 'Shots on Target', 'total tiros de esquina': 'Corners', 'total de fueras de juego': 'Offsides', 'total de tarjetas': 'Cards', 'total de faltas': 'Fouls' };
  function parse(det) {
    const [hn, an] = String(det.name || '').split(' vs. ');
    const om = {}; for (const o of det.odds || []) om[o.id] = o;
    const oddsOf = m => (m.desktopOddIds || m.oddIds || []).flat().map(i => om[i]).filter(o => o && o.price > 1);
    const out = { id: det.id, home: hn, away: an, start: det.startDate, lines: [], x12: null, oneUp: null, btts: null };
    const seen = new Set();
    for (const m of det.markets || []) {
      const n = String(m.name || '').trim();
      const odds = oddsOf(m);
      if (/^Resultado Final/i.test(n)) { const g = nm => (odds.find(o => o.name === nm) || {}).price; out.x12 = { H: g(hn), D: g('Empate'), A: g(an) }; continue; }
      if (/Súper Pago Anticipado/i.test(n)) { const g = nm => (odds.find(o => o.name === nm) || {}).price; out.oneUp = { H: g(hn), A: g(an) }; continue; }
      if (n === 'Ambos equipos marcan') { const g = nm => (odds.find(o => o.name === nm) || {}).price; out.btts = { yes: g('Sí'), no: g('No') }; continue; }
      let side = 't', rest = n;
      if (hn && n.startsWith(hn + ' ')) { side = 'h'; rest = n.slice(hn.length); } else if (an && n.startsWith(an + ' ')) { side = 'a'; rest = n.slice(an.length); }
      rest = rest.replace(/^\s*-\s*/, '').trim().toLowerCase();
      const stat = side === 't' ? TOTAL[rest] : TEAM[rest];
      if (!stat) continue;
      const byLine = {};
      for (const o of odds) {
        const mt = /(Más|Menos) de ([\d.]+)/.exec(o.name); if (!mt) continue;
        const L = +mt[2]; if (Math.abs(L % 1 - 0.5) > 1e-9) continue;
        (byLine[L] = byLine[L] || { stat, side, line: L, market: n })[mt[1] === 'Más' ? 'over' : 'under'] = o.price;
      }
      for (const x of Object.values(byLine)) { const k = stat + side + x.line; if (seen.has(k)) continue; seen.add(k); out.lines.push(x); }
    }
    out.lines.sort((a, b) => (a.stat + a.side).localeCompare(b.stat + b.side) || a.line - b.line);
    return out;
  }

  // Devigged 1X2 + the goals line closest to even, in the shape UCLM.solveLambda expects.
  function market(P) {
    if (!P || !P.x12 || !P.x12.H || !P.x12.D || !P.x12.A) return null;
    const r = [1 / P.x12.H, 1 / P.x12.D, 1 / P.x12.A], s = r[0] + r[1] + r[2];
    const m = { H: r[0] / s, D: r[1] / s, A: r[2] / s, overround: s, provider: 'Playdoit', dec: [P.x12.H, P.x12.D, P.x12.A] };
    let best = null;
    for (const x of P.lines) if (x.stat === 'Goals' && x.side === 't' && x.over && x.under) {
      const po = (1 / x.over) / (1 / x.over + 1 / x.under);
      if (!best || Math.abs(po - 0.5) < Math.abs(best.po - 0.5)) best = { line: x.line, po, o: x.over, u: x.under };
    }
    if (best) { m.line = best.line; m.pOver = best.po; m.ouDec = [best.o, best.u]; }
    return m;
  }

  // P(team is ever ahead) — minute DP on Poisson goals, 2nd half slightly busier.
  function everLead(lh, la) {
    const T = 94; let st = new Map([[0, 1]]), P = 0;
    for (let t = 0; t < T; t++) {
      const w = t < 47 ? 0.92 : 1.08, ph = lh / T * w, pa = la / T * w, n = new Map();
      for (const [d, p] of st) {
        const add = (k, v) => n.set(k, (n.get(k) || 0) + v);
        if (d + 1 >= 1) P += p * ph; else add(d + 1, p * ph);
        add(d - 1, p * pa); add(d, p * (1 - ph - pa));
      }
      st = n;
    }
    return P;
  }

  // ---- HTML (uses the pages' .ticket / .tName / .tLam classes) ----
  const LAB = { Goals: 'Goles', Shots: 'Tiros', 'Shots on Target': 'Tiros a puerta', Corners: 'Córners', Offsides: 'Fueras de juego', Cards: 'Tarjetas', Fouls: 'Faltas' };
  const pc = p => (p * 100).toFixed(0) + '%';
  const evs = ev => (ev >= 0 ? '+' : '') + (ev * 100).toFixed(0) + '%';
  const cell = (odds, p, min) => {
    if (!odds || p == null) return '<td style="text-align:center;color:#6b7a73">—</td>';
    const ev = p * odds - 1, good = ev >= min;
    return `<td style="text-align:center;${good ? 'background:rgba(76,201,140,.16);' : ''}"><b style="${good ? 'color:#4cc98c' : ''}">${odds.toFixed(2)}</b><br><span style="font-size:11px;opacity:.8">${pc(p)} · ${evs(ev)}</span></td>`;
  };
  // Goal expectations from a 1X2 + total line (same fit as UCLM.solveLambda).
  function pois(l, n) { const p = [Math.exp(-l)]; for (let k = 1; k <= n; k++) p.push(p[k - 1] * l / k); return p; }
  function lambdas(m) {
    if (!m) return null;
    const out = (lh, la) => { const ph = pois(lh, 14), pa = pois(la, 14); let H = 0, D = 0, O = 0; for (let i = 0; i < 15; i++) for (let j = 0; j < 15; j++) { const p = ph[i] * pa[j]; if (i > j) H += p; else if (i === j) D += p; if (m.line != null && i + j > m.line) O += p; } return { H, D, A: 1 - H - D, O }; };
    const loss = (lh, la) => { const o = out(lh, la); let L = (o.H - m.H) ** 2 + (o.D - m.D) ** 2 + (o.A - m.A) ** 2; if (m.pOver != null) L += (o.O - m.pOver) ** 2; return L; };
    let b = null;
    for (let i = 3; i <= 90; i++) for (let j = 3; j <= 90; j++) { const L = loss(i * 0.05, j * 0.05); if (!b || L < b.L) b = { lh: i * 0.05, la: j * 0.05, L }; }
    for (const st of [0.01, 0.002]) { const c = { ...b }; for (let i = -6; i <= 6; i++) for (let j = -6; j <= 6; j++) { const lh = c.lh + i * st, la = c.la + j * st; if (lh > 0.05 && la > 0.05) { const L = loss(lh, la); if (L < b.L) b = { lh, la, L }; } } }
    return { lh: b.lh, la: b.la };
  }

  // prob(stat, side, line) -> model P(over) or null; goals = {lh, la} for 1UP/BTTS; x12 = model {H,D,A}.
  // EV uses the model shrunk toward Playdoit's no-vig price (opt.shrink, default 0.5): raw model
  // edges on props run far too big, and the Nov 24 card showed it.
  function render(P, opt) {
    const min = opt.minEV == null ? 0.05 : opt.minEV, prob = opt.prob, names = { h: opt.home || P.home, a: opt.away || P.away, t: 'Total' };
    const w = opt.shrink == null ? 0.5 : opt.shrink, mix = (pm, pb) => pb == null ? pm : (1 - w) * pm + w * pb;
    const nv = (a, b) => (a && b) ? (1 / a) / (1 / a + 1 / b) : null;
    const value = [];
    const groups = {};
    for (const x of P.lines) {
      const po = prob(x.stat, x.side, x.line); if (po == null) continue;
      x.pb = nv(x.over, x.under); x.pm = po; x.po = mix(po, x.pb);
      (groups[x.stat + '|' + x.side] = groups[x.stat + '|' + x.side] || []).push(x);
    }
    // Guard: at Playdoit's main line (no-vig closest to 50%), if the model is 20+ points away the
    // model is probably wrong about this market (lineups, style, liguilla) — show it, don't list it.
    const far = {};
    for (const [k, g] of Object.entries(groups)) {
      const main = g.filter(x => x.pb != null).sort((a, b) => Math.abs(a.pb - 0.5) - Math.abs(b.pb - 0.5))[0];
      if (main && Math.abs(main.pm - main.pb) >= 0.20) far[k] = main;
    }
    for (const x of P.lines) {
      if (x.po == null || far[x.stat + '|' + x.side]) continue;
      const lab = `${names[x.side]} · ${LAB[x.stat] || x.stat}`;
      const po = x.pm;
      if (x.over && x.po * x.over - 1 >= min) value.push({ lab: `${lab} más de ${x.line}`, odds: x.over, p: x.po, pm: po });
      if (x.under && (1 - x.po) * x.under - 1 >= min) value.push({ lab: `${lab} menos de ${x.line}`, odds: x.under, p: 1 - x.po, pm: 1 - po });
    }
    const special = [];
    if (opt.goals && P.oneUp) {
      const ph = everLead(opt.goals.lh, opt.goals.la), pa = everLead(opt.goals.la, opt.goals.lh);
      // 1UP has no opposite side to de-vig, so take 5% margin off its price
      special.push(['1UP ' + names.h, P.oneUp.H, ph, P.oneUp.H && 1 / P.oneUp.H / 1.05], ['1UP ' + names.a, P.oneUp.A, pa, P.oneUp.A && 1 / P.oneUp.A / 1.05]);
    }
    if (opt.x12 && P.x12 && P.x12.H && P.x12.D && P.x12.A) { const t = 1 / P.x12.H + 1 / P.x12.D + 1 / P.x12.A; special.push([names.h + ' gana', P.x12.H, opt.x12.H, 1 / P.x12.H / t], ['Empate', P.x12.D, opt.x12.D, 1 / P.x12.D / t], [names.a + ' gana', P.x12.A, opt.x12.A, 1 / P.x12.A / t]); }
    if (opt.goals && P.btts) { const by = (1 - Math.exp(-opt.goals.lh)) * (1 - Math.exp(-opt.goals.la)), pb = nv(P.btts.yes, P.btts.no); special.push(['Ambos anotan: Sí', P.btts.yes, by, pb], ['Ambos anotan: No', P.btts.no, 1 - by, pb == null ? null : 1 - pb]); }
    for (const sp of special) { sp[4] = sp[2]; if (sp[2] != null) sp[2] = mix(sp[2], sp[3]); }
    for (const [lab, odds, p, , pm] of special) if (odds && p != null && p * odds - 1 >= min) value.push({ lab, odds, p, pm });
    value.sort((a, b) => (b.p * b.odds) - (a.p * a.odds));
    let h = `<div class="ticket"><div class="tName">Valor en Playdoit</div><div class="tLam">Momios en vivo de Playdoit. Prob. = ${Math.round((1 - w) * 100)}% modelo + ${Math.round(w * 100)}% precio sin margen de Playdoit (el modelo solo exagera). Verde = EV ≥ ${(min * 100).toFixed(0)}%. ${opt.note || ''}</div>`;
    h += value.length ? '<table class="mk" style="width:100%;margin-top:8px;font-size:13px"><tr><th></th><th>Momio</th><th>Prob.</th><th>EV</th></tr>' + value.slice(0, 12).map(v => `<tr><td>${v.lab}<br><span style="font-size:11px;opacity:.7">modelo solo ${pc(v.pm)}</span></td><td style="text-align:right"><b>${v.odds.toFixed(2)}</b></td><td style="text-align:right">${pc(v.p)}</td><td style="text-align:right;color:#4cc98c">${evs(v.p * v.odds - 1)}</td></tr>`).join('') + '</table>'
      : '<div class="tLam" style="margin-top:8px">Nada con EV suficiente en este partido.</div>';
    h += '</div>';
    if (special.length) h += `<div class="ticket"><div class="tName">1X2 · 1UP · Ambos anotan</div><table class="mk" style="width:100%;margin-top:6px"><tr><th></th><th>Playdoit</th><th>Prob. · EV</th></tr>${special.map(([l, o, p]) => `<tr><td>${l}</td>${o ? `<td style="text-align:center"><b>${o.toFixed(2)}</b></td><td style="text-align:center">${p == null ? '—' : pc(p) + ' · ' + evs(p * o - 1)}</td>` : '<td>—</td><td>—</td>'}</tr>`).join('')}</table><div class="tLam" style="margin-top:6px">1UP gana si el equipo va arriba en algún momento. Si Playdoit paga más el 1UP que "primer gol", el 1UP es mejor.</div></div>`;
    const order = ['Goals', 'Shots', 'Shots on Target', 'Corners', 'Offsides', 'Cards', 'Fouls'];
    const keys = Object.keys(groups).sort((a, b) => order.indexOf(a.split('|')[0]) - order.indexOf(b.split('|')[0]) || 'tha'.indexOf(a.split('|')[1]) - 'tha'.indexOf(b.split('|')[1]));
    for (const k of keys) {
      const [stat, side] = k.split('|');
      const fz = far[k];
      h += `<div class="ticket"><div class="tName">${names[side]} · ${LAB[stat] || stat}</div>${fz ? `<div class="tLam" style="color:#f5b53f;margin-top:4px">⚠ El modelo está muy lejos de Playdoit en la línea ${fz.line} (modelo ${pc(fz.pm)} más vs mercado ${pc(fz.pb)}). Probablemente el modelo se equivoca aquí: no entra en "Valor".</div>` : ''}<table class="mk" style="width:100%;margin-top:6px"><tr><th>Línea</th><th>Más de</th><th>Menos de</th></tr>` +
        groups[k].map(x => `<tr><td style="text-align:center">${x.line}</td>${cell(x.over, x.po, min)}${cell(x.under, 1 - x.po, min)}</tr>`).join('') + '</table></div>';
    }
    return h;
  }

  root.PD = { CHAMP, get, events, details, match, parse, market, lambdas, everLead, render, sim };
})(typeof window !== 'undefined' ? window : globalThis);
