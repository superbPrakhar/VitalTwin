"""Physiological forward model sanity tests — clinical plausibility gates."""
import random

import pytest

from app.engine.physiology import (
    EventModifier,
    params_from_ehr,
    simulate_days,
    hba1c_from_mean_glucose,
)

EHR_HEALTHY = {
    "patient_id": "t1",
    "demographics": {"age": 35, "sex": "M", "height_cm": 175, "weight_kg": 70},
    "conditions": [],
    "labs": {"hba1c_pct": 5.2},
    "baseline_vitals": {"sbp": 118, "dbp": 74},
    "medications": {},
    "self_report": {"activity_steps_day": 9000, "sleep_hours": 7.5, "stress_level": 0.3},
}

EHR_T2D = {
    "patient_id": "t2",
    "demographics": {"age": 58, "sex": "M", "height_cm": 170, "weight_kg": 84},
    "conditions": ["t2d", "hypertension"],
    "labs": {"hba1c_pct": 7.8, "fasting_glucose_mgdl": 145},
    "baseline_vitals": {"sbp": 146, "dbp": 88},
    "medications": {"metformin_mg": 1000, "antihypertensive_mmhg": 8},
    "self_report": {"activity_steps_day": 3800, "sleep_hours": 6.0, "stress_level": 0.6},
}


def test_healthy_glucose_response_after_meal():
    p = params_from_ehr(EHR_HEALTHY)
    states = simulate_days(p, 3, seed=1)
    # morning-post-meal peak vs pre-meal: expect a ~20-60 mg/dL excursion
    day1 = states[7:12]
    peak = max(s.glucose for s in day1)
    pre = states[6].glucose
    assert 15 <= peak - pre <= 70
    # returns near baseline within 4h of the meal
    assert states[11].glucose - p.glucose_base < 25


def test_t2d_excursions_larger_than_healthy():
    p_healthy = params_from_ehr(EHR_HEALTHY)
    p_t2d = params_from_ehr(EHR_T2D)
    h = simulate_days(p_healthy, 5, seed=2)
    t = simulate_days(p_t2d, 5, seed=2)
    exc = lambda st: max(s.glucose for s in st) - min(s.glucose for s in st)  # noqa: E731
    assert exc(t) > 1.6 * exc(h)
    # A1c anchored near the EHR value
    assert 7.0 <= hba1c_from_mean_glucose(sum(s.glucose for s in t) / len(t)) <= 8.6


def test_beta_blocker_lowers_hr():
    ehr = {**EHR_HEALTHY, "medications": {"beta_blocker_bpm": 10}}
    p = params_from_ehr(ehr)
    states = simulate_days(p, 5, seed=3)
    mean_hr = sum(s.hr for s in states if s.sleep_stage == "awake") / sum(
        1 for s in states if s.sleep_stage == "awake")
    assert mean_hr < 78


def test_weight_loss_on_diet_protocol_and_sensitivity_improves():
    p = params_from_ehr(EHR_T2D)
    base = simulate_days(p, 30, seed=4)
    interv = simulate_days(p, 30, seed=4, overrides={"kcal_delta_day": -400, "steps_day": 8000})
    assert interv[-1].weight_kg < base[-1].weight_kg - 1.0
    assert interv[-1].fitness > base[-1].fitness


def test_infection_event_produces_prodrome_then_acute_signature():
    p = params_from_ehr(EHR_HEALTHY)
    onset = 48  # hour 48
    prodrome = EventModifier(kind="infection", onset_h=onset, duration_h=30,
                             fever_peak=0.9, hr_mult_peak=0.16, rr_delta_peak=3.0,
                             hrv_mult_peak=0.62, stress_delta_peak=0.25)
    acute = EventModifier(kind="infection", onset_h=onset + 30, duration_h=48,
                          fever_peak=1.7, hr_mult_peak=0.28, sbp_delta_peak=-24,
                          spo2_delta_peak=-3.8, rr_delta_peak=6.5, hrv_mult_peak=0.45)
    states = simulate_days(p, 7, events=[prodrome, acute], seed=5)
    # compare like-for-like: all three snapshots are night hours (sleeping)
    pre = states[26]                  # ~2am, before prodrome
    pro = states[72]                  # night, prodrome active
    acu = states[onset + 30 + 20]     # acute phase (night)
    assert acu.temp_c - pre.temp_c > 1.0
    assert acu.hr > pre.hr + 12
    assert acu.rmssd < pro.rmssd
    assert acu.sbp < pre.sbp - 8      # vasodilatory fall
    assert acu.rr > pro.rr


def test_determinism_same_seed_same_stream():
    p = params_from_ehr(EHR_HEALTHY)
    a = [s.to_dict() for s in simulate_days(p, 4, seed=9)]
    b = [s.to_dict() for s in simulate_days(p, 4, seed=9)]
    assert a == b
