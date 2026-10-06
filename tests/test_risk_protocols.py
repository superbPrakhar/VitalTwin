"""Risk engine, protocol studio and store-level API tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.risk import news2, auroc, average_precision, train_logistic, sens_spec_at  # noqa: E402
from app.engine.protocols import compare_to_base, goal_seek, explain_scenario  # noqa: E402
from app.engine.physiology import params_from_ehr             # noqa: E402
from app.data.generator import generate_patient_cohort_entry  # noqa: E402
from app.engine.assimilation import assimilate_stream         # noqa: E402
from app.engine.features import build_feature_rows, FEATURE_NAMES  # noqa: E402
from app.store import TwinStore                               # noqa: E402


# ---- NEWS2 ----------------------------------------------------------------

def test_news2_scores_match_rcp_table():
    # normal vitals -> 0
    assert news2(hr=72, sbp=120, spo2=97, temp_c=36.6, rr=13)["score"] == 0
    # gross derangement -> high
    r = news2(hr=135, sbp=85, spo2=90, temp_c=39.3, rr=26)
    assert r["score"] >= 9 and r["band"] == "high"
    assert r["parts"]["respiration_rate"] == 3 and r["parts"]["systolic_bp"] == 3


# ---- logistic model ---------------------------------------------------------

def test_logistic_model_separates_synthetic_classes():
    rows_X, y = [], []
    for i in range(400):
        sick = i % 2 == 0
        rows_X.append({"hr_evening_z": 2.5 if sick else -0.5,
                       "hrv_evening_z": -2.0 if sick else 0.5,
                       "age": 60})
        y.append(1 if sick else 0)
    model = train_logistic(rows_X, y, ["hr_evening_z", "hrv_evening_z", "age"],
                           epochs=800)
    scores = [model.probability(r) for r in rows_X]
    assert auroc(y, scores) > 0.95


def test_metrics_known_values():
    assert auroc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auroc([0, 1, 0, 1], [0.9, 0.1, 0.8, 0.2]) == 0.0
    assert average_precision([1, 0], [0.9, 0.1]) == 1.0


# ---- protocol studio ---------------------------------------------------------

def _t2d_params():
    ehr = {"patient_id": "x", "demographics": {"age": 58, "sex": "M", "height_cm": 170, "weight_kg": 84},
           "conditions": ["t2d", "hypertension"], "labs": {"hba1c_pct": 7.8, "fasting_glucose_mgdl": 145},
           "baseline_vitals": {"sbp": 146, "dbp": 88},
           "medications": {"metformin_mg": 1000, "antihypertensive_mmhg": 8},
           "self_report": {"activity_steps_day": 3800, "sleep_hours": 6.0, "stress_level": 0.6}}
    return params_from_ehr(ehr)


def test_protocol_lowers_hba1c_and_weight():
    p = _t2d_params()
    res = compare_to_base(p, 90, {"steps_day": 9000, "kcal_delta_day": -300, "carbs_day": 150})
    d = res["deltas"]
    assert d["hba1c"] < 0
    assert d["weight"] < 0


def test_goal_seek_finds_minimum_metformin_for_target():
    p = _t2d_params()
    # metformin titration on top of a lifestyle protocol reaches A1c 7.0
    res = goal_seek(p, 90, "metformin_mg", "hba1c_end", 7.0,
                    scenario_base={"steps_day": 9000, "kcal_delta_day": -300})
    assert res["feasible"]
    assert 0 <= res["lever_value"] <= 3000
    assert res["achieved"] <= 7.0
    assert res["band"]["min"] <= res["achieved"] <= res["band"]["max"] + 0.6


def test_explain_scenario_ranks_levers():
    p = _t2d_params()
    rows = explain_scenario(p, 90, {"steps_day": 9000, "carbs_day": 120})
    assert len(rows) == 2
    assert all("hba1c_delta" in r for r in rows)


# ---- store / live loop ---------------------------------------------------------

def test_store_boots_and_syncs_with_alerts():
    store = TwinStore().boot()
    assert set(store.patients) == {"ravi", "meera", "arjun"}
    arjun = store.patients["arjun"]
    assert arjun.scheduled_events, "Arjun must have his scripted demo event"

    # Before syncing, no alert should be event-linked (the scripted event
    # lies in the not-yet-revealed future window). Benign threshold
    # crossings are expected at ~76% specificity.
    pre_linked = [a for a in store.alert_feed("arjun") if a["upcoming_event"]]
    assert not pre_linked

    # Sync across the event horizon: as telemetry reveals the prodrome,
    # TwinRisk must fire BEFORE the acute onset (positive lead time).
    for _ in range(14):
        store.sync("arjun", hours=6)
    fired = [a for a in store.alert_feed("arjun")
             if a["lead_hours"] is not None and a["lead_hours"] > 0]
    assert fired, "TwinRisk must flag Arjun's prodrome with positive lead time"

    # Live sync continues to work and keeps assimilating
    res = store.sync("ravi", hours=6)
    assert res["synced_hours"] == 6
    assert res["risk"]["twinrisk"]["probability"] >= 0
    assert store.patients["ravi"].last_t > 30 * 24 - 1


def test_risk_model_loaded_from_disk():
    store = TwinStore().boot()
    assert store.risk_model is not None
    assert store.risk_model.meta.get("val_auroc", 0) > 0.7
