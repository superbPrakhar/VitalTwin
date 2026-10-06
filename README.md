# VitalTwin — a patient digital twin that predicts, then prescribes

> **Happiest Health Digital Twin Challenge 2026 — Prototype & Code Submission**
>
> A living digital replica of a patient: **EHR history fused with real-time
> wearable telemetry** on one calibrated physiological model, so care can be
> **proactive, not reactive** — predicting adverse events *before* vitals
> derange, and simulating treatment protocols *before* they are prescribed.

![Twin mirror](docs/screenshots/01-twin-mirror.png)

## What it does

| Capability | How it works | Where |
|---|---|---|
| **Mirror** — a live physiological replica | Wearable/CGM telemetry assimilated (per-channel Kalman + circadian personal baselines) onto a physiology model calibrated from the EHR | Live sync, `app/engine/assimilation.py` |
| **Predict** — adverse events before they happen | TwinRisk: explainable logistic model over 19 personalised drift features → 48-hour deterioration probability with **~18.5 h mean lead time** (AUROC 0.784, AP 0.493 ≈ 30× prevalence on the synthetic validation cohort) | `app/engine/risk.py`, `docs/evaluation.md` |
| **Alarm** — current-state safety net | Three tiers: absolute-threshold alarms (hypo/hyperglycaemia, SpO₂, BP, HR) + NEWS2 on assimilated vitals + TwinRisk early warning | `app/store.py` |
| **Simulate** — protocols before prescriptions | The same forward model run 30–180 days ahead under medication/lifestyle levers: HbA1c, weight, BP, resting HR/HRV, TIR trajectories vs the current protocol | Protocol Studio, `app/engine/protocols.py` |
| **Prescribe** — the twin as prescription | Goal-seek finds the *smallest* lever change reaching a clinical target, with a ±10 % physiology jitter band — including safe deprescribing | Goal seek in Protocol Studio |

Three synthetic demo patients ship with scripted, deterministic stories:
**Arjun Rao** (72, post-PCI — deterioration early-warning), **Ravi Sharma**
(58, T2D + hypertension — protocol optimisation), **Meera Iyer** (45,
prediabetes — prevention).

## Quickstart (2 minutes)

```bash
pip install -r requirements.txt
python run.py                    # → http://127.0.0.1:8000
```

Then follow the on-screen demo script (also `docs/demo_walkthrough.md`):

1. Select **Arjun Rao** → press **⏵ Sync 6 h of telemetry** repeatedly —
   watch TwinRisk cross the alert threshold during the prodrome, hours
   before any vital breaches NEWS2.
2. Select **Ravi Sharma** → **Protocol studio** → set levers →
   **▶ Simulate on twin** → then **🎯 Find smallest change** to goal-seek
   the minimum metformin dose for a target HbA1c.

API docs at `/docs` (Swagger). Re-run tests with `python -m pytest tests/ -q`.

## Architecture in one picture

```text
EHR (FHIR-lite) ──► Calibration ──► Physiological forward model (hourly)
                                        ▲                    │
Wearable/CGM ──► Assimilation ──► Assimilated state ──► Risk engine (NEWS2 + TwinRisk)
   telemetry      Kalman + baselines      │                    │
                                          └──► Protocol Studio (what-if, goal-seek)
                                                                       │
                                                            Alerts ◄───┘
```

Every equation and constant is documented with its literature anchor in
[`docs/clinical_model.md`](docs/clinical_model.md); the system design and
production scaling path are in [`docs/architecture.md`](docs/architecture.md).

## Measured results (synthetic cohort — see threats-to-validity)

| Metric | Value |
|---|---|
| TwinRisk 48 h deterioration AUROC | **0.784** |
| Average precision (prevalence 1.7 %) | **0.493** (~30× base rate) |
| Sensitivity / specificity at deployed threshold | **0.70 / 0.77** |
| Mean lead time when detected | **≈ 18.5 h** |
| Assimilation fidelity | HR MAE 3.7 bpm · glucose MAE 3.0 mg/dL · SBP 5.1 mmHg (at sensor noise floor) |
| Protocol engine | Lifestyle: −0.6 % HbA1c, −3.5 kg / 90 d (DPP-magnitude); metformin dose–response monotone |

**All data in this repository is synthetic** — generated deterministically,
no real patients anywhere. The evaluation therefore demonstrates internal
consistency of the architecture, not clinical validity; the honest
limitations and the clinical-validation roadmap are in
[`docs/limitations_roadmap.md`](docs/limitations_roadmap.md) and
[`docs/privacy_and_ethics.md`](docs/privacy_and_ethics.md).

## Repository layout

```
app/
  engine/        physiology, events, assimilation, features, risk, protocols
  data/          archetypes + synthetic generator (sensor noise models)
  models/        TwinRisk v1 weights + training metadata (committed)
  main.py        FastAPI service layer      store.py  deterministic patient store
frontend/        zero-build dashboard (vanilla JS + vendored Chart.js)
tests/           26 tests: clinical plausibility gates, no-leakage, API contract
scripts/         train_risk_model.py (retrains + re-evaluates end-to-end)
docs/            architecture, clinical model, evaluation, data dictionary,
                 API reference, privacy & ethics, limitations & roadmap, demo script
```

## Reproducing the model

```bash
python scripts/train_risk_model.py --patients 120 --days 180 --seed 2026
# generates the cohort, assimilates, trains, evaluates, and writes
# app/models/twinrisk_v1.json + docs/evaluation.json (~60 s, pure Python)
```

## Team & licence

Built for the Happiest Health *Reimagining & Reforming Healthcare in India
Summit 2026* Digital Twin Challenge. MIT licence — see
[LICENSE](LICENSE). Not a medical device; not for clinical use.
