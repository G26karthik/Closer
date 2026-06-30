# Closer — AI Deadline Execution Agent

[![CI](https://github.com/G26karthik/Closer/actions/workflows/ci.yml/badge.svg)](https://github.com/G26karthik/Closer/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi)
![Google ADK](https://img.shields.io/badge/Google%20ADK-2.x-4285F4?logo=google)
![Cloud Run](https://img.shields.io/badge/Cloud%20Run-live-34A853?logo=googlecloud)

> Describe a goal and a deadline. Closer drafts your email, blocks calendar time, waits for your approval, then marks it done.

**Live demo:** https://closer-953486236675.us-central1.run.app

Built for the **Vibe2Ship Hackathon** — June 2026.

---

## How It Works

1. You submit a goal + deadline via the dashboard
2. **Gemini 2.0 Flash** generates five task titles tailored to your goal
3. **Gmail API** drafts and sends a submission email (ADK `RetryConfig` ensures the deadline lands in the subject by attempt 2)
4. **Google Calendar API** blocks a 2-hour prep window before the deadline
5. The workflow **pauses** — a decision card appears asking you to choose between two project description drafts
6. You pick A or B; Closer resumes, records your choice, and marks all tasks complete
7. Every step streams live to the dashboard via Firestore `onSnapshot`

```
Browser (Google OAuth + Firestore onSnapshot)
        │
        │ POST /api/goal
        ▼
   FastAPI on Cloud Run
        │ BackgroundTask
        ▼
   Google ADK 2.x Workflow
   ┌────────────────────────────────────────────┐
   │  plan_goal     ► Gemini 2.0 Flash (5 task titles) │
   │  draft_email   ► Gmail API  (attempt 1 → retry)   │
   │  create_event  ► Google Calendar API              │
   │  HITL pause    ► Firestore stores interrupt        │
   │       ▲                                           │
   │       └── POST /api/goal/{id}/resume             │
   │  final_prep    ► Firestore marks done              │
   └────────────────────────────────────────────┘
        │
   Firestore (goals + subtasks collections)
        │ onSnapshot
        ▼
   Browser dashboard (live subtask updates)
```

---

## Key Design Choices

| Decision | Rationale |
|---|---|
| **Google ADK 2.x `Workflow`** | Built-in HITL (`rerun_on_resume`), `RetryConfig`, and ADK event streaming — no custom orchestration needed |
| **ADK `RetryConfig` demo** | `draft_email` intentionally fails attempt 1 (no deadline in subject) to demonstrate native retry behaviour |
| **Firestore for state** | `onSnapshot` gives zero-polling live updates; persistence survives Cloud Run cold starts |
| **Single-file frontend** | No build step, no bundler — ships in one `index.html` with Firebase SDK loaded via CDN |
| **`BackgroundTasks`** | HTTP response returns immediately with `goal_id`; the workflow runs fully async in the background |
| **`min-instances=1`** | HITL state (`_pending_hitl`) is process-local; one warm instance prevents state loss between pause and resume |
| **structlog** | JSON logs in Cloud Run (searchable in Cloud Logging), pretty-print locally — controlled via `ENVIRONMENT` env var |

---

## Getting Started

### Prerequisites

- Python 3.12+
- A GCP project with **Firestore**, **Gmail API**, and **Google Calendar API** enabled
- A Firebase project (for frontend Google OAuth)
- A **Gemini API key** (from Google AI Studio or Vertex AI)

### Local setup

```bash
git clone https://github.com/G26karthik/Closer.git
cd Closer

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate          # Windows

pip install -r requirements.txt
cp .env.example .env              # fill in your credentials
python main.py
```

Open `http://localhost:8080` in your browser.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Gemini API key |
| `FIRESTORE_PROJECT_ID` | **Yes** | GCP project ID with Firestore enabled |
| `GOOGLE_CLIENT_ID` | For OAuth | OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | For OAuth | OAuth 2.0 client secret |
| `FIREBASE_API_KEY` | For auth | Firebase Web API key |
| `FIREBASE_AUTH_DOMAIN` | For auth | Firebase auth domain (e.g. `project.firebaseapp.com`) |
| `CLOUD_RUN_SERVICE_URL` | For CORS | Public URL of this service |
| `PORT` | No | Server port (default: `8080`) |

See `.env.example` for the full template with comments.

---

## API Reference

### `GET /health`
Health check. Returns `{"status": "ok"}`. Used by Cloud Run readiness probe.

### `GET /`
Serves the dashboard SPA with Firebase config injected at runtime.

### `POST /api/goal`
Start a new goal workflow.

**Request body:**
```json
{
  "goal": "Submit my hackathon project",
  "deadline": "2026-06-30T23:59:00Z",
  "user_id": "alice",
  "user_email": "alice@example.com",
  "access_token": "<google-oauth-access-token>"
}
```

**Response:** `{"goal_id": "<uuid>"}`

The workflow runs asynchronously. Listen to `goals/{goal_id}` and `goals/{goal_id}/subtasks` in Firestore for live status.

**Validation:** `goal` is 1–500 chars; `deadline` is 1–50 chars; `access_token` up to 4096 chars.

### `POST /api/goal/{goal_id}/resume`
Resume a workflow paused at the HITL decision step.

**Request body:** `{"choice": "A"}` — must be `"A"` or `"B"`.

**Response:** `{"status": "resuming"}`

**Errors:** `404` if no pending HITL interrupt exists for this `goal_id`.

---

## Project Structure

```
closer/
├── api.py                    # FastAPI app — endpoints, HITL state dict, background tasks
├── main.py                   # Local dev entry point (uvicorn with reload)
├── config.py                 # Env var validation + typed cfg singleton
├── logger.py                 # structlog: JSON in prod, pretty-print locally
├── agent/
│   ├── workflow.py           # ADK Workflow: CloserState Pydantic model + node wiring
│   ├── nodes.py              # Node functions: plan_goal, draft_email, create_event, HITL
│   └── errors.py             # EmailValidationError — triggers ADK RetryConfig
├── tools/
│   ├── firestore_client.py   # Async Firestore: goals + subtasks CRUD
│   ├── gmail_client.py       # Gmail API: send_email + create_draft
│   └── calendar_client.py    # Calendar API: create_event
├── frontend/
│   └── index.html            # Material Design SPA — Firebase auth + live subtask dashboard
├── tests/
│   ├── conftest.py           # Pytest env bootstrap (fake GEMINI_API_KEY + FIRESTORE_PROJECT_ID)
│   ├── test_errors.py        # EmailValidationError unit tests
│   ├── test_config.py        # _require() validation unit tests
│   └── test_deadline_parse.py # Deadline ISO 8601 parsing logic tests
├── Dockerfile                # python:3.12-slim, non-root appuser
├── .dockerignore             # Excludes .env, __pycache__, .git from Docker image
├── cloudbuild.yaml           # Cloud Build: ruff lint → docker build → Cloud Run deploy
├── requirements.txt          # Runtime dependencies
├── .env.example              # Local dev credentials template
└── .github/
    ├── workflows/ci.yml      # GitHub Actions: ruff + pyright + pytest on every push/PR
    └── dependabot.yml        # Weekly automated pip + Docker dependency updates
```

---

## Running Tests

```bash
pip install pytest
pytest --tb=short -v
```

Tests run against fake credentials (set in `tests/conftest.py`) — no GCP account needed.

### CI

Every push to `main` triggers the GitHub Actions workflow:

1. `pip install -r requirements.txt` — install all deps
2. `ruff check .` — linting
3. `pyright --pythonversion 3.12 .` — static type checking
4. `pytest --tb=short` — unit tests

---

## Deploying

Uses **Cloud Build** with substitution variables so secrets never touch the repository:

```bash
gcloud builds submit \
  --substitutions \
    _GEMINI_API_KEY=YOUR_KEY,\
    _GOOGLE_CLIENT_ID=YOUR_ID,\
    _GOOGLE_CLIENT_SECRET=YOUR_SECRET,\
    _FIREBASE_API_KEY=YOUR_FIREBASE_KEY,\
    _CLOUD_RUN_SERVICE_URL=https://your-service.run.app
```

See `cloudbuild.yaml` for the full lint → build → push → deploy spec.

---

## Known Constraints

| Constraint | Detail |
|---|---|
| **HITL state is process-local** | `_pending_hitl` dict is lost on restart or scale-out. Safe with `--min-instances=1`. Move to Firestore to support multiple instances. |
| **CORS is open** | `allow_origins=["*"]` is intentional for the demo deployment. Restrict to `CLOUD_RUN_SERVICE_URL` before multi-tenant use. |
| **`access_token` in request body** | Acceptable for short-lived demo tokens. Use `Authorization: Bearer` header for persistent sessions. |
| **No workflow integration tests** | The Cloud Run deployment is the integration test for the full ADK workflow. Unit tests cover pure logic only. |
| **Dependency ranges, not pins** | `requirements.txt` uses `>=` ranges. Run `pip freeze > requirements.lock` for fully reproducible production builds. |

---

## Stack

| Layer | Technology |
|---|---|
| AI orchestration | Google ADK 2.x `Workflow` |
| LLM | Gemini 2.0 Flash |
| API server | FastAPI + uvicorn |
| Database | Firestore (Async) |
| Email | Gmail API (OAuth2) |
| Calendar | Google Calendar API (OAuth2) |
| Frontend auth | Firebase Google Sign-In |
| Logging | structlog |
| Container | Docker (python:3.12-slim) |
| Hosting | Google Cloud Run |
| CI | GitHub Actions |

---

## License

MIT
