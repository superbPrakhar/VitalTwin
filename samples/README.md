# samples

Reference artefacts for integrators:

- `wearable_sample.csv` — the hourly ingest schema the assimilation layer
  consumes (see `docs/data_dictionary.md`). Column order matches
  `app/data/generator.py`; `sbp`/`dbp` are sparse (home cuff) by design —
  the twin carries blood pressure between readings.
- Device-integration note: production ingest maps vendor exports
  (Apple Health / Google Fit / LibreView) onto this same hourly schema in a
  thin adapter; the twin itself is agnostic to the source.
