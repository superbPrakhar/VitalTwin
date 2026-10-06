# Architecture

VitalTwin is a patient digital twin with three coupled loops, implemented as a
Python service (`app/`) plus a zero-build web dashboard (`frontend/`).

```
                       ┌──────────────────────────────────────────────────┐
                       │                    DIGITAL TWIN                  │
   EHR bundle ────────►│  Calibration        Physiological forward model   │
   (FHIR-lite JSON)    │  params_from_ehr ─► (hourly discrete-time sim)    │
                       │        ▲                    │            ▲        │
                       │        │ slow re-           │ what-if     │       │
                       │        │ calibration        ▼            │       │
   Wearable / CGM ────►│  Assimilation ──► Assimilated ──► Risk engine    │
   (hourly telemetry)  │  (Kalman + baselines)  state      NEWS2+TwinRisk │
                       │                                             │    │
                       └─────────────────────────────────────────────┼────┘
                                              ▲                      ▼
                                       Protocol Studio           Alerts / mirror
                                       (what-if, goal seek)      (dashboard, API)
```

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| Engine — physiology | `app/engine/physiology.py` | Hourly discrete-time simulation of cardiovascular, autonomic, respiratory, metabolic and energy-balance dynamics. The single forward model serves both synthetic data generation and what-if simulation. |
| Engine — events | `app/engine/events.py` | Adverse-event archetypes (biphasic infection/sepsis-like deterioration, severe hypoglycaemia, hypertensive crisis, nocturnal desaturation) and the hazard model that samples them. |
| Engine — assimilation | `app/engine/assimilation.py` | Per-channel 1-D Kalman filters, circadian personal baselines (mean/SD per hour-of-day), daily summariser, organ-status derivation. This is what makes the twin *live*. |
| Engine — features | `app/engine/features.py` | Per-patient-day feature rows built **only** from assimilated summaries, with personal baselines from the prior 14 days (no future leakage). The same code path runs at training time and in the live app — no training/serving skew. |
| Engine — risk | `app/engine/risk.py` | NEWS2 (RCP 2017) scored on assimilated vitals; TwinRisk logistic model (pure-Python training/inference); metrics (AUROC, AP, sensitivity/specificity); alert-threshold selection. |
| Engine — protocols | `app/engine/protocols.py` | Scenario simulation (medication + lifestyle levers), baseline comparison on identical noise realisations, goal-seek (binary search + ±10 % physiology jitter band), one-at-a-time lever ablation. |
| Data | `app/data/` | Archetype mixture → EHR bundles; wearable/CGM generator with sensor noise models; deterministic seeds everywhere. |
| Service | `app/main.py`, `app/store.py` | FastAPI routes; in-memory deterministic store with 3 seeded demo patients and a hidden 14-day future telemetry window revealed by `POST /sync`. |
| Frontend | `frontend/` | Vanilla JS + Chart.js (vendored, offline-capable). No build step. |

## The three loops

1. **Mirror (assimilation loop).** Hourly wearable/CGM measurements are
   assimilated into the twin state. Channels the wearables cannot observe
   (blood pressure) are carried by the forward model and corrected whenever a
   home-cuff reading arrives — the same mixed-sampling structure a real
   deployment faces. Each channel also maintains a circadian personal
   baseline so "abnormal" means *abnormal for this patient at this hour*, not
   abnormal for a population table.

2. **Predict (risk loop).** Daily summaries from the mirror feed the feature
   builder; TwinRisk (logistic regression over personalised deviation
   features) estimates the 48-hour probability of infection-like acute
   deterioration, while NEWS2 provides a transparent current-acuity baseline
   and absolute-threshold alarms catch abrupt events (hypoglycaemia,
   hypertension, hypoxaemia). See `docs/evaluation.md` for measured
   performance and `docs/clinical_model.md` for the alert taxonomy.

3. **Simulate (protocol loop).** The same forward model, run forward 30/180
   days under a modified protocol, projects HbA1c, weight, blood pressure,
   resting HR/HRV and time-in-range. Goal-seek binary-searches a lever to the
   smallest change reaching a clinical target and reports an uncertainty band
   from ±10 % physiological-parameter jitter.

## Design decisions

- **One forward model, two uses.** Generation and what-if share
  `simulate_days`, so simulated protocols inherit exactly the dynamics the
  risk model was trained on — and every equation is inspectable in one file.
- **Pure Python core.** No NumPy/pandas/scikit-learn: the engine runs
  anywhere (including restricted hospital environments), installs in
  seconds, and every constant is greppable. The models are small enough that
  vectorisation buys nothing at PoC scale.
- **Determinism.** Every generator takes an explicit `random.Random`; the
  same seed reproduces the same patient, stream and events — tests, demos
  and evaluations are reproducible bit-for-bit.
- **No persistence in the PoC.** The store regenerates from seeds at boot.
  Production wiring (device gateways → stream bus → feature store → twin
  service; FHIR R4 resources for EHR) is sketched in
  `docs/limitations_roadmap.md`.

## Scaling path (beyond the PoC)

| PoC | Production |
|---|---|
| In-memory store, seeded demo patients | Clinical data repository (FHIR R4) + device gateway (IoMT) |
| 1-hour time step, 8 channels | Adaptive step (1–15 min), patient-specific channel sets |
| 1-D Kalman per channel | Ensemble/particle assimilation over the full state |
| Logistic TwinRisk | Calibrated gradient-boosted / sequence model with the same feature contract |
| Single-process FastAPI | Queue-backed workers per patient twin; alert router to clinician inbox |
