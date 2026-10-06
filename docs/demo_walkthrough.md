# 5-minute demo walkthrough (jury script)

Open `http://127.0.0.1:8000` (start with `python run.py`). Everything below
is live and reproducible; no data is pre-baked.

**0:00 — The claim.** "VitalTwin is a living digital replica of a patient.
It fuses two silos — the EHR's static history and raw wearable telemetry —
into one calibrated physiological model that can *predict adverse events
before they happen* and *simulate treatment protocols before they are
prescribed*. Everything you'll see is synthetic, deterministic and
open-source."

**0:40 — The mirror (Arjun Rao, 72, post-cardiac-event).** Select Arjun →
**Twin mirror** tab. Point out: assimilated vitals (BP is *model-carried*
between home-cuff readings — wearables can't measure it, the twin infers
it), organ-system status vs his *own* circadian baseline, 972+ hours
assimilated across 8 channels. The CGM chart shows real meal excursions;
the HR/HRV chart shows his sleep dips.

**1:40 — Prediction (the demo's heart).** Press **⏵ Sync 6 h** repeatedly.
Each press reveals the next 6 hours of telemetry that the twin has *not
seen*. Around the 10th–13th press the twin enters the prodrome of an
infection-like deterioration: TwinRisk climbs past the alert threshold and
the feed fires — **with ~11–35 h of lead time before the acute onset**.
Switch to **Risk & alerts**: the risk trajectory shows the spike crossing
the dashed threshold *before* NEWS2 moves — "this is the difference between
a monitor and a twin: NEWS2 reacts to derangement, TwinRisk reads the drift
from *his own baseline*". Open a driver bar: "evening heart-rate drift and
HRV suppression — explainable, per-feature contributions".

**3:00 — Personalisation (Ravi Sharma, 58, T2D + hypertension).** Select
Ravi → **Protocol studio**. Set Steps 9,000, Dietary change −300 kcal,
Carbs 150 g → **▶ Simulate on twin**: "HbA1c 7.52 → 6.68 %, −3.5 kg, resting
HR −1.3 — projected, not prescribed". Then **🎯 Find smallest change**
(metformin lever, target 7.0): the twin returns **metformin 0 mg** — the
lifestyle protocol alone reaches target, i.e. the twin can also
*de-prescribe* safely, with a ±10 % physiology jitter band for honesty.

**4:10 — Trust & hygiene.** **Clinician report** tab: the markdown summary a
doctor would receive (mirror, risk, drivers, watermarked). Point at the
repo: 26 pytest tests (clinical plausibility gates, no-leakage checks, API
contract), GitHub Actions CI, `docs/clinical_model.md` documents every
equation with its literature anchor, `docs/evaluation.md` commits the real
numbers (AUROC 0.784, AP 0.493 ≈ 30× prevalence, 18.5 h mean lead time) —
and `docs/limitations_roadmap.md` says exactly what is *not* validated yet.

**4:50 — Close.** "The future of medicine is proactive, not reactive. The
twin is the machine that makes proactive measurable."

---

### One-line answers for likely questions

- **"Is the model real ML?"** Yes — a calibrated logistic model trained on a
  120-patient synthetic cohort with a patient-level split, pure-Python
  implementation, committed weights + metrics. The *architecture* (assimilate
  → features → risk → explain) is the deliverable; the model class is a
  placeholder for a stronger one behind the same contract.
- **"Why synthetic data?"** No real patient data can be in a hackathon repo
  (privacy); a physiology simulator additionally gives *ground truth* for
  lead-time measurement, which real data rarely labels.
- **"How does it integrate with EHRs?"** The EHR side is FHIR-lite JSON with
  a documented mapping (`params_from_ehr`); production wiring (FHIR R4,
  HL7v2 ingest) is sketched in the roadmap.
- **"What about alert fatigue?"** Threshold chosen at 76.5 % specificity
  with the full ROC sweep published; alarms are tiered (live alarms →
  NEWS2 → TwinRisk).
