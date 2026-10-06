"""FastAPI service layer for the VitalTwin digital twin.

Run:  uvicorn app.main:app  (or `python run.py`)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import __version__
from app.engine.protocols import LEVER_BOUNDS, compare_to_base, explain_scenario, goal_seek
from app.engine.physiology import hba1c_from_mean_glucose
from app.store import TwinStore

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

app = FastAPI(title="VitalTwin API", version=__version__,
              description="Patient digital twin PoC: EHR + wearable telemetry fusion, "
                          "adverse-event prediction, treatment protocol simulation.")
store: TwinStore = TwinStore().boot()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SyncRequest(BaseModel):
    hours: int = Field(default=6, ge=1, le=72)


class SimulateRequest(BaseModel):
    scenario: dict[str, float] = Field(default_factory=dict)
    horizon_days: int = Field(default=90, ge=7, le=365)


class GoalRequest(BaseModel):
    lever: str
    target_metric: str = "hba1c_end"
    target_value: float
    horizon_days: int = Field(default=90, ge=7, le=365)
    direction: str = "below"
    scenario_base: dict[str, float] = Field(default_factory=dict)


def _patient(pid: str):
    rec = store.patients.get(pid)
    if rec is None:
        raise HTTPException(404, f"unknown patient '{pid}'")
    return rec


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__,
            "model_loaded": store.risk_model is not None,
            "model_meta": store.risk_model.meta if store.risk_model else None}


@app.get("/api/patients")
def list_patients() -> list[dict]:
    out = []
    for rec in store.patients.values():
        risk = store.latest_risk(rec.patient_id)
        days = rec.mirror.days
        out.append({
            "patient_id": rec.patient_id,
            "name": rec.name,
            "age": rec.params.age,
            "sex": rec.params.sex,
            "conditions": sorted(rec.params.conditions),
            "hba1c_est": hba1c_from_mean_glucose(
                sum(d.glucose_mean for d in days[-14:]) / max(1, len(days[-14:]))),
            "risk_probability": risk["twinrisk"]["probability"] if risk else None,
            "risk_band": risk["twinrisk"]["band"] if risk else None,
            "news2": risk["news2"]["score"] if risk else None,
            "live_alarms": risk["live_alarms"] if risk else [],
        })
    return out


@app.get("/api/patients/{pid}")
def patient_detail(pid: str) -> dict:
    rec = _patient(pid)
    p = rec.params
    return {
        "patient_id": rec.patient_id,
        "name": rec.name,
        "ehr_id": rec.ehr.get("ehr_id"),
        "demographics": rec.ehr["demographics"],
        "conditions": sorted(p.conditions),
        "labs": rec.ehr.get("labs", {}),
        "medications": rec.ehr.get("medications", {}),
        "history_notes": rec.ehr.get("history_notes", []),
        "self_report": rec.ehr.get("self_report", {}),
        "calibrated_params": {
            "bmi": round(p.bmi, 1), "insulin_sensitivity": round(p.insulin_sensitivity, 3),
            "beta_function": round(p.beta_function, 3), "fitness": round(p.fitness, 3),
            "resting_hr_base": round(p.resting_hr_base, 1), "rmssd_base": round(p.rmssd_base, 1),
            "sbp_base": round(p.sbp_base, 1), "glucose_base": round(p.glucose_base, 1),
        },
        "sync": {"last_t": rec.last_t, "last_t_iso": _iso(rec.last_t),
                  "pending_hours": len(rec.pending)},
    }


@app.get("/api/patients/{pid}/mirror")
def patient_mirror(pid: str) -> dict:
    rec = _patient(pid)
    return {
        "patient_id": pid,
        "t": rec.last_t,
        "t_iso": _iso(rec.last_t),
        "organ_status": rec.mirror.organ_status(),
        "latest_estimate": rec.mirror.hours[-1]["est"] if rec.mirror.hours else {},
        "deviations": rec.mirror.hours[-1].get("z", {}) if rec.mirror.hours else {},
        "baseline_warmed_up": rec.mirror.baselines["hr"].warmed_up,
        "assimilated_hours": len(rec.mirror.hours),
    }


@app.get("/api/patients/{pid}/trends")
def patient_trends(pid: str, days: int = 14) -> dict:
    rec = _patient(pid)
    window = [d.to_dict() for d in rec.mirror.days[-days:]]
    return {"patient_id": pid, "days": days, "summaries": window}


@app.get("/api/patients/{pid}/hourly")
def patient_hourly(pid: str, hours: int = 48) -> dict:
    rec = _patient(pid)
    window = rec.mirror.hours[-hours:]
    return {"patient_id": pid, "hours": hours, "records": window}


@app.get("/api/patients/{pid}/risk")
def patient_risk(pid: str) -> dict:
    _patient(pid)
    risk = store.latest_risk(pid)
    if risk is None:
        raise HTTPException(503, "risk model not loaded or no data assimilated")
    # daily risk history for the trend chart
    history = []
    if store.risk_model is not None:
        from app.store import _features_for_day
        for d in range(14, len(store.patients[pid].mirror.days)):
            f = _features_for_day(store.patients[pid], d)
            history.append({"t": store.patients[pid].mirror.days[d].t_end,
                            "p": round(store.risk_model.probability(f), 4)})
    return risk | {"history": history[-30:]}


@app.get("/api/patients/{pid}/alerts")
def patient_alerts(pid: str) -> dict:
    _patient(pid)
    return {"patient_id": pid, "alerts": store.alert_feed(pid)}


@app.post("/api/patients/{pid}/sync")
def patient_sync(pid: str, req: SyncRequest) -> dict:
    _patient(pid)
    return store.sync(pid, req.hours)


@app.post("/api/patients/{pid}/simulate")
def patient_simulate(pid: str, req: SimulateRequest) -> dict:
    rec = _patient(pid)
    unknown = [k for k in req.scenario if k not in LEVER_BOUNDS]
    if unknown:
        raise HTTPException(422, f"unknown scenario levers: {unknown}")
    return compare_to_base(rec.params, req.horizon_days, req.scenario)


@app.post("/api/patients/{pid}/goal")
def patient_goal(pid: str, req: GoalRequest) -> dict:
    rec = _patient(pid)
    if req.lever not in LEVER_BOUNDS:
        raise HTTPException(422, f"unsupported lever '{req.lever}'")
    if req.direction not in ("below", "above"):
        raise HTTPException(422, "direction must be 'below' or 'above'")
    unknown = [k for k in req.scenario_base if k not in LEVER_BOUNDS]
    if unknown:
        raise HTTPException(422, f"unknown scenario_base levers: {unknown}")
    return goal_seek(rec.params, req.horizon_days, req.lever,
                     req.target_metric, req.target_value, direction=req.direction,
                     scenario_base=req.scenario_base)


@app.post("/api/patients/{pid}/explain")
def patient_explain(pid: str, req: SimulateRequest) -> dict:
    rec = _patient(pid)
    return {"patient_id": pid, "contributions": explain_scenario(rec.params, req.horizon_days, req.scenario)}


@app.get("/api/model")
def model_card() -> dict:
    m = store.risk_model
    if m is None:
        raise HTTPException(503, "risk model not loaded")
    return {"name": "TwinRisk v1", "type": "logistic regression (standardized features)",
            "task": "probability of infection-like acute deterioration within 48h",
            "features": m.feature_names, "meta": m.meta,
            "alert_threshold": store.risk_threshold,
            "training_data": "fully synthetic cohort (app/data/generator.py) — no real patient data",
            "news2": "scored live on assimilated vitals (RCP 2017)"}


@app.get("/api/patients/{pid}/report")
def patient_report(pid: str) -> JSONResponse:
    """Markdown clinical summary (the clinician-facing artefact)."""
    rec = _patient(pid)
    risk = store.latest_risk(pid)
    days = rec.mirror.days[-14:]
    avg = lambda k: round(sum(d.to_dict()[k] for d in days) / max(1, len(days)), 1)  # noqa: E731
    g14 = sum(avg("glucose_mean") for _ in [0]) / 1.0
    lines = [
        f"# VitalTwin clinical summary — {rec.name}",
        f"*Synthetic demo patient · twin state at {_iso(rec.last_t)} · NOT for clinical use*",
        "",
        f"**EHR snapshot**: {rec.params.age}y {rec.params.sex}, BMI {rec.params.bmi:.1f}, "
        f"conditions: {', '.join(sorted(rec.params.conditions)) or 'none'}. "
        f"Medications: {', '.join(f'{k}={v}' for k, v in rec.ehr.get('medications', {}).items()) or 'none'}.",
        "",
        "## Twin mirror (14-day assimilated summary)",
        f"- Resting HR (night): {avg('rest_hr')} bpm · evening HR: {avg('hr_evening_mean')} bpm",
        f"- Night HRV (RMSSD): {avg('night_hrv_mean')} ms",
        f"- Sleep: {avg('sleep_hours')} h/night · SpO2 dip hours: {avg('spo2_dip_hours')}",
        f"- Steps: {avg('steps')}/day",
        f"- Mean glucose: {avg('glucose_mean')} mg/dL · TIR: {avg('tir_pct')}% · "
        f"HbA1c-equivalent: {hba1c_from_mean_glucose(g14)}%",
        f"- Home BP: {next((d.sbp_cuff for d in reversed(rec.mirror.days) if d.sbp_cuff), '—')}/"
        f"{next((d.dbp_cuff for d in reversed(rec.mirror.days) if d.dbp_cuff), '—')} mmHg (last cuff)",
        "",
        "## Risk assessment",
    ]
    if risk:
        lines.append(f"- NEWS2 (assimilated vitals): **{risk['news2']['score']}** ({risk['news2']['band']})")
        tr = risk["twinrisk"]
        lines.append(f"- TwinRisk 48h deterioration probability: **{tr['probability'] * 100:.1f}%** "
                     f"({tr['band']}; alert threshold {tr['threshold']})")
        drivers = ", ".join(f"{d['feature']} ({d['contribution']:+.2f})" for d in tr["drivers"])
        lines.append(f"- Top drivers: {drivers}")
        if risk["live_alarms"]:
            lines.append(f"- **Active monitoring alarms**: " +
                         "; ".join(a["message"] for a in risk["live_alarms"]))
    lines += ["", "## Recommended review",
              "- Discuss protocol adjustments in the Protocol Studio (simulated before prescribed).",
              "- Re-assess after next wearable sync window.", "",
              "*Generated by VitalTwin PoC — synthetic data, not a medical device.*"]
    return JSONResponse({"markdown": "\n".join(lines)})


def _iso(t: int) -> str:
    """Hour counter -> demo timestamp (t=0 anchored to 2026-11-01 00:00)."""
    from datetime import datetime, timedelta
    return (datetime(2026, 11, 1) + timedelta(hours=t)).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Frontend (served last so /api takes precedence)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
