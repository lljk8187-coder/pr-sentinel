# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec.v2.0.0.html).

## [0.10.0] — 2026-09-24

Phase4 release hygiene (no new product surface; no real GitHub App / fixtures=false claims).

### Added
- **M17**: Version alignment to **0.10.0** across `pyproject.toml`, FastAPI `version`, GitHub `User-Agent` (`pr-sentinel/0.10`), README, and this changelog.

### Changed
- **M14**: Redact secrets outbound before Check Run annotations, sticky PR comment, and high-severity inline comments (same path as Postgres writeback when `privacy.redact_secrets` is on).
- **M16**: When worker transient retries are exhausted, mark the job `failed` in Postgres instead of leaving it stuck `running`.
- **M15**: Compose `restart: unless-stopped` for `api`/`worker`, process-level worker healthcheck, and required Settings vars called out in `.env.example`.

## [0.9.0] — 2026-09

Phase2/3 closeout highlights (M9–M13).

### Added
- **M9**: Job detail API + findings / `report_md` / `check_run_id` writeback to Postgres; console detail page.
- **M10**: Engineering hygiene — version **0.9.0**, CI pin `ubuntu-24.04` / Node 24 actions.
- **M11**: Inline comments use RIGHT-side line + fingerprint upsert (avoid 422 / duplicate noise).
- **M12**: `validate_config` soft-fallback for bad YAML fields; redact secrets before Postgres storage.
- **M13**: `check_run_url` (`/runs/{id}` UI link), structured log fields, console status counts + light `GET /metrics`.
