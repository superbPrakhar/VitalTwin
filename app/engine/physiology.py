"""Physiological forward model — the core of the VitalTwin digital twin.

A transparent, discrete-time (1-hour step) simulation of coupled
cardiovascular, autonomic, respiratory, metabolic and energy-balance
dynamics. The *same* forward model serves two purposes:

1. **Data generation** — producing labeled synthetic telemetry streams
   (EHR prior + wearables + injected adverse-event processes).
2. **Twin simulation** — the "what-if" engine behind the Protocol
   Studio: given a patient's calibrated parameters, project their
   physiology forward under a modified treatment/lifestyle protocol.

All equations are documented in ``docs/clinical_model.md`` alongside the
clinical literature they are grounded in (NEWS2, Bergman minimal model,
ADAG HbA1c relationship, Task Force HRV metrics, Mifflin-St Jeor BMR).

Everything is deterministic for a given RNG seed, which keeps tests and
evaluations reproducible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

import random

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

SLEEP_STAGES = ("awake", "light", "deep", "rem")


@dataclass
class MedEffects:
    """Steady-state pharmacodynamic offsets applied in the forward model."""

    antihyp_bp_mmhg: float = 0.0   # SBP reduction at steady state (mmHg)
    beta_blocker_hr: float = 0.0   # resting HR reduction (bpm)
    metformin_sens: float = 0.0    # relative insulin-sensitivity increase
    insulin_units_day: float = 0.0 # exogenous basal insulin (units/day)
    statin: bool = False


@dataclass
class PhysiologyParams:
    """Calibrated patient parameters (the twin's *fixed* side).

    ``params_from_ehr`` derives these from the EHR bundle at onboarding;
    the assimilation loop can slowly refine a few of them over time.
    """

    patient_id: str
    age: int
    sex: str                      # "M" | "F"
    height_cm: float
    weight_kg: float

    conditions: frozenset[str] = frozenset()

    # Behavioural baselines (what the twin believes the patient's day
    # looks like before we see their wearable data; refined by assimilation)
    diet_carbs_day: float = 220.0      # grams of carbohydrate / day
    diet_gi: float = 0.65              # mean glycaemic index of the diet
    diet_sodium_g: float = 4.0         # grams sodium / day
    activity_steps_day: float = 6000.0
    sleep_hours_target: float = 7.0
    stress_level: float = 0.45         # chronic stress 0..1

    # Physiology baselines
    bmr_kcal_day: float = 1600.0
    resting_hr_base: float = 72.0
    sbp_base: float = 126.0
    dbp_base: float = 78.0
    glucose_base: float = 100.0        # fasting plasma glucose, mg/dL
    insulin_sensitivity: float = 1.0   # 1.0 = healthy reference
    beta_function: float = 1.0         # pancreatic secretory capacity 0..1.1
    rmssd_base: float = 35.0           # night-time RMSSD, ms
    spo2_base: float = 97.0
    rr_base: float = 14.0
    temp_base: float = 36.5
    fitness: float = 0.5               # VO2max proxy 0..1
    stress_reactivity: float = 0.6     # acute stress gain 0..1
    sensitivity_ref: float = 1.0       # sensitivity at calibration (never modified by apply_meds)

    meds: MedEffects = field(default_factory=MedEffects)

    @property
    def bmi(self) -> float:
        return self.weight_kg / (self.height_cm / 100.0) ** 2


@dataclass
class TwinState:
    """The twin's hourly physiological state vector (the dynamic side)."""

    t_index: int                  # global hour counter (0-based from onboarding)
    hr: float = 72.0
    sbp: float = 126.0
    dbp: float = 78.0
    rr: float = 14.0
    spo2: float = 97.0
    temp_c: float = 36.5
    glucose: float = 100.0        # mg/dL (interstitial proxy)
    rmssd: float = 35.0           # ms
    stress: float = 0.4           # 0..1
    sleep_stage: str = "awake"
    steps_hour: float = 0.0
    kcal_in_hour: float = 0.0
    day_balance_kcal: float = 0.0 # running energy balance for the day
    weight_kg: float = 70.0
    insulin_sensitivity: float = 1.0  # dynamic (exercise/metformin adjusted)
    sleep_debt_h: float = 0.0     # cumulative sleep debt, hours
    fitness: float = 0.5          # dynamic fitness, drifts toward activity level
    slow_sens: float = 1.0        # slow sensitivity state (weight/fitness adapted)

    @property
    def map(self) -> float:
        """Mean arterial pressure."""
        return round((self.sbp + 2 * self.dbp) / 3.0, 1)

    @property
    def shock_index(self) -> float:
        return round(self.hr / max(self.sbp, 1.0), 3)

    def to_dict(self) -> dict:
        d = {
            "t_index": self.t_index,
            "hr": round(self.hr, 1),
            "sbp": round(self.sbp, 1),
            "dbp": round(self.dbp, 1),
            "map": self.map,
            "shock_index": self.shock_index,
            "rr": round(self.rr, 1),
            "spo2": round(self.spo2, 1),
            "temp_c": round(self.temp_c, 2),
            "glucose": round(self.glucose, 1),
            "rmssd": round(self.rmssd, 1),
            "stress": round(self.stress, 3),
            "sleep_stage": self.sleep_stage,
            "steps_hour": round(self.steps_hour),
            "kcal_in_hour": round(self.kcal_in_hour),
            "day_balance_kcal": round(self.day_balance_kcal),
            "weight_kg": round(self.weight_kg, 2),
            "insulin_sensitivity": round(self.insulin_sensitivity, 3),
        }
        return d


@dataclass
class Meal:
    hour: int            # hour of day the meal is eaten
    carbs_g: float
    gi: float = 0.65
    kcal: float = 600.0


@dataclass
class DayPlan:
    """One simulated day's behavioural schedule."""

    meals: list[Meal] = field(default_factory=list)
    steps_target: float = 6000.0
    sleep_hours: float = 7.0
    stress_level: float = 0.45
    sodium_g: float = 4.0


# --------------------------------------------------------------------------
# Calibration: EHR bundle -> PhysiologyParams
# --------------------------------------------------------------------------

def params_from_ehr(ehr: dict) -> PhysiologyParams:
    """Calibrate the twin's fixed parameters from an EHR summary bundle.

    The bundle is a FHIR-lite dict (see ``docs/data_dictionary.md`` and
    ``app/data/seed_patients.json``). Every mapping below encodes a
    standard clinical association and is cited in ``docs/clinical_model.md``.
    """
    demo = ehr["demographics"]
    age, sex = int(demo["age"]), demo["sex"]
    height, weight = float(demo["height_cm"]), float(demo["weight_kg"])
    conditions = frozenset(c.lower() for c in ehr.get("conditions", []))
    labs = ehr.get("labs", {}) or {}
    vitals = ehr.get("baseline_vitals", {}) or {}
    meds_in = ehr.get("medications", {}) or {}

    meds = MedEffects(
        antihyp_bp_mmhg=float(meds_in.get("antihypertensive_mmhg", 0.0)),
        beta_blocker_hr=float(meds_in.get("beta_blocker_bpm", 0.0)),
        metformin_sens=float(meds_in.get("metformin_mg", 0)) / 1000.0 * 0.18,
        insulin_units_day=float(meds_in.get("insulin_units_day", 0.0)),
        statin=bool(meds_in.get("statin", False)),
    )

    # Mifflin-St Jeor BMR
    if sex == "F":
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age + 5

    activity = float(ehr.get("self_report", {}).get("activity_steps_day", 6000.0))
    fitness = _clamp(0.15 + (activity / 12000.0) * 0.65 - (age - 40) * 0.004, 0.08, 1.0)

    # Resting HR: age and deconditioning raise it; beta-blockade lowers it.
    resting_hr = 62 + 0.25 * max(0, age - 30) + 8 * (1 - fitness) - meds.beta_blocker_hr
    resting_hr = _clamp(resting_hr, 48, 100)

    # Blood pressure baseline: EHR clinic readings are the anchor.
    sbp = float(vitals.get("sbp", 118 + 0.4 * max(0, age - 30) + 8 * ("hypertension" in conditions)))
    dbp = float(vitals.get("dbp", 76 + 0.15 * max(0, age - 40) + 3 * ("hypertension" in conditions)))
    sbp -= meds.antihyp_bp_mmhg
    dbp -= 0.55 * meds.antihyp_bp_mmhg

    # Metabolic: glucose base from labs; beta-cell function declines with
    # T2D duration and age; insulin sensitivity penalised by adiposity.
    glucose_base = float(labs.get("fasting_glucose_mgdl", 92 + 6 * ("prediabetes" in conditions) + 24 * ("t2d" in conditions)))
    hba1c = float(labs.get("hba1c_pct", 0.0))
    if hba1c:
        glucose_base = _clamp(glucose_base, 70, 0.0 + (hba1c * 28.7 - 46.7))  # ADAG inversion
    beta_function = _clamp(1.05 - 0.012 * max(0, age - 35)
                           - 0.35 * ("t2d" in conditions) - 0.10 * ("prediabetes" in conditions), 0.25, 1.1)
    bmi = weight / (height / 100.0) ** 2
    # Insulin sensitivity: 1.0 = healthy reference at BMI 22; adiposity,
    # T2D and metformin each shift it (scaled to relative factors).
    insulin_sensitivity = _clamp(
        (1.0 - 0.035 * max(0.0, bmi - 22.0))
        * (0.85 if "t2d" in conditions else 1.0)
        * (1.0 + meds.metformin_sens),
        0.30, 1.30)

    rmssd_base = _clamp(18 + 45 * fitness - 0.25 * (age - 30) + 4 * (sex == "F"), 12, 78)
    spo2_base = 97.5 - 4.5 * ("copd" in conditions) - 0.02 * max(0, age - 50)
    rr_base = 13.5 + 1.5 * ("copd" in conditions)
    temp_base = 36.5 if age < 70 else 36.3

    self_rep = ehr.get("self_report", {}) or {}
    return PhysiologyParams(
        patient_id=ehr["patient_id"],
        age=age,
        sex=sex,
        height_cm=height,
        weight_kg=weight,
        conditions=conditions,
        diet_carbs_day=float(self_rep.get("diet_carbs_day", 230 if "t2d" in conditions else 210)),
        diet_gi=float(self_rep.get("diet_gi", 0.68 if "t2d" in conditions else 0.62)),
        diet_sodium_g=float(self_rep.get("diet_sodium_g", 4.5 if "hypertension" in conditions else 3.6)),
        activity_steps_day=activity,
        sleep_hours_target=float(self_rep.get("sleep_hours", 6.6 if age > 60 else 6.9)),
        stress_level=float(self_rep.get("stress_level", 0.5)),
        bmr_kcal_day=bmr,
        resting_hr_base=resting_hr,
        sbp_base=sbp,
        dbp_base=dbp,
        glucose_base=glucose_base,
        insulin_sensitivity=insulin_sensitivity,
        beta_function=beta_function,
        rmssd_base=rmssd_base,
        spo2_base=spo2_base,
        rr_base=rr_base,
        temp_base=temp_base,
        fitness=fitness,
        stress_reactivity=_clamp(0.45 + 0.02 * (age // 10), 0.4, 0.85),
        sensitivity_ref=insulin_sensitivity,
        meds=meds,
    )


# --------------------------------------------------------------------------
# Daily plan construction
# --------------------------------------------------------------------------

# Fraction of the day's steps taken in each hour (waking hours weighted).
_STEPS_PROFILE = {
    7: 0.045, 8: 0.075, 9: 0.070, 10: 0.065, 11: 0.060, 12: 0.075, 13: 0.055,
    14: 0.050, 15: 0.055, 16: 0.060, 17: 0.070, 18: 0.075, 19: 0.070, 20: 0.060,
    21: 0.045, 22: 0.020,
}


def make_day_plan(params: PhysiologyParams, rng: random.Random, day_index: int,
                  overrides: Optional[dict] = None) -> DayPlan:
    """Build a day's behavioural schedule from the patient's baselines.

    ``overrides`` (from the Protocol Studio) may replace any behavioural
    field: ``steps_day``, ``sleep_hours``, ``stress_level``, ``carbs_day``,
    ``gi``, ``sodium_g``.
    """
    ov = overrides or {}
    steps = float(ov.get("steps_day", params.activity_steps_day))
    sleep_h = float(ov.get("sleep_hours", params.sleep_hours_target))
    stress = float(ov.get("stress_level", params.stress_level))
    carbs = float(ov.get("carbs_day", params.diet_carbs_day))
    gi = float(ov.get("gi", params.diet_gi))
    sodium = float(ov.get("sodium_g", params.diet_sodium_g))

    weekend = day_index % 7 in (5, 6)
    if weekend:
        steps *= 0.82
        sleep_h = min(sleep_h + 0.5, 9.0)

    # Three meals; dinner carries the largest carbohydrate load.
    # Total intake closes the energy balance against expected expenditure
    # at the day's planned activity level, so weight moves only when the
    # protocol changes intake or activity (the Protocol Studio's lever).
    share = (0.30, 0.33, 0.37)
    exp_intensity = sum(min(1.15, steps * w / 520.0) for w in _STEPS_PROFILE.values()) / 24.0
    total_kcal = max(params.bmr_kcal_day * 0.8,
                     params.bmr_kcal_day * (1.0 + 0.55 * exp_intensity) + float(ov.get("kcal_delta_day", 0.0)))
    meals = [
        Meal(hour=7 + int(rng.random() * 1.4), carbs_g=carbs * share[0] * (0.9 + 0.2 * rng.random()), gi=gi * (0.92 + 0.16 * rng.random()), kcal=share[0] * total_kcal),
        Meal(hour=12 + int(rng.random() * 1.6), carbs_g=carbs * share[1] * (0.9 + 0.2 * rng.random()), gi=gi * (0.95 + 0.12 * rng.random()), kcal=share[1] * total_kcal),
        Meal(hour=19 + int(rng.random() * 1.4), carbs_g=carbs * share[2] * (0.9 + 0.2 * rng.random()), gi=gi * (1.02 + 0.12 * rng.random()), kcal=share[2] * total_kcal),
    ]
    return DayPlan(meals=meals, steps_target=steps, sleep_hours=sleep_h,
                   stress_level=stress, sodium_g=sodium)


# --------------------------------------------------------------------------
# Event modifiers
# --------------------------------------------------------------------------

@dataclass
class EventModifier:
    """A transient pathological process injected into the forward model.

    Used by the data generator to create labeled adverse events. Each
    event supplies smooth hourly multiplier/offset curves; the forward
    model simply reads them at each time step (see ``events.py`` for the
    event archetypes and their hazard model).
    """

    kind: str
    onset_h: int                  # global hour of onset
    duration_h: int
    fever_peak: float = 0.0       # deg C
    hr_mult_peak: float = 1.0
    sbp_delta_peak: float = 0.0   # mmHg (may be negative, e.g. sepsis phase)
    dbp_delta_peak: float = 0.0
    spo2_delta_peak: float = 0.0
    rr_delta_peak: float = 0.0
    hrv_mult_peak: float = 1.0
    glucose_mult_peak: float = 1.0
    stress_delta_peak: float = 0.0
    label: str = ""               # human-readable event label

    def intensity(self, t_global: int) -> float:
        """Smooth 0..1 intensity profile: logistic ramp up, plateau, decay."""
        x = t_global - self.onset_h
        if x < -24 or x > self.duration_h + 36:
            return 0.0
        ramp_up = 1.0 / (1.0 + math.exp(-0.55 * x))
        tail = 1.0 / (1.0 + math.exp(0.45 * (x - self.duration_h)))
        return _clamp(ramp_up * tail, 0.0, 1.0)

    def active(self, t_global: int) -> bool:
        return self.intensity(t_global) > 0.01


# --------------------------------------------------------------------------
# Forward model step
# --------------------------------------------------------------------------

def _circadian_stress(hour: int) -> float:
    return 0.5 * (1.0 - math.cos(2.0 * math.pi * (hour - 9) / 24.0))


def _is_sleeping(hour: int, plan: DayPlan, rng_noise: float) -> bool:
    # Personalised sleep window: lights out ~22:30, wake time set so the
    # window length matches the day's sleep target.
    waketime = (22.5 + plan.sleep_hours) % 24.0
    return hour >= 23 or hour < waketime


def _sleep_stage(hour: int, sleeping: bool, rng: random.Random) -> str:
    if not sleeping:
        return "awake"
    if hour in (23, 0, 1):
        return "deep" if rng.random() < 0.55 else "light"
    if hour in (2, 3):
        return "rem" if rng.random() < 0.45 else "light"
    return "light" if rng.random() < 0.75 else "deep"


def step(state: TwinState, params: PhysiologyParams, plan: DayPlan,
         events: Iterable[EventModifier], hour: int, rng: random.Random,
         day_of_plan: int = 0) -> TwinState:
    """Advance the twin by one hour and return the new state.

    Inputs are the previous state, the day's behavioural plan and any
    active pathological events. Outputs are the new vitals and metabolic
    values. See ``docs/clinical_model.md`` for every equation's rationale.
    """
    sleeping = _is_sleeping(hour, plan, rng.random())
    stage = _sleep_stage(hour, sleeping, rng)

    # --- Behavioural inputs for this hour -------------------------------
    steps = 0.0 if sleeping else plan.steps_target * _STEPS_PROFILE.get(hour, 0.01) * (0.75 + 0.5 * rng.random())
    intensity = min(1.15, steps / 520.0)          # activity intensity 0..~1.1
    kcal_in = 0.0
    carb_load = 0.0
    for meal in plan.meals:
        if meal.hour == hour:
            kcal_in += meal.kcal
            carb_load += meal.carbs_g

    # --- Event intensity -------------------------------------------------
    ev_fever = ev_hr = ev_sbp = ev_dbp = ev_spo2 = ev_rr = ev_stress = 0.0
    ev_hrv_mult = 1.0
    ev_glucose_mult = 1.0
    t_glob = state.t_index
    for ev in events:
        a = ev.intensity(t_glob)
        if a <= 0.0:
            continue
        ev_fever += a * ev.fever_peak
        ev_hr += a * ev.hr_mult_peak
        ev_sbp += a * ev.sbp_delta_peak
        ev_dbp += a * ev.dbp_delta_peak
        ev_spo2 += a * ev.spo2_delta_peak
        ev_rr += a * ev.rr_delta_peak
        ev_hrv_mult *= 1.0 - a * (1.0 - ev.hrv_mult_peak)
        ev_glucose_mult *= 1.0 - a * (1.0 - ev.glucose_mult_peak)
        ev_stress += a * ev.stress_delta_peak

    # --- Stress / autonomic ----------------------------------------------
    circadian = _circadian_stress(hour)
    if sleeping:
        stress_target = 0.06 + ev_stress
    else:
        stress_target = _clamp(0.15 + plan.stress_level * circadian * 1.1
                               + state.sleep_debt_h * 0.045 + ev_stress, 0.0, 1.0)
    stress = _clamp(state.stress + 0.45 * (stress_target - state.stress) + rng.gauss(0, 0.05), 0.0, 1.0)

    # --- Cardiovascular ---------------------------------------------------
    fit_delta = state.fitness - params.fitness
    hr = (params.resting_hr_base - params.meds.beta_blocker_hr - 7.0 * fit_delta
          + 26.0 * min(1.2, intensity) * (0.5 if sleeping else 1.0)
          + 16.0 * stress
          + 9.0 * ev_fever
          + ev_hr * 30.0
          + rng.gauss(0, 1.6))
    hr = _clamp(hr, 38, 195)

    weight_delta = state.weight_kg - params.weight_kg
    sbp = (params.sbp_base
           + 11.0 * stress
           + 4.5 * intensity
           - 8.0 * fit_delta
           + 1.1 * weight_delta
           + ev_sbp
           + rng.gauss(0, 2.2))
    sbp = _clamp(sbp, 68, 235)
    pp = max(28.0, params.sbp_base - params.dbp_base)
    dbp = _clamp(sbp - pp * (0.96 if stress < 0.7 else 0.86) + ev_dbp, 45, 135)

    # --- Respiratory ------------------------------------------------------
    spo2 = (params.spo2_base - 0.6 * max(0.0, intensity - 0.85)
            + ev_spo2
            + (rng.gauss(0, 0.5) if not sleeping else rng.gauss(0, 0.4)))
    if sleeping and ("copd" in params.conditions or "osa" in params.conditions):
        spo2 -= 1.8 * (1.0 if "copd" in params.conditions else 0.6) * (0.5 + 0.5 * rng.random())
    spo2 = _clamp(spo2, 74, 100)

    rr = (params.rr_base + 2.6 * stress + 2.1 * ev_fever + 1.6 * intensity
          + ev_rr + (rng.gauss(0, 0.5) if not sleeping else rng.gauss(0, 0.25)))
    rr = _clamp(rr, 8, 42)

    temp_c = params.temp_base + ev_fever + 0.28 * intensity + rng.gauss(0, 0.12)

    # --- Autonomic (HRV) ---------------------------------------------------
    rmssd = (params.rmssd_base * (1.0 + 0.25 * fit_delta)
             * (1.35 if sleeping else 1.0)
             * (1.0 - 0.42 * stress)
             * (1.0 + 0.10 * (state.insulin_sensitivity - 1.0))
             * ev_hrv_mult
             * (1.0 - 0.09 * ev_fever)
             + rng.gauss(0, 2.0))
    rmssd = _clamp(rmssd, 6.0, 110.0)

    # --- Metabolic (glucose) ------------------------------------------------
    # Uptake clearance scales with insulin sensitivity; secretory capacity
    # (beta function) governs how much of the carbohydrate load can be
    # disposed of promptly. Decoupling them keeps T2D excursions ~2.5x
    # healthy excursions, matching CGM literature magnitudes. Sustained
    # weight loss improves sensitivity (~1.2% per kg, Holt et al. 2020
    # DiRECT-adjacent estimates). ``weight_delta`` is defined in the
    # cardiovascular block above (negative = weight lost).
    sens = params.insulin_sensitivity * (1.0 + 0.16 * intensity) * (1.0 - 0.012 * weight_delta)
    beta_eff = 0.4 + 0.6 * params.beta_function
    clearance = 0.85 * sens
    # Fasting glucose drifts down as slow sensitivity improves (weight loss,
    # fitness): gbase_eff ~ base * (sens_ref / slow_sens)^1.5 — roughly
    # 15-20 mg/dL fasting per 10% weight loss, DiRECT-phase-consistent.
    slow_ratio = _clamp(params.sensitivity_ref / max(state.slow_sens, 1e-6), 0.6, 1.6)
    gbase_eff = params.glucose_base * _clamp(slow_ratio ** 1.5, 0.62, 1.0)
    ingestion = 0.0
    for meal in plan.meals:
        if meal.hour <= hour <= meal.hour + 4:
            dt = hour - meal.hour
            kernel = math.exp(-0.5 * ((dt - 0.9) / 0.85) ** 2) / (0.85 * math.sqrt(2 * math.pi))
            ingestion += meal.carbs_g * meal.gi * kernel * 1.35 / (sens * beta_eff)
    uptake_extra = 0.0
    if state.glucose > gbase_eff:
        uptake_extra = clearance * (state.glucose - gbase_eff)
    # exogenous insulin (units/day) adds proportional uptake at night
    if params.meds.insulin_units_day > 0:
        uptake_extra += (params.meds.insulin_units_day / 24.0) * 18.0 * (1.6 if sleeping else 1.0) * (state.glucose / 120.0)

    glucose = state.glucose + ingestion - uptake_extra
    glucose *= ev_glucose_mult if ev_glucose_mult < 1.0 else 1.0
    glucose = _clamp(glucose, 38, 480)
    glucose += rng.gauss(0, 1.8)

    # --- Sleep / recovery bookkeeping ---------------------------------------
    # (sleep debt is updated at the day boundary in simulate_days)

    new_state = replace(
        state,
        t_index=state.t_index + 1,
        hr=hr,
        sbp=sbp,
        dbp=dbp,
        rr=rr,
        spo2=spo2,
        temp_c=temp_c,
        rmssd=rmssd,
        stress=stress,
        glucose=glucose,
        sleep_stage=stage,
        steps_hour=steps,
        kcal_in_hour=kcal_in,
        day_balance_kcal=state.day_balance_kcal + kcal_in - _kcal_out_hour(params, state, intensity),
        insulin_sensitivity=sens,
    )
    return new_state


def _kcal_out_hour(params: PhysiologyParams, state: TwinState, intensity: float) -> float:
    return (params.bmr_kcal_day / 24.0) * (1.0 + 0.55 * intensity)


def simulate_days(params: PhysiologyParams, n_days: int, events: Iterable[EventModifier] = (),
                  seed: int = 7, overrides: Optional[dict] = None,
                  start_state: Optional[TwinState] = None) -> list[TwinState]:
    """Simulate ``n_days`` and return the hourly state list (24 * n_days).

    Deterministic in ``(params, events, seed, overrides)`` — the Protocol
    Studio exploits this to compare scenarios on identical behavioural
    noise realisations.
    """
    rng = random.Random(seed)
    state = start_state or _initial_state(params)
    out: list[TwinState] = []
    events = list(events)
    for d in range(n_days):
        plan = make_day_plan(params, rng, d, overrides)
        for _ in range(24):
            hour = state.t_index % 24
            state = step(state, params, plan, events, hour, rng)
            out.append(state)
        # Day boundary updates: weight from energy balance, sleep debt,
        # and slow fitness adaptation toward the realised activity level
        # (~3%/day of the remaining gap — observable over weeks, which is
        # what makes 90-day protocol projections non-trivial).
        slept = sum(1 for s in out[-24:] if s.sleep_stage != "awake")
        debt_delta = max(0.0, 7.5 - slept) - 0.7
        state.sleep_debt_h = _clamp(state.sleep_debt_h + debt_delta, 0.0, 16.0)
        state.weight_kg = max(35.0, state.weight_kg + state.day_balance_kcal / 7700.0)
        state.day_balance_kcal = 0.0
        steps_today = sum(s.steps_hour for s in out[-24:])
        fit_target = _clamp(0.15 + (steps_today / 12000.0) * 0.65 - (params.age - 40) * 0.004, 0.08, 1.0)
        state.fitness = _clamp(state.fitness + 0.03 * (fit_target - state.fitness), 0.05, 1.0)
        # Slow insulin-sensitivity state: weight loss (~1.2%/kg) plus a
        # fitness-adaptation term. Drives the fasting-glucose drift.
        weight_delta = state.weight_kg - params.weight_kg
        fit_delta = state.fitness - params.fitness
        state.slow_sens = max(0.3, params.sensitivity_ref
                              * (1.0 - 0.012 * weight_delta)
                              * (1.0 + 0.30 * fit_delta))
    return out


def _initial_state(params: PhysiologyParams) -> TwinState:
    return TwinState(
        t_index=0,
        hr=params.resting_hr_base,
        sbp=params.sbp_base,
        dbp=params.dbp_base,
        rr=params.rr_base,
        spo2=params.spo2_base,
        temp_c=params.temp_base,
        glucose=params.glucose_base,
        rmssd=params.rmssd_base,
        stress=0.35,
        weight_kg=params.weight_kg,
        insulin_sensitivity=params.insulin_sensitivity,
        sleep_debt_h=0.0,
        fitness=params.fitness,
        slow_sens=params.sensitivity_ref,
    )


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def hba1c_from_mean_glucose(mean_glucose_mgdl: float) -> float:
    """ADAG study relationship (Nathan et al., 2008)."""
    return round((mean_glucose_mgdl + 46.7) / 28.7, 2)
