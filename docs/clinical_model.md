# Clinical & simulation model

Every equation in the VitalTwin forward model, its constants, and the
clinical grounding behind it. The implementation is
`app/engine/physiology.py`; this document is the readable specification.

> **Scope.** This is a proof-of-concept physiological model for a hackathon
> prototype. It reproduces *population-level* behaviour and plausible
> individual trajectories, not validated patient-specific physiology. It is
> not a medical device and must not be used for clinical decisions.

## 1. Time base

The model steps in **1-hour increments** (`step()` in
`app/engine/physiology.py`). Hourly resolution matches the dominant wearable
sampling granularity for sleep/HRV summaries and keeps the PoC fast; the
structure is step-size agnostic.

## 2. Calibration: EHR → twin parameters

`params_from_ehr()` derives fixed patient parameters from a FHIR-lite EHR
bundle:

| Parameter | Derivation | Grounding |
|---|---|---|
| BMR | Mifflin-St Jeor (10·weight + 6.25·height − 5·age ± sex term) | Mifflin et al., 1990 |
| Resting HR | 62 + 0.25·max(0, age−30) + 8·(1−fitness) − β-blocker effect | Age/fitness associations |
| SBP/DBP base | Clinic readings, minus declared antihypertensive effect (DBP ≈ 55 % of SBP reduction) | Standard antihypertensive response |
| Fasting glucose | Lab value; anchored to HbA1c via ADAG inversion when available | Nathan et al. (ADAG), 2008 |
| β-cell function | 1.05 − 0.012·max(0, age−35) − 0.35·T2D − 0.10·prediabetes, clamped [0.25, 1.1] | UKPDS-style decline |
| Insulin sensitivity | (1 − 0.035·max(0, BMI−22)) · (0.85 if T2D) · (1 + metformin effect) | Adiposity/T2D association |
| RMSSD base | 18 + 45·fitness − 0.25·(age−30) + 4·female, clamped [12, 78] | HRV Task Force; age/sex norms |
| SpO₂ base | 97.5 − 4.5·COPD − 0.02·max(0, age−50) | COPD resting hypoxaemia |

The Protocol Studio's `apply_meds` re-derives insulin sensitivity from the
*pre-metformin* baseline when a scenario changes the dose
(`sensitivity_ref` is frozen at calibration), so medication levers are
additive rather than re-applied multiplicatively.

## 3. Hourly dynamics

### 3.1 Activity & behaviour

- Steps per hour follow a fixed diurnal profile (`_STEPS_PROFILE`, waking
  hours 7–22, ~0.95 total mass) × the day's step target × jitter, zero while
  asleep. Activity intensity = min(1.15, steps/520).
- Meals: 3/day (≈7:30, 12:30, 19:30 with jitter), 30/33/37 % of the day's
  carbohydrate split, dinner the largest. Total intake **closes the energy
  balance** against expected expenditure at the planned activity level, so
  weight only moves when the protocol changes intake or activity — the
  Protocol Studio's lever semantics.
- Sleep: lights out 22:30; wake time = (22.5 + sleep target) mod 24. Stages:
  deep-weighted early night, REM mid, light otherwise. Sleep debt accrues
  max(0, 7.5 − slept) per day and decays 0.7 h/day.

### 3.2 Stress / autonomic

- Circadian stress curve `0.5·(1 − cos(2π(h−9)/24))` × chronic stress level
  × 1.1, plus sleep-debt loading (0.045/h) and event stress; first-order
  lag toward target (τ ≈ 2 h) + noise.

### 3.3 Cardiovascular

- **HR** = resting base − β-blockade − 7·(fitness drift) + 26·min(1.2,
  intensity)·(0.5 asleep / 1.0 awake) + 16·stress + 9·fever °C + event term.
- **SBP** = base + 11·stress + 4.5·intensity − 8·(fitness drift) +
  1.1·(weight delta) + event term. Fitness drift lowers resting BP over
  weeks (aerobic-training effect); weight loss contributes ≈ −1.1 mmHg/kg.
- **DBP** tracks SBP with a personality-stable pulse pressure.

### 3.4 Respiratory

- **SpO₂** = base − 0.6·(intensity > 0.85) + event term + noise; sleeping
  dips for COPD/OSA (−1.8 × severity). **RR** = base + 2.6·stress + 2.1·°C
  fever + 1.6·intensity + event term. **Skin temp deviation** (wearable
  observable) = 0.6 × core fever — a documented property of wrist skin
  temperature.

### 3.5 Autonomic (HRV)

RMSSD = base × (night 1.35) × (1 − 0.42·stress) × (1 + 0.25·fitness drift)
× event suppression × (1 − 0.09·fever). Grounded in the stress-HRV
literature (synthetic activation suppresses vagal tone); the fitness term
reflects resting-vagal adaptation over weeks.

### 3.6 Metabolic (glucose)

One-compartment first-order model:

```
G(t+1) = G(t) + ingestion(t) − uptake(t)

ingestion = Σ_meals  carbs · GI · gauss(t − meal, σ=0.85 h) · 1.35 / (sens · β_eff)
uptake    = 0.85 · sens · (G − G_base_eff)          [when above fasting base]
          + (insulin units/day)/24 · 18 · nocturnal factor · G/120
sens      = insulin_sensitivity · (1 + 0.16·intensity) · (1 − 0.012·Δweight)
β_eff     = 0.4 + 0.6·β_function
```

- Decoupling clearance (sensitivity-driven) from disposal capacity
  (β-cell-driven) keeps T2D excursions ≈ 2.5× healthy excursions, matching
  CGM-literature magnitudes, without unphysiological fasting drift.
- **Fasting drift:** `G_base_eff = G_base · (sensitivity_ref / slow_sens)^1.5`
  where `slow_sens` adapts daily to weight loss (~1.2 %/kg — DiRECT-adjacent
  estimates) and fitness adaptation. A sustained lifestyle protocol
  therefore lowers fasting glucose, which is what makes goal-seek reach
  near-normal HbA1c honestly.
- **HbA1c-equivalent** from mean glucose via ADAG: A1c ≈ (MG + 46.7)/28.7.
  Short horizons report GMI (3.31 + 0.02392·MG) per day.

### 3.7 Energy balance & weight

Daily: Δweight = Σ_hourly (intake − expenditure)/7700 kcal per kg;
expenditure = BMR·(1 + 0.55·intensity)/24 per hour.

## 4. Adverse-event archetypes (`app/engine/events.py`)

| Event | Shape | Key observable signature |
|---|---|---|
| **Infection/sepsis-like deterioration** | Biphasic: 20–40 h prodrome (fever +0.9 °C, HR +16 %, RR +3, HRV −38 %, stress +0.25) → acute 36–72 h (fever +1.7 °C, HR +28 %, SBP −24, SpO₂ −3.8 %, RR +6.5, HRV −55 %) | The prodrome is the early-warning window TwinRisk must read |
| **Severe hypoglycaemia** | Nocturnal 3–5 h glucose crash (×0.30–0.42), insulin/sulphonylurea-treated patients | Live alarm layer (glucose < 70), not prediction |
| **Hypertensive crisis** | 4–8 h SBP spike +38–52 mmHg | Live alarm layer (SBP > 180) |
| **Nocturnal desaturation** | 6–8 h SpO₂ −4.5–7 % during sleep (COPD/OSA) | Live alarm layer (SpO₂ < 88) |

**Hazard model** (per patient-day, transparent): infection = 0.004 · age
factor · comorbidity load (enriched to the home-monitored high-risk
deployment population); hypoglycaemia = 0.022 (insulin) / 0.004 (T2D);
crisis = 0.012·(1+stress) if hypertensive and undertreated; desaturation =
0.35 for COPD/OSA. Minimum 6-day separation per kind per patient.

## 5. Alert taxonomy (three layers)

1. **Live monitoring alarms** — absolute thresholds on the assimilated
   state (glucose < 70 / > 250, SpO₂ < 88, SBP > 180 / < 90, HR > 130 /
   < 40, temp > 38.5 °C). Current-state safety net, analogous to CGM/ward
   monitor alarms.
2. **NEWS2** (RCP 2017, on twin-estimated vitals: RR, SpO₂, temperature,
   SBP, HR; consciousness defaults to 0 in the PoC) — transparent current
   acuity, medium ≥ 5, high ≥ 7.
3. **TwinRisk** — learned 48-hour deterioration probability from personalised
   deviation features; fires *before* absolute thresholds. Threshold chosen
   on validation (see `docs/evaluation.md`).

## 6. Sensor models (`app/data/generator.py`)

| Channel | Model |
|---|---|
| Wrist PPG HR | Gaussian σ 3.5 bpm, 2 % dropout (holds previous) |
| HRV RMSSD | Gaussian σ 3.2 ms |
| SpO₂ | Gaussian σ 0.7 %, floor 70 |
| Steps | Integer, ±6 % multiplicative jitter |
| CGM glucose | Gaussian σ 2.5 mg/dL |
| Skin temp deviation | 0.6 × core fever + σ 0.15 °C |
| Respiration rate | Gaussian σ 0.6 brpm |
| Home cuff BP | Every 3rd morning, σ 4/3 mmHg (SBP/DBP) |

## 7. Assimilation (`app/engine/assimilation.py`)

- Per-channel **1-D Kalman filter** with random-walk process model;
  process noise is activity-dependent for HR (higher when active, lower
  asleep) and meal-window-dependent for glucose.
- **Circadian personal baselines:** per channel × hour-of-day EMA mean/SD
  (α = 0.05, ~14 effective days warm-up). Deviations are z-scores against
  the patient's *own* pattern at the same hour.
- **BP without a BP sensor:** the twin carries a model-based estimate,
  corrected only when a home-cuff reading arrives — the mixed-sampling
  reality of IoMT deployments.
- Measured assimilation accuracy on synthetic data (30-day streams):
  HR MAE ≈ 3.7 bpm, glucose MAE ≈ 3.0 mg/dL, SBP MAE ≈ 5.1 mmHg (vs. model
  truth; at or near the sensor noise floor).

## 8. TwinRisk features (19, all from assimilated data)

`rest_hr_z, hr_evening_z, hrv_night_z, hrv_evening_z, hr_up_hrv_down,
hrv_ratio_3_7, sleep_hours_7d, sleep_debt_7d, sleep_frag_3d, spo2_dip_3d,
steps_ratio, glucose_mean_z, glucose_cv_3d, tir_7d, glucose_night_min_3d,
hypo_7d, temp_dev_max_z, temp_dev_3d_z, rr_max_z` + demographics
(age, BMI, comorbidity count). All personal-deviation features are
z-scored against the prior 14 days of the same patient — the model reads
*drift from one's own norm*, which is the digital-twin advantage over
population thresholds.

## References

1. Royal College of Physicians. *National Early Warning Score (NEWS) 2*, 2017.
2. Nathan DM et al. Translating the A1C assay into estimated average glucose values. *Diabetes Care* 31:1473, 2008.
3. Bergman RN et al. Quantitative estimation of insulin sensitivity. *J Clin Invest* 63:1849, 1979 (minimal-model structure).
4. Task Force of the ESC & NASPE. Heart rate variability: standards of measurement. *Eur Heart J* 17:354, 1996.
5. Mifflin MD et al. A new predictive equation for resting energy expenditure. *Am J Clin Nutr* 51:241, 1990.
6. Lean MEJ et al. (DiRECT) Primary care-led weight management for remission of type 2 diabetes. *Lancet* 391:541, 2018.
7. Jung F et al. GMI: the relationship between estimated A1C and CGM. *Diabetes Technol Ther* 20:S2, 2018.
