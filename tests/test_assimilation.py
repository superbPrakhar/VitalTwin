"""Assimilation + feature pipeline tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.generator import generate_patient_cohort_entry   # noqa: E402
from app.engine.assimilation import assimilate_stream          # noqa: E402
from app.engine.features import build_feature_rows, FEATURE_NAMES  # noqa: E402
from app.engine.physiology import params_from_ehr              # noqa: E402


def _entry():
    return generate_patient_cohort_entry("p_test", 30, seed=101)


def test_assimilation_tracks_truth_within_sensor_tolerance():
    entry = _entry()
    params = params_from_ehr(entry["ehr"])
    mirror, days = assimilate_stream(params, entry["stream"])
    truth = entry["truth"]
    hr_err = [abs(m["est"]["hr"] - truth[m["t"]]["hr"]) for m in mirror.hours
              if m["t"] < len(truth)]
    assert sum(hr_err) / len(hr_err) < 6.0        # within ~1.7x sensor sd
    g_err = [abs(m["est"]["glucose"] - truth[m["t"]]["glucose"]) for m in mirror.hours
             if m["t"] < len(truth)]
    assert sum(g_err) / len(g_err) < 6.0


def test_daily_summaries_are_complete_and_bounded():
    entry = _entry()
    params = params_from_ehr(entry["ehr"])
    _mirror, days = assimilate_stream(params, entry["stream"])
    assert len(days) == 30
    d = days[-1]
    assert 30 <= d.rest_hr <= 95
    assert 0 <= d.sleep_hours <= 12
    assert 0 <= d.tir_pct <= 100
    assert d.steps >= 0
    assert 0 <= d.glucose_cv < 100


def test_feature_rows_have_no_future_leakage_and_complete_columns():
    entry = _entry()
    params = params_from_ehr(entry["ehr"])
    _mirror, days = assimilate_stream(params, entry["stream"])
    rows = build_feature_rows({"age": params.age, "sex": params.sex,
                               "bmi": round(params.bmi, 1),
                               "conditions": sorted(params.conditions)},
                              [d.to_dict() for d in days], entry["events"])
    assert rows and rows[0]["day_index"] == 14          # warm-up respected
    for r in rows:
        for f in FEATURE_NAMES:
            assert f in r
        assert r["label_deterioration_48h"] in (0, 1)
    # rows near an event should be labelled, rows far from events mostly not
    expected = sum(1 for r in rows for e in entry["events"]
                   if 0 < e["onset_t"] - r["t_end"] <= 48)
    assert sum(r["label_deterioration_48h"] for r in rows) == expected
