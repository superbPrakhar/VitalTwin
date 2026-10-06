# API reference

Base URL: `http://127.0.0.1:8000`. Interactive docs: `/docs` (Swagger UI)
and `/redoc`. All request/response bodies are JSON. The full schema lives in
`app/main.py`; this is the human reference.

## System

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness + model metadata (metrics, threshold, training size). |
| GET | `/api/model` | TwinRisk model card: features, task, evaluation metrics, training-data statement. |

## Patients

| Method | Path | Description |
|---|---|---|
| GET | `/api/patients` | Roster with headline risk (TwinRisk probability + band, NEWS2, HbA1c-equivalent, live alarms). |
| GET | `/api/patients/{pid}` | Full EHR snapshot + calibrated twin parameters + sync state. |
| GET | `/api/patients/{pid}/mirror` | Current assimilated state: organ-system status, latest estimate per channel, deviation z-scores, baseline warm-up status. |
| GET | `/api/patients/{pid}/hourly?hours=48` | Recent hourly assimilated records (per-channel estimates + z-scores). |
| GET | `/api/patients/{pid}/trends?days=14` | Daily assimilated summaries (resting HR, night HRV, sleep, steps, glucose metrics, cuff BPs). |

## Risk & alerts

| Method | Path | Description |
|---|---|---|
| GET | `/api/patients/{pid}/risk` | NEWS2 (score + per-parameter split), TwinRisk (probability, threshold, top driver contributions, band), live monitoring alarms, 30-day risk history. |
| GET | `/api/patients/{pid}/alerts` | Replay of the twin's alert feed with lead-time annotations. |
| POST | `/api/patients/{pid}/sync` `{hours: 6}` | Reveal the next telemetry window, assimilate it, re-score; returns new alerts (fires when TwinRisk crosses the threshold). |

## Protocol studio

| Method | Path | Description |
|---|---|---|
| POST | `/api/patients/{pid}/simulate` `{scenario, horizon_days}` | Runs the current protocol and the scenario on identical noise; returns daily series (weight, SBP, resting HR, night HRV, glucose, TIR, GMI) + summary deltas. |
| POST | `/api/patients/{pid}/goal` `{lever, target_metric, target_value, horizon_days, direction, scenario_base}` | Binary-searches the smallest lever value reaching the target; returns the required value, achieved metric, ±10 % jitter band, full trajectory and an interpretation string. |
| POST | `/api/patients/{pid}/explain` `{scenario, horizon_days}` | One-at-a-time lever ablation: each lever's isolated Δ HbA1c / weight / SBP. |
| GET | `/api/patients/{pid}/report` | Markdown clinician-facing summary (mirror, risk, drivers, review recommendations). |

**Scenario levers** (any subset, validated against `LEVER_BOUNDS`):
`metformin_mg` (0–3000), `insulin_units_day` (0–80), `antihyp_mmhg` (0–25),
`beta_blocker_bpm` (0–20), `steps_day` (1000–15000), `sleep_hours`
(4.5–9), `stress_level` (0.1–0.9), `carbs_day` (80–400), `gi` (0.4–0.9),
`kcal_delta_day` (−800–500), `sodium_g`.

### Example

```bash
curl -s -X POST http://127.0.0.1:8000/api/patients/ravi/goal \
  -H "Content-Type: application/json" \
  -d '{"lever":"metformin_mg","target_metric":"hba1c_end","target_value":7.0,
       "horizon_days":90,"scenario_base":{"steps_day":9000,"kcal_delta_day":-300}}'
```

Returns `{"feasible": true, "lever_value": 600, "achieved": 7.0,
"band": {...}, "run": {...}, "interpretation": "..."}` — i.e. with the
lifestyle protocol in place, 600 mg/day metformin suffices.

## Error semantics

`404` unknown patient · `422` invalid levers/direction (with a message) ·
`503` risk model not loaded. FastAPI's standard validation errors carry
field-level detail.
