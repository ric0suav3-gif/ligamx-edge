#!/usr/bin/env node
// Build the UCL edge card (markdown) from a saved model export.
//   node ucl/card.js data/ucl_model_2026-10-21.json > tracking/ucl-edge-card-2026-10-21.md
'use strict';
const fs = require('fs');
const path = require('path');
require(path.join(__dirname, 'model.js'));
const U = globalThis.UCLM;

const file = process.argv[2] || 'data/ucl_model_2026-10-21.json';
const M = JSON.parse(fs.readFileSync(file, 'utf8'));
const LAB = { Goals: 'Goals', Shots: 'Shots', 'Shots on Target': 'SOT', Corners: 'Corners', Fouls: 'Fouls', Cards: 'Cards', Offsides: 'Offsides' };
const pct = x => (x * 100).toFixed(0) + '%';
const fair = p => (p > 0 ? (1 / p).toFixed(2) : '—');
const mainLine = m => Math.max(0.5, Math.round(m - 0.5) + 0.5);
const cdmx = iso => new Date(iso.replace('Z', ':00Z')).toLocaleString('en-US', { timeZone: 'America/Mexico_City', weekday: 'short', hour: 'numeric', minute: '2-digit' });

const out = [];
out.push(`# UCL edge card — ${M.meta.today}`, '');
out.push(`Model ${M.meta.version}. Match strength comes from the market (DraftKings via ESPN, blended 50/50 with Polymarket for the 1X2); team style comes from ${M.meta.domesticLeagues.length} domestic leagues on ESPN; the UCL layer is fit on ${M.meta.uclRows} UCL games since Aug 2025 that have odds.`, '');
out.push('Fair prices carry no margin. A prop is a bet only if your book pays more than the fair price, ideally 5%+ more.', '');
out.push('**Backtest (2026-27 league phase, 45 games, mean log loss per team-game; lower is better):**', '');
out.push('| Stat | Flat UCL average | Market only | Market + domestic style |', '| --- | ---: | ---: | ---: |');
for (const s of ['Shots', 'Shots on Target', 'Corners', 'Fouls', 'Cards', 'Offsides']) {
  const b = M.backtest[s];
  out.push(`| ${LAB[s]} | ${b.m0.nll.toFixed(3)} | ${b.m1.nll.toFixed(3)} | ${b.m2 ? b.m2.nll.toFixed(3) : '—'} |`);
}
out.push('');

for (const fx of M.fixtures) {
  const mk = U.blendMarket(fx, 0.5);
  const mu = U.means(M, fx, mk);
  out.push(`## ${fx.home} vs ${fx.away} — ${cdmx(fx.kickoff)} CDMX`, '');
  const pmT = fx.pm ? fx.pm.H + fx.pm.D + fx.pm.A : 1;
  out.push('| 1X2 | ' + fx.home + ' | Draw | ' + fx.away + ' |', '| --- | ---: | ---: | ---: |');
  if (fx.dk) out.push(`| DraftKings (no vig) ${fx.dk.ml.map(x => (x > 0 ? '+' : '') + x).join(' / ')} | ${pct(fx.dk.H)} | ${pct(fx.dk.D)} | ${pct(fx.dk.A)} |`);
  if (fx.pm) out.push(`| Polymarket ($${(fx.pm.liq / 1e6).toFixed(1)}M liq) | ${pct(fx.pm.H / pmT)} | ${pct(fx.pm.D / pmT)} | ${pct(fx.pm.A / pmT)} |`);
  out.push(`| **Blend → fair** | **${pct(mk.H)}** ${fair(mk.H)} | **${pct(mk.D)}** ${fair(mk.D)} | **${pct(mk.A)}** ${fair(mk.A)} |`);
  if (fx.public) out.push(`| Public tickets / money | ${fx.public.ml.H[0]}% / ${fx.public.ml.H[1]}% | ${fx.public.ml.D[0]}% / ${fx.public.ml.D[1]}% | ${fx.public.ml.A[0]}% / ${fx.public.ml.A[1]}% |`);
  out.push('');
  const tot = mk.lh + mk.la;
  out.push(`Expected goals ${mk.lh.toFixed(2)}–${mk.la.toFixed(2)} (total ${tot.toFixed(2)}).` + (fx.public ? ` Public on the total: ${fx.public.tot.O[0]}% of tickets on over ${fx.public.tot.line}.` : ''), '');
  out.push('| Stat | ' + fx.homeAbbr + ' | ' + fx.awayAbbr + ' | Total | Line | Over | Fair O | Fair U |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |');
  const D = {};
  for (const s of ['Goals', 'Shots', 'Shots on Target', 'Corners', 'Fouls', 'Cards', 'Offsides']) {
    const m = mu[s]; if (!m) continue;
    const dh = U.dist(m.home, m.r), da = U.dist(m.away, m.r), dt = U.conv(dh, da); D[s] = { dh, da, dt };
    const L = s === 'Goals' && fx.dk && fx.dk.line ? fx.dk.line : mainLine(m.home + m.away), po = U.pOver(dt, L);
    out.push(`| ${LAB[s]} | ${m.home.toFixed(2)} | ${m.away.toFixed(2)} | ${(m.home + m.away).toFixed(2)} | ${L} | ${pct(po)} | ${fair(po)} | ${fair(1 - po)} |`);
  }
  out.push('');
  const tt = [];
  for (const [s, L] of [['Goals', 1.5], ['Shots', 12.5], ['Shots on Target', 4.5], ['Corners', 4.5], ['Cards', 1.5]]) {
    const ph = U.pOver(D[s].dh, L), pa = U.pOver(D[s].da, L);
    tt.push(`${LAB[s]} ${L}: ${fx.homeAbbr} O ${fair(ph)} / U ${fair(1 - ph)} · ${fx.awayAbbr} O ${fair(pa)} / U ${fair(1 - pa)}`);
  }
  out.push('Team totals: ' + tt.join('; ') + '.', '');
  const hh = ['Shots', 'Shots on Target', 'Corners'].map(s => { const r = U.h2h(D[s].dh, D[s].da); return `${LAB[s]} ${fx.homeAbbr} ${pct(r.H)} / tie ${pct(r.T)} / ${fx.awayAbbr} ${pct(r.A)}`; });
  out.push('Most (H2H): ' + hh.join('; ') + '.', '');
  // style notes
  const notes = [];
  for (const s of ['Shots', 'Shots on Target', 'Corners', 'Fouls', 'Cards']) {
    const st = fx.style[s]; if (!st) continue;
    for (const [side, name] of [['home', fx.home], ['away', fx.away]]) {
      const [a, d, ok] = st[side]; if (!ok) continue;
      if (Math.abs(a) >= 0.12) notes.push(`${name} ${a > 0 ? 'generate more' : 'generate fewer'} ${LAB[s].toLowerCase()} than their strength implies (${a > 0 ? '+' : ''}${(a * 100).toFixed(0)}%)`);
      if (Math.abs(d) >= 0.12) notes.push(`${name} ${d > 0 ? 'concede more' : 'concede fewer'} ${LAB[s].toLowerCase()} than their strength implies (${d > 0 ? '+' : ''}${(d * 100).toFixed(0)}%)`);
    }
  }
  if (!fx.info.away.league) notes.push(`${fx.away}: no domestic box scores on ESPN (Ukrainian league), so neutral style; strength from the market only`);
  if (notes.length) out.push('Style notes: ' + notes.join('; ') + '.', '');
}
process.stdout.write(out.join('\n') + '\n');
