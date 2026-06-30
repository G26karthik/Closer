# Closer

AI deadline execution agent built for the Vibe2Ship hackathon (June 2026).

Describe a goal. Closer drafts emails, creates calendar events, and handles decisions — autonomously, using Google ADK 2.x + Gemini 2.0 Flash.

**Live:** https://closer-953486236675.us-central1.run.app

## Stack

- **Backend:** FastAPI + Google ADK 2.x Workflow (HITL, RetryConfig)
- **AI:** Gemini 2.0 Flash
- **Data:** Firestore (real-time streaming)
- **Auth:** Firebase Google OAuth2
- **Integrations:** Gmail API, Google Calendar API
- **Deploy:** Cloud Run via Cloud Build

## Setup

```bash
cp .env.example .env  # fill in your keys
pip install -r requirements.txt
python main.py
```

See `cloudbuild.yaml` for production deployment.
