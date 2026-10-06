"""Protocol Studio: treatment/lifestyle what-if simulation on the twin.

Because the twin is a forward physiological model calibrated to the
patient, a proposed protocol change (medication dose, activity, diet,
sleep) can be *simulated before it is prescribed*:

- ``run_scenario``     — simulate one protocol over 30/90/180 days
- ``compare_to_base``  — intervention vs. current protocol, same noise
- ``goal_seek``        — smallest lever change that reaches a clinical target
- ``explain_scenario`` — one-at-a-time lever ablation (contribution table)

Scenario levers (all optional):
    metformin_mg, insulin_units_day, antihyp_mmhg, beta_blocker_bpm,
    steps_day, sleep_hours, stress_level, carbs_day, gi, kcal_delta_day
"""
from __future__ import annotations

import random
from dataclasses import replace
from typing import Optional

from app.engine.physiology import (
    MedEffects,
    PhysiologyParams,
    hba1c_from_mean_glucose,
    simulate_days,
)

LEVER_BOUNDS = {
    "metformin_mg": (0, 3000),
    "insulin_units_day": (0, 80),
    "antihyp_mmhg": (0, 25),
    "beta_blocker_bpm": (0, 20),
    "steps_day": (1000, 15000),
    "sleep_hours": (4.5, 9.0),
    "stress_level": (0.1, 0.9),
    "carbs_day": (80, 400),
    "gi": (0.4, 0.9),
    "kcal_delta_day": (-800, 500),
}


def apply_meds(params: PhysiologyParams, scenario: dict) -> PhysiologyParams:
    """Return params with scenario medication levels applied.

    ``insulin_sensitivity`` embeds the *current* metformin effect (folded in
    at EHR calibration), so a scenario dose change re-derives it from the
    pre-metformin baseline:  base = sens_now / (1 + metformin_sens_now).
    """
    mg_now = params.meds.metformin_sens / 0.18 * 1000.0
    mg_new = float(scenario.get("metformin_mg", mg_now))
    sens_base = params.insulin_sensitivity / (1.0 + params.meds.metformin_sens)
    sens_new = sens_base * (1.0 + 0.18 * mg_new / 1000.0)
    meds = MedEffects(
        antihyp_bp_mmhg=float(scenario.get("antihyp_mmhg", params.meds.antihyp_bp_mmhg)),
        beta_blocker_hr=float(scenario.get("beta_blocker_bpm", params.meds.beta_blocker_hr)),
        metformin_sens=0.18 * mg_new / 1000.0,
        insulin_units_day=float(scenario.get("insulin_units_day", params.meds.insulin_units_day)),
        statin=params.meds.statin,
    )
    return replace(params, meds=meds,
                   insulin_sensitivity=min(1.3, max(0.3, sens_new)))


def scenario_overrides(params: PhysiologyParams, scenario: dict) -> dict:
    """Behavioural levers -> simulate_days overrides (meds removed first)."""
    behaviour_keys = ("steps_day", "sleep_hours", "stress_level", "carbs_day",
                      "gi", "kcal_delta_day", "sodium_g")
    ov = {}
    mapping = {"steps_day": params.activity_steps_day, "sleep_hours": params.sleep_hours_target,
               "stress_level": params.stress_level, "carbs_day": params.diet_carbs_day,
               "gi": params.diet_gi, "kcal_delta_day": 0.0, "sodium_g": params.diet_sodium_g}
    for k in behaviour_keys:
        if k in scenario and scenario[k] != mapping.get(k):
            ov[k] = scenario[k]
    return ov


def _daily_series(states: list) -> dict:
    """Aggregate hourly states into per-day protocol metrics."""
    days = []
    n = len(states) // 24
    for d in range(n):
        chunk = states[d * 24:(d + 1) * 24]
        sleep = [s for s in chunk if s.sleep_stage != "awake"]
        awake = [s for s in chunk if s.sleep_stage == "awake"]
        g = [s.glucose for s in chunk]
        gmean = sum(g) / 24.0
        rest_hr = min((s.hr for s in sleep), default=None)
        days.append({
            "day": d + 1,
            "weight_kg": round(chunk[-1].weight_kg, 2),
            "sbp_day": round(sum(s.sbp for s in awake) / max(1, len(awake)), 1) if awake else round(sum(s.sbp for s in chunk) / 24.0, 1),
            "resting_hr": round(rest_hr, 1) if rest_hr else None,
            "night_hrv": round(sum(s.rmssd for s in sleep) / max(1, len(sleep)), 1) if sleep else None,
            "glucose_mean": round(gmean, 1),
            "tir_pct": round(100.0 * sum(1 for x in g if 70 <= x <= 180) / 24.0, 1),
            "hypo_hours": sum(1 for x in g if x < 70),
            "gmi_pct": round(3.31 + 0.02392 * gmean, 2),  # GMI (JDRF/Abbott)
        })
    return {"days": [d["day"] for d in days], **{k: [d[k] for d in days] for k in
            ("weight_kg", "sbp_day", "resting_hr", "night_hrv", "glucose_mean", "tir_pct", "hypo_hours", "gmi_pct")}}


def run_scenario(params: PhysiologyParams, horizon_days: int, scenario: dict,
                 seed: int = 11) -> dict:
    p = apply_meds(params, scenario)
    ov = scenario_overrides(params, scenario)
    states = simulate_days(p, horizon_days, seed=seed, overrides=ov)
    series = _daily_series(states)
    g_all = [s.glucose for s in states]
    awake = [s for s in states if s.sleep_stage == "awake"]
    sleep = [s for s in states if s.sleep_stage != "awake"]
    summary = {
        "hba1c_start": hba1c_from_mean_glucose(params.glucose_base),
        "hba1c_end": hba1c_from_mean_glucose(sum(g_all) / len(g_all)),
        "weight_start": round(states[0].weight_kg, 1),
        "weight_end": round(states[-1].weight_kg, 1),
        "sbp_start": round(params.sbp_base, 1),
        "sbp_end": round(sum(s.sbp for s in awake) / max(1, len(awake)), 1),
        "resting_hr_end": round(min((s.hr for s in sleep), default=params.resting_hr_base), 1),
        "night_hrv_end": round(sum(s.rmssd for s in sleep) / max(1, len(sleep)), 1) if sleep else None,
        "tir_end": series["tir_pct"][-1],
        "hypo_hours_total": sum(series["hypo_hours"]),
        "sleep_hours_end": round(sum(1 for s in states[-24:] if s.sleep_stage != "awake"), 1),
    }
    return {"scenario": scenario, "horizon_days": horizon_days,
            "series": series, "summary": summary}


def compare_to_base(params: PhysiologyParams, horizon_days: int, scenario: dict,
                    seed: int = 11) -> dict:
    """Run the current protocol and the proposed one on identical noise."""
    base = run_scenario(params, horizon_days, {}, seed=seed)
    interv = run_scenario(params, horizon_days, scenario, seed=seed)
    deltas = {}
    for k in ("hba1c_end", "weight_end", "sbp_end", "resting_hr_end", "night_hrv_end", "tir_end"):
        b, i = base["summary"].get(k), interv["summary"].get(k)
        if isinstance(b, (int, float)) and isinstance(i, (int, float)):
            deltas[k.replace("_end", "")] = round(i - b, 2)
    return {"baseline": base, "intervention": interv, "deltas": deltas}


def goal_seek(params: PhysiologyParams, horizon_days: int, lever: str,
              target_metric: str, target_value: float,
              direction: str = "below", seed: int = 11,
              scenario_base: Optional[dict] = None) -> dict:
    """Binary-search the smallest lever change reaching a clinical target.

    Example: lever="metformin_mg", target_metric="hba1c_end",
    target_value=6.5, direction="below"  →  the minimum dose reaching A1c 6.5.
    Returns the required lever value, the achieved trajectory, and an
    uncertainty band from ±10% physiological-parameter jitter (5 runs).
    """
    assert lever in LEVER_BOUNDS, f"unsupported lever {lever}"
    lo, hi = LEVER_BOUNDS[lever]
    base_scenario = dict(scenario_base or {})

    def achieved(value: float) -> float:
        sc = dict(base_scenario)
        sc[lever] = value
        return run_scenario(params, horizon_days, sc, seed=seed)["summary"][target_metric]

    def ok(value: float) -> bool:
        v = achieved(value)
        return v <= target_value if direction == "below" else v >= target_value

    if not ok(hi):
        return {"feasible": False, "lever": lever, "target_metric": target_metric,
                "target_value": target_value,
                "note": f"target not reachable even at lever maximum ({hi}) within {horizon_days} days"}
    if ok(lo):
        value = lo
    else:
        for _ in range(18):
            mid = (lo + hi) / 2
            if ok(mid):
                hi = mid
            else:
                lo = mid
        value = hi
    if lever in ("metformin_mg", "insulin_units_day", "antihyp_mmhg", "beta_blocker_bpm", "steps_day"):
        value = int(round(value / 50.0) * 50) if lever == "metformin_mg" else int(round(value))

    # Uncertainty band: jitter insulin sensitivity & beta function ±10%
    band = []
    for j, mult in enumerate((0.9, 0.95, 1.0, 1.05, 1.1)):
        pj = replace(params,
                     insulin_sensitivity=params.insulin_sensitivity * mult,
                     beta_function=max(0.2, params.beta_function * mult))
        sc = dict(base_scenario)
        sc[lever] = value
        band.append(run_scenario(pj, horizon_days, sc, seed=seed + j)["summary"][target_metric])

    sc_final = dict(base_scenario)
    sc_final[lever] = value
    run = run_scenario(params, horizon_days, sc_final, seed=seed)
    return {
        "feasible": True,
        "lever": lever,
        "lever_value": value,
        "target_metric": target_metric,
        "target_value": target_value,
        "achieved": run["summary"][target_metric],
        "band": {"min": min(band), "max": max(band)},
        "run": run,
        "interpretation": _interpret(lever, value, target_metric, params),
    }


def _interpret(lever: str, value: float, target_metric: str, params: PhysiologyParams) -> str:
    current = {
        "metformin_mg": params.meds.metformin_sens / 0.18 * 1000.0,
        "insulin_units_day": params.meds.insulin_units_day,
        "antihyp_mmhg": params.meds.antihyp_bp_mmhg,
        "steps_day": params.activity_steps_day,
    }.get(lever)
    if lever == "metformin_mg":
        return (f"Simulated protocol: metformin ≈ {value:.0f} mg/day "
                f"(currently ≈ {current:.0f} mg/day). The twin projects this reaches "
                f"{target_metric.replace('_end', '')} target with the smallest effective dose.")
    if lever == "steps_day":
        return (f"Simulated protocol: {value:.0f} steps/day "
                f"(currently ≈ {current:.0f}). Projected to reach the target within the horizon.")
    return f"Simulated protocol sets {lever} = {value} to reach the target."


def explain_scenario(params: PhysiologyParams, horizon_days: int, scenario: dict,
                     seed: int = 11) -> list[dict]:
    """One-at-a-time lever ablation: each lever's isolated contribution."""
    base = run_scenario(params, horizon_days, {}, seed=seed)
    rows = []
    for lever in scenario:
        if lever not in LEVER_BOUNDS:
            continue
        single = {lever: scenario[lever]}
        r = run_scenario(params, horizon_days, single, seed=seed)
        rows.append({
            "lever": lever,
            "value": scenario[lever],
            "hba1c_delta": round(r["summary"]["hba1c_end"] - base["summary"]["hba1c_end"], 2),
            "weight_delta": round(r["summary"]["weight_end"] - base["summary"]["weight_end"], 2),
            "sbp_delta": round(r["summary"]["sbp_end"] - base["summary"]["sbp_end"], 1),
        })
    return sorted(rows, key=lambda r: -abs(r["hba1c_delta"]) - abs(r["weight_delta"]))
