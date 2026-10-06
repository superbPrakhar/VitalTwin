/* VitalTwin — pitch deck + architecture diagram generator (pptxgenjs) */
const pptxgen = require("pptxgenjs");

// Palette (matches the VitalTwin dashboard)
const BG = "0D1220", CARD = "182135", CARD2 = "1E2942", LINE = "2A3A5C";
const TEXT = "E8EDF7", MUTED = "8FA0BD", PRIMARY = "4F8CFF", ACCENT = "35C98E";
const WARN = "F0B429", ALERT = "F2607A", ACCENT2 = "7BD0FF";
const F = "Segoe UI";
const W = 13.33, H = 7.5, M = 0.6;

const bu = () => ({ code: "2022", indent: 12 });
const shadow = () => ({ type: "outer", color: "000000", blur: 7, offset: 2, angle: 90, opacity: 0.25 });

function base(slide, title, kicker) {
  slide.background = { color: BG };
  if (kicker) slide.addText(kicker.toUpperCase(), { x: M, y: 0.32, w: 9, h: 0.3, fontFace: F, fontSize: 11, color: ACCENT, charSpacing: 3, margin: 0 });
  slide.addText(title, { x: M, y: 0.55, w: W - 2 * M, h: 0.75, fontFace: F, fontSize: 30, bold: true, color: TEXT, margin: 0 });
  slide.addText("VitalTwin", { x: W - 2.2, y: 0.35, w: 1.6, h: 0.3, align: "right", fontFace: F, fontSize: 11, color: MUTED, margin: 0 });
}

function card(slide, x, y, w, h, fill = CARD) {
  slide.addShape("roundRect", { x, y, w, h, fill: { color: fill }, rectRadius: 0.09, line: { color: LINE, width: 0.75 }, shadow: shadow() });
}

function stat(slide, x, y, w, value, label, color = ACCENT) {
  slide.addText(value, { x, y, w, h: 0.85, fontFace: F, fontSize: 44, bold: true, color, align: "center", margin: 0 });
  slide.addText(label, { x, y: y + 0.85, w, h: 0.55, fontFace: F, fontSize: 12.5, color: MUTED, align: "center", margin: 0 });
}

function arrow(slide, x1, y1, x2, y2, color = PRIMARY) {
  slide.addShape("line", { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width: 1.75, endArrowType: "triangle" } });
}

// ---------- shared architecture diagram ----------
function drawArchitecture(pres, slide, compact) {
  const box = (x, y, w, h, title, sub, stroke = PRIMARY, fill = CARD) => {
    card(slide, x, y, w, h, fill);
    slide.addText(title, { x: x + 0.12, y: y + 0.08, w: w - 0.24, h: 0.32, fontFace: F, fontSize: 13, bold: true, color: TEXT, margin: 0 });
    if (sub) slide.addText(sub, { x: x + 0.12, y: y + 0.42, w: w - 0.24, h: h - 0.52, fontFace: F, fontSize: 10.5, color: MUTED, margin: 0 });
  };
  // inputs (left)
  box(0.45, 1.35, 2.5, 1.0, "EHR (FHIR-lite)", "history · labs · meds · conditions", MUTED === 0 ? 0 : LINE, CARD2);
  box(0.45, 3.05, 2.5, 1.0, "Wearable / CGM stream", "PPG-HR · HRV · SpO₂ · steps · sleep · temp · CGM · cuff BP", LINE, CARD2);
  // engine column (center-left)
  box(3.55, 1.35, 2.75, 1.0, "Calibration", "EHR → twin parameters (params_from_ehr)");
  box(3.55, 3.05, 2.75, 1.0, "Assimilation", "per-channel Kalman + circadian personal baselines");
  box(6.95, 2.2, 2.9, 1.5, "Physiological forward model", "hourly discrete-time dynamics: cardiovascular · autonomic · respiratory · metabolic · energy", PRIMARY, CARD2);
  // outputs (right)
  box(10.5, 1.35, 2.4, 1.0, "Risk engine", "NEWS2 + TwinRisk (48 h deterioration probability) → tiered alerts", ALERT === 0 ? 0 : LINE);
  box(10.5, 3.05, 2.4, 1.0, "Protocol Studio", "what-if simulation · goal-seek · lever ablation", LINE);
  box(6.95, 4.6, 5.95, 0.85, "Dashboard + API", "twin mirror · risk & alerts · trends · clinician report (FastAPI + zero-build SPA)", LINE, CARD2);
  // connectors
  arrow(slide, 2.95, 1.85, 3.55, 1.85);
  arrow(slide, 2.95, 3.55, 3.55, 3.55);
  arrow(slide, 4.9, 2.35, 4.9, 3.05);            // calibration <-> assimilation vertical (down)
  arrow(slide, 6.3, 1.85, 6.95, 2.6);
  arrow(slide, 6.3, 3.55, 6.95, 3.3);
  arrow(slide, 9.85, 2.6, 10.5, 1.85);
  arrow(slide, 9.85, 3.3, 10.5, 3.55);
  arrow(slide, 9.9, 3.7, 9.9, 4.6);
  // feedback loop (assimilation <- model, dashed)
  slide.addShape("line", { x: 8.4, y: 3.7, w: 0, h: 0.62, line: { color: ACCENT, width: 1.5, dashType: "dash" } });
  slide.addText("sync loop: telemetry revealed → assimilated → re-scored", { x: 3.55, y: 5.62, w: 6.3, h: 0.3, fontFace: F, fontSize: 10.5, italic: true, color: ACCENT, margin: 0 });
  if (!compact) slide.addText("One forward model serves both data generation (labeled synthetic cohort) and what-if simulation — the twin's two superpowers share one equation set.", { x: 0.45, y: 6.15, w: 12.4, h: 0.6, fontFace: F, fontSize: 12.5, color: TEXT, margin: 0 });
}

// ---------- deck 1: pitch ----------
const p = new pptxgen();
p.layout = "LAYOUT_WIDE";
p.author = "Team VitalTwin";
p.title = "VitalTwin — Patient Digital Twin PoC";

// S1 — title
let s = p.addSlide();
s.background = { color: BG };
s.addShape("oval", { x: 9.2, y: -1.6, w: 6.2, h: 6.2, fill: { color: PRIMARY, transparency: 88 }, line: { type: "none" } });
s.addShape("oval", { x: 11.4, y: 3.9, w: 3.4, h: 3.4, fill: { color: ACCENT, transparency: 86 }, line: { type: "none" } });
s.addText("HAPPIEST HEALTH DIGITAL TWIN CHALLENGE 2026", { x: M, y: 1.35, w: 10, h: 0.35, fontFace: F, fontSize: 13, color: ACCENT, charSpacing: 3, margin: 0 });
s.addText("VitalTwin", { x: M, y: 1.8, w: 11, h: 1.35, fontFace: F, fontSize: 66, bold: true, color: TEXT, margin: 0 });
s.addText("A living digital replica of the patient — EHR history fused with real-time wearable telemetry.", { x: M, y: 3.25, w: 9.6, h: 0.8, fontFace: F, fontSize: 20, color: MUTED, margin: 0 });
s.addText([
  { text: "Predict adverse events before they happen. ", options: { color: TEXT } },
  { text: "Simulate treatment before it is prescribed.", options: { color: ACCENT } },
], { x: M, y: 4.15, w: 10.5, h: 0.55, fontFace: F, fontSize: 24, bold: true, margin: 0 });
s.addText("Prototype & Code Submission · Team VitalTwin · Synthetic PoC, not a medical device", { x: M, y: 6.55, w: 11, h: 0.35, fontFace: F, fontSize: 12.5, color: MUTED, margin: 0 });

// S2 — problem
s = p.addSlide();
base(s, "Two data silos, one reactive system", "Problem statement");
s.addText("\u201CThe future of medicine is proactive, not reactive.\u201D — Happiest Health, Digital Twin Challenge 2026", { x: M, y: 1.42, w: 12.1, h: 0.4, fontFace: F, fontSize: 14, italic: true, color: ACCENT2, margin: 0 });
card(s, M, 2.05, 5.95, 1.9, CARD2);
s.addText("EHR: a record of the past", { x: M + 0.25, y: 2.3, w: 5.5, h: 0.4, fontFace: F, fontSize: 17, bold: true, color: TEXT, margin: 0 });
s.addText("Static history — diagnoses, labs, medications. No live view of the patient between visits.", { x: M + 0.25, y: 2.78, w: 5.5, h: 0.95, fontFace: F, fontSize: 13.5, color: MUTED, margin: 0 });
card(s, 6.8, 2.05, 5.95, 1.9, CARD2);
s.addText("Wearables: numbers without context", { x: 7.05, y: 2.3, w: 5.5, h: 0.4, fontFace: F, fontSize: 17, bold: true, color: TEXT, margin: 0 });
s.addText("Raw IoMT telemetry — heart rate, SpO₂, glucose — with no physiological model to interpret it.", { x: 7.05, y: 2.78, w: 5.5, h: 0.95, fontFace: F, fontSize: 13.5, color: MUTED, margin: 0 });
s.addText("Result: deterioration is discovered when it has already happened — in the ER.", { x: M, y: 4.25, w: 12.1, h: 0.45, fontFace: F, fontSize: 17, bold: true, color: ALERT, margin: 0 });
card(s, M, 4.95, 12.1, 1.75, CARD);
s.addText("The challenge ask", { x: M + 0.25, y: 5.15, w: 11.6, h: 0.35, fontFace: F, fontSize: 13, bold: true, color: ACCENT, charSpacing: 2, margin: 0 });
s.addText("A Proof-of-Concept Digital Twin — a dynamic, virtual replica of a patient — integrating real-time wearable data with the EHR, to predict adverse health events and personalize treatment protocols.", { x: M + 0.25, y: 5.55, w: 11.6, h: 1.0, fontFace: F, fontSize: 15.5, color: TEXT, margin: 0 });

// S3 — healthcare use case
s = p.addSlide();
base(s, "Three clinical scenarios, shipped as demo patients", "Healthcare use case");
const uc = [
  ["Arjun Rao · 72 · post-PCI", "Early warning of acute deterioration", "TwinRisk reads his prodrome — HR drift + HRV suppression — and fires 11\u201335 h before acute onset, while NEWS2 still reads 0.", ACCENT],
  ["Ravi Sharma · 58 · T2D + HTN", "Chronic disease protocol design", "Metformin titration, walking and diet changes simulated on the twin; goal-seek finds the smallest dose reaching target HbA1c \u2014 including safe deprescribing.", PRIMARY],
  ["Meera Iyer · 45 · prediabetes", "Prevention & risk reversal", "A walking + diet protocol projects HbA1c 6.34 \u2192 5.9% and \u22123.5 kg over 90 days \u2014 quantified motivation for behaviour change.", WARN],
];
uc.forEach(([who, what, how, c], i) => {
  const x = M + i * 4.13;
  card(s, x, 1.6, 3.85, 4.6);
  s.addShape("oval", { x: x + 0.3, y: 1.95, w: 0.55, h: 0.55, fill: { color: c, transparency: 78 }, line: { color: c, width: 1.25 } });
  s.addText(String(i + 1), { x: x + 0.3, y: 1.95, w: 0.55, h: 0.55, align: "center", valign: "middle", fontFace: F, fontSize: 20, bold: true, color: c, margin: 0 });
  s.addText(who, { x: x + 0.3, y: 2.72, w: 3.3, h: 0.35, fontFace: F, fontSize: 12, color: MUTED, margin: 0 });
  s.addText(what, { x: x + 0.3, y: 3.1, w: 3.3, h: 0.85, fontFace: F, fontSize: 17, bold: true, color: TEXT, margin: 0 });
  s.addText(how, { x: x + 0.3, y: 4.0, w: 3.3, h: 2.0, fontFace: F, fontSize: 12.5, color: MUTED, margin: 0 });
});
s.addText("Care setting: home & community monitoring of chronic-disease patients between clinic visits \u2014 plus post-discharge monitoring.", { x: M, y: 6.5, w: 12.1, h: 0.4, fontFace: F, fontSize: 12.5, italic: true, color: MUTED, margin: 0 });

// S4 — the solution: three loops
s = p.addSlide();
base(s, "One twin, three loops", "Solution overview");
const loops = [
  ["MIRROR", "Assimilation loop", "Hourly wearable/CGM data assimilated onto the EHR-calibrated physiology model. Kalman filters + circadian personal baselines; BP model-carried between cuff readings.", PRIMARY],
  ["PREDICT", "Risk loop", "NEWS2 on assimilated vitals + TwinRisk: 19 personalized drift features \u2192 48 h deterioration probability with mean lead time \u2248 18.5 h. Every score explainable.", ALERT],
  ["SIMULATE", "Protocol loop", "Same forward model run 30\u2013180 days ahead under medication/lifestyle levers; goal-seek finds the smallest change reaching the clinical target, with a \u00B110% jitter band.", ACCENT],
];
loops.forEach(([tag, name, body, c], i) => {
  const x = M + i * 4.13;
  card(s, x, 1.7, 3.85, 4.1);
  s.addText(tag, { x: x + 0.3, y: 2.0, w: 3.25, h: 0.45, fontFace: F, fontSize: 26, bold: true, color: c, charSpacing: 3, margin: 0 });
  s.addText(name, { x: x + 0.3, y: 2.5, w: 3.25, h: 0.4, fontFace: F, fontSize: 15, bold: true, color: TEXT, margin: 0 });
  s.addText(body, { x: x + 0.3, y: 3.0, w: 3.25, h: 2.6, fontFace: F, fontSize: 12.5, color: MUTED, margin: 0 });
  if (i < 2) arrow(s, x + 3.85, 3.75, x + 4.13, 3.75, MUTED);
});
s.addText("Mirror keeps the replica live \u2192 Predict turns drift into early warning \u2192 Simulate turns the replica into a prescription.", { x: M, y: 6.2, w: 12.1, h: 0.4, fontFace: F, fontSize: 13.5, color: ACCENT2, margin: 0 });

// S5 — architecture
s = p.addSlide();
base(s, "Architecture: one forward model, two uses", "System design");
drawArchitecture(p, s, true);

// S6 — technical stack
s = p.addSlide();
base(s, "Technical stack", "Engineering");
const stack = [
  ["Twin engine", "Pure Python 3 \u2014 deterministic physiology simulation, zero numeric dependencies, every constant greppable"],
  ["API service", "FastAPI + Pydantic \u2014 14 endpoints, Swagger docs, strict validation of scenario levers"],
  ["Dashboard", "Vanilla JS + Chart.js (vendored, offline-capable) \u2014 zero build step"],
  ["ML layer", "From-scratch logistic regression (L2, standardized) + pure-Python AUROC/AP metrics"],
  ["Quality", "26 pytest tests \u2014 clinical plausibility gates, leakage checks, API contract; GitHub Actions CI (Python 3.11\u201313)"],
  ["Clinical grounding", "NEWS2 (RCP 2017) \u00B7 ADAG HbA1c \u00B7 Bergman minimal model \u00B7 HRV Task Force \u00B7 Mifflin-St Jeor"],
];
stack.forEach(([k, v], i) => {
  const y = 1.55 + i * 0.88;
  s.addText(k, { x: M, y, w: 2.9, h: 0.75, fontFace: F, fontSize: 15.5, bold: true, color: ACCENT2, valign: "top", margin: 0 });
  s.addText(v, { x: 3.7, y, w: 9.0, h: 0.75, fontFace: F, fontSize: 13.5, color: TEXT, valign: "top", margin: 0 });
  if (i < stack.length - 1) s.addShape("line", { x: M, y: y + 0.72, w: 12.1, h: 0, line: { color: LINE, width: 0.75 } });
});

// S7 — AI/ML model details
s = p.addSlide();
base(s, "TwinRisk v1 \u2014 explainable by construction", "AI/ML model details");
s.addText([
  { text: "Task", options: { bold: true, color: TEXT, breakLine: true } },
  { text: "Given a patient-day of assimilated summaries (personal baselines from the prior 14 days only \u2014 no future leakage), predict infection-like acute deterioration within 48 hours.", options: { color: MUTED, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Features (19)", options: { bold: true, color: TEXT, breakLine: true } },
  { text: "Personalized z-scores: resting/evening HR, night/evening HRV, HR\u2191+HRV\u2193 composite, sleep debt & fragmentation, SpO\u2082 dips, glycaemic variability & TIR, skin-temp trend, respiration \u2014 plus age, BMI, comorbidities.", options: { color: MUTED, breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "Model & pipeline", options: { bold: true, color: TEXT, breakLine: true } },
  { text: "Logistic regression with L2 \u2014 chosen for calibration and explainability. One command retrains end-to-end on a 120-patient \u00D7 180-day synthetic cohort, assimilated by the same mirror code the live app uses (no training/serving skew), split by patient.", options: { color: MUTED } },
], { x: M, y: 1.55, w: 6.4, h: 5.3, fontFace: F, fontSize: 13, paraSpaceAfter: 4, margin: 0, valign: "top" });
// top weights chart (real trained weights from app/models/twinrisk_v1.json)
s.addText("Top trained weights (logit contribution, standardized features)", { x: 7.35, y: 1.55, w: 5.4, h: 0.35, fontFace: F, fontSize: 13, bold: true, color: TEXT, margin: 0 });
s.addChart(p.charts.BAR, [{
  name: "weight",
  labels: ["rr_max_z", "hrv_ratio_3_7", "temp_dev_max_z", "hrv_evening_z", "steps_ratio", "hr_evening_z"],
  values: [0.698, 0.265, 0.255, -0.226, -0.191, 0.151],
}], {
  x: 7.35, y: 1.95, w: 5.4, h: 4.4, barDir: "bar",
  chartColors: [ALERT, ALERT, ALERT, ACCENT, ACCENT, ALERT],
  varyColors: true,
  chartArea: { fill: { color: CARD } },
  catAxisLabelColor: MUTED, valAxisLabelColor: MUTED,
  catAxisLabelFontSize: 10, valAxisLabelFontSize: 10,
  valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" },
  showValue: true, dataLabelPosition: "outEnd", dataLabelColor: TEXT, dataLabelFontSize: 10,
  showLegend: false, valAxisMinVal: -0.35, valAxisMaxVal: 0.85,
});
s.addText("Source: app/models/twinrisk_v1.json \u2014 red = risk-increasing (respiration peak, HRV-ratio drop, skin-temp trend), green = protective-direction activity.", { x: 7.35, y: 6.45, w: 5.4, h: 0.5, fontFace: F, fontSize: 10.5, color: MUTED, margin: 0 });

// S8 — results
s = p.addSlide();
base(s, "Measured results \u2014 synthetic validation cohort", "Evaluation");
stat(s, M, 1.7, 2.9, "0.784", "AUROC (48 h deterioration)", ACCENT);
stat(s, 3.62, 1.7, 2.9, "0.493", "Average precision (\u224830\u00D7 prevalence)", ACCENT);
stat(s, 6.79, 1.7, 2.9, "18.5 h", "Mean lead time when detected", PRIMARY);
stat(s, 9.83, 1.7, 2.9, "70 / 77", "Sensitivity / specificity %", PRIMARY);
s.addText("ROC sweep (24 held-out patients)", { x: M, y: 3.55, w: 8, h: 0.35, fontFace: F, fontSize: 13, bold: true, color: TEXT, margin: 0 });
s.addChart(p.charts.BAR, [
  { name: "Sensitivity", labels: ["thr 0.005", "thr 0.01 (deployed)", "thr 0.02", "thr 0.05"], values: [85, 70, 55, 42] },
  { name: "Specificity", labels: ["thr 0.005", "thr 0.01 (deployed)", "thr 0.02", "thr 0.05"], values: [55, 77, 88, 94] },
], {
  x: M, y: 3.95, w: 8.0, h: 2.9, barDir: "col", barGrouping: "clustered",
  chartColors: [ALERT, ACCENT],
  chartArea: { fill: { color: CARD } },
  catAxisLabelColor: MUTED, valAxisLabelColor: MUTED,
  catAxisLabelFontSize: 10.5, valAxisLabelFontSize: 10,
  valGridLine: { color: LINE, size: 0.5 }, catGridLine: { style: "none" },
  showValue: true, dataLabelPosition: "outEnd", dataLabelColor: TEXT, dataLabelFontSize: 10,
  showLegend: true, legendPos: "b", legendColor: MUTED, valAxisMaxVal: 100,
});
s.addText([
  { text: "Deployed operating point\n", options: { bold: true, color: TEXT } },
  { text: "sensitivity-weighted: a missed deterioration costs more than a review. Full ROC committed so the trade-off is explicit, not hidden.\n\n", options: { color: MUTED } },
  { text: "Assimilation fidelity\n", options: { bold: true, color: TEXT } },
  { text: "HR MAE 3.7 bpm \u00B7 glucose MAE 3.0 mg/dL \u00B7 SBP 5.1 mmHg \u2014 at the sensor noise floor.", options: { color: MUTED } },
], { x: 8.95, y: 3.95, w: 3.8, h: 2.9, fontFace: F, fontSize: 12.5, margin: 0, valign: "top" });
s.addText("Source: docs/evaluation.md \u00B7 docs/evaluation.json \u2014 synthetic data; internal consistency, not clinical validity.", { x: M, y: 7.0, w: 12.1, h: 0.3, fontFace: F, fontSize: 10.5, color: MUTED, margin: 0 });

// S9 — demo flow
s = p.addSlide();
base(s, "Live demo \u2014 deterministic, reproducible, no setup", "Demo flow");
const steps = [
  ["Run", "python run.py \u2192 http://127.0.0.1:8000 \u2014 three patients boot deterministically with 30 days of assimilated history."],
  ["Sync & predict", "Press \u201CSync 6 h\u201D on Arjun repeatedly \u2014 the twin reveals hidden telemetry; during the prodrome TwinRisk crosses the threshold ~11\u201335 h before acute onset."],
  ["Simulate", "On Ravi: set walking/diet/metformin levers \u2192 \u201CSimulate on twin\u201D \u2192 HbA1c 7.52 \u2192 6.68%, \u22123.5 kg, BP and resting HR improve."],
  ["Goal-seek", "\u201CFind smallest change\u201D \u2192 the twin returns metformin 0 mg: the lifestyle protocol alone reaches target \u2014 safe deprescribing, with a \u00B110% jitter band."],
];
steps.forEach(([k, v], i) => {
  const y = 1.6 + i * 1.28;
  s.addShape("oval", { x: M, y: y + 0.08, w: 0.62, h: 0.62, fill: { color: i === 1 ? ALERT : CARD2 }, line: { color: i === 1 ? ALERT : PRIMARY, width: 1.5 } });
  s.addText(String(i + 1), { x: M, y: y + 0.08, w: 0.62, h: 0.62, align: "center", valign: "middle", fontFace: F, fontSize: 20, bold: true, color: TEXT, margin: 0 });
  s.addText(k, { x: 1.5, y, w: 2.2, h: 0.85, fontFace: F, fontSize: 17, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addText(v, { x: 3.8, y, w: 8.9, h: 0.85, fontFace: F, fontSize: 13, color: MUTED, valign: "middle", margin: 0 });
  if (i < steps.length - 1) s.addShape("line", { x: M, y: y + 1.12, w: 12.1, h: 0, line: { color: LINE, width: 0.75 } });
});
s.addText("Full jury script with Q&A prep: docs/demo_walkthrough.md \u00B7 screenshots: docs/screenshots/", { x: M, y: 6.85, w: 12.1, h: 0.35, fontFace: F, fontSize: 11.5, color: MUTED, margin: 0 });

// S10 — outcomes
s = p.addSlide();
base(s, "Outcomes \u2014 what the prototype demonstrates today", "Results & impact");
const outcomes = [
  ["A working twin, not a mockup", "End-to-end pipeline: EHR calibration \u2192 assimilation \u2192 early warning \u2192 protocol simulation \u2192 clinician report, all live in the browser."],
  ["Early warning with lead time", "Deterioration risk flagged a median of ~18.5 h before acute onset on held-out synthetic patients \u2014 while NEWS2 remains normal through the prodrome."],
  ["Protocols simulated before prescribed", "DPP-magnitude lifestyle effects (\u22120.6% HbA1c, \u22123.5 kg / 90 d), monotone metformin dose\u2013response, deprescribing found by goal-seek."],
  ["Trust engineered in", "Per-feature alert drivers, transparent NEWS2 baseline, published ROC sweep, 26 tests, every equation documented with its literature anchor."],
];
outcomes.forEach(([k, v], i) => {
  const y = 1.65 + i * 1.25;
  s.addShape("oval", { x: M, y: y + 0.18, w: 0.28, h: 0.28, fill: { color: ACCENT }, line: { type: "none" } });
  s.addText(k, { x: 1.15, y, w: 4.4, h: 1.1, fontFace: F, fontSize: 16, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addText(v, { x: 5.7, y, w: 7.0, h: 1.1, fontFace: F, fontSize: 12.5, color: MUTED, valign: "middle", margin: 0 });
  if (i < outcomes.length - 1) s.addShape("line", { x: M, y: y + 1.12, w: 12.1, h: 0, line: { color: LINE, width: 0.75 } });
});

// S11 — limitations & roadmap
s = p.addSlide();
base(s, "What is not validated yet \u2014 and the path there", "Honest limitations");
card(s, M, 1.6, 5.95, 4.9, CARD2);
s.addText("Limitations", { x: M + 0.3, y: 1.85, w: 5.3, h: 0.4, fontFace: F, fontSize: 18, bold: true, color: ALERT, margin: 0 });
s.addText([
  { text: "All quantitative results are on synthetic data generated by the twin's own physiology model \u2014 internal consistency, not clinical validity.", options: { bullet: bu(), breakLine: true, color: MUTED } },
  { text: "Hourly resolution; beat-level phenomena (e.g. AF screening) out of scope.", options: { bullet: bu(), breakLine: true, color: MUTED } },
  { text: "Channels filtered independently \u2014 joint (ensemble/particle) assimilation is the upgrade path.", options: { bullet: bu(), breakLine: true, color: MUTED } },
  { text: "Steady-state medication model; no pharmacokinetics yet.", options: { bullet: bu(), color: MUTED } },
], { x: M + 0.3, y: 2.35, w: 5.35, h: 3.9, fontFace: F, fontSize: 12.5, paraSpaceAfter: 8, margin: 0, valign: "top" });
card(s, 6.8, 1.6, 5.95, 4.9, CARD2);
s.addText("Roadmap", { x: 7.1, y: 1.85, w: 5.3, h: 0.4, fontFace: F, fontSize: 18, bold: true, color: ACCENT, margin: 0 });
s.addText([
  { text: "0\u20133 mo: retrain on real cohorts (MIMIC-IV waveforms / wearable + infection labels); subgroup calibration report; CSV device ingestion.", options: { bullet: bu(), breakLine: true, color: MUTED } },
  { text: "3\u20139 mo: joint assimilation; clinician alert router with acknowledgement loop; patient app; PK-aware medication layer; multi-tenant service.", options: { bullet: bu(), breakLine: true, color: MUTED } },
  { text: "9\u201318 mo: prospective pilot with a clinical partner; CDSCO SaMD regulatory scoping; randomised evaluation of twin-guided protocol reviews.", options: { bullet: bu(), color: MUTED } },
], { x: 7.1, y: 2.35, w: 5.35, h: 3.9, fontFace: F, fontSize: 12.5, paraSpaceAfter: 10, margin: 0, valign: "top" });
s.addText("We consider honesty a feature: knowing where the model ends is part of the engineering.", { x: M, y: 6.75, w: 12.1, h: 0.4, fontFace: F, fontSize: 13, italic: true, color: ACCENT2, margin: 0 });

// S12 — closing
s = p.addSlide();
s.background = { color: BG };
s.addShape("oval", { x: -2.2, y: 3.6, w: 7.0, h: 7.0, fill: { color: PRIMARY, transparency: 88 }, line: { type: "none" } });
s.addText("Proactive, measurable.", { x: M, y: 2.0, w: 12.1, h: 1.0, fontFace: F, fontSize: 48, bold: true, color: TEXT, margin: 0 });
s.addText("The twin is the machine that makes proactive care measurable \u2014 mirror, predict, simulate.", { x: M, y: 3.1, w: 11, h: 0.6, fontFace: F, fontSize: 19, color: MUTED, margin: 0 });
const links = [
  ["Repository", "github.com/superbPrakhar/VitalTwin"],
  ["Run it", "pip install -r requirements.txt \u00B7 python run.py \u00B7 pytest: 26 passed"],
  ["License", "MIT \u2014 fully open source"],
  ["Docs", "architecture \u00B7 clinical model \u00B7 evaluation \u00B7 privacy & ethics \u00B7 roadmap"],
];
links.forEach(([k, v], i) => {
  const x = M + (i % 2) * 6.2, y = 4.3 + Math.floor(i / 2) * 1.0;
  s.addText(k, { x, y, w: 5.8, h: 0.3, fontFace: F, fontSize: 12, bold: true, color: ACCENT, charSpacing: 2, margin: 0 });
  s.addText(v, { x, y: y + 0.32, w: 5.8, h: 0.35, fontFace: F, fontSize: 13.5, color: TEXT, margin: 0 });
});
s.addText("Thank you \u00B7 Team VitalTwin \u00B7 Happiest Health Digital Twin Challenge 2026 \u00B7 synthetic data only, not a medical device", { x: M, y: 6.85, w: 12.1, h: 0.35, fontFace: F, fontSize: 11.5, color: MUTED, margin: 0 });

p.writeFile({ fileName: "docs/VitalTwin_Pitch.pptx" }).then(() => console.log("pitch done"));

// ---------- deck 2: architecture diagram ----------
const a = new pptxgen();
a.layout = "LAYOUT_WIDE";
a.author = "Team VitalTwin";
a.title = "VitalTwin — Architecture Diagram";
let sa = a.addSlide();
sa.background = { color: BG };
sa.addText("VitalTwin \u2014 System Architecture", { x: M, y: 0.35, w: 10, h: 0.6, fontFace: F, fontSize: 26, bold: true, color: TEXT, margin: 0 });
sa.addText("Patient digital twin \u00B7 EHR + wearable fusion \u00B7 Happiest Health Digital Twin Challenge 2026", { x: M, y: 0.95, w: 11, h: 0.35, fontFace: F, fontSize: 13, color: MUTED, margin: 0 });
drawArchitecture(a, sa, false);
sa.addText("Legend: blue = calibrated twin core \u00B7 dashed green = live sync loop \u00B7 grey boxes = data plane. Details: docs/architecture.md \u00B7 equations: docs/clinical_model.md", { x: M, y: 6.85, w: 12.1, h: 0.4, fontFace: F, fontSize: 11, color: MUTED, margin: 0 });
a.writeFile({ fileName: "docs/architecture_diagram.pptx" }).then(() => console.log("arch done"));
