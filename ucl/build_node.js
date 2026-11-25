#!/usr/bin/env node
// Rebuild the UCL model from ESPN (+ Playdoit market when ESPN has no odds) and write
// data/ucl_latest.json. Run by .github/workflows/update-data.yml, or locally:
//   node ucl/build_node.js [--days 7] [--today YYYY-MM-DD]
'use strict';
const fs = require('fs');
const path = require('path');
require(path.join(__dirname, 'model.js'));
require(path.join(__dirname, '..', 'playdoit.js'));
const U = globalThis.UCLM, PD = globalThis.PD;

const arg = k => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const cdmxToday = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Mexico_City' }).format(new Date());

(async () => {
  const today = arg('--today') || cdmxToday(), days = +(arg('--days') || 7);
  const M = await U.build({ today, days, log: m => console.error(m) });
  let evs = [];
  try { evs = await PD.events('ucl'); console.error('Playdoit UCL events ' + evs.length); } catch (e) { console.error('Playdoit unreachable: ' + e.message); }
  for (const fx of M.fixtures) {
    const e = evs.length ? PD.match(evs, fx.home, fx.away, fx.kickoff) : null;
    if (!e) continue;
    fx.pdId = e.id;
    if (!fx.dk) {
      try { const mk = PD.market(PD.parse(await PD.details(e.id))); if (mk) fx.dk = mk; } catch (err) { console.error('Playdoit details ' + e.id + ': ' + err.message); }
    }
  }
  M.meta.sources = { espn: true, playdoit: evs.length > 0 };
  const out = path.join(__dirname, '..', 'data', 'ucl_latest.json');
  fs.writeFileSync(out, JSON.stringify(M));
  console.error(`fixtures ${M.fixtures.length} (with market ${M.fixtures.filter(f => f.dk).length}), UCL rows ${M.meta.uclRows}, teams with UCL sample ${Object.keys(M.teamUcl).length}`);
  console.error('calib ' + JSON.stringify(M.calib));
})().catch(e => { console.error(e); process.exit(1); });
