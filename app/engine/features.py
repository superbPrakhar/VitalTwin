"""Feature engineering: assimilated daily summaries -> model feature rows.

The same ``build_feature_rows`` code path is used for offline training and
for live scoring in the app, so there is no training/serving skew.
Features are computed only from information available at the end of day d
(personal baselines use the *prior* 14 days) — no future leakage.
"""
from __future__ import annotations

import math
from typing import Optional

# TwinRisk's *prediction* target: prodromal (infection-like) deterioration.
# Abrupt events (hypertensive crisis, hypoglycaemia) carry no wearable-
# detectable prodrome; they are handled by the live monitoring-alarm layer
# (absolute thresholds on the assimilated vitals), which mirrors how real
# CGM/monitoring systems behave.
PREDICTION_KINDS = ("infection",)

FEATURE_NAMES = [
    "rest_hr_z", "hr_evening_z", "hrv_night_z", "hrv_evening_z",
    "hr_up_hrv_down", "hrv_ratio_3_7",
    "sleep_hours_7d", "sleep_debt_7d", "sleep_frag_3d", "spo2_dip_3d",
    "steps_ratio", "glucose_mean_z", "glucose_cv_3d", "tir_7d",
    "glucose_night_min_3d", "hypo_7d", "temp_dev_max_z", "temp_dev_3d_z",
    "rr_max_z", "age", "bmi", "comorbidity_count",
]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _z(value: Optional[float], history: list) -> Optional[float]:
    m, s = _mean(history), _sd(history)
    if value is None or m is None or not s:
        return None
    return (value - m) / s


def build_feature_rows(params_summary: dict, days: list, events: list[dict],
                       warmup_days: int = 14) -> list[dict]:
    """One feature row per completed day from ``warmup_days`` onward.

    ``days``: list of DailySummary.to_dict() assimilated by the mirror.
    ``events``: event records with ``onset_t`` (acute onset hour) and ``kind``.
    """
    rows: list[dict] = []
    det_onsets = [e["onset_t"] for e in events if e["kind"] in PREDICTION_KINDS]

    for d in range(warmup_days, len(days)):
        day = days[d]
        prior = days[max(0, d - 14):d]
        last3 = days[max(0, d - 3):d + 1]
        prior7 = days[max(0, d - 10):max(0, d - 3)] or prior

        row = {
            "day_index": d,
            "t_end": day["t_end"],
            "rest_hr_z": _z(day["rest_hr"], [x["rest_hr"] for x in prior]),
            "hr_evening_z": _z(day["hr_evening_mean"], [x["hr_evening_mean"] for x in prior]),
            "hrv_night_z": _z(-day["night_hrv_mean"], [-x["night_hrv_mean"] for x in prior]),
            "hrv_evening_z": _z(-day["hrv_evening_mean"], [-x["hrv_evening_mean"] for x in prior]),
            "hr_up_hrv_down": ((_z(day["hr_evening_mean"], [x["hr_evening_mean"] for x in prior]) or 0.0)
                               - (_z(day["hrv_evening_mean"], [x["hrv_evening_mean"] for x in prior]) or 0.0)),
            "hrv_ratio_3_7": (_mean([x["night_hrv_mean"] for x in last3]) /
                              _mean([x["night_hrv_mean"] for x in prior7])
                              if _mean([x["night_hrv_mean"] for x in prior7]) else None),
            "sleep_hours_7d": _mean([x["sleep_hours"] for x in days[max(0, d - 6):d + 1]]),
            "sleep_debt_7d": sum(max(0.0, 7.5 - x["sleep_hours"]) for x in days[max(0, d - 6):d + 1]),
            "sleep_frag_3d": _mean([x["sleep_frag"] for x in last3]),
            "spo2_dip_3d": _mean([x["spo2_dip_hours"] for x in last3]),
            "steps_ratio": (day["steps"] / m if (m := _mean([x["steps"] for x in prior])) else None),
            "glucose_mean_z": _z(day["glucose_mean"], [x["glucose_mean"] for x in prior]),
            "glucose_cv_3d": _mean([x["glucose_cv"] for x in last3]),
            "tir_7d": _mean([x["tir_pct"] for x in days[max(0, d - 6):d + 1]]),
            "glucose_night_min_3d": min((x["glucose_min_night"] for x in last3), default=None),
            "hypo_7d": sum(x["hypo_episodes"] for x in days[max(0, d - 6):d + 1]),
            "temp_dev_max_z": _z(day["temp_dev_max"], [x["temp_dev_max"] for x in prior]),
            "temp_dev_3d_z": _z(_mean([x["temp_dev_max"] for x in last3]),
                                [x["temp_dev_max"] for x in prior]),
            "rr_max_z": _z(day["rr_max"], [x["rr_max"] for x in prior]),
            "age": params_summary.get("age"),
            "bmi": params_summary.get("bmi"),
            "comorbidity_count": len(params_summary.get("conditions", [])),
        }
        t_end = day["t_end"]
        row["label_deterioration_48h"] = int(any(t_end < o <= t_end + 48 for o in det_onsets))
        future = [o - t_end for o in det_onsets if o > t_end]
        row["hours_to_next_event"] = min(future) if future else -1
        rows.append(row)
    return rows
