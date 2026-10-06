"""State assimilation: turning noisy wearable telemetry into a twin state.

This is the loop that makes the twin *live*:

    wearable window ──►  per-channel Kalman filter  ──►  assimilated state
                          + circadian personal baseline ──►  deviation z-scores
                          + daily summariser        ──►  daily summaries

Design notes (full rationale in docs/architecture.md):

- Wearables observe HR, HRV, SpO2, steps, sleep, skin temperature and (CGM)
  glucose. They do **not** observe blood pressure. The twin carries a
  model-based BP estimate updated whenever a home-cuff reading arrives —
  the same structure as a real deployment mixingIoMT devices of unequal
  sampling rates.
- Each channel uses a 1-D Kalman filter with a random-walk process model;
  process noise is activity-dependent for HR/glucose (they move fast around
  meals/exertion) and fixed elsewhere. This is deliberately simple and
  explainable; ensemble/particle methods are the production roadmap.
- Personal baselines are per-channel × per-hour-of-day exponential moving
  means/SDs over ~14 effective days, so "elevated" is measured against the
  patient's *own* circadian pattern, not a population table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# channel -> (measurement noise sd, process noise sd)
CHANNELS: dict[str, tuple[float, float]] = {
    "hr": (3.5, 1.3),
    "hrv": (3.2, 1.6),
    "spo2": (0.7, 0.06),
    "rr": (0.6, 0.10),
    "temp_dev": (0.15, 0.006),
    "glucose": (2.5, 4.0),
    "sbp": (4.5, 0.55),
    "dbp": (3.5, 0.40),
}

_FAST_CHANNELS = {"hr", "glucose"}   # larger process noise while awake/active
_WARMUP_DAYS = 14
_BASELINE_ALPHA = 0.05


class Kalman1D:
    """Minimal 1-D Kalman filter (random-walk process model)."""

    def __init__(self, x0: float, q: float, r: float):
        self.x = x0
        self.P = r  # start with variance equal to sensor noise
        self.q = q
        self.r = r

    def predict(self, q_scale: float = 1.0) -> None:
        self.P += self.q * q_scale

    def update(self, z: float) -> None:
        K = self.P / (self.P + self.r)
        self.x += K * (z - self.x)
        self.P *= (1.0 - K)

    def step(self, z: float, q_scale: float = 1.0) -> float:
        self.predict(q_scale)
        self.update(z)
        return self.x


@dataclass
class CircadianBaseline:
    """Per-hour-of-day EMA mean/SD for one channel."""

    mean: list[float] = field(default_factory=lambda: [0.0] * 24)
    var: list[float] = field(default_factory=lambda: [1.0] * 24)
    count: list[int] = field(default_factory=lambda: [0] * 24)

    def observe(self, hour: int, value: float) -> float | None:
        """Update the baseline and return the pre-update z-score if warmed up."""
        h = hour % 24
        z = None
        if self.count[h] >= _WARMUP_DAYS:
            sd = math.sqrt(max(self.var[h], 1e-6))
            if sd > 1e-6:
                z = (value - self.mean[h]) / sd
        m0, v0 = self.mean[h], self.var[h]
        self.mean[h] += _BASELINE_ALPHA * (value - m0)
        self.var[h] += _BASELINE_ALPHA * ((value - self.mean[h]) ** 2 - v0)
        self.count[h] += 1
        return z

    @property
    def warmed_up(self) -> bool:
        return min(self.count) >= _WARMUP_DAYS


@dataclass
class DailySummary:
    """One assimilated day (aggregated from hourly measurements)."""

    day_index: int
    t_end: int
    rest_hr: float = 0.0            # min HR during sleep (or 10th pct)
    hr_evening_mean: float = 0.0    # mean HR 18:00-23:00 (same-day prodrome signal)
    hrv_evening_mean: float = 0.0   # mean evening HRV
    night_hrv_mean: float = 0.0
    sleep_hours: float = 0.0
    sleep_frag: float = 0.0         # stage transitions per night hour
    spo2_dip_hours: float = 0.0     # sleep hours with SpO2 < 91%
    steps: int = 0
    glucose_mean: float = 0.0
    glucose_min_night: float = 0.0
    glucose_cv: float = 0.0
    tir_pct: float = 0.0            # % of day in 70-180 mg/dL
    hypo_episodes: int = 0          # hours < 70 mg/dL
    hyper_hours: int = 0            # hours > 250 mg/dL
    temp_dev_max: float = 0.0
    rr_max: float = 0.0
    sbp_cuff: float | None = None   # most recent home BP reading, if any
    dbp_cuff: float | None = None
    stress_mean: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class TwinMirror:
    """Assimilates a wearable/CGM stream into the twin's state estimate."""

    def __init__(self, params):
        self.params = params
        self.filters = {
            "hr": Kalman1D(params.resting_hr_base, CHANNELS["hr"][1], CHANNELS["hr"][0]),
            "hrv": Kalman1D(params.rmssd_base, CHANNELS["hrv"][1], CHANNELS["hrv"][0]),
            "spo2": Kalman1D(params.spo2_base, CHANNELS["spo2"][1], CHANNELS["spo2"][0]),
            "rr": Kalman1D(params.rr_base, CHANNELS["rr"][1], CHANNELS["rr"][0]),
            "temp_dev": Kalman1D(0.0, CHANNELS["temp_dev"][1], CHANNELS["temp_dev"][0]),
            "glucose": Kalman1D(params.glucose_base, CHANNELS["glucose"][1], CHANNELS["glucose"][0]),
            "sbp": Kalman1D(params.sbp_base, CHANNELS["sbp"][1], CHANNELS["sbp"][0]),
            "dbp": Kalman1D(params.dbp_base, CHANNELS["dbp"][1], CHANNELS["dbp"][0]),
        }
        self.baselines = {ch: CircadianBaseline() for ch in
                          ("hr", "hrv", "spo2", "rr", "glucose", "temp_dev")}
        self.t = 0
        self.hours: list[dict] = []      # assimilated hourly records
        self.days: list[DailySummary] = []
        self._day_buffer: list[dict] = []

    # -- assimilation ------------------------------------------------------

    def assimilate(self, rec: dict) -> dict:
        """Assimilate one hourly measurement record; returns the estimate."""
        hour = rec["t"] % 24
        sleeping = rec.get("sleep_stage", "awake") != "awake"
        active = rec.get("steps", 0) > 350
        est = {}
        for ch in ("hr", "hrv", "spo2", "rr", "temp_dev", "glucose"):
            if rec.get(ch) is None:
                continue
            qs = 1.0
            if ch == "hr":
                qs = 1.6 if active else (0.3 if sleeping else 1.0)
            elif ch == "glucose":
                qs = 3.0 if self._meal_window(hour) else 0.8
            est[ch] = round(self.filters[ch].step(rec[ch], qs), 2)
            self.baselines[ch].observe(hour, est[ch])
        # Blood pressure: carried by the model; updated on cuff readings only
        for ch in ("sbp", "dbp"):
            if rec.get(ch) is not None:
                est[ch] = round(self.filters[ch].step(rec[ch], 2.0), 1)
            else:
                self.filters[ch].predict(1.0)
                est[ch] = round(self.filters[ch].x, 1)
        z = {}
        for ch in ("hr", "hrv", "spo2", "rr", "glucose", "temp_dev"):
            b = self.baselines[ch]
            if b.count[hour % 24] >= _WARMUP_DAYS:
                sd = math.sqrt(max(b.var[hour % 24], 1e-6))
                if sd > 1e-6:
                    z[ch] = round((est[ch] - b.mean[hour % 24]) / sd, 2)
        out = {"t": rec["t"], "sleep_stage": rec.get("sleep_stage", "awake"),
               "steps": rec.get("steps", 0), "est": est, "z": z,
               "cuff": rec.get("sbp") is not None}
        self.hours.append(out)
        self._day_buffer.append(out)
        self.t = rec["t"]
        if hour == 23:
            self._close_day()
        return out

    def _meal_window(self, hour: int) -> bool:
        return hour in (7, 8, 12, 13, 14, 19, 20, 21)

    def _close_day(self) -> None:
        if not self._day_buffer:
            return
        buf = self._day_buffer
        self._day_buffer = []
        day = len(self.days)
        sleep_recs = [r for r in buf if r["sleep_stage"] != "awake"]
        night_hrv = [r["est"]["hrv"] for r in sleep_recs] or [r["est"]["hrv"] for r in buf]
        rest_hr = min((r["est"]["hr"] for r in sleep_recs), default=None)
        if rest_hr is None:
            hrs = sorted(r["est"]["hr"] for r in buf)
            rest_hr = hrs[max(0, int(len(hrs) * 0.1))]
        g = [r["est"]["glucose"] for r in buf]
        gmean = sum(g) / len(g)
        nights = [r for r in buf if r["sleep_stage"] != "awake"]
        gmin_night = min((r["est"]["glucose"] for r in nights), default=min(g))
        transitions = sum(1 for i in range(1, len(sleep_recs))
                          if sleep_recs[i]["sleep_stage"] != sleep_recs[i - 1]["sleep_stage"])
        frag = transitions / max(1.0, len(sleep_recs))
        evening = [r for r in buf if 18 <= (r["t"] % 24) < 23]
        hr_eve = sum(r["est"]["hr"] for r in evening) / len(evening) if evening else rest_hr
        hrv_eve = sum(r["est"]["hrv"] for r in evening) / len(evening) if evening else night_hrv[0]
        cuff = [r for r in buf if r["cuff"]]
        last_cuff = cuff[-1]["est"] if cuff else {}
        self.days.append(DailySummary(
            day_index=day,
            t_end=buf[-1]["t"],
            rest_hr=round(rest_hr, 1),
            hr_evening_mean=round(hr_eve, 1),
            hrv_evening_mean=round(hrv_eve, 1),
            night_hrv_mean=round(sum(night_hrv) / len(night_hrv), 1),
            sleep_hours=round(len(nights), 1),
            sleep_frag=round(frag, 2),
            spo2_dip_hours=round(sum(1 for r in nights if r["est"]["spo2"] < 91.0), 1),
            steps=sum(r["steps"] for r in buf),
            glucose_mean=round(gmean, 1),
            glucose_min_night=round(gmin_night, 1),
            glucose_cv=round(_cv(g), 3),
            tir_pct=round(100.0 * sum(1 for x in g if 70 <= x <= 180) / len(g), 1),
            hypo_episodes=sum(1 for x in g if x < 70),
            hyper_hours=sum(1 for x in g if x > 250),
            temp_dev_max=round(max(r["est"]["temp_dev"] for r in buf), 2),
            rr_max=round(max(r["est"]["rr"] for r in buf), 1),
            sbp_cuff=last_cuff.get("sbp"),
            dbp_cuff=last_cuff.get("dbp"),
            stress_mean=0.0,
        ))

    # -- status ------------------------------------------------------------

    def organ_status(self) -> list[dict]:
        """Organ-system view of the current assimilated state (for the UI)."""
        est = self.hours[-1]["est"] if self.hours else {}
        z = self.hours[-1].get("z", {}) if self.hours else {}
        def _stat(*zs: str) -> str:
            vals = [abs(z[k]) for k in zs if k in z]
            m = max(vals) if vals else 0.0
            return "alert" if m > 2.5 else ("watch" if m > 1.5 else "ok")
        hrv_status = _stat("hrv")
        return [
            {"system": "Cardiovascular", "metrics": f"HR {est.get('hr', '—')} bpm · BP {est.get('sbp', '—')}/{est.get('dbp', '—')} · MAP {round((est.get('sbp', 0) + 2 * est.get('dbp', 0)) / 3) if est.get('sbp') else '—'}",
             "status": _stat("hr")},
            {"system": "Autonomic / stress", "metrics": f"HRV {est.get('hrv', '—')} ms · skin temp {est.get('temp_dev', 0):+.1f}°C",
             "status": _stat("hrv", "temp_dev")},
            {"system": "Respiratory", "metrics": f"SpO₂ {est.get('spo2', '—')}% · RR {est.get('rr', '—')}",
             "status": _stat("spo2", "rr")},
            {"system": "Metabolic", "metrics": f"Glucose {est.get('glucose', '—')} mg/dL",
             "status": _stat("glucose")},
            {"system": "Activity / recovery", "metrics": f"Steps today {sum(r['steps'] for r in self.hours if r['t'] // 24 == self.t // 24)} · sleep debt tracked",
             "status": "ok"},
        ]


def _cv(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    if m <= 0:
        return 0.0
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) / m * 100.0


def assimilate_stream(params, stream: list[dict]) -> tuple[TwinMirror, list[DailySummary]]:
    """Assimilate a full wearable stream; returns (mirror, daily summaries)."""
    mirror = TwinMirror(params)
    for rec in stream:
        mirror.assimilate(rec)
    if len(mirror._day_buffer) >= 12:   # flush only near-complete days
        mirror._close_day()
    return mirror, mirror.days
