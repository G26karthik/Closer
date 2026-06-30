import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from agent.workflow import closer_workflow
from config import cfg
from logger import configure_logging, get_logger
from tools import firestore_client as fs
from tools.firestore_client import create_goal
from google.adk.workflow.utils._workflow_hitl_utils import (
    create_request_input_response,
    get_request_input_interrupt_ids,
    has_request_input_function_call,
)

configure_logging()
log = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Closer API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

_origins = [cfg.CLOUD_RUN_SERVICE_URL] if cfg.CLOUD_RUN_SERVICE_URL else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


_session_service = InMemorySessionService()
_runner = Runner(
    node=closer_workflow, session_service=_session_service,
    app_name="closer", auto_create_session=True,
)

# NOTE: Process-local. Lost on restart or scale-out. Safe with min-instances=1.
_pending_hitl: dict[str, dict[str, str]] = {}

_MAX_GOAL_LEN = 500
_MAX_DEADLINE_LEN = 50


class GoalRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=_MAX_GOAL_LEN)
    deadline: str = Field(..., min_length=1, max_length=_MAX_DEADLINE_LEN)
    user_id: str = Field(default="demo_user", max_length=128)
    user_email: str = Field(default="", max_length=254)
    access_token: str = Field(default="", max_length=4096)


class ResumeRequest(BaseModel):
    choice: str = Field(..., pattern="^[AB]$")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def serve_frontend() -> HTMLResponse:
    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    html = frontend_path.read_text(encoding="utf-8")
    config_script = f"""<script>
window._FIREBASE_API_KEY = "{cfg.FIREBASE_API_KEY}";
window._FIREBASE_AUTH_DOMAIN = "{cfg.FIREBASE_AUTH_DOMAIN}";
window._FIREBASE_PROJECT_ID = "{cfg.FIRESTORE_PROJECT_ID}";
window._GOOGLE_CLIENT_ID = "{cfg.GOOGLE_CLIENT_ID}";
window._API_BASE = "{cfg.CLOUD_RUN_SERVICE_URL}";
</script>"""
    html = html.replace("</head>", config_script + "\n</head>", 1)
    return HTMLResponse(content=html)


@app.post("/api/goal")
@limiter.limit("5/minute")
async def start_goal(request: Request, body: GoalRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    goal_id = str(uuid.uuid4())
    log.info("goal.start", goal_id=goal_id, user_id=body.user_id)
    await create_goal(goal_id, body.goal, body.deadline, body.user_id)
    background_tasks.add_task(
        _run_workflow, goal_id=goal_id, goal=body.goal, deadline=body.deadline,
        user_id=body.user_id, user_email=body.user_email, access_token=body.access_token,
    )
    return {"goal_id": goal_id}


@app.post("/api/goal/{goal_id}/resume")
@limiter.limit("10/minute")
async def resume_goal(request: Request, goal_id: str, body: ResumeRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    pending = _pending_hitl.pop(goal_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="No pending HITL for this goal")
    log.info("goal.resume", goal_id=goal_id, choice=body.choice)
    response_part = create_request_input_response(pending["interrupt_id"], {"choice": body.choice})
    resume_content = genai_types.Content(role="user", parts=[response_part])
    background_tasks.add_task(
        _resume_workflow, goal_id=goal_id, user_id=pending["user_id"],
        session_id=pending["session_id"], resume_content=resume_content,
    )
    return {"status": "resuming"}


async def _run_workflow(goal_id: str, goal: str, deadline: str, user_id: str, user_email: str, access_token: str) -> None:
    initial_state = {
        "goal": goal, "deadline": deadline, "user_id": user_id,
        "user_email": user_email, "goal_id": goal_id, "access_token": access_token,
    }
    session = await _session_service.create_session(app_name="closer", user_id=user_id, state=initial_state)
    init_msg = genai_types.Content(role="user", parts=[genai_types.Part(text=f"Execute goal: {goal} by {deadline}")])
    try:
        async for event in _runner.run_async(user_id=user_id, session_id=session.id, new_message=init_msg):
            if has_request_input_function_call(event):
                interrupt_ids = get_request_input_interrupt_ids(event)
                if interrupt_ids:
                    _pending_hitl[goal_id] = {
                        "interrupt_id": interrupt_ids[0], "session_id": session.id, "user_id": user_id,
                    }
                log.info("goal.hitl_pause", goal_id=goal_id)
                return
    except Exception as exc:
        log.error("goal.workflow_error", goal_id=goal_id, error=str(exc), exc_info=True)
        await fs.update_goal(goal_id, {"status": "error", "error": str(exc)})
        raise


async def _resume_workflow(goal_id: str, user_id: str, session_id: str, resume_content: genai_types.Content) -> None:
    try:
        async for _ in _runner.run_async(user_id=user_id, session_id=session_id, new_message=resume_content):
            pass
        log.info("goal.complete", goal_id=goal_id)
    except Exception as exc:
        log.error("goal.resume_error", goal_id=goal_id, error=str(exc), exc_info=True)
        await fs.update_goal(goal_id, {"status": "error", "error": str(exc)})
        raise
