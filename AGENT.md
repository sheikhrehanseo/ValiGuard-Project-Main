# AGENT.md — ValiGuard AI Implementation Guide

This document is the single source of truth for completing the ValiGuard AI Final Year Project (FYP-F25-14, The University of Lahore, Department of Software Engineering). It is derived from a full codebase-vs-documentation audit and supersedes any assumptions an implementing agent might otherwise make. Read this entire file before writing any code.

**Scope discipline:** This is a Final Year Project, not a production system. Implement only what is required to satisfy `ValiGuard_AI_Proposal.md` and `ValiGuard_AI_Phase_1_Documentation.md` (FR-01 through FR-15, NFR-01 through NFR-12, UC-01 through UC-05, and the ERD/Data Dictionary in Chapter 4). Do not add production-hardening features (Docker, Redis, CI/CD, load balancing, horizontal scaling, external secret managers, etc.) unless a task below explicitly says to. Do not invent features not listed here.

---

## 1. Project Overview

**Purpose:** ValiGuard AI is an intelligent security dashboard for QIE Blockchain validators. It combines (a) automated validator node orchestration, (b) an AI-driven anomaly-detection layer that scores cross-chain bridge transactions 0–100 using an unsupervised Isolation Forest model, and (c) a unified Next.js dashboard showing node health and color-coded security alerts. The goal is to move validators from "passive signers" to "active security guardians" with semantic visibility into transaction risk.

**Current implementation status:** The project has two parallel tracks that were never merged:
- A working, real-RPC-backed **node orchestration and Flask API** (`backend/app.py`) that uses **in-memory Python lists** for storage and **`random.uniform()` placeholders** for all anomaly/ML scoring.
- A separately built, independently tested **SQLAlchemy database layer** (`backend/database/`) that matches the documented ERD closely, plus a set of DB-integrated Flask route *examples* living only in `docs/DATABASE_FLASK_EXAMPLES.py` — never imported into the live app.

**Estimated completion (against documented Phase 1 + Phase 2 scope):** ~50–55%.

**Overall objective of this guide:** Wire the existing, working pieces together; replace placeholder/random logic with the documented Isolation Forest pipeline; close the authentication gap; add the missing ingestion loop and WebSocket layer; and bring the dashboard, API, and database into a single consistent system that matches Chapters 1–4 of the Phase 1 documentation.

---

## 2. Current State

### 2.1 Completed Features (do not rebuild — reuse/extend only)
- **Node orchestration**: `backend/qie_setup_manager.py` (`QIESetupManager`), `backend/qie_validator_manager.py`, `backend/qie_node_manager.py` (`QIENodeManager`), plus shell scripts in `scripts/` (`install_qie.sh`, `init_qie_node.sh`, `configure_qie_node.sh`, `start_qie_node.sh`, `run_validator_setup.sh`, `create_wallet.sh`, `verify_qie_setup.sh`). Satisfies FR-01, FR-02.
- **Node sync/health reporting**: `QIENodeManager.check_node_health()`, `get_node_status()`, exposed at `GET /api/v1/qie/node/status`. Satisfies FR-03.
- **Database schema**: `backend/database/models.py` — `Bridge`, `Transaction`, `AnomalyDetection`, `Alert`, `Validator` models, matching the ERD/Data Dictionary in Doc §4.2 almost field-for-field. `backend/database/db.py` (`DatabaseConfig`, `DatabaseManager`, session handling, supports SQLite and PostgreSQL). `backend/database/alembic_env.py` (migrations). `backend/manage_db.py` (CLI: init/reset/seed/export/backup/health/stats/migrate). `backend/test_database.py` (pytest suite, passes against in-memory SQLite).
- **Rate limiting**: `check_rate_limit()` + `@rate_limit` decorator in `backend/app.py`, applied to nearly all `/api/v1/*` routes. Satisfies NFR-12.
- **Structured JSON logging**: `pythonjsonlogger` configured in `backend/app.py`.
- **Dashboard shell with mock/real toggle**: `frontend/src/app/page.js` (Next.js/React) — `dataSource` state (`MOCK`/`REAL`), charts via `react-chartjs-2`/`chart.js`, matches the documented Phase 1 scope ("Next.js dashboard with mock data integration").
- **Wallet connection (client-side)**: `frontend/src/components/WalletConnect.js` uses `ethers.js` `BrowserProvider` to connect MetaMask and read balance.
- **Pydantic request validation**: `backend/app.py` — `TransactionData`, `BroadcastTransactionRequest`, `AnomalyReportRequest`, `ValidationRequest`.

### 2.2 Partially Completed Features
- **Transaction data normalization (FR-05)**: schema exists and is correct; never exercised because nothing ingests live data into it.
- **Alert generation/severity tiers (FR-09, FR-10)**: severity bucketing logic exists in `/api/v1/bridge/anomaly-score`, but operates on a random number, not a real risk score; results go to an in-memory list, not the `Alert`/`AnomalyDetection` tables.
- **Anomaly reasoning + model version storage (FR-11)**: `AnomalyDetection.reason`, `features_used`, `model_version` columns exist but are never populated by any code path.
- **Dashboard operational metrics (FR-13)**: node height/healthy are real when `dataSource === 'REAL'`; validator "voting power" is `random.randint`-generated in `/api/v1/analytics/validator-stats`, not sourced from the chain.
- **Historical alert query (FR-15, UC-05)**: `GET /api/v1/bridge/history` exists but only supports `limit`/`offset` pagination — no severity or date filtering, and it returns *transactions*, not *alerts*.
- **Wallet auth flow (UC-01)**: wallet connect works client-side; there is no backend endpoint that validates the wallet address or issues a session token/API key.

### 2.3 Missing Features
- **Isolation Forest ML pipeline (FR-07, FR-08)**: no `sklearn`/`IsolationForest` import anywhere; `scikit-learn` is only a line in `requirements.txt`. No feature-extraction module, no training script, no persisted model file.
- **Continuous ingestion worker (FR-04)**: no background poller/scheduler that watches the QIE mempool/blocks for bridge transactions.
- **Database wiring into the live app**: `backend/app.py` never imports `backend/database/models.py`; it uses `transaction_history = []` and `alerts_log = []` instead (FR-06 not actually satisfied by the running app).
- **API key authentication enforcement (NFR-11)**: `require_api_key` decorator is fully written in `backend/app.py` but is applied to **zero** routes.
- **WebSocket real-time push (Doc §1.5, §4.9 sequence/dataflow)**: no `Flask-SocketIO` or `/ws` route on the backend. A WebSocket **client** exists in `frontend_legacy/api-client.js`, but that file belongs to the retired legacy frontend, not the active Next.js app, so even the client side isn't reachable from the current dashboard.
- **Session/JWT issuance for wallet auth (UC-01)**: no endpoint validates a wallet address and returns a session token/API key.
- **Real, non-random analytics**: `/api/v1/analytics/daily-stats`, `/api/v1/analytics/model-accuracy`, `/api/v1/analytics/validator-stats` return fabricated data (`random.randint`, a static `model_metrics` dict with hardcoded accuracy/precision/recall/F1).

### 2.4 Known Implementation Issues (fix, don't just extend around them)
- **Two disconnected frontends**: `frontend/` (current, Next.js — keep and extend) vs `frontend_legacy/` (plain HTML/JS — contains the only WebSocket client code; must be ported or retired, see Phase 3).
- **`docs/SYSTEM_STATUS.md` is stale and misleading**: dated Jan 15 2025, claims "Production Ready", describes the legacy frontend and a 13-endpoint "complete" system that predates the DB layer and Next.js migration. Must be corrected or removed (Phase 5).
- **`docs/DATABASE_FLASK_EXAMPLES.py` contains a second, more complete, DB-integrated route set** (`/api/bridges`, `/api/transactions`, `/api/anomalies`, `/api/validators`, `/api/alerts`, `/api/stats/*`) that was never merged into `backend/app.py`. This is the starting point for Phase 1 work below — reuse it, don't rewrite it from scratch.
- **Duplicate/overlapping orchestration logic** across `qie_node_manager.py`, `qie_setup_manager.py`, `qie_validator_manager.py`, `quick_validator_setup.py` (repeated `get_node_status`/`get_validator_info` definitions). Do not add a fifth implementation — consolidate only if a task explicitly requires touching this area; otherwise leave as-is (out of scope per the audit's priority list).
- **Undocumented artifacts** (`nginx/*.conf`, `hardhat.config.js`) exist outside the documented tech stack. Leave untouched — not in scope for this FYP; do not build features around them.

---

## 3. Development Rules

Before implementing anything, the agent must:

1. **Reuse existing code first.** Specifically: reuse `backend/database/models.py`, `backend/database/db.py`, and the route logic already written in `docs/DATABASE_FLASK_EXAMPLES.py` — move/adapt them into `backend/app.py` rather than writing new equivalents.
2. **Do not rewrite working components.** `qie_node_manager.py`, `qie_setup_manager.py`, `qie_validator_manager.py`, `qie_wallet_manager.py`, the shell scripts in `scripts/`, and the existing dashboard layout/components in `frontend/src/app/page.js` and `frontend/src/components/WalletConnect.js` are working — extend them, don't replace them.
3. **Maintain the existing architecture**: Flask + SQLAlchemy backend, Next.js/React frontend, Tendermint RPC via `QIENodeManager`, Pydantic request validation, decorator-based cross-cutting concerns (`@rate_limit`, `@require_api_key`). Do not introduce a different web framework, ORM, or frontend framework.
4. **Follow existing coding style**: Python — type hints, docstrings, `Dict[str, Any]` return types, `success_response()`/`error_response()` wrapper pattern already used in `app.py`. JavaScript/React — the existing functional-component + hooks style in `page.js`, Tailwind CSS classes, `lucide-react` icons.
5. **Avoid duplicate functionality.** Before adding a route, class, or component, check §2.1/§2.2 above and the relevant existing file. If something already exists (even as an "example" in `docs/`), adapt it in place.
6. **Keep changes modular.** The ML scoring engine, the ingestion worker, and the WebSocket layer must each be a separate, swappable module per NFR-09 ("ML algorithm swappable without refactoring ingestion/alerting layers"). Do not hard-code the Isolation Forest logic directly inside Flask route handlers.
7. **Preserve backward compatibility.** Existing route paths (`/api/v1/qie/...`, `/api/v1/bridge/...`, `/api/v1/analytics/...`) and their current response shapes (`success_response`/`error_response` envelope) must keep working after these changes — extend response payloads, don't break existing fields the frontend already reads.
8. **Document as you go.** Create/update `docs/` markdown files for any new module (ML pipeline, ingestion worker, WebSocket layer, auth flow) per Phase instructions below. Correct or retire `docs/SYSTEM_STATUS.md` once the database wiring and API auth are done, so it stops contradicting the real state of the repo.

---

## 4. Implementation Roadmap

Work through phases in order — each phase depends on the previous one being functional.

### Phase 1 – Database Wiring (Foundation)
*Everything else depends on this. Do this first.*
- Import `backend/database/models.py` and `backend/database/db.py` into `backend/app.py`.
- Initialize a `DatabaseManager` instance at app startup (SQLite by default, PostgreSQL via env var, per existing `DatabaseConfig`).
- Replace `transaction_history = []` and `alerts_log = []` in-memory stores with real DB reads/writes using the existing `Bridge`, `Transaction`, `AnomalyDetection`, `Alert`, `Validator` models.
- Port the working route logic from `docs/DATABASE_FLASK_EXAMPLES.py` into `backend/app.py` (adapt, don't copy-paste blindly — reconcile with existing route names where they overlap, e.g. `/api/v1/bridge/history`).

**Expected outcome:** `backend/app.py` persists and reads all transactions/alerts/anomalies from the database instead of in-memory lists. `manage_db.py init` provisions the schema used by the live app.
**Dependencies:** none (this is the foundation).
**Files likely to modify:** `backend/app.py`, `backend/database/__init__.py`.
**Files likely to create:** none required (reuse `database/` package as-is).

### Phase 2 – AI Intelligence Core (Business Logic)
*Depends on Phase 1 (needs somewhere to read/write scores and reasoning).*
- Build the Isolation Forest anomaly-scoring pipeline (feature extraction + model + inference wrapper) as a standalone module.
- Replace the `random.uniform()` calls in `/api/v1/bridge/anomaly-score` and `/api/v1/bridge/validate-cross-chain` with real inference calls.
- Persist `AnomalyDetection` rows (`anomaly_score`, `confidence`, `features_used`, `model_version`, `severity`, `reason`) on every scored transaction.
- Generate `Alert` rows when thresholds are breached, with real severity tiers (Critical/High/Medium/Low) driven by the actual score, not a random number.
- Replace the hardcoded `model_metrics` dict in `/api/v1/analytics/model-accuracy` with metrics computed from the model's own evaluation (even a small synthetic/historical dataset is acceptable for FYP scope — just make it real).

**Expected outcome:** Every transaction scored by the API produces a real Isolation-Forest-derived risk score (0–100), a persisted reasoning string, and — where thresholds are breached — a real `Alert` row.
**Dependencies:** Phase 1 (DB wiring).
**Files likely to modify:** `backend/app.py`.
**Files likely to create:** `backend/ml/feature_extraction.py`, `backend/ml/anomaly_model.py`, `backend/ml/train_model.py`, `backend/ml/models/isolation_forest.joblib` (or similar persisted artifact path).

### Phase 3 – Ingestion & Real-Time Layer
*Depends on Phase 1 and Phase 2 (ingested transactions need to be scored and stored).*
- Build a background ingestion worker that polls QIE mempool/blocks via `QIENodeManager` (reuse existing RPC methods; do not duplicate them) and feeds new transactions through Phase 2's scoring pipeline, then persists them (Phase 1).
- Add a WebSocket layer (`Flask-SocketIO`) to `backend/app.py` that pushes new transactions/alerts to subscribed dashboard clients.
- Port the WebSocket **client** logic currently stranded in `frontend_legacy/api-client.js` into the active `frontend/` Next.js app (either as a small client module or inline in `page.js`), and wire the "REAL" dashboard mode to consume live pushes instead of (or in addition to) polling `fetch()`.
- Retire or clearly mark `frontend_legacy/` as unused once the port is done (see Phase 5 documentation cleanup).

**Expected outcome:** New bridge transactions are ingested automatically (no manual trigger), scored, persisted, and pushed to the dashboard in real time.
**Dependencies:** Phase 1, Phase 2.
**Files likely to modify:** `backend/app.py`, `frontend/src/app/page.js`, `requirements.txt` (add `flask-socketio`), `frontend/package.json` (add `socket.io-client` if used instead of raw WebSocket).
**Files likely to create:** `backend/ingestion/worker.py`, `backend/ingestion/__init__.py`, `frontend/src/lib/websocket.js` (or equivalent client module).

### Phase 4 – Security & Auth
*Can be done in parallel with Phase 2/3, but must land before final submission since NFR-11 is a stated requirement.*
- Apply the existing `require_api_key` decorator to every `/api/v1/*` route that should be protected (per NFR-11, "external endpoints").
- Implement the wallet-auth backend half of UC-01: an endpoint that accepts a connected wallet address, validates it, and issues a session token/API key (simple signed-token or API-key-per-wallet-record is sufficient for FYP scope — do not build full JWT infrastructure unless it's the simplest path).
- Wire `frontend/src/components/WalletConnect.js` to call this new endpoint after connecting, store the returned token, and attach it (`X-API-Key` header, matching the existing `require_api_key` check) to subsequent `fetch()` calls in `page.js`.

**Expected outcome:** API endpoints reject unauthenticated requests; the dashboard's wallet-connect flow actually produces a usable session per the documented UC-01 flow.
**Dependencies:** Phase 1 (need somewhere to store issued tokens/validator records, using the existing `Validator` model).
**Files likely to modify:** `backend/app.py`, `frontend/src/components/WalletConnect.js`, `frontend/src/app/page.js`.
**Files likely to create:** `backend/auth.py` (token issuance/validation helpers), if the logic grows beyond a few functions inline in `app.py`.

### Phase 5 – Dashboard Completion, Documentation, and Testing
*Final phase — depends on all previous phases producing real data to display/test against.*
- Add severity/date filtering to alert/transaction history endpoints and the corresponding dashboard UI controls (FR-15, UC-05).
- Replace `random.randint`-generated validator stats in `/api/v1/analytics/validator-stats` with real reads from the `Validator` table (populated via `QIENodeManager.get_validator_info()` where available).
- Update `docs/SYSTEM_STATUS.md` to reflect the actual current architecture (Next.js frontend, DB-backed API, real ML pipeline) or remove it if it can't be kept accurate — do not leave a stale "Production Ready" claim in the repo.
- Write/extend unit tests: ML pipeline (feature extraction + inference), ingestion worker (mocked RPC), new auth endpoints, and any new DB-backed routes, following the existing `pytest` conventions in `backend/test_database.py` / `backend/test_qie_node_manager.py`.
- Manual verification pass against every UC-01 through UC-05 flow end-to-end (wallet connect → orchestration → ingestion → scoring → alert → dashboard display → historical query).

**Expected outcome:** The full documented UC-01–UC-05 workflow works end-to-end against real data, with no fabricated/random values left in any endpoint the dashboard depends on, and documentation matches the implementation.
**Dependencies:** Phases 1–4.
**Files likely to modify:** `backend/app.py`, `frontend/src/app/page.js`, `docs/SYSTEM_STATUS.md`.
**Files likely to create:** `backend/test_ml_pipeline.py`, `backend/test_ingestion_worker.py`, `backend/test_auth.py`, `docs/ML_PIPELINE.md`, `docs/WEBSOCKET_INTEGRATION.md`, `docs/AUTH_FLOW.md`.

---

## 5. Detailed Task List

### Task 5.1 — Wire Database Into Live API
- **Description:** Replace in-memory `transaction_history`/`alerts_log` in `backend/app.py` with real reads/writes against `backend/database/models.py` via `DatabaseManager`.
- **Current status:** Missing (DB layer built and tested in isolation; unused by the running app).
- **Required implementation:**
  - Instantiate `DatabaseManager`/session handling at app startup (reuse `DatabaseConfig` from `backend/database/db.py`).
  - In `/api/v1/bridge/validate-cross-chain`: create/update a `Transaction` row instead of appending to `transaction_history`.
  - In `/api/v1/bridge/anomaly-score`: create an `AnomalyDetection` row linked to the `Transaction`; create an `Alert` row when the threshold is breached, instead of appending to `alerts_log`.
  - In `/api/v1/bridge/history`: query `Transaction` table (with pagination) instead of slicing the in-memory list.
  - In `/api/v1/bridge/alert`: create an `Alert` row instead of appending to `alerts_log`.
  - Ensure a `Bridge` record exists (create if missing) before attaching `Transaction` rows to it (per FK constraint in the schema).
- **Files to modify:** `backend/app.py`.
- **New files to create:** none (reuse `backend/database/` package).
- **API changes:** response payload shapes should stay the same where already consumed by the frontend; add `id`/DB fields where useful.
- **UI changes:** none required for this task alone (handled implicitly once Phase 1 lands — data becomes real instead of ephemeral).
- **Validation rules:** enforce `tx_hash` uniqueness (already a DB constraint) — return a clear 409/400 on duplicate.
- **Edge cases:** app restart should no longer wipe data (this is the point of the task — verify persistence survives a restart against SQLite file, not `:memory:`).
- **Acceptance criteria:** submitting a transaction via `/api/v1/bridge/validate-cross-chain`, restarting the Flask process, and calling `/api/v1/bridge/history` still returns the transaction.
- **Testing checklist:** extend `backend/test_database.py`-style tests to cover the new route behavior; manual `curl` smoke test of create → restart → read.
- **Dependencies:** none.
- **Priority:** Highest (blocks Phase 2–5).
- **Estimated complexity:** Medium.

### Task 5.2 — Isolation Forest Anomaly Scoring Engine
- **Description:** Implement the actual unsupervised ML pipeline described in FR-07/FR-08/Doc §1.5.2.
- **Current status:** Missing entirely (only a `requirements.txt` line).
- **Required implementation:**
  - `backend/ml/feature_extraction.py`: functions that turn a `Transaction` (volume, frequency vs. baseline, time-of-day) into a feature vector, matching the documented feature set ("volume, frequency, and temporal patterns").
  - `backend/ml/anomaly_model.py`: wraps `sklearn.ensemble.IsolationForest`; exposes `fit(historical_transactions)` and `score(transaction) -> (risk_score_0_100, confidence, reason)`.
  - `backend/ml/train_model.py`: CLI/script to train on seeded/historical data (reuse `backend/database/models.py` `SeedData` if present, or generate synthetic baseline data) and persist the model artifact.
  - Wire `anomaly_model.score()` into `/api/v1/bridge/anomaly-score` and `/api/v1/bridge/validate-cross-chain`, replacing `random.uniform()`.
  - Populate `AnomalyDetection.reason` with a human-readable string (e.g., "10x volume spike vs. 7-day baseline", matching the example in the documentation) and `model_version` with a version string/hash of the persisted model file.
- **Files to modify:** `backend/app.py`.
- **New files to create:** `backend/ml/__init__.py`, `backend/ml/feature_extraction.py`, `backend/ml/anomaly_model.py`, `backend/ml/train_model.py`.
- **API changes:** `/api/v1/bridge/anomaly-score` response should include `reason` (currently missing) alongside `anomaly_score`, `severity`, `model_confidence`.
- **UI changes:** display the new `reason` field wherever risk scores are shown in `page.js` (matches FR-11/UC-04's "reasoning" requirement).
- **Validation rules:** risk score must be clamped to [0, 100] (per FR-08/NFR/data dictionary constraint on `anomaly_score`).
- **Edge cases:** insufficient historical data for baseline (per Doc §2.2.5 "Assumption of Data Availability") — document that early false-positive rates may be higher; don't crash if the model hasn't been trained yet (fall back gracefully, log a warning).
- **Acceptance criteria:** a transaction with an artificially large `value`/off-hours timestamp scores meaningfully higher than a "normal" transaction, and the score is reproducible for the same input given a fixed trained model.
- **Testing checklist:** unit tests for `feature_extraction.py` outputs; unit tests for `anomaly_model.score()` bounds ([0,100]) and severity bucketing; integration test that `/api/v1/bridge/anomaly-score` no longer imports `random` for scoring.
- **Dependencies:** Task 5.1 (needs historical `Transaction` data to compute baselines/train against).
- **Priority:** High.
- **Estimated complexity:** High.

### Task 5.3 — Continuous Transaction Ingestion Worker
- **Description:** Implement the background process that continuously pulls mempool/confirmed transactions from QIE via Tendermint RPC (FR-04, UC-03).
- **Current status:** Missing.
- **Required implementation:**
  - `backend/ingestion/worker.py`: a loop (thread, `APScheduler` job, or simple `while True` + `time.sleep`) that calls existing `QIENodeManager` RPC methods to fetch new transactions.
  - For each new transaction: normalize into the `Transaction` schema (FR-05, reuse Task 5.1's persistence path), run it through Task 5.2's scoring pipeline, persist `AnomalyDetection`/`Alert` as needed.
  - Start the worker alongside the Flask app (e.g., on app startup in a background thread) — keep it simple; no external job queue/broker required for FYP scope.
- **Files to modify:** `backend/app.py` (start the worker on boot).
- **New files to create:** `backend/ingestion/__init__.py`, `backend/ingestion/worker.py`.
- **API changes:** none required directly, but this is what populates the data the other endpoints read.
- **UI changes:** none directly (dashboard "REAL" mode will start showing genuinely new transactions over time instead of only historical ones).
- **Validation rules:** de-duplicate by `tx_hash` (already a unique DB constraint — handle the resulting integrity error gracefully, skip/log rather than crash the loop).
- **Edge cases:** RPC endpoint temporarily unreachable — log and retry with backoff, don't kill the worker thread; empty mempool — no-op, no error.
- **Acceptance criteria:** with the worker running and a live/test QIE RPC endpoint reachable, new transactions appear in `/api/v1/bridge/history` without any manual API call.
- **Testing checklist:** unit test with a mocked `QIENodeManager` verifying the worker correctly normalizes and persists a sample transaction; verify duplicate tx_hash handling doesn't crash the loop.
- **Dependencies:** Task 5.1, Task 5.2.
- **Priority:** Medium-High (documented as core to FR-04, but explicitly deferrable to "Phase 2" in the project's own phasing language — still required for final completion).
- **Estimated complexity:** Medium.

### Task 5.4 — WebSocket Real-Time Push
- **Description:** Implement the sub-100ms real-time alert/transaction push described in Doc §1.5.4/§4.9 and referenced (client-only) in `frontend_legacy/api-client.js`.
- **Current status:** Missing on backend; stranded client-only stub in the unused legacy frontend.
- **Required implementation:**
  - Add `Flask-SocketIO` (or plain `flask-sock`) to `backend/app.py`; expose a `/ws` (or Socket.IO default) endpoint.
  - On new transaction/alert creation (from Task 5.3's worker, or from the manual scoring endpoints), emit an event to connected clients with the transaction/alert payload.
  - Port the connection logic from `frontend_legacy/api-client.js` (`connectWebSocket()`, `handleWebSocketMessage()`, reconnect-with-backoff pattern) into a new small client module inside the active `frontend/` Next.js app.
  - Wire `frontend/src/app/page.js`'s `dataSource === 'REAL'` branch to update state from incoming WebSocket messages in addition to (or instead of) the existing polling `fetch()` calls.
- **Files to modify:** `backend/app.py`, `frontend/src/app/page.js`, `requirements.txt`, `frontend/package.json`.
- **New files to create:** `frontend/src/lib/websocket.js` (client module, adapted from `frontend_legacy/api-client.js`).
- **API changes:** new WebSocket endpoint; document its message schema.
- **UI changes:** live feed updates without a manual refresh/poll interval when in REAL mode.
- **Validation rules:** none beyond existing payload shapes.
- **Edge cases:** client disconnect/reconnect (reuse the reconnect-with-timeout pattern already present in the legacy client); multiple browser tabs open simultaneously.
- **Acceptance criteria:** opening the dashboard in REAL mode and triggering a new scored transaction (via Task 5.3 or a manual API call) updates the UI without a page refresh or manual poll firing.
- **Testing checklist:** manual test with two browser windows; basic backend test that emitting an event doesn't throw when zero clients are connected.
- **Dependencies:** Task 5.1, Task 5.3 (needs real events to push).
- **Priority:** Medium (documented requirement, but functionally the dashboard already polls in REAL mode as a fallback).
- **Estimated complexity:** Medium.

### Task 5.5 — API Key Authentication Enforcement
- **Description:** Actually apply the existing `require_api_key` decorator (NFR-11).
- **Current status:** Decorator fully written, applied to zero routes.
- **Required implementation:** Add `@require_api_key` to every `/api/v1/*` route in `backend/app.py` (order decorators correctly: `@app.route(...)`, then `@require_api_key`, then `@rate_limit`, matching Flask decorator stacking conventions already implied by existing `@rate_limit` usage). Leave `/health` and dashboard-serving routes (`/`, `/dashboard`, static JS) unauthenticated, since they're not "external data" endpoints per NFR-11's own wording.
- **Files to modify:** `backend/app.py`.
- **New files to create:** none.
- **API changes:** all protected routes now require `X-API-Key` header or `api_key` query param, returning `401 INVALID_API_KEY` otherwise (behavior already implemented in the decorator — just needs to be attached).
- **UI changes:** `frontend/src/app/page.js`'s `fetchRealData()` and any other backend `fetch()` calls must attach the API key/session token (see Task 5.6) as a header.
- **Validation rules:** reuse existing decorator logic as-is.
- **Edge cases:** ensure `require_api_key` is evaluated before `rate_limit` doesn't matter functionally, but confirm both fire correctly together (test an unauthenticated + rate-limited request only triggers the 401, not a 429 first, or vice versa — pick one consistent order and keep it).
- **Acceptance criteria:** calling any protected `/api/v1/*` route without a valid key returns 401; the dashboard in REAL mode continues to work because it now sends the key.
- **Testing checklist:** unit test per protected route verifying 401 without key, 200 with valid key.
- **Dependencies:** Task 5.6 (dashboard needs a key to send — sequence these together).
- **Priority:** High (explicit NFR, currently a one-line-per-route gap).
- **Estimated complexity:** Low.

### Task 5.6 — Wallet Auth / Session Token Issuance (UC-01)
- **Description:** Implement the backend half of "Authenticate & Connect Validator Wallet" — validating the wallet address and issuing a session token/API key, per UC-01's basic flow.
- **Current status:** Missing (wallet connects client-side only; no backend validation/token issuance).
- **Required implementation:**
  - New endpoint, e.g. `POST /api/v1/auth/connect-wallet`, accepting a wallet address (and optionally a signed message for basic proof-of-ownership — keep this simple, a full signature-verification flow is optional polish, not a hard FYP requirement per the documented basic flow which only says "validates the wallet address and issues a session token/API key").
  - On success: create/update a `Validator` record (reuse existing model) keyed by wallet address, and return a token (a generated API key string is sufficient — store it against the `Validator` row or a small in-process/DB-backed token table).
  - Update `require_api_key` (Task 5.5) to also accept these issued per-wallet tokens, not just the single static `VALIGUARD_API_KEY` env var (extend, don't replace, the existing check).
- **Files to modify:** `backend/app.py`.
- **New files to create:** `backend/auth.py` (token issuance/lookup helpers) — optional, inline in `app.py` is acceptable if kept small.
- **API changes:** new `POST /api/v1/auth/connect-wallet` endpoint.
- **UI changes:** `frontend/src/components/WalletConnect.js` calls this endpoint immediately after a successful `ethers.js` connection; stores the returned token (React state, matching existing patterns in `page.js` — no `localStorage`); `page.js` attaches it to subsequent `fetch()` calls.
- **Validation rules:** wallet address format validation (basic Ethereum-style address regex/`ethers.isAddress` equivalent server-side).
- **Edge cases:** reconnecting with the same wallet should reuse/refresh the existing `Validator` record rather than creating duplicates (enforce via the existing `address` unique constraint on `Validator`).
- **Acceptance criteria:** connecting a wallet in the UI results in a token being issued and successfully used for subsequent authenticated API calls, matching UC-01's post-condition ("Secure session established; access to real-time validator telemetry... granted").
- **Testing checklist:** unit test for the endpoint (valid address → token issued; invalid address → 400); manual end-to-end test of connect → authenticated fetch succeeding.
- **Dependencies:** Task 5.1 (uses the `Validator` table).
- **Priority:** Medium-High (closes a clearly documented use case gap).
- **Estimated complexity:** Medium.

### Task 5.7 — Historical Alert Filtering (FR-15, UC-05)
- **Description:** Add severity/date filtering to alert history queries, and an endpoint that actually returns *alerts* (not just transactions).
- **Current status:** Partial — `/api/v1/bridge/history` returns paginated transactions with no filters; no dedicated alert-history endpoint.
- **Required implementation:**
  - New/extended endpoint, e.g. `GET /api/v1/bridge/alerts` supporting `severity` and `date_from`/`date_to` query params, querying the `Alert` table (now real, per Task 5.1).
  - Include the associated `Transaction` and `AnomalyDetection.reason` in the response (per UC-05's documented post-condition: "operator views the historical anomaly data" including reasoning).
- **Files to modify:** `backend/app.py`.
- **New files to create:** none.
- **API changes:** new query parameters as above; document them.
- **UI changes:** add severity/date filter controls to the dashboard's history/alerts view in `page.js`.
- **Validation rules:** validate `severity` against the enum (`low`/`medium`/`high`/`critical`); validate date parsing, return 400 on malformed input.
- **Edge cases:** no results matching filters → return an empty list with 200, not an error.
- **Acceptance criteria:** filtering by `severity=critical` returns only critical alerts; filtering by date range returns only alerts in that window.
- **Testing checklist:** unit tests per filter combination (severity only, date only, both, neither).
- **Dependencies:** Task 5.1, Task 5.2 (needs real severities to filter on).
- **Priority:** Medium.
- **Estimated complexity:** Low-Medium.

### Task 5.8 — Real Validator/Analytics Data
- **Description:** Replace fabricated `random.randint`/hardcoded values in the analytics endpoints with real data.
- **Current status:** Missing (all three analytics endpoints are synthetic).
- **Required implementation:**
  - `/api/v1/analytics/validator-stats`: query the `Validator` table (populated via `QIENodeManager.get_validator_info()` during ingestion or a dedicated sync step) instead of `random.randint`.
  - `/api/v1/analytics/model-accuracy`: compute real metrics from the trained Isolation Forest model's evaluation run (Task 5.2's `train_model.py` should output and persist these alongside the model artifact) instead of the static `model_metrics` dict.
  - `/api/v1/analytics/daily-stats`: aggregate real `Transaction`/`Alert` counts for the given date from the database instead of `random.randint`.
- **Files to modify:** `backend/app.py`.
- **New files to create:** none (reuses Task 5.1–5.3 outputs).
- **API changes:** none in shape, only in data source.
- **UI changes:** none required (same response shape).
- **Validation rules:** handle the case of zero data gracefully (return zeros, not an error, for a day with no transactions yet).
- **Edge cases:** model not yet trained → `model-accuracy` should indicate that clearly rather than crash or silently return stale hardcoded numbers.
- **Acceptance criteria:** these three endpoints return values that change based on actual database/model state rather than being random on every call.
- **Testing checklist:** unit test verifying deterministic output given a known seeded database state.
- **Dependencies:** Task 5.1, Task 5.2, Task 5.3.
- **Priority:** Medium.
- **Estimated complexity:** Low-Medium.

### Task 5.9 — Documentation Cleanup
- **Description:** Correct stale/misleading documentation so it matches the implemented system (per Development Rule 8).
- **Current status:** `docs/SYSTEM_STATUS.md` is stale (Jan 2025, describes legacy frontend, claims "Production Ready" before DB/ML/auth existed).
- **Required implementation:** Rewrite `docs/SYSTEM_STATUS.md` to reflect the actual current state after each phase lands, or remove it and replace with the new `docs/ML_PIPELINE.md`, `docs/WEBSOCKET_INTEGRATION.md`, `docs/AUTH_FLOW.md` created in Phase 5. Note in documentation that `frontend_legacy/` is retired once Task 5.4's port is complete.
- **Files to modify:** `docs/SYSTEM_STATUS.md`.
- **New files to create:** `docs/ML_PIPELINE.md`, `docs/WEBSOCKET_INTEGRATION.md`, `docs/AUTH_FLOW.md`.
- **Priority:** Low (do last, but do not skip).
- **Estimated complexity:** Low.

---

## 6. File-Level Implementation Plan

### Existing files to update
| File | Reason |
|---|---|
| `backend/app.py` | Core integration point for all phases: DB wiring (5.1), ML scoring (5.2), ingestion worker startup (5.3), WebSocket setup (5.4), auth decorators (5.5, 5.6), new/extended endpoints (5.7, 5.8) |
| `frontend/src/app/page.js` | Attach auth headers, consume WebSocket updates, add filter UI, display `reason` field |
| `frontend/src/components/WalletConnect.js` | Call new wallet-auth endpoint after connecting, store returned token |
| `requirements.txt` | Add `flask-socketio` (or `flask-sock`) for Task 5.4; `scikit-learn`/`numpy`/`joblib` already listed but confirm pinned versions used by Task 5.2 |
| `frontend/package.json` | Add WebSocket client dependency if not using native `WebSocket` |
| `docs/SYSTEM_STATUS.md` | Correct stale claims (Task 5.9) |

### New files to create
| File | Purpose |
|---|---|
| `backend/ml/__init__.py`, `backend/ml/feature_extraction.py`, `backend/ml/anomaly_model.py`, `backend/ml/train_model.py` | Isolation Forest pipeline (Task 5.2) |
| `backend/ingestion/__init__.py`, `backend/ingestion/worker.py` | Continuous ingestion loop (Task 5.3) |
| `backend/auth.py` | Wallet-auth token issuance/lookup helpers (Task 5.6, optional split from `app.py`) |
| `frontend/src/lib/websocket.js` | WebSocket client, ported from `frontend_legacy/api-client.js` (Task 5.4) |
| `backend/test_ml_pipeline.py`, `backend/test_ingestion_worker.py`, `backend/test_auth.py` | New test coverage (Phase 5) |
| `docs/ML_PIPELINE.md`, `docs/WEBSOCKET_INTEGRATION.md`, `docs/AUTH_FLOW.md` | New-module documentation (Task 5.9) |

### Files that should remain untouched
- `backend/qie_node_manager.py`, `backend/qie_setup_manager.py`, `backend/qie_validator_manager.py`, `backend/qie_wallet_manager.py`, `backend/quick_validator_setup.py` — working orchestration logic; reuse their methods, do not refactor unless a task explicitly requires it.
- `scripts/*.sh` — working shell orchestration scripts.
- `backend/database/models.py`, `backend/database/db.py`, `backend/database/alembic_env.py`, `backend/manage_db.py` — working DB layer; reuse as-is.
- `backend/test_database.py`, `backend/test_qie_node_manager.py` — existing passing tests; extend the suite alongside them, don't modify their existing cases.
- `nginx/*.conf`, `hardhat.config.js` — out of documented scope; leave alone.
- `frontend_legacy/dashboard.html`, `frontend_legacy/dashboard.js`, `frontend_legacy/styles.css`, `frontend_legacy/contact.html` — retired; only `api-client.js`'s WebSocket logic within this folder should be read (for porting in Task 5.4), not modified in place.

### Potential refactoring opportunities (optional, low priority, do not do unless time remains after all tasks above)
- Consolidate the overlapping `get_node_status`/`get_validator_info` implementations spread across `qie_node_manager.py`, `qie_validator_manager.py`, and `quick_validator_setup.py` into a single source of truth. **Not required for FYP completion** — flagged only for awareness; do not spend time on this unless every task in §5 is already done.

---

## 7. Completion Checklist

- [ ] **Task 5.1** — Database wired into `backend/app.py`; in-memory `transaction_history`/`alerts_log` removed
- [ ] **Task 5.2** — Isolation Forest feature extraction module implemented
- [ ] **Task 5.2** — Isolation Forest model training script implemented and model artifact persisted
- [ ] **Task 5.2** — `/api/v1/bridge/anomaly-score` uses real model inference (no `random`)
- [ ] **Task 5.2** — `/api/v1/bridge/validate-cross-chain` uses real model inference (no `random`)
- [ ] **Task 5.2** — `AnomalyDetection.reason`/`model_version` populated on every scored transaction
- [ ] **Task 5.3** — Background ingestion worker implemented and started with the app
- [ ] **Task 5.3** — Ingested transactions normalized, scored, and persisted automatically
- [ ] **Task 5.4** — `Flask-SocketIO`/WebSocket endpoint added to backend
- [ ] **Task 5.4** — WebSocket client ported from `frontend_legacy` into active `frontend/` app
- [ ] **Task 5.4** — Dashboard REAL mode updates live from WebSocket events
- [ ] **Task 5.5** — `require_api_key` applied to all appropriate `/api/v1/*` routes
- [ ] **Task 5.6** — `POST /api/v1/auth/connect-wallet` endpoint implemented
- [ ] **Task 5.6** — `WalletConnect.js` calls new auth endpoint and stores token
- [ ] **Task 5.6** — Dashboard `fetch()` calls attach issued token/API key
- [ ] **Task 5.7** — Alert history endpoint supports severity/date filtering
- [ ] **Task 5.7** — Dashboard UI includes filter controls for alert history
- [ ] **Task 5.8** — `/api/v1/analytics/validator-stats` returns real data
- [ ] **Task 5.8** — `/api/v1/analytics/model-accuracy` returns real evaluation metrics
- [ ] **Task 5.8** — `/api/v1/analytics/daily-stats` returns real aggregated data
- [ ] **Task 5.9** — `docs/SYSTEM_STATUS.md` corrected to match implemented system
- [ ] **Task 5.9** — `docs/ML_PIPELINE.md`, `docs/WEBSOCKET_INTEGRATION.md`, `docs/AUTH_FLOW.md` created
- [ ] Unit tests added/passing for: DB-backed routes, ML pipeline, ingestion worker, auth endpoints
- [ ] End-to-end manual verification of UC-01 through UC-05 completed
- [ ] No route in `backend/app.py` uses `random` for anomaly/validation/analytics output
- [ ] `frontend_legacy/` confirmed fully superseded (WebSocket logic ported) and noted as retired in docs
