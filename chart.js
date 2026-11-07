// Hand-drawn canvas charts. No library.
function setup(cv, h, fw) {
  const dpr = window.devicePixelRatio || 1, w = fw || cv.clientWidth || 360;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + "px";
  const x = cv.getContext("2d"); x.scale(dpr, dpr); return [x, w, h];
}
export function line(cv, pts, { h = 140, base = null } = {}) {
  const [x, w] = setup(cv, h);
  if (!pts.length) return;
  const v = pts.map(p => p.value), lo = Math.min(...v, base ?? Infinity), hi = Math.max(...v, base ?? -Infinity), pad = (hi - lo) * 0.1 || 1;
  const Y = y => h - 8 - (y - lo + pad) / (hi - lo + 2 * pad) * (h - 16), X = i => pts.length === 1 ? w / 2 : i / (pts.length - 1) * w;
  const up = v[v.length - 1] >= (base ?? v[0]), col = up ? "#22c55e" : "#ef4444";
  if (base != null) { x.strokeStyle = "#2a3142"; x.setLineDash([4, 4]); x.beginPath(); x.moveTo(0, Y(base)); x.lineTo(w, Y(base)); x.stroke(); x.setLineDash([]); }
  const g = x.createLinearGradient(0, 0, 0, h); g.addColorStop(0, up ? "rgba(34,197,94,.25)" : "rgba(239,68,68,.25)"); g.addColorStop(1, "rgba(0,0,0,0)");
  x.beginPath(); v.forEach((y, i) => i ? x.lineTo(X(i), Y(y)) : x.moveTo(X(i), Y(y)));
  x.strokeStyle = col; x.lineWidth = 2; x.stroke();
  x.lineTo(X(v.length - 1), h); x.lineTo(X(0), h); x.closePath(); x.fillStyle = g; x.fill();
}
export function candles(cv, cs, { h = 220, exitLine = null, entry = null } = {}) {
  const [x, w] = setup(cv, h);
  if (!cs.length) return;
  const lv = [...cs.map(c => c.l), ...cs.map(c => c.h)]; if (exitLine) lv.push(exitLine); if (entry) lv.push(entry);
  const lo = Math.min(...lv), hi = Math.max(...lv), pad = (hi - lo) * 0.08 || hi * 0.05 || 1e-9;
  const Y = y => 10 + (1 - (y - lo + pad) / (hi - lo + 2 * pad)) * (h - 20);
  const n = Math.max(cs.length, 20), cw = w / n, bw = Math.max(2, cw * 0.6);
  cs.forEach((c, i) => {
    const cx = (n - cs.length + i) * cw + cw / 2, up = c.c >= c.o; x.strokeStyle = x.fillStyle = up ? "#22c55e" : "#ef4444";
    x.beginPath(); x.moveTo(cx, Y(c.h)); x.lineTo(cx, Y(c.l)); x.lineWidth = 1; x.stroke();
    const t = Y(Math.max(c.o, c.c)), b = Y(Math.min(c.o, c.c)); x.fillRect(cx - bw / 2, t, bw, Math.max(1, b - t));
  });
  const hline = (y, col, label, dash) => {
    x.strokeStyle = col; x.setLineDash(dash); x.lineWidth = 1.5; x.beginPath(); x.moveTo(0, Y(y)); x.lineTo(w, Y(y)); x.stroke(); x.setLineDash([]);
    x.fillStyle = col; x.font = "600 11px -apple-system,system-ui"; x.fillText(label, 6, Y(y) - 5);
  };
  if (entry) hline(entry, "#8a93a6", "entry", [2, 3]);
  if (exitLine) hline(exitLine, "#f59e0b", "Risk trailing stop", [6, 4]);
}
export function ring(cv, score, min, size = 96) {
  cv.style.width = size + "px"; const [x] = setup(cv, size, size); const r = size / 2 - 7, c = size / 2;
  x.lineWidth = 8; x.strokeStyle = "#232938"; x.beginPath(); x.arc(c, c, r, 0, Math.PI * 2); x.stroke();
  if (score != null) { x.strokeStyle = score >= min ? "#22c55e" : "#ef4444"; x.lineCap = "round"; x.beginPath(); x.arc(c, c, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * score / 100); x.stroke(); }
  x.fillStyle = "#e8ecf3"; x.font = "800 24px -apple-system,system-ui"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(score ?? "–", c, c);
}
export function disc(cv, layers, size = 240) {
  // 8 segments; cyan beam on the running layer, green ok, red failed, grey not checked
  cv.style.width = size + "px"; const [x] = setup(cv, size, size); const c = size / 2, r = size / 2 - 14;
  layers.forEach((l, i) => {
    const a0 = -Math.PI / 2 + i * Math.PI / 4 + 0.04, a1 = a0 + Math.PI / 4 - 0.08;
    x.strokeStyle = l.pass === true ? "#22c55e" : l.pass === false ? "#ef4444" : l.running ? "#22d3ee" : "#232938";
    x.lineWidth = 16; x.beginPath(); x.arc(c, c, r, a0, a1); x.stroke();
    const am = (a0 + a1) / 2; x.fillStyle = "#8a93a6"; x.font = "700 11px -apple-system,system-ui"; x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText(l.n, c + Math.cos(am) * (r - 22), c + Math.sin(am) * (r - 22));
  });
}
