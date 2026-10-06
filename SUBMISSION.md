# Submission — Happiest Health Digital Twin Challenge 2026

**Team VitalTwin** · Submission stage: *Prototype & Code Submission* ·
Repository: (this repository — push to GitHub and paste the URL in the
submission form)

## The one-liner

**VitalTwin** is a proof-of-concept patient digital twin that answers the
challenge's core problem statement directly: it is a *dynamic, virtual
replica of a patient* that integrates **real-time wearable data with EHR
records** to (1) **predict adverse health events** before they occur and
(2) **personalise treatment protocols** by simulating them before they are
prescribed.

## How to run (evaluators)

```bash
pip install -r requirements.txt
python run.py             # open http://127.0.0.1:8000
python -m pytest tests/ -q   # 26 tests, ~5 s
```

Python ≥ 3.10 (developed on 3.14, CI on 3.11/3.12/3.13). No API keys, no
external services, no database — the deterministic synthetic world rebuilds
itself at boot. A 5-minute guided demo script for the jury is at
[`docs/demo_walkthrough.md`](docs/demo_walkthrough.md).

## Deliverables map (per the submission guidelines)

| Guideline item | Where |
|---|---|
| Working PoC prototype | `app/` + `frontend/` — runs with the two commands above |
| Source code | `app/engine/*` (twin engine), `app/main.py` (API), `frontend/app.js` (dashboard) |
| Required documentation | `README.md` + `docs/` (architecture, clinical model, evaluation, data dictionary, API, privacy & ethics, limitations & roadmap) |
| Demo instructions | `docs/demo_walkthrough.md` (jury script, question prep) + on-screen demo list |
| Screenshots | `docs/screenshots/*.png` (6 pages, captured from the running app) |
| Model artefact + metrics | `app/models/twinrisk_v1.json`, `docs/evaluation.md` + `docs/evaluation.json` |
| Tests | `tests/` (26 pytest tests — clinical plausibility gates, leakage checks, metric sanity, API contract) |
| CI | `.github/workflows/ci.yml` — pytest on Python 3.11–3.13 |
| Licence | MIT (`LICENSE`) |

## What to look at first (for the technical panel)

1. `docs/architecture.md` — the three loops (mirror / predict / simulate)
   and why one forward model serves both data generation and what-if.
2. `docs/clinical_model.md` — every equation with its literature anchor
   (NEWS2, ADAG, Bergman, HRV Task Force, DiRECT); the alert taxonomy.
3. `scripts/train_risk_model.py` + `docs/evaluation.md` — the full
   train→evaluate pipeline is reproducible in one command, with the
   patient-level split, committed metrics and the ROC sweep.
4. `app/engine/protocols.py::goal_seek` — the "twin as prescription"
   primitive (binary search + ±10 % physiology jitter band).
5. `docs/limitations_roadmap.md` — what is *not* validated and the
   prospective-clinical-evaluation path. We consider honesty a feature.

## Design claims we will defend in the jury round

- **Assimilation is the twin.** The mirror (Kalman filters + circadian
  personal baselines + model-carried blood pressure between cuff readings)
  is what distinguishes a digital twin from a dashboard: every downstream
  number — risk, protocol projection, report — reads the *assimilated
  state*, never a raw feed.
- **Explainability by construction.** TwinRisk ships per-feature
  contributions for every score; NEWS2 is the transparent baseline; the
  protocol engine explains results by one-at-a-time lever ablation.
- **Synthetic data is a privacy decision, not a shortcut** — and it buys
  measurable lead-time ground truth. Its limits are stated and the
  roadmap's first item is real-cohort validation (MIMIC-IV / wearable
  cohorts).
- **Alert fatigue is designed against** — tiered alerts, published ROC
  sweep, specificity-weighted operating point.
