"""Synthetic patient + telemetry generation.

Produces, per patient: an EHR bundle (FHIR-lite), calibrated twin
parameters, an hourly wearable/CGM telemetry stream with realistic sensor
noise and dropouts, and labeled adverse-event records.

Everything is seeded and reproducible. No real patient data is used
anywhere in VitalTwin (see docs/privacy_and_ethics.md).
"""
from __future__ import annotations

import random
from dataclasses import asdict

from app.engine.physiology import (
    PhysiologyParams,
    TwinState,
    params_from_ehr,
    simulate_days,
)
from app.engine.events import sample_event_schedule
from app.data.archetypes import sample_ehr, display_name


def generate_patient_ehr(patient_id: str, rng: random.Random) -> dict:
    ehr = sample_ehr(rng)
    ehr["patient_id"] = patient_id
    ehr["name"] = display_name(rng)
    ehr["ehr_id"] = f"EHR-{patient_id.upper()}"
    # A small historical problem list for realism
    ehr["history_notes"] = ehr.get("history_notes", [])
    return ehr


def generate_wearable_stream(params: PhysiologyParams, n_days: int, seed: int,
                             events: list | None = None, start_t: int = 0) -> list[dict]:
    """Simulate true physiology, then apply the sensor model.

    Sensor models (documented in docs/clinical_model.md#sensor-models):
    - wrist PPG HR: gaussian sd 3.5 bpm, 2% dropout (carries previous value)
    - HRV RMSSD: gaussian sd 3.2 ms
    - SpO2: gaussian sd 0.7%, rounded to 1 decimal, floor 70
    - steps: integer, ±6% multiplicative jitter
    - CGM: gaussian sd 2.5 mg/dL, rounded
    - skin temperature deviation: 0.6 × core fever, sd 0.15 °C
    - respiration rate: gaussian sd 0.6 brpm
    """
    events = events or []
    truth = simulate_days(params, n_days, events=events, seed=seed)
    rng = random.Random(seed * 7919 + 13)
    out: list[dict] = []
    prev_hr: float | None = None
    for s in truth:
        t = start_t + s.t_index - 1   # s.t_index counts completed hours; rec t = hour of day it describes
        hr = s.hr + rng.gauss(0, 3.5)
        if rng.random() < 0.02 and prev_hr is not None:      # PPG dropout
            hr = prev_hr
        prev_hr = hr
        steps = max(0, int(s.steps_hour * (0.94 + 0.12 * rng.random())))
        rec = {
            "t": t,
            "hr": round(max(35.0, hr), 1),
            "hrv": round(max(4.0, s.rmssd + rng.gauss(0, 3.2)), 1),
            "spo2": round(max(70.0, s.spo2 + rng.gauss(0, 0.7)), 1),
            "steps": steps,
            "sleep_stage": s.sleep_stage,
            "glucose": round(max(35.0, s.glucose + rng.gauss(0, 2.5)), 1),
            "temp_dev": round(0.6 * (s.temp_c - params.temp_base) + rng.gauss(0, 0.15), 2),
            "rr": round(s.rr + rng.gauss(0, 0.6), 1),
        }
        # Home cuff BP ~every 3rd morning at 08:00 (mixed-sampling reality)
        if t % 24 == 8 and (t // 24) % 3 == 0:
            rec["sbp"] = round(max(70.0, s.sbp + rng.gauss(0, 4.0)), 0)
            rec["dbp"] = round(max(45.0, s.dbp + rng.gauss(0, 3.0)), 0)
        out.append(rec)
    return out, truth


def generate_patient_cohort_entry(patient_id: str, n_days: int, seed: int,
                                  ehr_override: dict | None = None) -> dict:
    """Full data package for one patient: EHR, params, stream, events, truth."""
    rng = random.Random(seed)
    ehr = ehr_override or generate_patient_ehr(patient_id, rng)
    params = params_from_ehr(ehr)
    # Place events anywhere in the stream but avoid the first 5 days
    # (assimilation warm-up) so every patient starts with a clean baseline.
    mods, records = sample_event_schedule(params, n_days, rng, start_t=5 * 24)
    stream, truth = generate_wearable_stream(params, n_days, seed + 1, events=mods)
    return {
        "patient_id": patient_id,
        "ehr": ehr,
        "params": _params_summary(params),
        "stream": stream,
        "truth": [s.to_dict() for s in truth],
        "events": records,
    }


def _params_summary(p: PhysiologyParams) -> dict:
    return {
        "age": p.age, "sex": p.sex, "bmi": round(p.bmi, 1),
        "conditions": sorted(p.conditions),
        "insulin_sensitivity": round(p.insulin_sensitivity, 3),
        "beta_function": round(p.beta_function, 3),
        "fitness": round(p.fitness, 3),
        "rmssd_base": round(p.rmssd_base, 1),
        "resting_hr_base": round(p.resting_hr_base, 1),
        "sbp_base": round(p.sbp_base, 1),
    }
