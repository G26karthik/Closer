import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

from google import genai
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput
from google.adk.workflow.utils._workflow_hitl_utils import create_request_input_event

from agent.errors import EmailValidationError
from config import cfg
from logger import get_logger
from tools import firestore_client as fs
from tools.calendar_client import create_event
from tools.gmail_client import send_email

log = get_logger(__name__)

_gemini = genai.Client(api_key=cfg.GEMINI_API_KEY)

# Update this constant (not scattered call sites) if the model changes.
_GEMINI_MODEL = "gemini-2.0-flash"

_SUBTASK_TEMPLATES: list[dict[str, Any]] = [
    {"id": "draft_email",            "type": "email",    "needsHuman": False},
    {"id": "create_calendar_event",  "type": "calendar", "needsHuman": False},
    {"id": "validate_draft",         "type": "validate", "needsHuman": False},
    {"id": "request_human_decision", "type": "decision", "needsHuman": True},
    {"id": "final_prep",             "type": "misc",     "needsHuman": False},
]

_PREP_WINDOW_HOURS = 2


async def plan_goal(ctx: Context, goal: str, deadline: str, goal_id: str) -> None:
    default_titles = [
        f"Draft submission email for {goal[:35]}",
        "Block 2h prep window before deadline",
        "Validate email contains deadline date",
        "Choose project description A or B",
        "Final checklist before submission",
    ]
    subtasks: list[dict[str, Any]] = [
        {**tmpl, "title": default_titles[i]} for i, tmpl in enumerate(_SUBTASK_TEMPLATES)
    ]
    prompt = f"""You are a task planner. Write 5 specific, action-oriented task titles for this goal.

Goal: {goal}
Deadline: {deadline}

Return ONLY this JSON array (keep id/type/needsHuman exactly as shown, customize only title):
[
  {{"id": "draft_email", "title": "Draft submission email by {deadline}", "type": "email", "needsHuman": false}},
  {{"id": "create_calendar_event", "title": "Block 2h prep window before deadline", "type": "calendar", "needsHuman": false}},
  {{"id": "validate_draft", "title": "Validate email contains deadline date", "type": "validate", "needsHuman": false}},
  {{"id": "request_human_decision", "title": "Choose project description A or B", "type": "decision", "needsHuman": true}},
  {{"id": "final_prep", "title": "Final checklist before submission", "type": "misc", "needsHuman": false}}
]

Customize the title fields to be specific to: "{goal}". Return only the JSON array."""

    try:
        response = await _gemini.aio.models.generate_content(model=_GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed: list[dict[str, Any]] = json.loads(raw)
        for i, tmpl in enumerate(_SUBTASK_TEMPLATES):
            if i < len(parsed):
                subtasks[i] = {**tmpl, "title": parsed[i].get("title", default_titles[i])}
    except Exception as exc:
        log.warning("plan_goal.gemini_fallback", goal_id=goal_id, error=str(exc))

    ctx.state["subtasks"] = subtasks
    await fs.create_subtasks(goal_id, subtasks)
    await fs.update_goal(goal_id, {"status": "executing"})


async def draft_email(
    ctx: Context, goal: str, deadline: str, goal_id: str, user_email: str, access_token: str,
) -> None:
    """NOTE: Attempt 1 intentionally omits deadline to demo ADK RetryConfig."""
    attempt = ctx.attempt_count
    await fs.update_subtask(goal_id, "draft_email", {"status": "running", "retryCount": attempt})

    subject = f"Submission: {goal}"
    if attempt == 1:
        body = "Hi,\n\nPlease find our project submission attached.\n\nBest regards,\nThe Team"
    else:
        subject = f"Submission by {deadline}: {goal}"
        body = f"Hi,\n\nPlease find our project submission attached.\n\nSubmission deadline: {deadline}\n\nBest regards,\nThe Team"

    if deadline not in subject:
        await fs.update_subtask(goal_id, "draft_email", {"status": "retry_pending"})
        raise EmailValidationError(f"Draft subject missing deadline '{deadline}' — retrying.")

    to_addr = user_email or "me"
    msg_id = send_email(access_token=access_token, to=to_addr, subject=subject, body=body)
    ctx.state["email_draft_id"] = msg_id
    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, "draft_email", {"status": "done", "result": f"sent:{msg_id}", "executedAt": now})
    await fs.update_subtask(goal_id, "validate_draft", {"status": "done", "result": f"Deadline '{deadline}' confirmed in subject", "executedAt": now})


async def create_calendar_event(ctx: Context, goal: str, deadline: str, goal_id: str, access_token: str) -> None:
    await fs.update_subtask(goal_id, "create_calendar_event", {"status": "running"})
    try:
        if "T" in deadline:
            end_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        else:
            end_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        log.warning("create_calendar_event.deadline_parse_failed", goal_id=goal_id, deadline=deadline)
        end_dt = datetime.now(timezone.utc) + timedelta(hours=_PREP_WINDOW_HOURS)

    start_dt = end_dt - timedelta(hours=_PREP_WINDOW_HOURS)
    event_id = create_event(
        access_token=access_token, summary=f"DEADLINE: {goal}",
        description=f"Final prep and submission window for: {goal}",
        start_iso=start_dt.isoformat(), end_iso=end_dt.isoformat(),
    )
    ctx.state["calendar_event_id"] = event_id
    await fs.update_subtask(goal_id, "create_calendar_event", {
        "status": "done", "result": f"event:{event_id}",
        "executedAt": datetime.now(timezone.utc).isoformat(),
    })


async def request_human_decision(ctx: Context, goal_id: str) -> AsyncGenerator[Any, None]:
    interrupt_id = f"hitl_project_desc_{goal_id}"
    resume = ctx.resume_inputs.get(interrupt_id)
    if resume is not None:
        choice = resume.get("choice", "A")
        ctx.state["human_decision"] = choice
        now = datetime.now(timezone.utc).isoformat()
        await fs.update_subtask(goal_id, "request_human_decision", {
            "status": "done", "result": f"Selected: Option {choice}", "needsHuman": False, "executedAt": now,
        })
        await fs.update_subtask(goal_id, "final_prep", {"status": "done", "result": "All tasks complete", "executedAt": now})
        await fs.update_goal(goal_id, {"status": "done", "hitlInterruptId": None})
        return

    await fs.update_subtask(goal_id, "request_human_decision", {"status": "needs_human", "needsHuman": True})
    payload = {
        "options": [
            {"id": "A", "label": "Draft A", "text": "Closer: An AI agent that autonomously executes your deadlines."},
            {"id": "B", "label": "Draft B", "text": "Closer clears the mechanical steps between you and done, so the only thing left is the part that needs your judgment."},
        ],
        "goal_id": goal_id,
    }
    await fs.store_hitl_interrupt(goal_id, interrupt_id, payload)
    yield create_request_input_event(RequestInput(
        interrupt_id=interrupt_id,
        message="Which project description do you want submitted?",
        payload=payload,
    ))
