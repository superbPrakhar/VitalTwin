# Data dictionary

All schemas are JSON-shaped; sources of truth are the dataclasses in
`app/engine/physiology.py`, `app/engine/assimilation.py`,
`app/engine/features.py` and the seeds in `app/store.py`.

## EHR bundle (FHIR-lite) — input at onboarding

```jsonc
{
  "patient_id": "ravi",
  "name": "Ravi Sharma",              // demo-only display name
  "ehr_id": "EHR-RAVI-58214",
  "demographics": {"age": 58, "sex": "M", "height_cm": 170, "weight_kg": 84},
  "conditions": ["t2d", "hypertension", "dyslipidemia"],
    // vocabulary: t2d, prediabetes, hypertension, cad, ckd, copd, osa, afib, dyslipidemia
  "labs": {"hba1c_pct": 7.8, "fasting_glucose_mgdl": 145, "ldl_mgdl": 118,
            "egfr_ml_min": 78, "creatinine_mgdl": 1.1},
  "baseline_vitals": {"sbp": 146, "dbp": 88},          // clinic anchor
  "medications": {                    // all optional
    "metformin_mg": 1000, "insulin_units_day": 0.0,
    "antihypertensive_mmhg": 8,       // steady-state SBP effect
    "beta_blocker_bpm": 0,            // resting HR effect
    "statin": true
  },
  "self_report": {                    // behavioural prior, refined by assimilation
    "activity_steps_day": 3800, "sleep_hours": 6.0, "stress_level": 0.6,
    "diet_carbs_day": 260, "diet_gi": 0.72, "diet_sodium_g": 5.2
  },
  "history_notes": ["..."]            // free text for the demo UI
}
```

## Hourly wearable/CGM record — the ingest schema

| Field | Type | Unit / values | Source device |
|---|---|---|---|
| `t` | int | global hour counter (t=0 anchored 2026-11-01 00:00) | — |
| `hr` | float | bpm | wrist PPG |
| `hrv` | float | ms (RMSSD) | wrist PPG |
| `spo2` | float | % | wrist PPG |
| `steps` | int | steps/hour | accelerometer |
| `sleep_stage` | enum | awake / light / deep / rem | accelerometer + PPG |
| `glucose` | float | mg/dL | CGM |
| `temp_dev` | float | °C vs personal skin-temp baseline | wrist thermistor |
| `rr` | float | breaths/min | PPG-derived |
| `sbp`, `dbp` | float (optional) | mmHg | home cuff, ~3-day cadence |

## Twin state (assimilated estimate, per hour)

`hr, sbp, dbp, rr, spo2, glucose, rmssd, temp_dev` (filtered estimates) +
`steps, sleep_stage` (observed) + deviation z-scores per channel vs the
personal circadian baseline + derived `map`, `shock_index`
(`app/engine/physiology.py::TwinState`).

## Daily summary (assimilated, per patient-day)

| Field | Meaning |
|---|---|
| `rest_hr` | minimum HR during sleep (night-time resting HR) |
| `hr_evening_mean` / `hrv_evening_mean` | 18:00–23:00 means (same-day prodrome signals) |
| `night_hrv_mean` | mean RMSSD during sleep |
| `sleep_hours`, `sleep_frag` | sleep duration; stage transitions per night-hour |
| `spo2_dip_hours` | sleep hours with SpO₂ < 91 % |
| `steps` | total daily steps |
| `glucose_mean`, `glucose_cv` | CGM mean and coefficient of variation (%) |
| `tir_pct` | time-in-range 70–180 mg/dL (%) |
| `glucose_min_night`, `hypo_episodes`, `hyper_hours` | glycaemic risk markers |
| `temp_dev_max`, `rr_max` | daily peaks |
| `sbp_cuff`, `dbp_cuff` | most recent home BP reading that day, if any |

## TwinRisk feature row (19 model features + label)

See `docs/clinical_model.md §8`. Labels: `label_deterioration_48h` ∈ {0,1}
(infection-like acute onset within 48 h) and `hours_to_next_event` for
lead-time analysis. Built exclusively by
`app/engine/features.py::build_feature_rows` — offline (training) and
online (scoring) share this code path.

## Event records (labels)

```jsonc
{"kind": "infection", "label": "Acute deterioration",
 "onset_t": 826,            // hour of ACUTE phase onset (prediction target)
 "prodrome_t": 796}         // prodrome onset (infection events only)
```

## Model artefact — `app/models/twinrisk_v1.json`

`feature_names`, `weights`, `intercept`, standardisation `means`/`sds`,
and `meta`: training size, validation AUROC / AP / sensitivity /
specificity, alert threshold, mean lead time. Loaded at boot; retraining
replaces the file atomically via `scripts/train_risk_model.py`.
