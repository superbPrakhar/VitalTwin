"""Patient archetypes used by the synthetic cohort generator.

Each archetype is an EHR-shaped bundle plus a demographic jitter spec.
They cover the clinical spread the demo targets: metabolic risk, hypertension,
post-cardiac-event elderly, respiratory disease, insulin-treated diabetes.
All data is synthetic — no real patient data exists anywhere in this repo.
"""
from __future__ import annotations

import random

ARCHETYPES: list[dict] = [
    {
        "name": "healthy_adult",
        "weight": 22,
        "ehr": {
            "demographics": {"age": [28, 45], "sex": ["M", "F"], "height_cm": [158, 185], "weight_kg": [55, 82]},
            "conditions": [],
            "labs": {"hba1c_pct": [5.0, 5.6]},
            "baseline_vitals": {"sbp": [108, 124], "dbp": [68, 80]},
            "medications": {},
            "self_report": {"activity_steps_day": [7000, 12000], "sleep_hours": [6.8, 8.2], "stress_level": [0.2, 0.45]},
        },
    },
    {
        "name": "t2d_hypertension",
        "weight": 24,
        "ehr": {
            "demographics": {"age": [48, 66], "sex": ["M", "F"], "height_cm": [152, 180], "weight_kg": [70, 98]},
            "conditions": ["t2d", "hypertension"],
            "labs": {"hba1c_pct": [7.0, 8.6], "fasting_glucose_mgdl": [126, 172]},
            "baseline_vitals": {"sbp": [138, 158], "dbp": [84, 94]},
            "medications": {"metformin_mg": [500, 1500], "antihypertensive_mmhg": [6, 12], "statin": [True]},
            "self_report": {"activity_steps_day": [2500, 6000], "sleep_hours": [5.6, 7.0], "stress_level": [0.45, 0.7]},
        },
    },
    {
        "name": "prediabetes_stress",
        "weight": 18,
        "ehr": {
            "demographics": {"age": [34, 52], "sex": ["M", "F"], "height_cm": [155, 178], "weight_kg": [62, 88]},
            "conditions": ["prediabetes"],
            "labs": {"hba1c_pct": [5.8, 6.4], "fasting_glucose_mgdl": [105, 124]},
            "baseline_vitals": {"sbp": [120, 136], "dbp": [76, 86]},
            "medications": {},
            "self_report": {"activity_steps_day": [3000, 7000], "sleep_hours": [5.2, 6.6], "stress_level": [0.55, 0.8]},
        },
    },
    {
        "name": "elderly_cardiac",
        "weight": 14,
        "ehr": {
            "demographics": {"age": [66, 80], "sex": ["M", "F"], "height_cm": [150, 175], "weight_kg": [58, 84]},
            "conditions": ["cad", "hypertension"],
            "labs": {"hba1c_pct": [5.6, 6.6]},
            "baseline_vitals": {"sbp": [128, 148], "dbp": [76, 88]},
            "medications": {"beta_blocker_bpm": [6, 12], "antihypertensive_mmhg": [8, 14], "statin": [True]},
            "self_report": {"activity_steps_day": [3000, 6500], "sleep_hours": [6.0, 7.4], "stress_level": [0.3, 0.55]},
        },
    },
    {
        "name": "copd_elderly",
        "weight": 10,
        "ehr": {
            "demographics": {"age": [62, 78], "sex": ["M", "F"], "height_cm": [150, 175], "weight_kg": [50, 78]},
            "conditions": ["copd"],
            "labs": {"hba1c_pct": [5.2, 6.2]},
            "baseline_vitals": {"sbp": [118, 140], "dbp": [72, 86]},
            "medications": {},
            "self_report": {"activity_steps_day": [2000, 5000], "sleep_hours": [5.8, 7.2], "stress_level": [0.35, 0.6]},
        },
    },
    {
        "name": "insulin_t2d",
        "weight": 8,
        "ehr": {
            "demographics": {"age": [50, 70], "sex": ["M", "F"], "height_cm": [152, 180], "weight_kg": [68, 100]},
            "conditions": ["t2d", "hypertension"],
            "labs": {"hba1c_pct": [7.8, 9.4], "fasting_glucose_mgdl": [150, 200]},
            "baseline_vitals": {"sbp": [136, 156], "dbp": [82, 94]},
            "medications": {"metformin_mg": [1000, 2000], "insulin_units_day": [12, 30], "antihypertensive_mmhg": [8, 14], "statin": [True]},
            "self_report": {"activity_steps_day": [2500, 5500], "sleep_hours": [5.6, 7.0], "stress_level": [0.4, 0.65]},
        },
    },
    {
        "name": "osa_obese",
        "weight": 4,
        "ehr": {
            "demographics": {"age": [38, 58], "sex": ["M", "F"], "height_cm": [155, 182], "weight_kg": [88, 118]},
            "conditions": ["osa", "hypertension", "prediabetes"],
            "labs": {"hba1c_pct": [5.9, 6.5]},
            "baseline_vitals": {"sbp": [132, 152], "dbp": [84, 94]},
            "medications": {"antihypertensive_mmhg": [6, 12]},
            "self_report": {"activity_steps_day": [2500, 5500], "sleep_hours": [5.5, 6.8], "stress_level": [0.45, 0.7]},
        },
    },
]


def sample_ehr(rng: random.Random) -> dict:
    """Sample one EHR bundle from the archetype mixture."""
    total = sum(a["weight"] for a in ARCHETYPES)
    pick = rng.random() * total
    acc, archetype = 0.0, ARCHETYPES[0]
    for a in ARCHETYPES:
        acc += a["weight"]
        if pick <= acc:
            archetype = a
            break
    return _materialize(archetype["ehr"], rng)


_FIRST = ["Aarav", "Diya", "Rohan", "Meera", "Kabir", "Ananya", "Vikram", "Sunita",
          "Arjun", "Priya", "Dev", "Kavya", "Ravi", "Lakshmi", "Nikhil", "Isha"]
_LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Nair", "Gupta", "Menon", "Rao",
         "Joshi", "Das", "Kulkarni", "Pillai"]


def _materialize(spec: dict, rng: random.Random) -> dict:
    out: dict = {}
    for section, fields in spec.items():
        if isinstance(fields, dict):
            out[section] = {}
            for key, rng_spec in fields.items():
                out[section][key] = _draw(rng_spec, rng)
        else:
            out[section] = fields  # list/scalar sections (conditions, statin, …)
    return out


def _draw(spec, rng: random.Random):
    if isinstance(spec, list) and len(spec) == 2 and all(isinstance(v, (int, float)) for v in spec):
        lo, hi = spec
        if isinstance(lo, int) and isinstance(hi, int):
            return rng.randint(lo, hi)
        return round(rng.uniform(lo, hi), 2)
    if isinstance(spec, list):
        return rng.choice(spec)
    return spec


def display_name(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
