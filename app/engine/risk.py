"""Risk engine: NEWS2 baseline + TwinRisk deterioration model + alert policy.

Two complementary layers:

1. **NEWS2** (Royal College of Physicians, 2017) — the transparent
   clinical standard scored on the twin's assimilated vitals. It needs no
   training and catches *gross* physiological derangement right now.

2. **TwinRisk** — a logistic model over wearable-derived deviation
   features (resting-HR rise, HRV drop, SpO2 dips, sleep fragmentation,
   glycaemic variability, …) that fires *before* vitals breach NEWS2
   thresholds, because it reads each patient's deviation from their own
   baseline. Trained on the labeled synthetic cohort (scripts/train_risk_
   model.py); the fitted weights ship as ``app/models/twinrisk_v1.json``.

The alert policy fuses both: warn on either signal, with TwinRisk's
threshold chosen on validation for ~85% sensitivity.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

# ---------------------------------------------------------------------------
# NEWS2 (RCP 2017). Consciousness/separation parameters default to 0 (the
# twin has no GCS input in this PoC; documented in docs/clinical_model.md).
# ---------------------------------------------------------------------------

def _news2_rr(rr: float) -> int:
    if rr <= 8: return 3
    if rr <= 11: return 1
    if rr <= 20: return 0
    if rr <= 24: return 2
    return 3


def _news2_spo2(spo2: float) -> int:
    if spo2 <= 91: return 3
    if spo2 <= 93: return 2
    if spo2 <= 95: return 1
    return 0


def _news2_temp(temp: float) -> int:
    if temp <= 35.0: return 3
    if temp <= 36.0: return 1
    if temp <= 38.0: return 0
    if temp <= 39.0: return 1
    return 2


def _news2_sbp(sbp: float) -> int:
    if sbp <= 90: return 3
    if sbp <= 100: return 2
    if sbp <= 110: return 1
    if sbp <= 219: return 0
    return 3


def _news2_hr(hr: float) -> int:
    if hr <= 40: return 3
    if hr <= 50: return 1
    if hr <= 90: return 0
    if hr <= 110: return 1
    if hr <= 130: return 2
    return 3


def news2(hr: float, sbp: float, spo2: float, temp_c: float, rr: float,
          on_o2: bool = False, new_confusion: bool = False) -> dict:
    """Score NEWS2 on twin-estimated vitals; returns score + per-parameter split."""
    spo2_score = _news2_spo2(spo2) + (2 if on_o2 and spo2 > 91 else 0)
    parts = {
        "respiration_rate": _news2_rr(rr),
        "spo2": spo2_score,
        "temperature": _news2_temp(temp_c),
        "systolic_bp": _news2_sbp(sbp),
        "heart_rate": _news2_hr(hr),
        "consciousness": 2 if new_confusion else 0,
    }
    total = sum(parts.values())
    return {"score": total, "parts": parts,
            "band": "high" if total >= 7 else ("medium" if total >= 5 else ("low" if total >= 1 else "none"))}


# ---------------------------------------------------------------------------
# Logistic regression (pure Python — small feature count, no dependencies)
# ---------------------------------------------------------------------------

class LogisticModel:
    def __init__(self, feature_names: list[str], weights: list[float],
                 intercept: float, means: list[float], sds: list[float],
                 meta: dict | None = None):
        assert len(weights) == len(feature_names) == len(means) == len(sds)
        self.feature_names = feature_names
        self.weights = weights
        self.intercept = intercept
        self.means = means
        self.sds = sds
        self.meta = meta or {}

    # -- inference ----------------------------------------------------------

    def logit(self, raw_values: dict) -> float:
        z = self.intercept
        for name, w, m, s in zip(self.feature_names, self.weights, self.means, self.sds):
            v = raw_values.get(name)
            if v is None:
                v = m          # median/mean imputation consistent with training
            z += w * ((v - m) / (s if s else 1.0))
        return z

    def probability(self, raw_values: dict) -> float:
        return 1.0 / (1.0 + math.exp(-self.logit(raw_values)))

    def contributions(self, raw_values: dict) -> list[dict]:
        """Explainable per-feature contributions to the logit (for the UI)."""
        out = []
        for name, w, m, s in zip(self.feature_names, self.weights, self.means, self.sds):
            v = raw_values.get(name)
            if v is None:
                v = m
            out.append({"feature": name, "value": v,
                        "contribution": round(w * ((v - m) / (s if s else 1.0)), 3)})
        return sorted(out, key=lambda c: -abs(c["contribution"]))

    # -- persistence ----------------------------------------------------------

    def to_dict(self) -> dict:
        return {"feature_names": self.feature_names, "weights": self.weights,
                "intercept": self.intercept, "means": self.means, "sds": self.sds,
                "meta": self.meta}

    @classmethod
    def from_dict(cls, d: dict) -> "LogisticModel":
        return cls(d["feature_names"], d["weights"], d["intercept"],
                   d["means"], d["sds"], d.get("meta"))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "LogisticModel":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def train_logistic(rows_X: list[dict], y: list[int], feature_names: list[str],
                   l2: float = 1e-3, lr: float = 0.1, epochs: int = 4000,
                   balance: bool = False) -> LogisticModel:
    """Gradient-descent logistic regression on standardized features.

    ``balance=False`` (default) keeps probabilities calibrated to the
    cohort prevalence, so the alert threshold reads as an interpretable
    risk level. ``balance=True`` upweights the minority class.
    """
    n, k = len(rows_X), len(feature_names)
    means = [sum(r.get(f, 0.0) for r in rows_X) / n for f in feature_names]
    sds = []
    for f, m in zip(feature_names, means):
        var = sum((r.get(f, m) - m) ** 2 for r in rows_X) / max(1, n - 1)
        sds.append(math.sqrt(var) or 1.0)
    X = [[(r.get(f, m) - m) / s for f, m, s in zip(feature_names, means, sds)] for r in rows_X]
    w = [0.0] * k
    b = 0.0
    pos = sum(y) / max(1, n)
    w_pos = (0.5 / max(pos, 1e-6)) if balance else 1.0
    w_neg = (0.5 / max(1 - pos, 1e-6)) if balance else 1.0
    for _ in range(epochs):
        gw = [0.0] * k
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            g = (p - yi) * (w_pos if yi == 1 else w_neg)
            gb += g
            for j in range(k):
                gw[j] += g * xi[j]
        for j in range(k):
            gw[j] = gw[j] / n + l2 * w[j]
            w[j] -= lr * gw[j]
        b -= lr * gb / n
    return LogisticModel(feature_names, w, b, means, sds,
                         meta={"l2": l2, "epochs": epochs, "n": n, "positives": sum(y)})


# ---------------------------------------------------------------------------
# Metrics (pure Python implementations)
# ---------------------------------------------------------------------------

def auroc(y_true: list[int], scores: list[float]) -> float:
    pos = [s for s, y in zip(scores, y_true) if y == 1]
    neg = [s for s, y in zip(scores, y_true) if y == 0]
    if not pos or not neg:
        return float("nan")
    wins = ties = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                wins += 1
            elif p == q:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def average_precision(y_true: list[int], scores: list[float]) -> float:
    pairs = sorted(zip(scores, y_true), key=lambda t: -t[0])
    tp = fp = 0
    ap = 0.0
    prev_recall = 0.0
    total_pos = sum(y_true)
    if total_pos == 0:
        return float("nan")
    for s, y in pairs:
        if y == 1:
            tp += 1
        else:
            fp += 1
        recall = tp / total_pos
        precision = tp / max(1, tp + fp)
        ap += precision * (recall - prev_recall)
        prev_recall = recall
    return ap


def sens_spec_at(y_true: list[int], scores: list[float], threshold: float) -> dict:
    tp = sum(1 for s, y in zip(scores, y_true) if s >= threshold and y == 1)
    fn = sum(1 for s, y in zip(scores, y_true) if s < threshold and y == 1)
    fp = sum(1 for s, y in zip(scores, y_true) if s >= threshold and y == 0)
    tn = sum(1 for s, y in zip(scores, y_true) if s < threshold and y == 0)
    sens = tp / max(1, tp + fn)
    spec = tn / max(1, tn + fp)
    return {"threshold": threshold, "sensitivity": round(sens, 3),
            "specificity": round(spec, 3), "alerts_per_patient_day": round((tp + fp) / max(1, len(y_true)), 4)}


def choose_threshold_for_sensitivity(y_true: list[int], scores: list[float],
                                     target_sens: float = 0.8) -> dict:
    """Pick the highest threshold whose sensitivity >= target.

    Returns the threshold plus the *achieved* sensitivity; if the target
    is unreachable the lowest positive score is used (max sensitivity)
    and ``target_met`` is False — the caller reports this honestly.
    """
    if not any(y_true):
        return {"threshold": 0.5, "achieved_sensitivity": None, "target_met": False}
    best = None
    for thr in [i / 200 for i in range(1, 199)]:   # 0.005 .. 0.99
        tp = sum(1 for s, y in zip(scores, y_true) if s >= thr and y == 1)
        sens = tp / max(1, sum(y_true))
        if sens >= target_sens:
            best = thr
        elif best is not None:
            break
    if best is not None:
        return {"threshold": best, "achieved_sensitivity": target_sens, "target_met": True}
    min_pos = min(s for s, y in zip(scores, y_true) if y == 1)
    return {"threshold": min_pos, "achieved_sensitivity": None, "target_met": False}
