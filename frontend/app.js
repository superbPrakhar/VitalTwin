/* VitalTwin PoC — dashboard logic (vanilla JS, no build step) */
"use strict";

const API = "";  // same origin
if (window.Chart) { Chart.defaults.animation = false; }   // stable renders, instant updates
const charts = {};
let patients = [];
let current = null;
let leverValues = {};

const T0 = Date.UTC(2026, 10, 1);           // matches app.main._iso anchor
const iso = (t) => new Date(T0 + t * 3600e3).toISOString().slice(5, 16).replace("T", " ");

const $ = (sel) => document.querySelector(sel);
const el = (id) => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const model = await api("/api/model");
    el("modelBadge").textContent = `TwinRisk v1 · AUROC ${model.meta.val_auroc} (synthetic)`;
  } catch { el("modelBadge").textContent = "model: not loaded"; }
  await refreshPatients();
  setInterval(() => el("apiBase") && (el("apiBase").textContent = location.origin), 500);
}

async function refreshPatients() {
  patients = await api("/api/patients");
  renderPatientList();
}

function renderPatientList() {
  const wrap = el("patientList");
  wrap.innerHTML = "";
  for (const p of patients) {
    const div = document.createElement("div");
    div.className = "patient-card" + (current === p.patient_id ? " active" : "");
    const band = p.risk_band || "low";
    div.innerHTML = `
      <div class="pc-top">
        <span class="pc-name">${p.name}</span>
        <span class="dot ${band === "high" ? "alert" : band === "elevated" ? "watch" : "ok"}"></span>
      </div>
      <div class="pc-sub">${p.age}y ${p.sex} · HbA1c≈${p.hba1c_est}% · NEWS2 ${p.news2}</div>
      <div class="chips">${p.conditions.map((c) => `<span class="chip">${c}</span>`).join("")}</div>`;
    div.onclick = () => selectPatient(p.patient_id);
    wrap.appendChild(div);
  }
}

async function selectPatient(pid) {
  current = pid;
  const p = patients.find((x) => x.patient_id === pid);
  el("patientHeader").classList.remove("hidden");
  el("tabs").classList.remove("hidden");
  el("welcome").classList.add("hidden");
  el("phName").textContent = p.name;
  el("phMeta").textContent = `${p.age}y ${p.sex} · synthetic demo patient`;
  el("phAvatar").textContent = p.name.split(" ").map((w) => w[0]).join("");
  el("phConditions").innerHTML = p.conditions.map((c) => `<span class="chip">${c}</span>`).join("");
  setRiskPill(p.risk_probability, p.risk_band);
  renderPatientList();
  await Promise.all([loadMirror(), loadRisk(), loadTrends(), loadReport()]);
  buildLevers();
  showTab("mirror");
}

function setRiskPill(prob, band) {
  const pill = el("phRisk");
  pill.className = "risk-pill risk-" + (band || "low");
  pill.textContent = prob == null ? "—" : `48h risk ${(prob * 100).toFixed(1)}%`;
}

/* ------------------------------------------------------------------ tabs */
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((s) => s.classList.add("hidden"));
  el("tab-" + name).classList.remove("hidden");
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => showTab(t.dataset.tab)));

/* ------------------------------------------------------------------ mirror */
async function loadMirror() {
  const [mirror, hourly] = await Promise.all([
    api(`/api/patients/${current}/mirror`),
    api(`/api/patients/${current}/hourly?hours=48`),
  ]);
  el("mirrorTime").textContent = `· ${mirror.t_iso}`;
  const est = mirror.latest_estimate;
  const tempC = (mirror.latest_estimate.temp_dev ?? 0);
  const vitals = [
    ["HR", Math.round(est.hr), "bpm", Math.abs(est.hr_z || 0) > 2.5 ? "alert" : Math.abs(est.hr_z || 0) > 1.5 ? "warn" : ""],
    ["BP", est.sbp != null ? `${Math.round(est.sbp)}/${Math.round(est.dbp)}` : "—", "mmHg", ""],
    ["SpO₂", Math.round(est.spo2 * 10) / 10, "%", est.spo2 < 91 ? "alert" : est.spo2 < 93 ? "warn" : ""],
    ["Glucose", Math.round(est.glucose), "mg/dL", est.glucose < 70 || est.glucose > 250 ? "alert" : ""],
    ["HRV", est.hrv != null ? Math.round(est.hrv) : "—", "ms", Math.abs(est.hrv_z || 0) > 2.5 ? "warn" : ""],
    ["Temp dev", (tempC >= 0 ? "+" : "") + tempC.toFixed(1), "°C skin", tempC > 0.9 ? "warn" : ""],
  ];
  el("vitalsGrid").innerHTML = vitals.map(([l, v, u, cls]) => `
    <div class="vital ${cls}"><div class="v">${v}<span class="muted small"> ${u}</span></div><div class="l">${l}</div></div>`).join("");
  el("organList").innerHTML = mirror.organ_status.map((o) => `
    <div class="organ-row">
      <div><div class="organ-name">${o.system}</div><div class="organ-metrics">${o.metrics}</div></div>
      <div class="dot ${o.status}"></div>
    </div>`).join("");
  const alarms = await api(`/api/patients/${current}/risk`);
  renderAlarms(alarms.live_alarms);
  el("fusionInfo").textContent =
    `${mirror.assimilated_hours} h assimilated · baseline ${mirror.baseline_warmed_up ? "established" : "warming up (14 d)"} · ` +
    `channels: PPG-HR, HRV, SpO₂, steps, sleep, skin temp, CGM, home BP`;
  drawGlucose(hourly.records);
  drawHr(hourly.records);
}

function renderAlarms(alarms) {
  el("alarmList").innerHTML = alarms && alarms.length
    ? alarms.map((a) => `<div class="alarm">⚠ ${a.message}</div>`).join("")
    : `<div class="quiet">✓ No threshold alarms — within safe range</div>`;
}

function chartFor(id, cfg) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(el(id), cfg);
  return charts[id];
}

function drawGlucose(records) {
  const recs = records.filter((r) => r.est.glucose != null);
  chartFor("glucoseChart", {
    type: "line",
    data: {
      labels: recs.map((r) => iso(r.t)),
      datasets: [
        { label: "glucose (mg/dL)", data: recs.map((r) => r.est.glucose),
          borderColor: "#f0b429", backgroundColor: "rgba(240,180,41,.12)",
          fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
        { label: "hypo 70", data: recs.map(() => 70), borderColor: "rgba(242,96,122,.55)", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.2 },
        { label: "upper 180", data: recs.map(() => 180), borderColor: "rgba(53,201,142,.55)", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.2 },
      ]
    },
    options: baseOpts(),
  });
}

function drawHr(records) {
  const recs = records.filter((r) => r.est.hr != null);
  chartFor("hrChart", {
    type: "line",
    data: {
      labels: recs.map((r) => iso(r.t)),
      datasets: [
        { label: "HR (bpm)", data: recs.map((r) => r.est.hr), borderColor: "#4f8cff", tension: 0.35, pointRadius: 0, borderWidth: 2 },
        { label: "HRV RMSSD (ms)", data: recs.map((r) => r.est.hrv), borderColor: "#7bd0ff", tension: 0.35, pointRadius: 0, borderWidth: 1.5, borderDash: [4, 3] },
      ]
    },
    options: baseOpts(),
  });
}

function baseOpts() {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { color: "#8fa0bd", font: { size: 10 } } } },
    scales: {
      x: { ticks: { color: "#8fa0bd", maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "rgba(42,58,92,.35)" } },
      y: { ticks: { color: "#8fa0bd", font: { size: 10 } }, grid: { color: "rgba(42,58,92,.35)" } },
    },
  };
}

/* ------------------------------------------------------------------ risk */
async function loadRisk() {
  const [risk, feed] = await Promise.all([
    api(`/api/patients/${current}/risk`),
    api(`/api/patients/${current}/alerts`),
  ]);
  const p = risk.twinrisk.probability;
  const band = risk.twinrisk.band;
  setRiskPill(p, band);
  const pct = Math.min(100, Math.round(p * 100));
  const gauge = el("riskGauge");
  gauge.style.setProperty("--pct", pct);
  gauge.style.setProperty("--gauge-color", band === "high" ? "#f2607a" : band === "elevated" ? "#f0b429" : band === "watch" ? "#7bd0ff" : "#35c98e");
  el("riskValue").textContent = (p * 100).toFixed(1) + "%";
  el("riskBand").textContent = band;
  el("riskThresholdNote").textContent =
    `alert threshold ${(risk.twinrisk.threshold * 100).toFixed(1)}% · calibrated on synthetic cohort`;

  el("news2Score").innerHTML = `${risk.news2.score} <span class="muted small">/ band: ${risk.news2.band}</span>`;
  el("news2Parts").innerHTML = Object.entries(risk.news2.parts)
    .map(([k, v]) => `<div class="news2-part"><span class="muted">${k}</span><b>${v}</b></div>`).join("");

  const drivers = risk.twinrisk.drivers;
  chartFor("driversChart", {
    type: "bar",
    data: {
      labels: drivers.map((d) => d.feature),
      datasets: [{ data: drivers.map((d) => d.contribution), backgroundColor: drivers.map((d) => d.contribution >= 0 ? "rgba(242,96,122,.75)" : "rgba(53,201,142,.75)") }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { title: (items) => featureTip(items[0].label, drivers) } } },
      scales: { x: { ticks: { color: "#8fa0bd", font: { size: 10 } }, grid: { color: "rgba(42,58,92,.35)" } },
                y: { ticks: { color: "#cdd8ec", font: { size: 10 } }, grid: { display: false } } },
    },
  });

  const hist = risk.history || [];
  chartFor("riskHistoryChart", {
    type: "line",
    data: {
      labels: hist.map((h) => iso(h.t)),
      datasets: [
        { label: "TwinRisk", data: hist.map((h) => h.p), borderColor: "#f2607a", backgroundColor: "rgba(242,96,122,.12)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "threshold", data: hist.map(() => risk.twinrisk.threshold), borderColor: "rgba(240,180,41,.7)", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 },
      ],
    },
    options: baseOpts(),
  });

  el("alertFeed").innerHTML = feed.alerts.length
    ? feed.alerts.slice().reverse().map((a) => `
      <div class="alert-item ${a.band === "high" ? "hot" : "warm"}">
        <div class="t">${iso(a.t)} · probability ${(a.probability * 100).toFixed(1)}%</div>
        <div>${a.message}</div>
        ${a.lead_hours != null ? `<div class="lead">⏱ detected ${a.lead_hours}h before acute onset</div>` : ""}
      </div>`).join("")
    : `<div class="quiet">✓ No deterioration alerts in the twin's history window.</div>`;
}

const FEATURE_LABELS = {
  hr_evening_z: "evening HR vs baseline", hrv_evening_z: "evening HRV vs baseline",
  rest_hr_z: "night resting HR", hrv_night_z: "night HRV",
  hr_up_hrv_down: "HR↑ + HRV↓ composite", temp_dev_3d_z: "skin temp 3-day trend",
  temp_dev_max_z: "skin temp peak", rr_max_z: "respiration rate peak",
  sleep_frag_3d: "sleep fragmentation", sleep_debt_7d: "7-day sleep debt",
  spo2_dip_3d: "SpO₂ dips", glucose_mean_z: "mean glucose", glucose_cv_3d: "glucose variability",
  steps_ratio: "activity vs baseline", age: "age", bmi: "BMI", comorbidity_count: "comorbidities",
};
function featureTip(f) { return FEATURE_LABELS[f] || f; }

/* ------------------------------------------------------------------ trends */
async function loadTrends() {
  const t = await api(`/api/patients/${current}/trends?days=21`);
  const s = t.summaries;
  const labels = s.map((d) => "d" + d.day_index);
  chartFor("trendHrChart", {
    type: "line",
    data: { labels, datasets: [
      { label: "resting HR", data: s.map((d) => d.rest_hr), borderColor: "#4f8cff", tension: 0.35, pointRadius: 2, borderWidth: 2 },
      { label: "night HRV (ms)", data: s.map((d) => d.night_hrv_mean), borderColor: "#7bd0ff", tension: 0.35, pointRadius: 2, borderWidth: 1.5, borderDash: [4, 3] },
    ] },
    options: baseOpts(),
  });
  chartFor("trendSleepChart", {
    type: "bar",
    data: { labels, datasets: [
      { label: "sleep (h)", data: s.map((d) => d.sleep_hours), backgroundColor: "rgba(123,208,255,.6)", borderRadius: 4 },
      { label: "fragmentation", data: s.map((d) => d.sleep_frag), type: "line", borderColor: "#f0b429", pointRadius: 0, borderWidth: 1.5, yAxisID: "y1" },
    ] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8fa0bd", font: { size: 10 } } } },
      scales: {
        x: { ticks: { color: "#8fa0bd", maxTicksLimit: 8, font: { size: 10 } }, grid: { color: "rgba(42,58,92,.35)" } },
        y: { ticks: { color: "#8fa0bd", font: { size: 10 } }, grid: { color: "rgba(42,58,92,.35)" }, beginAtZero: true },
        y1: { position: "right", grid: { display: false }, ticks: { color: "#8fa0bd", font: { size: 10 } } },
      },
    },
  });
  chartFor("trendStepsChart", {
    type: "bar",
    data: { labels, datasets: [{ label: "steps", data: s.map((d) => d.steps), backgroundColor: "rgba(53,201,142,.6)", borderRadius: 4 }] },
    options: baseOpts(),
  });
  chartFor("trendGlucoseChart", {
    type: "line",
    data: { labels, datasets: [
      { label: "mean glucose (mg/dL)", data: s.map((d) => d.glucose_mean), borderColor: "#f0b429", tension: 0.35, pointRadius: 2, borderWidth: 2 },
      { label: "TIR (%)", data: s.map((d) => d.tir_pct), borderColor: "#35c98e", tension: 0.35, pointRadius: 2, borderWidth: 1.5, borderDash: [4, 3] },
    ] },
    options: baseOpts(),
  });
}

/* ------------------------------------------------------------------ sync */
el("syncBtn").onclick = async () => {
  el("syncStatus").textContent = "syncing…";
  try {
    const res = await api(`/api/patients/${current}/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hours: 6 }),
    });
    el("syncStatus").textContent = `+${res.synced_hours}h · ${res.pending_hours}h buffered`;
    setRiskPill(res.risk.twinrisk.probability, res.risk.twinrisk.band);
    await Promise.all([loadMirror(), loadRisk()]);
    await refreshPatients();
    if (res.new_alerts.length) {
      showTab("risk");
    }
  } catch (e) {
    el("syncStatus").textContent = "sync failed: " + e.message;
  }
};

/* ------------------------------------------------------------------ protocol studio */
const LEVERS = [
  ["metformin_mg", "Metformin (mg/day)", 0, 3000, 250, 0],
  ["antihyp_mmhg", "Antihypertensive effect (mmHg)", 0, 25, 1, 0],
  ["steps_day", "Steps / day", 1000, 15000, 250, 0],
  ["sleep_hours", "Sleep (h/night)", 4.5, 9, 0.25, 1],
  ["carbs_day", "Carbohydrates (g/day)", 80, 400, 10, 0],
  ["gi", "Diet glycaemic index", 0.4, 0.9, 0.02, 2],
  ["kcal_delta_day", "Dietary change (kcal/day)", -800, 500, 50, 0],
  ["stress_level", "Chronic stress (0-1)", 0.1, 0.9, 0.05, 2],
];

function buildLevers() {
  const wrap = el("levers");
  wrap.innerHTML = "";
  leverValues = {};
  for (const [key, label, min, max, step, dec] of LEVERS) {
    leverValues[key] = null;   // null = leave at patient's current value
    const row = document.createElement("div");
    row.className = "lever";
    row.innerHTML = `
      <div class="lv"><span>${label}</span><span class="muted" id="lv-${key}">current</span></div>
      <input type="range" min="${min}" max="${max}" step="${step}" data-key="${key}" data-dec="${dec}">`;
    const input = row.querySelector("input");
    input.oninput = () => {
      leverValues[key] = parseFloat(input.value);
      el(`lv-${key}`).textContent = parseFloat(input.value).toFixed(dec);
    };
    wrap.appendChild(row);
  }
}

el("resetSimBtn").onclick = () => buildLevers();

function scenarioFromLevers() {
  const sc = {};
  for (const [k, v] of Object.entries(leverValues)) if (v != null) sc[k] = v;
  return sc;
}

el("runSimBtn").onclick = async () => {
  el("simSummary").textContent = "running twin simulation…";
  try {
    const res = await api(`/api/patients/${current}/simulate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: scenarioFromLevers(), horizon_days: parseInt(el("horizon").value) }),
    });
    renderSim(res);
    renderExplain();
  } catch (e) { el("simSummary").innerHTML = `<span class="bad">${e.message}</span>`; }
};

function fmtDelta(v, unit, good = "down") {
  if (v == null) return "";
  const cls = v === 0 ? "" : (good === "down" ? (v < 0 ? "good" : "bad") : (v > 0 ? "good" : "bad"));
  return ` <b class="${cls}">(${v > 0 ? "+" : ""}${v} ${unit})</b>`;
}

function renderSim(res) {
  const d = res.deltas || {};
  const s = res.intervention.summary;
  const delta = (k, u, g) => (d[k] == null ? "" : ` <b class="${d[k] === 0 ? "" : (g === "up" ? (d[k] > 0 ? "good" : "bad") : (d[k] < 0 ? "good" : "bad"))}">(${d[k] > 0 ? "+" : ""}${d[k]} ${u})</b>`);
  el("simSummary").innerHTML = `
    <b>Projected at ${res.intervention.horizon_days}d on the twin vs current protocol:</b><br>
    HbA1c ${s.hba1c_end}%${delta("hba1c", "%")} ·
    weight ${s.weight_end} kg${delta("weight", "kg")} ·
    SBP ${s.sbp_end} mmHg${delta("sbp", "mmHg")} ·
    resting HR ${s.resting_hr_end} bpm${delta("resting_hr", "bpm")} ·
    night HRV ${s.night_hrv_end} ms${delta("night_hrv", "ms", "up")}`;

  const days = res.baseline.series.days;
  chartFor("simChart", {
    type: "line",
    data: {
      labels: days,
      datasets: [
        { label: "HbA1c-equivalent % (protocol)", data: res.intervention.series.gmi_pct, borderColor: "#f0b429", pointRadius: 0, borderWidth: 2.5, tension: 0.25 },
        { label: "HbA1c-equivalent % (current)", data: res.baseline.series.gmi_pct, borderColor: "rgba(240,180,41,.45)", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5, tension: 0.25 },
        { label: "weight kg (protocol)", data: res.intervention.series.weight_kg, borderColor: "#35c98e", pointRadius: 0, borderWidth: 2, tension: 0.25, yAxisID: "y1" },
        { label: "weight kg (current)", data: res.baseline.series.weight_kg, borderColor: "rgba(53,201,142,.45)", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5, tension: 0.25, yAxisID: "y1" },
      ],
    },
    options: baseOpts(),
  });
}

el("goalBtn").onclick = async () => {
  el("goalResult").textContent = "searching the twin's response surface…";
  try {
    const res = await api(`/api/patients/${current}/goal`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lever: el("goalLever").value,
        target_metric: "hba1c_end",
        target_value: parseFloat(el("goalTarget").value),
        horizon_days: parseInt(el("goalDays").value),
        direction: "below",
        scenario_base: scenarioFromLevers(),   // levers designed above form the base protocol
      }),
    });
    renderGoal(res);
  } catch (e) { el("goalResult").innerHTML = `<span class="bad">${e.message}</span>`; }
};

function renderGoal(res) {
  if (!res.feasible) {
    el("goalResult").innerHTML = `<span class="bad">${res.note}</span>`;
    return;
  }
  const leverLabel = LEVERS.find((l) => l[0] === res.lever)?.[1] || res.lever;
  el("goalResult").innerHTML = `
    <b>${leverLabel}: ${res.lever_value}</b> reaches HbA1c ${res.achieved}% within the horizon
    (band ${res.band.min}% – ${res.band.max}% under ±10% physiology jitter).<br>
    <span class="muted">${res.interpretation}</span>`;
  renderSim({ baseline: res.run, intervention: res.run, deltas: {} });
  const days = res.run.series.days;
  chartFor("simChart", {
    type: "line",
    data: {
      labels: days,
      datasets: [
        { label: `HbA1c-equivalent % @ ${res.lever}=${res.lever_value}`, data: res.run.series.gmi_pct, borderColor: "#f0b429", pointRadius: 0, borderWidth: 2.5, tension: 0.25 },
        { label: "target", data: days.map(() => parseFloat(el("goalTarget").value)), borderColor: "rgba(53,201,142,.8)", borderDash: [6, 4], pointRadius: 0, borderWidth: 1.5 },
      ],
    },
    options: baseOpts(),
  });
}

async function renderExplain() {
  el("explainTable").textContent = "computing lever contributions…";
  try {
    const res = await api(`/api/patients/${current}/explain`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: scenarioFromLevers(), horizon_days: parseInt(el("horizon").value) }),
    });
    const rows = res.contributions;
    el("explainTable").innerHTML = rows.length ? `
      <table class="delta-table">
        <tr><th>Lever</th><th>Value</th><th>Δ HbA1c</th><th>Δ weight</th><th>Δ SBP</th></tr>
        ${rows.map((r) => `<tr><td>${r.lever}</td><td>${r.value}</td>
          <td class="${r.hba1c_delta < 0 ? "good" : "bad"}">${r.hba1c_delta > 0 ? "+" : ""}${r.hba1c_delta}</td>
          <td class="${r.weight_delta < 0 ? "good" : ""}">${r.weight_delta > 0 ? "+" : ""}${r.weight_delta}</td>
          <td class="${r.sbp_delta < 0 ? "good" : ""}">${r.sbp_delta > 0 ? "+" : ""}${r.sbp_delta}</td></tr>`).join("")}
      </table>` : "<span class='muted'>Set at least one lever first.</span>";
  } catch (e) { el("explainTable").textContent = e.message; }
}

/* ------------------------------------------------------------------ report */
async function loadReport() {
  const r = await api(`/api/patients/${current}/report`);
  el("reportPre").textContent = r.markdown;
}
el("copyReport").onclick = () => navigator.clipboard?.writeText(el("reportPre").textContent);

boot();
