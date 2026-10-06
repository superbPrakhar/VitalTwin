"""In-memory patient store.

The PoC boots with three seeded demo patients whose 30-day history is
pre-generated deterministically, plus a hidden *future* telemetry window
(with scripted adverse events for the demo) that is revealed hour by hour
as the client calls ``sync``. Restarting the server resets to the same
deterministic state — no persistence is needed for the PoC (documented in
docs/architecture.md; production would stream from device gateways and a
clinical data repository).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.data.generator import generate_wearable_stream
from app.engine.assimilation import TwinMirror, DailySummary
from app.engine.events import make_hypertensive_crisis, make_infection_sepsis_like, EventModifier
from app.engine.physiology import params_from_ehr, PhysiologyParams
from app.engine.risk import LogisticModel, MODEL_DIR, news2

HISTORY_DAYS = 30
FUTURE_DAYS = 14


@dataclass
class PatientRecord:
    patient_id: str
    ehr: dict
    params: PhysiologyParams
    mirror: TwinMirror
    pending: list[dict]                  # telemetry not yet assimilated
    scheduled_events: list[dict]         # events in history + future (for demo/labels)
    last_t: int = 0

    @property
    def name(self) -> str:
        return self.ehr.get("name", self.patient_id)


class TwinStore:
    def __init__(self) -> None:
        self.patients: dict[str, PatientRecord] = {}
        self.risk_model: LogisticModel | None = None
        self.risk_threshold: float = 0.5

    # -- boot ---------------------------------------------------------------

    def load_risk_model(self) -> None:
        path = MODEL_DIR / "twinrisk_v1.json"
        if path.exists():
            model = LogisticModel.load(path)
            self.risk_model = model
            self.risk_threshold = float(model.meta.get("alert_threshold", 0.5))

    def boot(self) -> "TwinStore":
        self.load_risk_model()
        for pid, ehr, modifiers, seed in _seed_patients():
            params = params_from_ehr(ehr)
            stream, _truth = generate_wearable_stream(params, HISTORY_DAYS + FUTURE_DAYS,
                                                      seed, events=modifiers)
            history = [r for r in stream if r["t"] < HISTORY_DAYS * 24]
            pending = [r for r in stream if r["t"] >= HISTORY_DAYS * 24]
            mirror = TwinMirror(params)
            for rec in history:
                mirror.assimilate(rec)
            records = _event_records(modifiers)
            self.patients[pid] = PatientRecord(
                patient_id=pid, ehr=ehr, params=params, mirror=mirror,
                pending=pending, scheduled_events=records,
                last_t=history[-1]["t"] if history else 0)
        return self

    # -- sync -----------------------------------------------------------------

    def sync(self, patient_id: str, hours: int = 6) -> dict:
        """Reveal the next ``hours`` telemetry hours, assimilate, re-score."""
        rec = self.patients[patient_id]
        window = rec.pending[:hours]
        rec.pending = rec.pending[hours:]
        new_alerts = []
        prev_risk = self.latest_risk(patient_id)
        for w in window:
            rec.mirror.assimilate(w)
        rec.last_t = window[-1]["t"] if window else rec.last_t
        cur_risk = self.latest_risk(patient_id)
        if (cur_risk and prev_risk
                and prev_risk["twinrisk"]["probability"] < self.risk_threshold
                and cur_risk["twinrisk"]["probability"] >= self.risk_threshold):
            new_alerts.append(self._alert_from(patient_id, cur_risk))
        return {
            "patient_id": patient_id,
            "synced_hours": len(window),
            "last_t": rec.last_t,
            "latest_vitals": rec.mirror.hours[-1]["est"] if rec.mirror.hours else {},
            "risk": cur_risk,
            "new_alerts": new_alerts,
            "pending_hours": len(rec.pending),
        }

    # -- scoring ----------------------------------------------------------------

    def latest_risk(self, patient_id: str) -> dict | None:
        rec = self.patients[patient_id]
        if not rec.mirror.hours or self.risk_model is None:
            return None
        est = rec.mirror.hours[-1]["est"]
        t_dev = est.get("temp_dev", 0.0)
        temp_c = rec.params.temp_base + t_dev / 0.6
        n2 = news2(hr=est.get("hr", 75), sbp=est.get("sbp", 125),
                   spo2=est.get("spo2", 97), temp_c=temp_c,
                   rr=est.get("rr", 14))
        feats = _features_from_mirror(rec)
        prob = self.risk_model.probability(feats)
        return {
            "t": rec.last_t,
            "news2": n2,
            "twinrisk": {
                "probability": round(prob, 4),
                "threshold": self.risk_threshold,
                "drivers": [d for d in self.risk_model.contributions(feats)[:5]],
                "band": self._risk_band(prob),
            },
            "live_alarms": self.live_alarms(patient_id),
        }

    # Absolute-threshold monitoring alarms on the assimilated vitals
    # (the "current state" layer — distinct from TwinRisk's prediction).
    def live_alarms(self, patient_id: str) -> list[dict]:
        rec = self.patients[patient_id]
        if not rec.mirror.hours:
            return []
        est = rec.mirror.hours[-1]["est"]
        temp_c = rec.params.temp_base + est.get("temp_dev", 0.0) / 0.6
        checks = [
            ("hypoglycemia", "Glucose below 70 mg/dL", est.get("glucose", 999) < 70),
            ("hyperglycemia", "Glucose above 250 mg/dL", est.get("glucose", 0) > 250),
            ("hypoxemia", "SpO2 below 88%", est.get("spo2", 999) < 88),
            ("hypertension", "Systolic BP above 180 mmHg", est.get("sbp", 0) > 180),
            ("hypotension", "Systolic BP below 90 mmHg", est.get("sbp", 999) < 90),
            ("tachycardia", "Heart rate above 130 bpm", est.get("hr", 0) > 130),
            ("bradycardia", "Heart rate below 40 bpm", est.get("hr", 999) < 40),
            ("fever", "Estimated core temperature above 38.5 °C", temp_c > 38.5),
        ]
        return [{"kind": k, "message": m} for k, m, hit in checks if hit]

    def alert_feed(self, patient_id: str) -> list[dict]:
        """Replay the twin's daily risk history into an alert feed."""
        rec = self.patients[patient_id]
        if self.risk_model is None:
            return []
        alerts = []
        days = rec.mirror.days
        for d in range(14, len(days)):
            feats = _features_for_day(rec, d)
            prob = self.risk_model.probability(feats)
            day_events = [e for e in rec.scheduled_events
                          if e["kind"] in ("infection",)
                          and days[d].t_end < e["onset_t"] <= days[d].t_end + 48]
            if prob >= self.risk_threshold or day_events:
                alerts.append(self._alert_from(patient_id, {
                    "t": days[d].t_end, "twinrisk": {
                        "probability": round(prob, 4), "threshold": self.risk_threshold,
                        "drivers": self.risk_model.contributions(feats)[:5], "band": self._risk_band(prob)}},
                    events=day_events))
        return alerts

    def _alert_from(self, patient_id: str, risk: dict, events: list[dict] | None = None) -> dict:
        tr = risk["twinrisk"]
        ev = (events or [{}])[0]
        lead = None
        if ev and ev.get("onset_t") is not None:
            lead = ev["onset_t"] - risk["t"]
        return {
            "t": risk["t"],
            "probability": tr["probability"],
            "threshold": tr["threshold"],
            "band": tr["band"],
            "drivers": tr["drivers"],
            "upcoming_event": ev.get("label"),
            "lead_hours": lead,
            "message": _alert_message(tr["probability"], ev.get("label"), lead),
        }

    @staticmethod
    def _risk_band(p: float) -> str:
        return "high" if p >= 0.5 else ("elevated" if p >= 0.2 else ("watch" if p >= 0.08 else "low"))


def _alert_message(prob: float, label: str | None, lead: int | None) -> str:
    pct = f"{prob * 100:.0f}%"
    if label:
        lead_txt = f" — approximately {lead}h before acute onset" if lead is not None else ""
        return (f"Elevated risk of infection-like deterioration ({pct}); the twin detects "
                f"prodromal drift from this patient's own baseline{lead_txt}.")
    return (f"Elevated deterioration risk ({pct}) versus this patient's own baseline; "
            f"recommend review of wearable trends.")


# ---------------------------------------------------------------------------
# Seed patients (all synthetic; events scripted for the demo narrative)
# ---------------------------------------------------------------------------
# - Ravi demos the Protocol Studio (A1c goal-seek) plus a hypertensive crisis.
# - Meera demos prevention (prediabetes reversal, no acute events).
# - Arjun demos deterioration prediction: a biphasic infection lands just
#   after the boot boundary so "Sync now" reveals the prodrome live.

def _seed_patients():
    ravi_crisis = [make_hypertensive_crisis(HISTORY_DAYS * 24 + 62, random.Random(4))]
    arjun_infection = make_infection_sepsis_like(HISTORY_DAYS * 24 + 72, random.Random(9), severity=1.15)
    return [
        ("ravi", {
            "patient_id": "ravi", "name": "Ravi Sharma", "ehr_id": "EHR-RAVI-58214",
            "demographics": {"age": 58, "sex": "M", "height_cm": 170, "weight_kg": 84},
            "conditions": ["t2d", "hypertension", "dyslipidemia"],
            "labs": {"hba1c_pct": 7.8, "fasting_glucose_mgdl": 145, "ldl_mgdl": 118,
                      "egfr_ml_min": 78, "creatinine_mgdl": 1.1},
            "baseline_vitals": {"sbp": 146, "dbp": 88},
            "medications": {"metformin_mg": 1000, "antihypertensive_mmhg": 8, "statin": True},
            "self_report": {"activity_steps_day": 3800, "sleep_hours": 6.0,
                             "stress_level": 0.6, "diet_carbs_day": 260, "diet_gi": 0.72,
                             "diet_sodium_g": 5.2},
            "history_notes": ["T2D diagnosed 2019", "BP above target at last two reviews",
                               "Sedentary desk occupation"],
        }, ravi_crisis, 101),
        ("meera", {
            "patient_id": "meera", "name": "Meera Iyer", "ehr_id": "EHR-MEERA-47903",
            "demographics": {"age": 45, "sex": "F", "height_cm": 161, "weight_kg": 76},
            "conditions": ["prediabetes"],
            "labs": {"hba1c_pct": 6.1, "fasting_glucose_mgdl": 115, "ldl_mgdl": 102,
                      "egfr_ml_min": 96},
            "baseline_vitals": {"sbp": 126, "dbp": 80},
            "medications": {},
            "self_report": {"activity_steps_day": 4600, "sleep_hours": 5.6,
                             "stress_level": 0.72, "diet_carbs_day": 240, "diet_gi": 0.68,
                             "diet_sodium_g": 4.0},
            "history_notes": ["HbA1c rising over 18 months (5.6 → 6.1)", "High occupational stress"],
        }, [], 202),
        ("arjun", {
            "patient_id": "arjun", "name": "Arjun Rao", "ehr_id": "EHR-ARJUN-71266",
            "demographics": {"age": 72, "sex": "M", "height_cm": 168, "weight_kg": 72},
            "conditions": ["cad", "hypertension"],
            "labs": {"hba1c_pct": 6.2, "ldl_mgdl": 74, "egfr_ml_min": 62,
                      "creatinine_mgdl": 1.35},
            "baseline_vitals": {"sbp": 132, "dbp": 78},
            "medications": {"beta_blocker_bpm": 9, "antihypertensive_mmhg": 10, "statin": True},
            "self_report": {"activity_steps_day": 5200, "sleep_hours": 6.5, "stress_level": 0.4},
            "history_notes": ["Post-PCI 2023 (LAD stent)", "Lives with spouse; home BP monitoring"],
        }, arjun_infection, 303),
    ]


def _event_records(modifiers: list[EventModifier]) -> list[dict]:
    """EventModifier objects -> label records (acute onset for infections)."""
    records = []
    acute = next((m for m in modifiers if m.kind == "infection"
                  and m.sbp_delta_peak < 0), None)
    for m in modifiers:
        if m.kind == "infection":
            if acute is not None and m is not acute:
                continue  # record only the acute phase (the prediction target)
            records.append({"kind": m.kind, "label": m.label, "onset_t": m.onset_h})
        else:
            records.append({"kind": m.kind, "label": m.label, "onset_t": m.onset_h})
    return records


def _features_from_mirror(rec: PatientRecord) -> dict:
    from app.engine.features import build_feature_rows
    rows = build_feature_rows(_params_summary(rec.params),
                              [d.to_dict() for d in rec.mirror.days], [])
    return rows[-1] if rows else {}


def _features_for_day(rec: PatientRecord, day_index: int) -> dict:
    from app.engine.features import build_feature_rows
    rows = build_feature_rows(_params_summary(rec.params),
                              [d.to_dict() for d in rec.mirror.days[:day_index + 1]], [])
    return rows[-1] if rows else {}


def _params_summary(p: PhysiologyParams) -> dict:
    return {"age": p.age, "sex": p.sex, "bmi": round(p.bmi, 1),
            "conditions": sorted(p.conditions),
            "insulin_sensitivity": round(p.insulin_sensitivity, 3),
            "beta_function": round(p.beta_function, 3), "fitness": round(p.fitness, 3),
            "rmssd_base": round(p.rmssd_base, 1), "resting_hr_base": round(p.resting_hr_base, 1),
            "sbp_base": round(p.sbp_base, 1)}
