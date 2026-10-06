"""Adverse-event archetypes and the sampling hazard model.

The data generator injects these transient pathological processes into the
physiological forward model to create labeled adverse events:

- **Acute deterioration (infection/sepsis-like)** — a biphasic process:
  a 24-48h prodrome (rising resting HR, falling HRV, low-grade fever,
  rising respiration rate) followed by an acute phase (fever spike,
  SBP fall, SpO2 fall, tachypnoea). The prodrome is the early-warning
  window the risk model must learn to read.
- **Severe hypoglycaemia** — nocturnal glucose crash (<54 mg/dL), seen in
  insulin/sulphonylurea-treated patients.
- **Hypertensive crisis** — SBP > 180 episodes in uncontrolled hypertension.
- **Nocturnal desaturation** — recurrent SpO2 dips in COPD/OSA.

Event probabilities follow a transparent hazard model over patient risk
factors (age, comorbidities, therapy) so cohort prevalence is controlled
and reproducible.
"""
from __future__ import annotations

import random
from typing import Optional

from app.engine.physiology import PhysiologyParams, EventModifier


def make_infection_sepsis_like(onset_h: int, rng: random.Random, severity: float = 1.0) -> list[EventModifier]:
    """Biphasic infection event. Returns [prodrome, acute].

    Prodrome magnitudes follow the documented pre-deterioration pattern:
    rising resting/evening heart rate (+10-16%), falling HRV (-30-40%),
    low-grade fever and rising respiration rate — detectable 12-40h before
    the acute phase.
    """
    prodrome_len = rng.randint(20, 40)      # hours of prodrome before acute
    acute_len = rng.randint(36, 72)
    prodrome = EventModifier(
        kind="infection",
        onset_h=onset_h,
        duration_h=prodrome_len,
        fever_peak=0.9 * severity,
        hr_mult_peak=0.16 * severity,       # +16% HR via the ev_hr path
        sbp_delta_peak=6.0 * severity,
        spo2_delta_peak=-0.6 * severity,
        rr_delta_peak=3.0 * severity,
        hrv_mult_peak=0.62 * severity + 0.38,
        stress_delta_peak=0.25 * severity,
        label="Acute deterioration",
    )
    acute = EventModifier(
        kind="infection",
        onset_h=onset_h + prodrome_len,
        duration_h=acute_len,
        fever_peak=1.7 * severity,
        hr_mult_peak=0.28 * severity,
        sbp_delta_peak=-24.0 * severity,    # vasodilatory fall
        dbp_delta_peak=-12.0 * severity,
        spo2_delta_peak=-3.8 * severity,
        rr_delta_peak=6.5 * severity,
        hrv_mult_peak=0.45,
        stress_delta_peak=0.35 * severity,
        label="Acute deterioration",
    )
    return [prodrome, acute]


def make_hypoglycemia(onset_h: int, rng: random.Random) -> EventModifier:
    return EventModifier(
        kind="hypoglycemia",
        onset_h=onset_h,
        duration_h=rng.randint(3, 5),
        glucose_mult_peak=rng.uniform(0.30, 0.42),
        hrv_mult_peak=0.85,
        hr_mult_peak=0.06,
        stress_delta_peak=0.15,
        label="Severe hypoglycaemia",
    )


def make_hypertensive_crisis(onset_h: int, rng: random.Random) -> EventModifier:
    return EventModifier(
        kind="hypertensive_crisis",
        onset_h=onset_h,
        duration_h=rng.randint(4, 8),
        sbp_delta_peak=rng.uniform(38, 52),
        dbp_delta_peak=rng.uniform(18, 26),
        hr_mult_peak=0.08,
        stress_delta_peak=0.3,
        label="Hypertensive crisis",
    )


def make_nocturnal_desaturation(onset_h: int, rng: random.Random) -> EventModifier:
    return EventModifier(
        kind="desaturation",
        onset_h=onset_h,
        duration_h=rng.randint(6, 8),
        spo2_delta_peak=rng.uniform(-7.0, -4.5),
        rr_delta_peak=1.5,
        label="Nocturnal desaturation",
    )


# ---------------------------------------------------------------------------
# Hazard model
# ---------------------------------------------------------------------------

def _comorbidity_load(params: PhysiologyParams) -> float:
    load = 0.0
    for c in ("ckd", "copd", "cad", "t2d", "hypertension", "afib"):
        if c in params.conditions:
            load += 1.0
    return load


def daily_event_hazards(params: PhysiologyParams) -> dict[str, float]:
    """Per-day event probabilities for this patient (transparent hazard model).

    The infection base rate is set for a *home-monitored high-risk* cohort
    (the deployment population of the PoC: elderly, multi-morbid patients
    monitored after discharge), so it is enriched relative to the general
    population — documented in docs/clinical_model.md.
    """
    age_f = 1.0 + max(0.0, params.age - 50) / 60.0
    comorb = 1.0 + 0.22 * _comorbidity_load(params)
    infection = 0.004 * age_f * comorb
    hypo = 0.0
    if params.meds.insulin_units_day > 0:
        hypo = 0.022
    elif "t2d" in params.conditions:
        hypo = 0.004  # sulphonylurea proxy
    crisis = 0.0
    if "hypertension" in params.conditions and params.meds.antihyp_bp_mmhg < 12:
        crisis = 0.012 * (1.0 + params.stress_level)
    desat = 0.35 if ("copd" in params.conditions or "osa" in params.conditions) else 0.0
    return {"infection": infection, "hypoglycemia": hypo,
            "hypertensive_crisis": crisis, "desaturation": desat}


def sample_event_schedule(params: PhysiologyParams, n_days: int, rng: random.Random,
                          start_t: int = 0, min_separation_days: int = 6
                          ) -> tuple[list[EventModifier], list[dict]]:
    """Draw an event schedule for a simulated stay of ``n_days``.

    Returns ``(modifiers, event_records)``; each record carries the global
    onset hour, kind and label so the generator can attach labels for the
    deterioration-prediction task.
    """
    hazards = daily_event_hazards(params)
    last_onset: dict[str, float] = {}
    modifiers: list[EventModifier] = []
    records: list[dict] = []

    for day in range(n_days):
        for kind, p in hazards.items():
            if p <= 0 or rng.random() > p:
                continue
            last = last_onset.get(kind, -10**9)
            if (start_t / 24.0 + day) - last < min_separation_days:
                continue
            hour_of_day = {
                "hypoglycemia": rng.randint(1, 4),
                "desaturation": rng.randint(23, 23),
            }.get(kind, rng.randint(6, 21))
            onset = start_t + day * 24 + hour_of_day
            if kind == "infection":
                sev = rng.uniform(0.8, 1.25)
                mods = make_infection_sepsis_like(onset, rng, severity=sev)
                modifiers.extend(mods)
                # Label onset = start of the ACUTE phase (what we want to
                # predict with lead time); prodrome precedes it.
                records.append({"kind": kind, "label": mods[1].label,
                                "onset_t": mods[1].onset_h,
                                "prodrome_t": mods[0].onset_h, "severity": sev})
            elif kind == "hypoglycemia":
                m = make_hypoglycemia(onset, rng)
                modifiers.append(m)
                records.append({"kind": kind, "label": m.label, "onset_t": onset})
            elif kind == "hypertensive_crisis":
                m = make_hypertensive_crisis(onset, rng)
                modifiers.append(m)
                records.append({"kind": kind, "label": m.label, "onset_t": onset})
            elif kind == "desaturation":
                m = make_nocturnal_desaturation(onset, rng)
                modifiers.append(m)
                records.append({"kind": kind, "label": m.label, "onset_t": onset})
            last_onset[kind] = start_t / 24.0 + day

    return modifiers, records
