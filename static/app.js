/* Shared by both Aurora fixtures — conflict-exo-pg and conflict-quake-mysql
   serve identical API shapes so one frontend covers both engines. Inline SVG,
   no CDN: a private install should not reach out to draw its own dashboard. */
"use strict";

const LEAD = "#8FD82A";
const WARN = "#E0B34A";
// Past this, a connect is Aurora resuming rather than a slow network: a warm
// connect to a running writer is tens of milliseconds.
const RESUME_MS = 2000;
const tip = document.getElementById("tip");

const fmt = (n, d = 0) =>
  n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

const el = (tag, attrs = {}, kids = []) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  for (const kid of [].concat(kids)) node.appendChild(kid);
  return node;
};

function showTip(evt, html) {
  tip.innerHTML = html;
  tip.classList.add("on");
  const pad = 14;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => tip.classList.remove("on");

function niceTicks(max, count = 4) {
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  return { ticks: out, top: out[out.length - 1] || 1 };
}

function barPath(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return `M${x},${y + h}V${y + rr}a${rr},${rr} 0 0 1 ${rr},${-rr}h${w - 2 * rr}a${rr},${rr} 0 0 1 ${rr},${rr}V${y + h}Z`;
}

/* ---------- the hero: connection latency, resumes called out ---------- */
function connectChart(host, rows) {
  if (!rows.length) {
    host.innerHTML = `<p class="mark-label" style="font-family:var(--mono);color:var(--muted)">` +
      `No connections recorded yet.</p>`;
    return;
  }
  const W = 1000, H = 260, m = { t: 16, r: 14, b: 34, l: 62 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const { ticks, top: max } = niceTicks(Math.max(...rows.map((d) => d.connect_ms), RESUME_MS * 1.2));
  const step = iw / rows.length;
  const bw = Math.max(2, step - 2);
  const y = (v) => ih - (v / max) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Database connection latency, most recent first" });
  const g = el("g", { transform: `translate(${m.l},${m.t})` });

  for (const v of ticks) {
    g.appendChild(el("line", { class: "gridline", x1: 0, x2: iw, y1: y(v), y2: y(v) }));
    g.appendChild(el("text", { class: "axis", x: -8, y: y(v) + 3.5, "text-anchor": "end" },
      [document.createTextNode(fmt(v))]));
  }

  // The resume threshold, drawn as a reference line so a long bar is readable
  // as "the cluster was asleep" rather than just "this one was slow".
  g.appendChild(el("line", {
    x1: 0, x2: iw, y1: y(RESUME_MS), y2: y(RESUME_MS),
    stroke: WARN, "stroke-width": 1, "stroke-dasharray": "4 3", "stroke-opacity": ".7",
  }));
  g.appendChild(el("text", {
    class: "axis", x: iw, y: y(RESUME_MS) - 6, "text-anchor": "end", fill: WARN,
  }, [document.createTextNode("resume threshold 2s")]));

  rows.forEach((d, i) => {
    const h = ih - y(d.connect_ms);
    const p = el("path", {
      d: barPath(i * step, y(d.connect_ms), bw, h, 4),
      fill: d.likely_resume ? WARN : LEAD,
    });
    p.addEventListener("mousemove", (e) => showTip(e,
      `<div>${d.at.replace("T", " ").replace("Z", "")}Z</div>` +
      `<div><span class="k">connect</span> ${fmt(d.connect_ms, 1)} ms</div>` +
      `<div><span class="k">${d.likely_resume ? "resumed from 0 ACU" : "cluster was warm"}</span></div>`));
    p.addEventListener("mouseleave", hideTip);
    g.appendChild(p);
  });

  g.appendChild(el("line", { class: "axis", x1: 0, x2: iw, y1: ih, y2: ih }));
  g.appendChild(el("text", { class: "axis", x: iw / 2, y: ih + 28, "text-anchor": "middle" },
    [document.createTextNode("connection latency (ms) — newest on the left")]));
  svg.appendChild(g);

  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML =
    `<span><span class="swatch" style="background:${LEAD}"></span>warm connect</span>` +
    `<span><span class="swatch" style="background:${WARN}"></span>resumed from 0 ACU</span>`;
  host.replaceChildren(svg, legend);
}

function bucketChart(host, rows, unit) {
  if (!rows.length) return;
  const W = 720, H = 280, m = { t: 14, r: 12, b: 40, l: 54 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const { ticks, top: max } = niceTicks(Math.max(...rows.map((d) => d.n)));
  const step = iw / rows.length;
  const bw = Math.max(1, step - 2);
  const y = (v) => ih - (v / max) * ih;
  const every = Math.max(1, Math.ceil(rows.length / 8));

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Distribution of ${unit}` });
  const g = el("g", { transform: `translate(${m.l},${m.t})` });
  for (const v of ticks) {
    g.appendChild(el("line", { class: "gridline", x1: 0, x2: iw, y1: y(v), y2: y(v) }));
    g.appendChild(el("text", { class: "axis", x: -8, y: y(v) + 3.5, "text-anchor": "end" },
      [document.createTextNode(fmt(v))]));
  }
  rows.forEach((d, i) => {
    const h = ih - y(d.n);
    const p = el("path", { class: "bar", d: barPath(i * step, y(d.n), bw, h, 4) });
    p.addEventListener("mousemove", (e) => showTip(e,
      `<div>${d.bucket}</div><div><span class="k">${unit}</span> ${fmt(d.n)}</div>`));
    p.addEventListener("mouseleave", hideTip);
    g.appendChild(p);
    if (i % every === 0 || i === rows.length - 1) {
      g.appendChild(el("text", { class: "axis", x: i * step + bw / 2, y: ih + 16,
        "text-anchor": "middle" }, [document.createTextNode(String(d.bucket))]));
    }
  });
  g.appendChild(el("line", { class: "axis", x1: 0, x2: iw, y1: ih, y2: ih }));
  svg.appendChild(g);
  host.replaceChildren(svg);
}

function topTable(host, rows) {
  host.innerHTML =
    `<table class="table"><thead><tr><th>Name</th>` +
    `<th style="text-align:right">Value</th><th style="text-align:right">Secondary</th>` +
    `</tr></thead><tbody>` +
    rows.map((d) =>
      `<tr><td>${d.label}</td><td class="num">${fmt(d.value, 2)}</td>` +
      `<td class="num">${d.depth === null ? "—" : fmt(d.depth, 1)}</td></tr>`).join("") +
    "</tbody></table>";
}

function connectTable(host, rows, seed) {
  const resumes = rows.filter((r) => r.likely_resume).length;
  const warm = rows.length - resumes;
  const fastest = rows.length ? Math.min(...rows.map((r) => r.connect_ms)) : null;
  host.innerHTML =
    `<div class="legend" style="margin-top:1rem">` +
    `<span>${rows.length} connections recorded</span>` +
    `<span>${resumes} resumed from zero</span>` +
    `<span>${warm} warm</span>` +
    `<span>fastest ${fmt(fastest, 1)} ms</span>` +
    `<span>seed ${seed && seed.state ? seed.state : "—"}</span>` +
    `</div>`;
}

function tiles(host, s) {
  const items = [
    { num: fmt(s.events), lbl: `${s.unit} in the database`, sub: s.engine },
    { num: fmt(s.last_connect_ms, 1), lbl: "last connect (ms)",
      sub: s.last_connect_ms > RESUME_MS ? "included a resume" : "cluster was warm" },
    { num: "0", lbl: "minimum ACU", sub: "auto-pause after 5 idle minutes" },
    { num: fmt(s.significant), lbl: s.max_mag === null ? "distinct hosts" : "at M4.5 or above",
      sub: s.strongest_place || "—" },
  ];
  host.innerHTML = items.map((i) =>
    `<div class="tile"><div class="num">${i.num}</div>` +
    `<div class="lbl">${i.lbl}</div><div class="sub">${i.sub}</div></div>`).join("");
}

const get = (p) => fetch(p).then((r) => {
  if (!r.ok) return r.json().then((b) => { throw new Error(b.error || `${p} -> ${r.status}`); });
  return r.json();
});

async function main() {
  try {
    const [s, buckets, top, conns, dbg] = await Promise.all([
      get("/api/summary"), get("/api/buckets"), get("/api/top"),
      get("/api/connections"), get("/debug"),
    ]);
    document.title = `${s.title} — Astrolift demo`;
    document.getElementById("brand").childNodes[0].nodeValue = s.title;
    document.getElementById("brand-slug").textContent = dbg.app;
    tiles(document.getElementById("tiles"), s);
    connectChart(document.getElementById("c-connect"), conns.history);
    connectTable(document.getElementById("t-connect"), conns.history, conns.seed);
    bucketChart(document.getElementById("c-buckets"), buckets, s.unit);
    topTable(document.getElementById("t-top"), top);
    document.getElementById("f-engine").textContent = s.engine;
    document.getElementById("f-version").textContent = `version ${dbg.version}`;
    document.getElementById("f-pod").textContent = `pod ${dbg.hostname}`;
    document.getElementById("f-seed").textContent = `seed ${dbg.seed.state}`;
  } catch (err) {
    const h = document.getElementById("health");
    h.className = "status status--err";
    h.textContent = "degraded";
    document.getElementById("lede").innerHTML =
      `Could not read the database: <code>${err.message}</code>. ` +
      `If the cluster is resuming from 0 ACU this clears on its own within a minute.`;
    console.error(err);
  }
}
main();
