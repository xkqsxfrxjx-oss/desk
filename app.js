import { creds, decryptEnvelope } from "./crypto.js";
import * as chart from "./chart.js";
const $ = s => document.querySelector(s), view = $("#view");
const C = creds();
const S = { tab: "home", stack: [], data: {}, err: null, loaded: false, coin: {} };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const usd = (v, d = 2) => v == null ? "–" : (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = v => v == null ? "–" : (v >= 0 ? "+" : "-") + usd(Math.abs(v)).slice(0);
const pct = v => v == null ? "–" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%";
const px = v => v == null ? "–" : "$" + (v >= 1 ? v.toFixed(4) : Number(v).toPrecision(4));
const k = v => v == null ? "–" : "$" + (v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : v.toFixed(0));
const hm = ts => ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
const ago = ts => { if (!ts) return "never"; const s = (Date.now() - new Date(ts)) / 1000; return s < 90 ? Math.round(s) + "s ago" : Math.round(s / 60) + "m ago"; };
const fomo = (url, label = "Buy on FOMO") => url ? `<a class="btn fomo" href="${esc(url)}" target="_blank" rel="noopener">${label}</a>` : "";

async function get(name) {
  if (!C.t || !C.d) throw new Error("nolink");
  const r = await fetch(`d/${encodeURIComponent(C.d)}/${name}?n=${Date.now()}`, { cache: "no-store" });
  if (r.status === 404) throw new Error("nodata");
  if (!r.ok) throw new Error("HTTP " + r.status);
  try { return await decryptEnvelope(await r.json(), C.t); } catch { throw new Error("badkey"); }
}
async function load() {
  try {
    const [state, chartd, activity, account] = await Promise.all(["state.json", "chart.json", "activity.json", "account.json"].map(get));
    const pipeline = await get("pipeline.json").catch(() => null);
    const shorter = await get("shorter.json").catch(() => null);
    const cmp = await get("compare.json").catch(() => null);
    S.data = { state, chart: chartd, activity, account, pipeline, shorter, cmp }; S.err = null;
  } catch (e) { S.err = e.message; }
  S.loaded = true; render();
}
async function loadCoin(mint) {
  try { S.coin[mint] = { doc: await get(`coin/${mint}.json`) }; } catch (e) { S.coin[mint] = { err: e.message }; }
  render();
}

const ERR = { nolink: ["Open your desk link", "Open the full link from Telegram once. It saves the key on this phone."],
  badkey: ["Key doesn't match", "Open the latest desk link from Telegram again."],
  nodata: ["No data published yet", "The desk publishes every few minutes. Pull to refresh soon."] };
function stateBox(kind, title, msg) {
  return `<div class="card state ${kind}"><b>${esc(title)}</b>${esc(msg)}${kind === "err" ? `<div style="margin-top:12px"><button class="btn ghost" data-act="retry">Try again</button></div>` : ""}</div>`;
}
function guard() {
  if (!S.loaded) return `<div class="skel"></div><div class="skel"></div><div class="skel" style="height:160px"></div>`;
  if (S.err) { const [t, m] = ERR[S.err] || ["Can't load the desk", S.err]; return stateBox("err", t, m); }
  return null;
}

// ---------- screens ----------
function home() {
  const g = guard(); if (g) return g;
  const s = S.data.state, ch = S.data.chart, acts = S.data.activity.items;
  const pos = s.positions.map(p => `<div class="row" data-coin="${p.mint}"><div class="l"><div class="t">${esc(p.name)}</div>
      <div class="s">${usd(p.size_usd)} · entry ${px(p.entry_price)} · stop -${p.stop_pct}%</div></div>
      <div class="v ${p.pnlUsd >= 0 ? "g" : "r"}">${sgn(p.pnlUsd)}<div class="sm">${pct(p.pct)}</div></div></div>
      <div style="padding-bottom:10px">${fomo(p.link, "Sell on FOMO")}</div>`).join("");
  return `<div class="card"><h2>${s.mode === "PAPER" ? "PAPER balance" : "Balance"}<span class="sm mut">${ago(s.updated)}</span></h2>
    <div class="big">${usd(s.equity)}</div><div class="${s.pnlUsd >= 0 ? "g" : "r"}" style="font-weight:700">${sgn(s.pnlUsd)} (${pct(s.pnlPct)}) today</div>
    ${ch.points.length ? `<canvas id="bal" style="margin-top:10px"></canvas>` : `<div class="state" style="padding:24px 0">No balance points yet</div>`}
    <div class="kv" style="margin-top:8px"><span>Free</span><span>${usd(s.free)}</span><span>In positions</span><span>${s.positions.length}</span></div></div>
   <div class="card"><h2>Open positions</h2>${pos || `<div class="state" style="padding:20px 0"><b>Nothing open</b>Risk starts guarding when Executor fills.</div>`}</div>
   <button class="btn ghost full" data-go="vertailu" style="margin-bottom:12px">Vertailu · all comparison variants</button>
   <div class="card"><h2>Latest</h2>${acts.slice(0, 5).map(actRow).join("") || `<div class="state" style="padding:20px 0">No activity yet tonight</div>`}</div>`;
}
function actRow(a) {
  const col = { bought: "c", sold: a.value && a.value.startsWith("-") ? "r" : "g", stopped: "r", rejected: "mut" }[a.kind];
  return `<div class="row" ${a.mint ? `data-coin="${a.mint}"` : ""}><div class="l"><div class="t">${esc(a.title)}</div><div class="s">${esc(a.subtitle)} · ${hm(a.ts)}</div></div>
    <div class="v ${col}">${esc(a.value)}</div></div>`;
}
// ---------- live pipeline feed ----------
const LIVE_URL = "https://5-230-73-175.sslip.io/api/pipeline";
const P = { ev: [], cursor: null, paused: false, live: false, filter: "All", timer: null, busy: false, pending: 0 };
const STG = ["All", "Scanner", "Auditor", "Analyst", "Executor", "Shorter"];
function mergeEv(list) {
  const seen = new Set(P.ev.map(e => e.id)); const add = list.filter(e => !seen.has(e.id));
  if (add.length) { P.ev = add.concat(P.ev).sort((a, b) => a.ts < b.ts ? 1 : a.ts > b.ts ? -1 : 0).slice(0, 300); }
  return add.length;
}
async function pollLive() {
  if (P.busy || !C.t) return; P.busy = true;
  try {
    const r = await fetch(LIVE_URL + (P.cursor ? "?after=" + encodeURIComponent(P.cursor) : ""), { headers: { Authorization: "Bearer " + C.t }, cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await decryptEnvelope(await r.json(), C.t);
    P.live = true; if (d.cursor) P.cursor = d.cursor;
    const n = mergeEv(d.events);
    if (n && current() === "activity") { if (P.paused) P.pending += n; else render(); }
    else if (current() === "activity") liveDot();
  } catch { P.live = false; const pj = S.data.pipeline; if (pj) mergeEv(pj.events); if (current() === "activity" && !P.paused) render(); }
  P.busy = false;
}
function liveDot() { const el = $("#livepill"); if (el) { el.className = "livepill " + (P.paused ? "pause" : P.live ? "on" : "off"); el.textContent = P.paused ? "PAUSED" : P.live ? "LIVE" : "DELAYED"; } }
const HTM = ts => ts ? new Date(ts).toLocaleTimeString("fi-FI", { timeZone: "Europe/Helsinki", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
function evRow(e) {
  const meta = [e.score != null ? "score " + e.score : "", e.mcap != null ? "mcap " + k(e.mcap) : "", e.liq != null ? "liq " + k(e.liq) : ""].filter(Boolean).join(" · ");
  const sh = e.shadow ? `<span class="pill m">NEW ${e.shadow.new ? "✓" : "✗"} · OLD ${e.shadow.old ? "✓" : "✗"}</span>` : "";
  return `<div class="ev"><div class="evh"><span class="stg">${esc(e.stage)}</span><span class="pill ${e.pass ? "g" : "r"}">${e.pass ? "PASS" : "FAIL"}</span>
    <a class="lnk sym" href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.symbol)}</a><span class="sm mut tm">${HTM(e.ts)}</span></div>
    <div class="sm ${e.pass ? "mut" : "r"}">${esc(e.reason || "")}</div>${meta || sh ? `<div class="sm mut evm">${esc(meta)} ${sh}</div>` : ""}</div>`;
}
function activity() {
  const g = guard(); if (g) return g;
  if (!P.ev.length && S.data.pipeline) mergeEv(S.data.pipeline.events);
  const list = P.ev.filter(e => P.filter === "All" || e.stage === P.filter).slice(0, 150);
  const it = S.data.activity.items;
  return `<div class="card"><h2>Pipeline<span><span id="livepill"></span> <button class="btn ghost sm pz" data-act="pause">${P.paused ? "▶ Resume" + (P.pending ? " (" + P.pending + ")" : "") : "❚❚ Pause"}</button></span></h2>
    <div class="chips">${STG.map(s => `<button class="chip ${P.filter === s ? "on" : ""}" data-act="f:${s}">${s}</button>`).join("")}</div>
    ${list.map(evRow).join("") || `<div class="state" style="padding:20px 0">No decisions yet</div>`}</div>
    ${it.length ? `<div class="card"><h2>Trades &amp; rejects</h2>${it.map(actRow).join("")}</div>` : ""}`;
}
function hb(a) {
  const s = S.data.state.agents, ts = s.heartbeats[a];
  const off = !ts || (Date.now() - new Date(ts)) > 120000, pause = s.paused.includes(a);
  return `<span class="hb ${pause ? "pause" : off ? "off" : ""}" title="${ago(ts)}"></span>`;
}
function strips(layers, running) {
  const by = Object.fromEntries((layers || []).map(l => [l.layer ?? l.n, l]));
  return `<div class="strips">${[1, 2, 3, 4, 5, 6, 7, 8].map(n => { const l = by[n]; const c = !l ? (running ? "run" : "") : l.pass ? "ok" : l.pass === 0 || l.pass === false ? "bad" : ""; return `<div class="strip ${c}"></div>`; }).join("")}</div>`;
}
function agents() {
  const g = guard(); if (g) return g;
  const a = S.data.state.agents, la = a.auditor.last, v = a.analyst.last, ex = a.executor.last;
  const feed = a.scanner.feed.slice(0, 6).map(f => f.verdict === "pass"
      ? `<div class="row" data-coin="${f.mint}"><div class="l"><div class="t">${esc(f.name)} · ${esc(f.source || "pumpfun")} · liq ${k(f.liq)} · → auditor</div></div></div>`
      : `<div class="row killed" data-coin="${f.mint}"><div class="l"><div class="t">${esc(f.name)} · ${esc(f.source || "")}</div></div><div class="v r sm">${esc(f.reason)}</div></div>`).join("");
  return `
  <div class="card agent"><div class="head"><h2>${hb("scanner")}Scanner</h2><span class="mid">${a.scanner.pools} pools</span></div>
    <div class="sm mut">${a.scanner.passed} passed · ${a.scanner.killed} killed</div>${feed || `<div class="state" style="padding:16px 0">Waiting for the first graduation</div>`}</div>
  <div class="card agent" data-go="auditor"><div class="head"><h2>${hb("auditor")}Auditor</h2><span class="mid">${a.auditor.takenApart} taken apart</span></div>
    ${la ? `${strips(la.layers)}<div class="${la.passed ? "g" : "r"}" style="font-weight:600">${esc(la.name)} · ${la.passed ? "8/8 → Executor" : esc(la.reason || "taking apart...")}</div>` : `${strips([], false)}<div class="mut">Nothing taken apart yet</div>`}
    <div class="sm mut" style="margin-top:4px">${a.auditor.rejected} rejected · tap for the disc</div></div>
  <div class="card agent"><div class="head"><h2>${hb("analyst")}Analyst${a.analyst.mode === "rules" ? " (rules)" : ""}</h2><span class="mid">Scoring</span></div>
    <div style="display:flex;gap:14px;align-items:center"><canvas id="ring"></canvas><div>${v ? `<div class="t">${esc(v.name)}</div><div class="sm ${v.pass ? "g" : "r"}">${v.pass ? "passed" : esc(v.reason)}</div>
    <div class="sm mut">alive ${v.alive_6h} · organic ${v.organic} · flush ${v.flush} · chase ${v.chase}</div>` : `<div class="mut">No coin scored yet</div>`}<div class="sm mut">${a.analyst.scored} scored · green from ${a.analyst.minScore}</div></div></div></div>
  <div class="card agent"><div class="head"><h2>${hb("executor")}Executor</h2><span class="mid">${a.executor.trades} trades</span></div>
    ${ex ? `<div class="t">${esc(ex.name)} · ${usd(ex.size_usd)} · ${ex.stack_pct ?? a.executor.stackPct}% of stack</div>
      <div class="bar"><i style="width:${ex.status === "bought" ? 100 : ex.status === "sent" ? 60 : 0}%"></i></div>
      <div class="sm ${ex.status === "bought" ? "g" : "mut"}" style="margin-top:4px">${ex.status === "bought" ? "✓ Filled" : ex.status === "sent" ? "Executing... 60%" : esc(ex.status + (ex.reason ? " · " + ex.reason : ""))}</div>`
      : `<div class="mut">${usd(null)} · ${a.executor.stackPct}% of stack · no trade yet</div>`}</div>
  <div class="card agent"><div class="head"><h2>${hb("risk")}Risk</h2><span class="mid">${a.risk.open ? "Guarding" : a.risk.lastExit || "Idle"}</span></div>
    <div class="pills"><span class="pill r">stop -${a.risk.stopPct}%</span><span class="pill g">trail ${a.risk.trailPct}%</span>
    <span class="pill m">${a.risk.open} open</span>${a.risk.lastExit ? `<span class="pill m">last: ${esc(a.risk.lastExit)}</span>` : ""}</div></div>
  ${shorterCard()}
  <div class="card agent" data-go="vertailu"><div class="head"><h2>Vertailu <span class="pill o">PAPER</span></h2><span class="mid">all variants</span></div>
    <div class="sm mut">Long and short comparison variants, live · tap to open</div></div>`;
}
function shorterCard() {
  const p = S.data.shorter; if (!p) return "";
  return `<div class="card agent" data-go="shorter"><div class="head"><h2>Shorter <span class="pill o">PAPER</span></h2><span class="mid">${usd(p.balance)}</span></div>
    <div class="sm mut">${p.trades} trades · ${p.winRatePct ?? "–"}% wins · ${p.open.length} open · tap for profile</div></div>`;
}
const VNAME = { new: "NEW (live paper)", skipTemplateCap4: "Skip template + max 4", skipTemplateCap4Holders: "Skip template + ≥200 holders + max 4",
  skipTemplate: "Skip template", cap4: "Max 4 open", cap3: "Max 3 open", copycatPriority: "Copycat priority", templateDelay20: "Template via +20s",
  fakeMcapHold: "Fake-mcap hold", delay20: "+20s entry delay" };
const hel = ts => ts ? new Date(ts).toLocaleString("fi-FI", { timeZone: "Europe/Helsinki", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
const LNAME = { new: "NEW (live)", loose: "LOOSE", dev10: "Dev ≤10%", stop20: "Stop −20%", stop25: "Stop −25%", smartMoney: "Smart money (≥2)" };
function tpCard(t) {
  if (!t) return "";
  const rowsT = Object.entries(t.trails).map(([kk, v]) => `<div class="vrow"><span>${esc(kk.replace("trail", "Trail "))}%</span><span></span>
      <span>${v.betterShare == null ? "–" : Math.round(100 * v.betterShare) + "%"}</span><span>${v.avgDiffUsd == null ? "–" : sgn(v.avgDiffUsd)}</span><span class="${v.totalDiffUsd >= 0 ? "g" : "r"}">${sgn(v.totalDiffUsd)}</span></div>`).join("");
  return `<div class="card"><h2>+40% TP vs trailing stop<span class="sm mut">${t.closed} done · ${t.open} tracking</span></h2>
    ${t.tpExits ? `<div class="vrow hd"><span>Trail off high</span><span></span><span>Better</span><span>Avg</span><span>Total</span></div>${rowsT}` : `<div class="state" style="padding:16px 0">No +40% exits yet</div>`}
    <div class="sm mut" style="margin-top:6px">After each +40% exit the price is followed up to 6 h; trail activates at the exit price.</div></div>`;
}
function communityCard(d) {
  const c = d.community; if (!c) return "";
  const rows = (c.rows || []).map(x => `<div class="vrow"><span>${esc(x.label || x.key)}</span><span>${x.trades ?? "–"}</span>
      <span class="${(x.netUsd ?? 0) >= 0 ? "g" : "r"}">${sgn(x.netUsd)}</span><span>${usd(x.balance)}</span><span class="r">${x.maxDrawdownPct ?? "–"}%</span></div>
      <div class="sm mut" style="padding:0 0 6px">${x.wins ?? "–"} wins · ${x.open ?? 0} open${x.skippedNoFunds ? ` · ${x.skippedNoFunds} no-funds skips` : ""}${x.unconstrainedNet != null ? ` · unconstrained ${sgn(x.unconstrainedNet)} / ${x.unconstrainedTrades ?? "–"} tr` : ""}</div>`).join("");
  return `<div class="card"><h2>Community<span class="sm mut">$50 book per window · after first dump, before hype</span></h2>
      <div class="sm mut" style="margin-bottom:8px">${esc(c.note || "")} Watching ${c.watched ?? 0}/${c.watchCap ?? "–"}. X/Telegram mentions skipped (no free reliable source).</div>
      <div class="vrow hd"><span>Window</span><span>Tr</span><span>Net</span><span>Bal</span><span>DD</span></div>
      ${rows || `<div class="state" style="padding:16px 0">No community trades yet</div>`}</div>`;
}
function vertailu() {
  const g = guard(); if (g) return g;
  const d = S.data.cmp;
  if (!d) return stateBox("", "No comparison data yet", "It appears after the next publish.");
  const fn = f => Object.entries(f || {}).filter(([, v]) => typeof v !== "object").map(([kk, v]) => `<span class="pill m">${esc(kk)} ${esc(v)}</span>`).join("");
  const lnk = (x) => `<a class="lnk" href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.name)}</a>`;
  const longs = d.long.map(x => `<div class="card${x.key === d.leaderLong ? " lead" : ""}"><h2>${esc(LNAME[x.key] || x.key)}${x.key === d.leaderLong ? ` <span class="pill g">leader</span>` : ""}
      <span class="${x.netUsd >= 0 ? "g" : "r"}">${sgn(x.netUsd)}</span></h2>
      <div class="sm mut">${x.trades} closed · ${x.wins} wins · ${x.open.length} open</div>
      ${fn(x.funnel) ? `<div class="pills" style="margin-top:6px">${fn(x.funnel)}</div>` : ""}
      ${x.open.map(p => `<div class="row"><div class="l"><div class="t">${lnk(p)}</div><div class="s">entry ${px(p.entry_price)} · ${usd(p.size_usd)}</div></div><div class="v ${p.pct >= 0 ? "g" : "r"}">${pct(p.pct)}</div></div>`).join("")}
      ${x.closed.slice(0, 5).map(p => `<div class="row"><div class="l"><div class="t">${lnk(p)}</div><div class="s">${esc(p.exit_reason)} · ${hel(p.closed_at)}</div></div><div class="v ${p.pnl_usd >= 0 ? "g" : "r"}">${sgn(p.pnl_usd)}</div></div>`).join("")}</div>`).join("");
  const shorts = d.short.map(x => `<div class="vrow${x.key === d.leaderShort ? " cur lead" : ""}"><span>${esc(VNAME[x.key] || x.key)}${x.key === d.leaderShort ? " ★" : ""}</span><span>${x.trades ?? "–"}</span>
      <span class="${(x.netUsd ?? 0) >= 0 ? "g" : "r"}">${sgn(x.netUsd)}</span><span>${usd(x.balance)}</span><span class="r">${x.maxDrawdownPct ?? "–"}%</span></div>
      <div class="sm mut" style="padding:0 0 6px">${x.wins ?? "–"} wins · ${x.open ?? 0} open · low ${usd(x.minBalance)}${x.skippedNoFunds ? ` · ${x.skippedNoFunds} no-funds skips` : ""}${x.unconstrainedNet != null ? ` · unconstrained ${sgn(x.unconstrainedNet)} / ${x.unconstrainedTrades ?? "–"} tr` : ""}</div>`).join("");
  const srcs = Object.entries(d.sources || {}).map(([kk, v]) => `<div class="vrow"><span>${esc(kk)}</span><span>${v.coins ?? 0}</span><span>${v.passed ?? 0}</span><span>${v.killed ?? 0}</span><span>${v.discovered ?? 0}</span></div>`).join("");
  const hs = d.holderSold || {};
  return `<div class="card"><h2>Vertailu <span class="pill o">PAPER</span><span class="sm mut">${hel(d.updated)} Helsinki</span></h2>
      <div class="sm mut">Hypothetical results only. Long since ${hel(d.since)}. Leader: long ${esc(LNAME[d.leaderLong] || d.leaderLong || "–")}, short ${esc(VNAME[d.leaderShort] || d.leaderShort || "–")}.</div></div>
    <div class="card"><h2>Sources<span class="sm mut">paper · comparable per platform</span></h2>
      <div class="vrow hd"><span>Source</span><span>Coins</span><span>Pass</span><span>Kill</span><span>Disc.</span></div>
      ${srcs || `<div class="state" style="padding:16px 0">No source counts yet</div>`}
      <div class="sm mut" style="margin-top:8px">Top 100 sold (info only): ${hs.coins ?? 0} coins, avg ${hs.avgTop100SoldShare ?? "–"}% of top 100 have sold any. Hooked is discovery only (no paper trades).</div>
      <div class="sm mut">Smart money: ${(d.smartMoney && d.smartMoney.wallets) ?? 0} wallets on our list, ${(d.smartMoney && d.smartMoney.coinsWithSmart) ?? 0} coins with a tagged holder (shadow copies live NEW when ≥${(d.smartMoney && d.smartMoney.minHold) ?? 2} hold).</div></div>
    <div class="sect">Long</div>${longs}${tpCard(d.tpVsTrail)}
    ${communityCard(d)}
    <div class="card"><h2>Short<span class="sm mut">$50 virtual · funded trades</span></h2><div class="vrow hd"><span>Variant</span><span>Tr</span><span>Net</span><span>Bal</span><span>DD</span></div>${shorts}</div>`;
}
function shorter() {
  const g = guard(); if (g) return g;
  const p = S.data.shorter;
  if (!p) return stateBox("", "No Shorter data yet", "The profile appears after the next publish.");
  const dd = p.maxDrawdownPct, up = p.balance >= p.start;
  const open = p.open.map(o => `<div class="row"><div class="l"><div class="t"><a class="lnk" href="${esc(o.link)}" target="_blank" rel="noopener">${esc(o.name)}</a> · ${o.leverage}x short</div>
      <div class="s">entry ${px(o.entry)} · now ${px(o.price)} (${pct(o.movePct)}) · ${o.trailActive ? `trail on ${px(o.trailLevel)}` : `stop ${px(o.stop)}`}</div></div>
      <div class="v ${o.pnlPct >= 0 ? "g" : "r"}">${pct(o.pnlPct)}<div class="sm">${usd(o.stake)}</div></div></div>`).join("");
  const closed = p.closed.slice(0, 40).map(x => `<div class="row"><div class="l"><div class="t"><a class="lnk" href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.name)}</a></div>
      <div class="s">${hm(x.closedAt)} · ${esc(x.reason)}${x.fillModel === "inverse" ? " · Inverse fill" : ""}</div></div>
      <div class="v ${x.pnlUsd >= 0 ? "g" : "r"}">${sgn(x.pnlUsd)}<div class="sm">${pct(x.pnlPct)}</div></div></div>`).join("");
  const vars = p.variants.map(v => `<div class="vrow${v.key === "new" ? " cur" : ""}"><span>${esc(VNAME[v.key] || v.key)}</span><span>${v.trades}</span>
      <span class="${v.netUsd >= 0 ? "g" : "r"}">${sgn(v.netUsd)}</span><span>${usd(v.balance)}</span><span class="r">${v.maxDrawdownPct ?? "–"}%</span></div>
      <div class="sm mut" style="padding:0 0 6px">${v.skippedNoFunds ? `${v.skippedNoFunds} no-funds skips · ` : ""}unconstrained ${sgn(v.unconstrainedNet)} / ${v.unconstrainedTrades ?? "–"} tr</div>`).join("");
  return `<div class="card"><h2>Virtual balance <span class="pill o">PAPER</span><span class="sm mut">${ago(p.updated)}</span></h2>
    <div class="big">${usd(p.balance)}</div><div class="${up ? "g" : "r"}" style="font-weight:700">${sgn(p.balance - p.start)} from ${usd(p.start, 0)} start</div>
    <canvas id="sbal" style="margin-top:10px"></canvas>
    <div class="kv" style="margin-top:8px"><span>Funded trades</span><span>${p.trades} · ${p.winRatePct ?? "–"}% wins</span><span>Funded net</span><span>${sgn(p.netUsd)}</span>
    <span>Max drawdown</span><span class="r">${dd}%</span><span>Lowest</span><span>${usd(p.minBalance)}</span>
    <span>Peak capital</span><span>${p.peakOpen} open · ${usd(p.peakCapitalUsd, 0)}</span></div>
    <div class="sm mut" style="margin-top:8px">Hypothetical Inverse shorts. Paper only, no orders, no alerts. Balance is a $50 bankroll (skipped ${p.skippedNoFunds ?? 0} trades with no free cash). Unconstrained NEW: ${p.unconstrainedTrades ?? "–"} tr, ${sgn(p.unconstrainedNet)}.</div></div>
   <div class="card"><h2>Open shorts<span class="mid">${p.open.length}</span></h2>${open || `<div class="state" style="padding:20px 0">Nothing open</div>`}</div>
   <div class="card"><h2>Variants<span class="sm mut">$50 virtual · funded</span></h2><div class="vrow hd"><span>Variant</span><span>Tr</span><span>Net</span><span>Bal</span><span>DD</span></div>${vars}</div>
   <div class="card"><h2>Closed<span class="mid">newest first</span></h2>${closed || `<div class="state" style="padding:20px 0">No closed shorts</div>`}</div>`;
}
const NAMES = ["Mint authority", "Freeze authority", "Dev wallet", "Top 10 holders", "Liquidity", "Pool age", "Bundled wallets", "Delegations"];
function layerList(rows) {
  const by = Object.fromEntries((rows || []).map(l => [l.layer, l]));
  return NAMES.map((nm, i) => { const l = by[i + 1]; const cls = !l ? "nc" : l.pass ? "ok" : "bad";
    return `<div class="layer ${cls}"><span class="n">${i + 1}</span><span class="nm">${nm}</span><span class="vl">${l ? esc(l.value_text) : "not checked"}</span></div>`; }).join("");
}
function auditor() {
  const g = guard(); if (g) return g;
  const la = S.data.state.agents.auditor.last;
  if (!la) return stateBox("", "Nothing taken apart yet", "When Scanner passes a coin, Auditor checks its 8 layers here, live.");
  return `<div class="card" style="text-align:center"><h2>${esc(la.name)}<span class="${la.passed ? "g" : "r"}">${la.passed ? "8/8" : "RED"}</span></h2>
    <canvas id="disc" style="margin:4px auto"></canvas><div class="${la.passed ? "g" : "r"}" style="font-weight:700">${la.passed ? "8/8 → Executor" : esc(la.reason)}</div></div>
    <div class="card">${layerList(la.layers)}</div><button class="btn ghost full" data-coin="${la.mint}">Open coin</button>`;
}
function coin(mint) {
  const st = S.coin[mint];
  if (!st) return `<div class="skel" style="height:240px"></div><div class="skel"></div>`;
  if (st.err) { const [t, m] = st.err === "nodata" ? ["No data for this coin yet", "Coin pages appear once Scanner has judged the coin."] : ERR[st.err] || ["Can't load this coin", st.err]; return stateBox("err", t, m); }
  const d = st.doc, c = d.coin, p = d.position, sc = d.scans[d.scans.length - 1], v = d.verdict;
  return `<div class="card"><h2>${esc(c.symbol || "")}<span class="mut sm">${esc(c.mint.slice(0, 4) + "…" + c.mint.slice(-4))}</span></h2>
     <div class="big" style="font-size:28px">${px(d.price)}</div>
     ${d.candles.length ? `<canvas id="cdl" style="margin-top:8px"></canvas>` : `<div class="state" style="padding:30px 0">No candles yet. Prices start when Scanner sees the pool.</div>`}
     <div style="margin-top:10px">${fomo(d.link)}</div></div>
   ${p ? `<div class="card"><h2>Position<span class="${p.status === "closed" ? "mut" : "o"}">${esc(p.status)}</span></h2><div class="kv">
      <span>Entry</span><span>${px(p.entry_price)}</span><span>Size</span><span>${usd(p.size_usd)}</span><span>Stop</span><span>-${p.stop_pct}% (${px(p.stop_price)})</span>
      <span>Peak</span><span>${px(p.peak_price)}</span>${p.exit_reason ? `<span>Exit</span><span>${esc(p.exit_reason)} at ${px(p.exit_price)}</span><span>PnL</span><span class="${p.pnl_usd >= 0 ? "g" : "r"}">${sgn(p.pnl_usd)}</span>` : ""}</div></div>` : ""}
   <div class="card"><h2>Scanner</h2>${sc ? `<div class="kv"><span>Source</span><span>${esc(c.source || sc.source || "pumpfun")}</span><span>Liquidity</span><span>${k(sc.liquidity_usd)}</span><span>Top 10</span><span>${sc.top10_pct ?? "–"}%</span>
      <span>1h</span><span>${pct(sc.h1_change_pct)}</span><span>Verdict</span><span class="${sc.verdict === "pass" ? "g" : "r"}">${sc.verdict}${sc.reason ? " · " + esc(sc.reason) : ""}</span>
      <span>Holders</span><span>${c.holders ?? "n/a"}</span>
      <span>Top 100 sold</span><span>${d.holderSold && d.holderSold.top100_sold_share != null ? d.holderSold.top100_sold_share + "% (" + d.holderSold.top100_sold + "/" + d.holderSold.top100_n + ")" : "–"}</span></div>` : `<div class="mut">Still in the waiting room</div>`}</div>
   <div class="card"><h2>Auditor</h2>${d.audit.length ? layerList(d.audit) : `<div class="mut">Not audited</div>`}</div>
   ${v ? `<div class="card"><h2>Analyst<span class="${v.pass ? "g" : "r"}">${v.score ?? "–"}</span></h2><div class="kv"><span>alive_6h</span><span>${v.alive_6h ?? "–"}</span><span>organic</span><span>${v.organic ?? "–"}</span>
      <span>flush</span><span>${v.flush ?? "–"}</span><span>chase</span><span>${v.chase ?? "–"}</span>${v.reason ? `<span>Failed</span><span class="r">${esc(v.reason)}</span>` : ""}</div></div>` : ""}`;
}
function account() {
  const g = guard(); if (g) return g;
  const a = S.data.account, s = a.settings;
  const groups = {}; Object.entries(s).forEach(([kk, vv]) => { const [grp, ...rest] = kk.split("."); (groups[grp] ||= []).push([rest.join("."), vv]); });
  return `<div class="card"><h2>Desk</h2><div class="kv"><span>Mode</span><span class="${a.mode === "PAPER" ? "o" : "g"}">${a.mode}</span>
      <span>FOMO</span><span><a class="lnk" href="${esc(a.profileUrl)}" target="_blank">@${esc(a.fomoHandle)}</a></span>
      <span>Web push</span><span>${esc(a.webPush)}</span><span>RPC</span><span>${esc(a.rpc)}</span><span>Min stack</span><span>${usd(a.minStack)}</span></div>
      <div class="sm mut" style="margin-top:10px">Read-only here. Change settings in Telegram, e.g. "set stop to -8%".</div></div>
    ${Object.entries(groups).map(([gname, items]) => `<div class="card"><h2>${esc(gname)}</h2>${items.map(([kk, vv]) => `<div class="set"><span>${esc(kk)}</span><span>${esc(vv)}</span></div>`).join("")}</div>`).join("")}
    ${a.changeLog.length ? `<div class="card"><h2>Changes</h2>${a.changeLog.map(x => `<div class="set"><span>${esc(x.key)}</span><span>${esc(x.old)} → ${esc(x.new)}</span></div>`).join("")}</div>` : ""}
    <footer>New to FOMO? <a href="${esc(a.signupUrl)}" target="_blank">${esc(a.signupUrl)}</a></footer>`;
}

// ---------- render / nav ----------
const TITLES = { home: "Desk", agents: "Agents", activity: "Activity", account: "Account", auditor: "Auditor", shorter: "Shorter", vertailu: "Vertailu" };
function current() { return S.stack.length ? S.stack[S.stack.length - 1] : S.tab; }
function render() {
  const cur = current(), isCoin = cur.startsWith("coin:");
  const m = S.data.state?.mode; const b = $("#mode"); b.textContent = m || "…"; b.className = "badge " + (m === "PAPER" ? "paper" : m === "LIVE" ? "live" : "");
  $("#back").hidden = !S.stack.length;
  $("#title").textContent = isCoin ? (S.coin[cur.slice(5)]?.doc?.coin.name || "Coin") : TITLES[cur];
  view.innerHTML = isCoin ? coin(cur.slice(5)) : { home, agents, activity, account, auditor, shorter, vertailu }[cur]();
  document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x.dataset.tab === S.tab));
  requestAnimationFrame(draw); liveDot();
}
function draw() {
  const bal = $("#bal"); if (bal) chart.line(bal, S.data.chart.points, { base: S.data.chart.start });
  const sb = $("#sbal"); if (sb && S.data.shorter) chart.line(sb, S.data.shorter.curve, { base: S.data.shorter.start });
  const rg = $("#ring"); if (rg) { const v = S.data.state.agents.analyst; chart.ring(rg, v.last?.score ?? null, v.minScore); }
  const dc = $("#disc"); if (dc) { const la = S.data.state.agents.auditor.last; const by = Object.fromEntries(la.layers.map(l => [l.layer, l]));
    chart.disc(dc, [1, 2, 3, 4, 5, 6, 7, 8].map(n => ({ n, pass: by[n] ? !!by[n].pass : null }))); }
  const cd = $("#cdl"); if (cd) { const d = S.coin[current().slice(5)].doc; chart.candles(cd, d.candles, { exitLine: d.exitLine, entry: d.position?.entry_price }); }
}
document.addEventListener("click", e => {
  const t = e.target.closest("[data-tab],[data-coin],[data-go],[data-act],#back"); if (!t || e.target.closest("a")) return;
  if (t.id === "back") S.stack.pop();
  else if (t.dataset.tab) { S.tab = t.dataset.tab; S.stack = []; }
  else if (t.dataset.coin) { S.stack.push("coin:" + t.dataset.coin); loadCoin(t.dataset.coin); }
  else if (t.dataset.go) S.stack.push(t.dataset.go);
  else if (t.dataset.act === "retry") { S.loaded = false; render(); load(); return; }
  else if (t.dataset.act === "pause") { P.paused = !P.paused; P.pending = 0; render(); return; }
  else if (t.dataset.act && t.dataset.act.startsWith("f:")) { P.filter = t.dataset.act.slice(2); render(); return; }
  window.scrollTo(0, 0); render();
});
if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js");
window.__desk = S;
render(); load(); pollLive(); setInterval(pollLive, 4000); setInterval(() => { load(); const c = current(); if (c.startsWith("coin:")) loadCoin(c.slice(5)); }, 15000);
