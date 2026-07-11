const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = (p, opts) => fetch(p, opts).then(r => r.json());
const esc = s => (s ?? "").toString().replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// --- tab switching ---
$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  $$(".view").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("#" + t.dataset.view).classList.add("active");
  if (t.dataset.view === "dashboard") loadDashboard();
  if (t.dataset.view === "rankings") loadRankings();
  if (t.dataset.view === "company") loadCompanies();
}));

// --- fundamental rankings ---
const FLAG_TITLE = {
  M: "Management-disclosed (historical)", C: "Computed from filing figures",
  G: "Forward guidance only (not historical)", P: "ROCE used as ROE proxy",
  MD: "Management-disclosed but dated", NA: "Not available",
};
function cagrCell(val, flag, note, years) {
  if (val == null) return `<td class="na" title="${esc(note || "not available")}">n/a</td>`;
  const star = (years != null && years < 3) ? `<span class="star" title="since-listing window &lt;3y — annualized, treat as inflated">*</span>` : "";
  const fl = flag && flag !== "NA" ? `<sup class="fl fl-${flag}" title="${esc(FLAG_TITLE[flag] || flag)}">${flag}</sup>` : "";
  const cls = val < 0 ? "neg" : "";
  return `<td class="${cls}" title="${esc(note || "")}">${val}%${star}${fl}</td>`;
}
function scoreBar(v) {
  const w = Math.max(0, Math.min(100, v));
  return `<div class="scorebar"><span style="width:${w}%"></span><em>${v}</em></div>`;
}
function valCell(r) {
  const peg = r.peg_ratio;
  if (peg == null) {
    const why = r.trailing_pe == null ? "loss-making — no PE" : "no growth figure available";
    return `<td class="na" title="${esc(why)}">n/a</td>`;
  }
  const under = peg < 1;
  const cls = under ? "under" : "over";
  const label = under ? "Under" : "Over";
  const gs = r.valuation_growth_source;
  const tip = `PE ${r.trailing_pe} ÷ growth ${r.valuation_growth_pct}% (${gs === "C" ? "computed Profit CAGR" : gs === "S" ? "sustainable Sales CAGR" : "1yr YoY earnings growth — volatile"}) = PEG ${peg}`;
  const star = gs === "Y" ? `<span class="star" title="growth = 1yr YoY earnings jump — PEG may be distorted">*</span>` : "";
  return `<td title="${esc(tip)}"><span class="peg ${cls}">${peg}${star}</span><span class="verdict ${cls}">${label}</span></td>`;
}
async function loadRankings() {
  const wrap = $("#rankTable");
  wrap.innerHTML = `<div class="note">Loading ranking…</div>`;
  try {
    const d = await api("/fundamental-ranking");
    $("#rankMethod").textContent = d.methodology || "";
    const rows = (d.ranking || []).map(r => {
      const band = (r.decision_band || "").split(" ")[0];
      const medal = r.rank === 1 ? "🥇" : r.rank === 2 ? "🥈" : r.rank === 3 ? "🥉" : r.rank;
      return `<tr>
        <td class="rk">${medal}</td>
        <td class="nmcell"><b>${esc(r.name)}</b><span class="tick">${esc(r.ticker)}</span></td>
        <td>${scoreBar(r.composite_score)}</td>
        <td>${r.business_quality ?? "–"}${r.decision_band ? ` <span class="band ${band}">${esc(band)}</span>` : ""}</td>
        ${cagrCell(r.stock_price_cagr_pct, null, `${r.stock_cagr_years ?? "?"}y window`, r.stock_cagr_years)}
        ${cagrCell(r.sales_cagr_pct, r.sales_cagr_flag, r.sales_cagr_note)}
        ${cagrCell(r.profit_cagr_pct, r.profit_cagr_flag, r.profit_cagr_note)}
        ${cagrCell(r.roe_pct, r.roe_flag, r.roe_note)}
        ${valCell(r)}
        <td class="compl">${esc(r.completeness || "")}</td>
      </tr>`;
    }).join("");
    wrap.innerHTML = `
      <table class="ranktable">
        <thead><tr>
          <th>#</th><th>Company</th><th>Blended Score</th><th>Business Quality</th>
          <th>Stock CAGR</th><th>Sales CAGR</th><th>Profit CAGR</th><th>ROE</th>
          <th>Valuation<br><span class="thsub">PEG</span></th><th>Data</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="legend">
        <b>Flags:</b>
        <span class="fl fl-M">M</span> mgmt-disclosed ·
        <span class="fl fl-C">C</span> computed ·
        <span class="fl fl-G">G</span> forward-guidance only ·
        <span class="fl fl-P">P</span> ROCE proxy ·
        <span class="fl fl-MD">MD</span> dated ·
        <span class="star">*</span> stock window &lt;3y / YoY growth (may distort) ·
        <b>Valuation:</b> <span class="peg under">PEG&lt;1 Under</span> <span class="peg over">PEG≥1 Over</span> (PE ÷ growth%) ·
        <b>Data</b> = factors present / 4
      </div>`;
  } catch (e) {
    wrap.innerHTML = `<div class="note">Could not load ranking. ${esc(e.message || e)}</div>`;
  }
}

// --- dashboard / leaderboards ---
const BOARDS = [
  ["high_growth", "High Growth"],
  ["aggressive_management", "Aggressive Management"],
  ["consistent_compounders", "Consistent Compounders"],
  ["top_composite", "Top Composite Picks"],
];
async function loadDashboard() {
  const boards = $("#boards");
  try {
    const d = await api("/leaderboards?top_n=10");
    $("#asof").textContent = "as of " + d.as_of_period;
    boards.innerHTML = BOARDS.map(([k, title]) => `
      <div class="board card">
        <h3>${title}</h3>
        <ol>${(d[k] || []).map((e, i) => `
          <li><span class="rank">${i + 1}</span>
            <span class="nm">${esc(e.name)} <span class="tick">${esc(e.ticker)}</span></span>
            <span class="val">${e.value}</span></li>`).join("")}
        </ol>
      </div>`).join("");
  } catch {
    boards.innerHTML = `<div class="note">No scored companies yet. Upload a transcript to get started.</div>`;
    $("#asof").textContent = "";
  }
}

// --- company insights ---
async function loadCompanies() {
  const sel = $("#companySelect");
  const list = await api("/companies");
  sel.innerHTML = list.map(c => `<option value="${c.id}">${esc(c.name)} (${esc(c.ticker)})</option>`).join("");
  if (list.length) loadInsights(sel.value);
}
$("#refreshCompany").addEventListener("click", () => loadInsights($("#companySelect").value));
$("#companySelect")?.addEventListener("change", e => loadInsights(e.target.value));

function barClass(v) { return v >= 7 ? "high" : v >= 5 ? "mid" : "low"; }

async function loadInsights(id) {
  const wrap = $("#companyInsights");
  if (!id) { wrap.innerHTML = ""; return; }
  const [ins, chains] = await Promise.all([
    api(`/companies/${id}/insights`),
    api(`/companies/${id}/guidance-chains`),
  ]);
  const s = ins.score || {};
  const band = (s.decision_band || "").split(" ")[0];

  const v = ins.valuation;
  let valuationCard = "";
  if (v) {
    if (v.peg != null) {
      const under = v.peg < 1;
      const cls = under ? "under" : "over";
      const gsLabel = v.growth_source === "C" ? "computed Profit CAGR"
        : v.growth_source === "S" ? "sustainable Sales CAGR"
        : v.growth_source === "Y" ? "1-yr YoY earnings growth (volatile)" : "n/a";
      const warn = v.growth_source === "Y"
        ? `<div class="muted" style="font-size:12px;margin-top:6px">⚠ Growth = single-year YoY jump — PEG may be distorted.</div>` : "";
      valuationCard = `
        <div class="card">
          <h3 class="sec">💰 Section 9 — Valuation (PEG)</h3>
          <div class="peg-head">
            <div class="peg-big ${cls}">${v.peg}<span>PEG</span></div>
            <div>
              <span class="verdict-badge ${cls}">${under ? "Undervalued" : "Overvalued"}</span>
              <div class="metrics-inline" style="margin-top:10px">
                <span>Current PE <b>${v.trailing_pe ?? "–"}</b></span>
                <span>Growth <b>${v.growth_pct ?? "–"}%</b></span>
                <span>Growth basis <b>${esc(gsLabel)}</b></span>
              </div>
              <div class="muted" style="font-size:12px;margin-top:8px">
                PEG = PE ÷ Growth% = ${v.trailing_pe} ÷ ${v.growth_pct} = <b>${v.peg}</b>.
                Rule: PEG &lt; 1 ⇒ undervalued, else overvalued.
              </div>
              ${warn}
            </div>
          </div>
        </div>`;
    } else {
      const why = v.trailing_pe == null ? "Company is loss-making — no meaningful PE." : "No reliable growth figure available.";
      valuationCard = `
        <div class="card">
          <h3 class="sec">💰 Section 9 — Valuation (PEG)</h3>
          <div class="muted">PEG not computable. ${esc(why)}
          ${v.trailing_pe != null ? ` (Current PE ${v.trailing_pe})` : ""}</div>
        </div>`;
    }
  }

  const sections = (ins.sections || []).map(x => `
    <div class="section-bar">
      <div class="lab"><span>${x.no}. ${esc(x.name)}</span><span>${x.score}/10</span></div>
      <div class="bar ${barClass(x.score)}"><span style="width:${x.score * 10}%"></span></div>
      ${x.rationale ? `<div class="muted" style="font-size:12px;margin-top:3px">${esc(x.rationale)}</div>` : ""}
    </div>`).join("");

  const flags = (ins.red_flags || []).map(f => `
    <div class="flag ${f.severity}">
      <span class="t">${esc(f.type.replace(/_/g, " "))}</span><span class="sev ${f.severity}">${esc(f.severity)}</span>
      <div>${esc(f.description)}</div>
      ${f.quote ? `<div class="q">“${esc(f.quote)}”</div>` : ""}
    </div>`).join("") || `<div class="muted">No red flags recorded.</div>`;

  const future = (ins.future_guidance || []).map(g => `
    <div class="guide">
      <span class="arrow ${g.direction || "flat"}">${g.direction === "up" ? "▲" : g.direction === "down" ? "▼" : "▬"}</span>
      <div>
        <b>${esc(g.metric_name.replace(/_/g, " "))}</b>
        ${g.target_value != null ? `→ ${g.target_value}${esc(g.target_unit || "")}` : ""}
        <span class="muted">by ${esc(g.target_period)}</span>
        <div class="g-quote">“${esc(g.quote)}”</div>
      </div>
    </div>`).join("") || `<div class="muted">No forward guidance extracted.</div>`;

  const chainHtml = (chains || []).map(c => `
    <div class="chain">
      <div class="top">
        <div><b>${esc(c.metric_name.replace(/_/g, " "))}</b>
          <span class="meta">(${esc(c.category)}) · promised ${esc(c.created_period)} → target ${esc(c.target_period)}
          ${c.target_value != null ? "· " + c.target_value + esc(c.target_unit || "") : ""}</span>
        </div>
        <span class="status ${c.current_status}">${esc(c.current_status)}</span>
      </div>
      <div class="q">“${esc(c.raw_quote)}”</div>
      ${c.chain.length ? `<div class="timeline">${c.chain.map(l => `
        <span class="node">${esc(l.resolved_period)}: <span class="status ${l.status}">${esc(l.status)}</span>
        ${l.actual_value != null ? " (" + l.actual_value + ")" : ""}
        ${l.variance_pct != null ? " · " + l.variance_pct + "%" : ""}</span>`).join("")}</div>`
      : `<div class="muted" style="font-size:12px;margin-top:6px">Awaiting a future quarter to resolve this promise.</div>`}
    </div>`).join("") || `<div class="muted">No guidance chains yet.</div>`;

  wrap.innerHTML = `
    <div class="card">
      <div class="score-head">
        <div class="gauge"><div class="num">${s.total_0_100 ?? "–"}</div><div class="den">/ 100</div></div>
        <div>
          <span class="band ${band}">${esc(s.decision_band || "Not scored")}</span>
          <div class="metrics-inline" style="margin-top:10px">
            <span>Guidance reliability <b>${pct(s.guidance_reliability)}</b></span>
            <span>Growth <b>${s.growth ?? "–"}/10</b></span>
            <span>Aggression <b>${fmt(s.aggression)}</b></span>
            <span>Consistency <b>${fmt(s.consistency)}</b></span>
            <span>As of <b>${esc(ins.as_of || "–")}</b></span>
          </div>
        </div>
      </div>
    </div>
    <div class="card"><h3 class="sec">Business Analysis Template — 10 sections</h3>${sections}</div>
    ${valuationCard}
    <div class="card"><h3 class="sec">🚩 Red flags</h3>${flags}</div>
    <div class="card"><h3 class="sec">🔮 Future guidance / next projections</h3>${future}</div>
    <div class="card"><h3 class="sec">🔗 Guidance → Outcome chains</h3>${chainHtml}</div>`;
}
function pct(v) { return v == null ? "–" : Math.round(v * 100) + "%"; }
function fmt(v) { return v == null ? "–" : v; }

// --- upload ---
$("#uploadForm").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  const res = $("#uploadResult");
  res.innerHTML = `<div class="note">Uploading & extracting…</div>`;

  // ensure company exists (get-or-create by ticker)
  const ticker = f.ticker.value.trim();
  let companies = await api("/companies");
  let company = companies.find(c => c.ticker === ticker);
  if (!company) {
    company = await api("/companies", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, name: f.name.value.trim() }),
    });
  }

  const fd = new FormData();
  fd.append("fiscal_year", f.fiscal_year.value);
  fd.append("quarter", f.quarter.value);
  fd.append("file", f.file.files[0]);
  const out = await api(`/companies/${company.id}/transcripts`, { method: "POST", body: fd });

  if (out.status === "processed") {
    res.innerHTML = `<div class="note">✅ Analyzed. Score <b>${out.total_0_100}/100</b> — ${esc(out.decision_band)}.
      Guidance issued: ${out.guidance_issued}, resolved from prior quarters: ${out.guidance_resolved}.
      Open <b>Company Insights</b> to view.</div>`;
  } else if (out.status === "awaiting_analysis") {
    res.innerHTML = `<div class="note">📄 Extracted ${out.chars_extracted} characters.<br>${esc(out.message)}</div>`;
  } else if (out.status === "duplicate_no_op") {
    res.innerHTML = `<div class="note">This quarter was already uploaded (identical file). No changes.</div>`;
  } else {
    res.innerHTML = `<div class="note">${esc(JSON.stringify(out))}</div>`;
  }
});

loadDashboard();
