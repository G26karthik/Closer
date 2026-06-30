"""
@file nodes.py
@description ADK 2.x Workflow FunctionNode functions for Closer.
             Each async function maps 1-to-1 to a node in the workflow graph.
             ADK binds parameters from ctx.state by matching field names to
             CloserState attributes.
@module closer.agent.nodes
"""
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

# NOTE: gemini-2.0-flash is the stable production model for ADK 2.x as of the
# initial deployment. Update this constant (not scattered call sites) if the
# project migrates to a newer model.
_GEMINI_MODEL = "gemini-2.0-flash"

# Fixed subtask schema — Gemini only customises the `title` field.
# Structured as a list of dicts so the shape is self-documenting and
# eliminates three parallel lists that had to stay in sync.
_SUBTASK_TEMPLATES: list[dict[str, Any]] = [
    {"id": "draft_email",             "type": "email",    "needsHuman": False},
    {"id": "create_calendar_event",   "type": "calendar", "needsHuman": False},
    {"id": "validate_draft",          "type": "validate", "needsHuman": False},
    {"id": "request_human_decision",  "type": "decision", "needsHuman": True},
    {"id": "final_prep",              "type": "misc",     "needsHuman": False},
]

# Block this many hours before the deadline for the calendar prep event.
_PREP_WINDOW_HOURS = 2


# ---------------------------------------------------------------------------
# Node 1: Plan the goal using Gemini
# ---------------------------------------------------------------------------

async def plan_goal(
    ctx: Context,
    goal: str,
    deadline: str,
    goal_id: str,
) -> None:
    """Use Gemini to generate task titles, then write five fixed-schema subtasks to Firestore.

    The fixed IDs, types, and needsHuman flags are enforced after Gemini returns,
    so a hallucinated schema never reaches Firestore.

    @param ctx: ADK node context with mutable state.
    @param goal: Plain-text goal description from GoalRequest.
    @param deadline: ISO 8601 deadline string.
    @param goal_id: Firestore document ID for this goal.
    """
    default_titles = [
        f"Draft submission email for {goal[:35]}",
        "Block 2h prep window before deadline",
        "Validate email contains deadline date",
        "Choose project description A or B",
        "Final checklist before submission",
    ]

    subtasks: list[dict[str, Any]] = [
        {**tmpl, "title": default_titles[i]}
        for i, tmpl in enumerate(_SUBTASK_TEMPLATES)
    ]

    prompt = f"""You are a task planner. Write 5 specific, action-oriented task titles for this goal.

Goal: {goal}
Deadline: {deadline}

Return ONLY this JSON array — keep id/type/needsHuman exactly as shown, customize only the title:
[
  {{"id": "draft_email", "title": "Draft submission email by {deadline}", "type": "email", "needsHuman": false}},
  {{"id": "create_calendar_event", "title": "Block 2h prep window before deadline", "type": "calendar", "needsHuman": false}},
  {{"id": "validate_draft", "title": "Validate email contains deadline date", "type": "validate", "needsHuman": false}},
  {{"id": "request_human_decision", "title": "Choose project description A or B", "type": "decision", "needsHuman": true}},
  {{"id": "final_prep", "title": "Final checklist before submission", "type": "misc", "needsHuman": false}}
]

Customize the title fields to be specific to: "{goal}". Return only the JSON array."""

    try:
        response = await _gemini.aio.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed: list[dict[str, Any]] = json.loads(raw)
        # Enforce fixed schema fields — only accept the title from Gemini.
        for i, tmpl in enumerate(_SUBTASK_TEMPLATES):
            if i < len(parsed):
                subtasks[i] = {**tmpl, "title": parsed[i].get("title", default_titles[i])}
    except Exception as exc:
        # LEGACY: Gemini response parsing failing silently keeps the demo moving.
        # Do not remove this fallback without adding a hard error + user feedback path.
        log.warning("plan_goal.gemini_fallback", goal_id=goal_id, error=str(exc))

    ctx.state["subtasks"] = subtasks
    await fs.create_subtasks(goal_id, subtasks)
    await fs.update_goal(goal_id, {"status": "executing"})
    log.info("plan_goal.done", goal_id=goal_id, subtask_count=len(subtasks))


# ---------------------------------------------------------------------------
# Node 2: Draft email (with ADK native retry via RetryConfig)
# ---------------------------------------------------------------------------

async def draft_email(
    ctx: Context,
    goal: str,
    deadline: str,
    goal_id: str,
    user_email: str,
    access_token: str,
) -> None:
    """Draft and send a submission email via the Gmail API.

    NOTE: Attempt 1 intentionally omits the deadline from the subject line to
    demonstrate ADK's native RetryConfig. The EmailValidationError triggers a
    second attempt that includes the deadline, which passes validation.
    This is a deliberate demo mechanic, not a bug.

    @param ctx: ADK node context. `ctx.attempt_count` is 1-indexed.
    @param goal: Plain-text goal description.
    @param deadline: ISO 8601 deadline string to include from attempt 2 onward.
    @param goal_id: Firestore document ID for subtask updates.
    @param user_email: Recipient address; falls back to 'me' (authenticated user).
    @param access_token: OAuth token with gmail.compose scope.
    @throws: EmailValidationError on attempt 1 to trigger ADK retry.
    """
    attempt = ctx.attempt_count
    log.info("draft_email.start", goal_id=goal_id, attempt=attempt)
    await fs.update_subtask(goal_id, "draft_email", {
        "status": "running",
        "retryCount": attempt,
    })

    subject = f"Submission: {goal}"
    if attempt == 1:
        body = (
            "Hi,\n\nPlease find our project submission attached.\n\n"
            "Best regards,\nThe Team"
        )
    else:
        subject = f"Submission by {deadline}: {goal}"
        body = (
            f"Hi,\n\nPlease find our project submission attached.\n\n"
            f"Submission deadline: {deadline}\n\n"
            "Best regards,\nThe Team"
        )

    if deadline not in subject:
        await fs.update_subtask(goal_id, "draft_email", {"status": "retry_pending"})
        raise EmailValidationError(
            f"Draft subject missing deadline '{deadline}' — retrying."
        )

    to_addr = user_email or "me"
    msg_id = send_email(
        access_token=access_token,
        to=to_addr,
        subject=subject,
        body=body,
    )
    ctx.state["email_draft_id"] = msg_id
    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, "draft_email", {
        "status": "done",
        "result": f"sent:{msg_id}",
        "executedAt": now,
    })
    await fs.update_subtask(goal_id, "validate_draft", {
        "status": "done",
        "result": f"Deadline '{deadline}' confirmed in subject",
        "executedAt": now,
    })
    log.info("draft_email.done", goal_id=goal_id, msg_id=msg_id)


# ---------------------------------------------------------------------------
# Node 3: Create calendar event
# ---------------------------------------------------------------------------

async def create_calendar_event(
    ctx: Context,
    goal: str,
    deadline: str,
    goal_id: str,
    access_token: str,
) -> None:
    """Create a Google Calendar event blocking time before the deadline.

    @param ctx: ADK node context.
    @param goal: Plain-text goal description used as the event summary.
    @param deadline: ISO 8601 deadline string for the event end time.
    @param goal_id: Firestore document ID for subtask updates.
    @param access_token: OAuth token with calendar.events scope.
    """
    await fs.update_subtask(goal_id, "create_calendar_event", {"status": "running"})

    try:
        if "T" in deadline:
            end_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        else:
            end_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        # Fallback: unrecognised format — block starting from now.
        log.warning("create_calendar_event.deadline_parse_failed",
                    goal_id=goal_id, deadline=deadline)
        end_dt = datetime.now(timezone.utc) + timedelta(hours=_PREP_WINDOW_HOURS)

    start_dt = end_dt - timedelta(hours=_PREP_WINDOW_HOURS)
    event_id = create_event(
        access_token=access_token,
        summary=f"DEADLINE: {goal}",
        description=f"Final prep and submission window for: {goal}",
        start_iso=start_dt.isoformat(),
        end_iso=end_dt.isoformat(),
    )
    ctx.state["calendar_event_id"] = event_id
    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, "create_calendar_event", {
        "status": "done",
        "result": f"event:{event_id}",
        "executedAt": now,
    })
    log.info("create_calendar_event.done", goal_id=goal_id, event_id=event_id)


# ---------------------------------------------------------------------------
# Node 4: HITL — choose project description (async generator)
# ---------------------------------------------------------------------------

async def request_human_decision(
    ctx: Context,
    goal_id: str,
) -> AsyncGenerator[Any, None]:
    """Pause the workflow and surface a decision card in the frontend dashboard.

    ADK calls this function twice for HITL nodes:
      - First call:  no resume input → yields RequestInput event → workflow pauses.
      - Second call: resume_inputs populated → records choice and marks tasks done.

    @param ctx: ADK node context with resume_inputs populated on the second call.
    @param goal_id: Firestore document ID for subtask and goal updates.
    @yields: RequestInput event on the first call; nothing on the second.
    """
    interrupt_id = f"hitl_project_desc_{goal_id}"

    resume = ctx.resume_inputs.get(interrupt_id)
    if resume is not None:
        choice = resume.get("choice", "A")
        ctx.state["human_decision"] = choice
        now = datetime.now(timezone.utc).isoformat()
        await fs.update_subtask(goal_id, "request_human_decision", {
            "status": "done",
            "result": f"Selected: Option {choice}",
            "needsHuman": False,
            "executedAt": now,
        })
        await fs.update_subtask(goal_id, "final_prep", {
            "status": "done",
            "result": "All tasks complete",
            "executedAt": now,
        })
        await fs.update_goal(goal_id, {"status": "done", "hitlInterruptId": None})
        log.info("request_human_decision.complete", goal_id=goal_id, choice=choice)
        return

    # First call: surface the decision card in the dashboard.
    await fs.update_subtask(goal_id, "request_human_decision", {
        "status": "needs_human",
        "needsHuman": True,
    })
    payload = {
        "options": [
            {
                "id": "A",
                "label": "Draft A",
                "text": "Closer: An AI agent that autonomously executes your deadlines.",
            },
            {
                "id": "B",
                "label": "Draft B",
                "text": (
                    "Closer clears the mechanical steps between you and done, "
                    "so the only thing left is the part that needs your judgment."
                ),
            },
        ],
        "goal_id": goal_id,
    }
    await fs.store_hitl_interrupt(goal_id, interrupt_id, payload)
    log.info("request_human_decision.waiting", goal_id=goal_id, interrupt_id=interrupt_id)

    yield create_request_input_event(
        RequestInput(  # type: ignore[call-arg]
            interrupt_id=interrupt_id,
            message="Which project description do you want submitted?",
            payload=payload,
        )
    )
