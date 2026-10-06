"""Train the TwinRisk deterioration model on the labeled synthetic cohort.

Pipeline:
  1. Generate a synthetic cohort (archetype mixture, hourly wearable/CGM
     streams, injected adverse events with prodrome dynamics).
  2. Assimilate every stream with the twin mirror (the *same* code the
     live app uses — no training/serving skew).
  3. Build per-patient-day feature rows; label = acute deterioration
     (infection-like, hypertensive crisis, or severe hypoglycaemia)
     within the next 48 hours.
  4. Split by patient (no patient leakage), train the logistic model,
     choose the alert threshold for >= 85% sensitivity on validation.
  5. Save app/models/twinrisk_v1.json + docs/evaluation.json metrics.

Usage:  python scripts/train_risk_model.py [--patients 60] [--days 180] [--seed 2026]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.generator import generate_patient_cohort_entry          # noqa: E402
from app.engine.assimilation import assimilate_stream                 # noqa: E402
from app.engine.features import build_feature_rows, FEATURE_NAMES     # noqa: E402
from app.engine.physiology import params_from_ehr                     # noqa: E402
from app.engine.risk import (train_logistic, auroc, average_precision,  # noqa: E402
                             sens_spec_at, choose_threshold_for_sensitivity)

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=60)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    print(f"Generating cohort: {args.patients} patients x {args.days} days ...")
    entries: list[tuple[str, list[dict]]] = []   # (pid, rows)
    t0 = time.time()
    all_rows: list[tuple[str, dict]] = []
    cohort_meta = []
    for i in range(args.patients):
        pid = f"c{i:03d}"
        entry = generate_patient_cohort_entry(pid, args.days, seed=args.seed + i * 101)
        params = params_from_ehr(entry["ehr"])
        _mirror, days = assimilate_stream(params, entry["stream"])
        summaries = [d.to_dict() for d in days]
        psum = {"age": params.age, "sex": params.sex, "bmi": round(params.bmi, 1),
                "conditions": sorted(params.conditions)}
        for row in build_feature_rows(psum, summaries, entry["events"]):
            all_rows.append((pid, row))
        cohort_meta.append({"patient_id": pid, "age": params.age,
                            "conditions": sorted(params.conditions),
                            "n_events": len(entry["events"])})
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{args.patients} ({time.time() - t0:.0f}s)", flush=True)

    # ---- split by patient -------------------------------------------------
    rng = __import__("random").Random(args.seed)
    pids = sorted({pid for pid, _ in all_rows})
    rng.shuffle(pids)
    cut = int(len(pids) * 0.8)
    train_pids = set(pids[:cut])
    train = [r for pid, r in all_rows if pid in train_pids]
    val = [r for pid, r in all_rows if pid not in train_pids]
    pos_t = sum(r["label_deterioration_48h"] for r in train)
    pos_v = sum(r["label_deterioration_48h"] for r in val)
    print(f"rows: train={len(train)} (pos {pos_t}, {100 * pos_t / max(1, len(train)):.1f}%)  "
          f"val={len(val)} (pos {pos_v}, {100 * pos_v / max(1, len(val)):.1f}%)")

    # ---- train --------------------------------------------------------------
    model = train_logistic(train, [r["label_deterioration_48h"] for r in train],
                           FEATURE_NAMES, l2=1e-3, epochs=3000)
    val_scores = [model.probability(r) for r in val]
    val_y = [r["label_deterioration_48h"] for r in val]
    metrics = {
        "val_auroc": round(auroc(val_y, val_scores), 3),
        "val_average_precision": round(average_precision(val_y, val_scores), 3),
        "prevalence": round(pos_v / max(1, len(val)), 4),
        "n_patients": args.patients,
        "n_days": args.days,
    }
    threshold_info = choose_threshold_for_sensitivity(val_y, val_scores, 0.65)
    threshold = round(threshold_info["threshold"], 3)
    metrics.update(sens_spec_at(val_y, val_scores, threshold))
    metrics["alert_threshold"] = threshold
    metrics["sensitivity_target_met"] = threshold_info["target_met"]
    metrics["at_sens_080"] = sens_spec_at(val_y, val_scores,
                                          choose_threshold_for_sensitivity(val_y, val_scores, 0.80)["threshold"])
    # store a compact ROC sweep for docs/evaluation.md
    roc = []
    for thr in (0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18, 0.25, 0.35):
        roc.append({"threshold": thr, **sens_spec_at(val_y, val_scores, thr)})
    metrics["roc_sweep"] = roc
    print("metrics:", metrics)

    # ---- lead time ------------------------------------------------------------
    leads = []
    for pid in [p for p in pids if p not in train_pids]:
        rows = [r for p, r in all_rows if p == pid]
        for r in rows:
            if r["hours_to_next_event"] == -1:
                continue
            if model.probability(r) >= threshold:
                lead = r["hours_to_next_event"]
                if 0 < lead <= 48:
                    leads.append(lead)
    metrics["mean_lead_hours_when_detected"] = round(sum(leads) / len(leads), 1) if leads else None
    metrics["detected_events"] = len(leads)

    model.meta.update(metrics)
    out_dir = ROOT / "app" / "models"
    out_dir.mkdir(exist_ok=True)
    model.save(out_dir / "twinrisk_v1.json")
    (ROOT / "docs" / "evaluation.json").write_text(json.dumps({
        "metrics": metrics,
        "cohort": {"n_patients": args.patients, "n_days": args.days, "seed": args.seed,
                   "total_events": sum(c["n_events"] for c in cohort_meta)},
        "feature_names": FEATURE_NAMES,
        "weights": dict(zip(FEATURE_NAMES, [round(w, 4) for w in model.weights])),
    }, indent=2), encoding="utf-8")
    print(f"saved {out_dir / 'twinrisk_v1.json'} and docs/evaluation.json")


if __name__ == "__main__":
    main()
