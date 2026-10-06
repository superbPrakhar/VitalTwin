# Privacy, security & ethics

VitalTwin is designed so that **no real patient data is required anywhere**
— for development, evaluation or the demo. This document explains what the
PoC does today and what a production deployment must add.

## What the PoC does

- **100 % synthetic data.** Every patient, EHR bundle, wearable stream and
  adverse event in this repository is generated deterministically by
  `app/data/generator.py`. Names are fictional; demographics are sampled
  from archetype ranges. There is no network egress, no telemetry, no
  third-party services; Chart.js is vendored so the dashboard runs offline.
- **No persistence.** The in-memory store is rebuilt from seeds at process
  start; nothing is written to disk at runtime.
- **Minimal data model.** The twin holds physiological time series and an
  EHR summary — no identifiers beyond a first/last name for the demo, which
  a production build replaces with pseudonymous IDs.
- **Dashboard disclaimers.** The UI carries a persistent "Synthetic PoC ·
  not a medical device" badge, and every generated clinician report is
  watermarked accordingly.

## Production privacy architecture (roadmap)

1. **Data minimisation & residency.** Wearable streams and EHR data stay in
   the covered entity's environment (hospital VPC / India DPDP-compliant
   region); the twin service consumes de-identified, pseudonymised
   resources via a FHIR R4 interface with consent scopes.
2. **Consent & purpose limitation.** Twin enrolment is explicit and
   revocable; every assimilation event records its consent basis. Patients
   see the same mirror the clinician sees (transparency by design).
3. **Federation.** The twin's parameters (not the raw data) could remain
   patient-held — the PoC's parameter/state separation
   (`PhysiologyParams` vs `TwinState`) is deliberately shaped for a
   patient-owned-parameter future.
4. **Security.** OAuth2/mTLS between device gateway and twin service, audit
   logging of every read, RBAC for clinician vs patient views, encrypted
   feature store at rest. The PoC's FastAPI layer already separates the
   public read APIs from state-mutating sync/simulate endpoints to make
   policy insertion points explicit.
5. **Model governance.** Versioned model artefacts
   (`app/models/twinrisk_v1.json` carries training metadata), documented
   evaluation (`docs/evaluation.md`), an update path that re-trains and
   re-evaluates before promotion, and human-in-the-loop review for every
   alert tier before any clinical workflow integration.

## Ethics

- **Alert fatigue is a first-class design constraint:** the operating
  threshold was chosen with specificity (0.765) in mind, and the ROC sweep
  is published so the trade-off is explicit rather than hidden.
- **Explainability over accuracy theatre:** TwinRisk ships its per-feature
  contributions for every score, and NEWS2 provides a transparent baseline
  clinicians already know.
- **Equity:** the archetype mixture spans age/sex/comorbidity groups, but a
  production model must be evaluated for subgroup calibration (the roadmap's
  first evaluation task on real data).
- **Not a medical device.** This PoC does not diagnose, treat or prevent
  disease; it demonstrates an architecture and interaction model for the
  Happiest Health Digital Twin Challenge.
