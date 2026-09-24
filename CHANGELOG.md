# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec.v2.0.0.html).

## [Unreleased]

## [1.2.0] — 2026-09-24

Phase7 analysis-quality release. **Notes:** real GitHub App / live E2E remains **optional**, not a hard gate.

### Added
- **M26**: Rules `skipped_tests` + `dangerous_commands`; default secrets patterns add `ghp_` / `sk-`.
- **M27**: `llm_parse_soft` — soft-degrade when LLM output is not structured findings; remove synthetic info Finding.
- **M28**: `ignore_paths` documentation boundaries + empty-list contract tests (no behavior change to default filter).
- **M29**: Version alignment to **1.2.0** across `pyproject.toml`, FastAPI `version`, GitHub `User-Agent` (`pr-sentinel/1.2`), README, and this changelog.

## [1.1.0] — 2026-09-24

Phase6 hardening release. **Notes:** real GitHub App / live E2E remains **optional**, not a hard gate.

### Added
- **M24**: Webhook body Content-Length/body oversize → **413** (default 1 MiB); Redis `INCR`+`EXPIRE` rate limit → **429** (default 120/60s); order rate-limit → body-size → HMAC; no slowapi.
- **M23**: `validate_config` nested walk strips unknown keys with path notes (still soft).
- **M22**: pytest `filterwarnings` silence Starlette TestClient / anyio BlockingPortal deprecation (keep sync TestClient).
- **M25**: Version alignment to **1.1.0** across `pyproject.toml`, FastAPI `version`, GitHub `User-Agent` (`pr-sentinel/1.1`), README, and this changelog.

## [1.0.0] — 2026-09-24

Phase5 readiness release. **Notes:** real GitHub App / live E2E is **optional**, not a hard gate for 1.0.0.

### Added
- **M18**: Live mode (`USE_FIXTURES=false`) **fail-fast** when App/PAT credentials are missing (no silent fixtures fallback).
- **M19**: Fixtures smoke scaffold — docs + env/compose for **无真 App smoke** (HMAC webhook → 202 → `/console` from Postgres); optional `scripts/smoke_fixtures_webhook.py`.
- **M20**: Console ops UX — failed-row highlight, error truncate, `?status=` filter.
- **M21**: Version alignment to **1.0.0** across `pyproject.toml`, FastAPI `version`, GitHub `User-Agent` (`pr-sentinel/1.0`), README, and this changelog.

### Changed
- **M19**: `docs/e2e-demo.md` — jobs archive is Postgres (removed outdated Redis `pr-sentinel:jobs` LIST wording); real App / smee kept optional.

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
