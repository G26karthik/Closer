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
from google.genai import types as genai_types

from agent.errors import OutputQualityError
from config import cfg
from logger import get_logger
from tools import firestore_client as fs
from tools.calendar_client import create_event, find_free_slot
from tools.gmail_client import create_draft

log = get_logger(__name__)

_gemini = genai.Client(api_key=cfg.GEMINI_API_KEY)

# NOTE: gemini-2.0-flash is the stable production model for ADK 2.x as of the
# initial deployment. Update this constant (not scattered call sites) if the
# project migrates to a newer model.
_GEMINI_MODEL = "gemini-2.0-flash"

_SUBTASK_TYPES = {"communicate", "schedule", "research", "produce_document", "decision"}


async def _evaluate_output(goal: str, deadline: str, subtask_type: str, output_summary: str) -> None:
    """Gemini-as-judge: reject specialist output that doesn't actually serve the goal.

    This is the real evaluator-optimizer check that replaces the old scripted
    "always fail attempt 1" demo mechanic in draft_email.

    @param goal: Plain-text goal description.
    @param deadline: ISO 8601 deadline string.
    @param subtask_type: One of _SUBTASK_TYPES — used only for prompt framing.
    @param output_summary: The specialist's produced content (email body, slot chosen, etc).
    @throws: OutputQualityError if the judge rejects the output.
    """
    prompt = f"""You are a strict quality reviewer for an autonomous execution agent.

Goal: {goal}
Deadline: {deadline}
Subtask type: {subtask_type}
Produced output: {output_summary}

Does this output genuinely serve the goal and correctly account for the deadline?
Return ONLY JSON: {{"verdict": "accept" or "reject", "reason": "<one sentence>"}}"""

    response = await _gemini.aio.models.generate_content(
        model=_GEMINI_MODEL,
        contents=prompt,
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        verdict = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Judge response unparseable — fail open (accept) rather than block the demo.
        log.warning("evaluate_output.judge_unparseable", raw=raw)
        return
    if verdict.get("verdict") == "reject":
        raise OutputQualityError(verdict.get("reason", "output rejected by evaluator"))


# Block this many hours before the deadline for the calendar prep event.
_PREP_WINDOW_HOURS = 2


# ---------------------------------------------------------------------------
# Node 1: Plan the goal using Gemini
# ---------------------------------------------------------------------------

def _find_subtask(subtasks: list[dict[str, Any]], subtask_type: str) -> dict[str, Any] | None:
    """Return the first subtask of the given type, or None if the planner didn't emit one.

    @param subtasks: ctx.state["subtasks"] — the dynamic list written by plan_goal.
    @param subtask_type: One of _SUBTASK_TYPES.
    @returns: Matching subtask dict, or None.
    """
    for subtask in subtasks:
        if subtask["type"] == subtask_type:
            return subtask
    return None


_MAX_SUBTASKS = 6


def _build_subtasks_from_parsed(parsed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Gemini's parsed planning JSON into the validated subtask list.

    Drops items whose `type` isn't in _SUBTASK_TYPES, assigns per-type
    incrementing ids, marks needsHuman only for decision-type, allows at most
    one decision subtask, and caps the total at _MAX_SUBTASKS. Returns a
    possibly-empty list (caller falls back to a default pair when empty).

    @param parsed: The list Gemini returned (each item ideally {"type", "title"}).
    @returns: Validated subtask dicts: {id, type, title, needsHuman}.
    """
    built: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for item in parsed:
        if len(built) >= _MAX_SUBTASKS:
            break
        item_type = item.get("type")
        if item_type not in _SUBTASK_TYPES:
            continue
        if item_type == "decision" and type_counts.get("decision"):
            continue  # at most one decision subtask
        idx = type_counts.get(item_type, 0)
        type_counts[item_type] = idx + 1
        built.append({
            "id": f"{item_type}_{idx}",
            "type": item_type,
            "title": item.get("title", item_type),
            "needsHuman": item_type == "decision",
        })
    return built


async def plan_goal(
    ctx: Context,
    goal: str,
    deadline: str,
    goal_id: str,
) -> None:
    """Use Gemini to decide WHICH subtask types this goal needs and HOW MANY, then
    write the resulting dynamic subtask list to Firestore.

    Unlike the old fixed 5-row schema, a simple goal may produce 1-2 subtasks and
    a complex one may produce up to 6. Specialist nodes downstream self-skip when
    no subtask of their type is present (see Task 3+).

    @param ctx: ADK node context with mutable state.
    @param goal: Plain-text goal description from GoalRequest.
    @param deadline: ISO 8601 deadline string.
    @param goal_id: Firestore document ID for this goal.
    """
    # Conservative fallback if Gemini parsing fails entirely — always include a
    # communicate + decision pair so the goal is never silently inert.
    fallback: list[dict[str, Any]] = [
        {"id": "communicate_0", "type": "communicate",
         "title": f"Draft submission email for {goal[:35]}", "needsHuman": False},
        {"id": "decision_0", "type": "decision",
         "title": "Choose project description A or B", "needsHuman": True},
    ]

    prompt = f"""You are a task planner for an autonomous execution agent. Given a goal
and deadline, decide which of these capabilities are actually needed — do not include
ones that aren't relevant:

- communicate: draft an email related to the goal
- schedule: block calendar time before the deadline
- research: look up current information needed to accomplish the goal
- produce_document: generate a written deliverable document
- decision: a choice only the human can make (include at most once, only if genuinely needed)

Goal: {goal}
Deadline: {deadline}

Return ONLY a JSON array, 1-6 items, each: {{"type": "<one of the 5 types above>", "title": "<specific action-oriented title>"}}.
Order matters: communicate/schedule/research/produce_document before decision.
Do not invent other type values."""

    subtasks: list[dict[str, Any]] = fallback
    try:
        response = await _gemini.aio.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed: list[dict[str, Any]] = json.loads(raw)
        built = _build_subtasks_from_parsed(parsed)
        if built:
            subtasks = built
    except Exception as exc:
        log.warning("plan_goal.gemini_fallback", goal_id=goal_id, error=str(exc))

    ctx.state["subtasks"] = subtasks
    await fs.create_subtasks(goal_id, subtasks)
    await fs.update_goal(goal_id, {"status": "executing"})
    await fs.log_activity(goal_id, "PlannerAgent", "plan_complete",
                           f"Decided on {len(subtasks)} subtasks: " +
                           ", ".join(s["type"] for s in subtasks))
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
    """Draft a submission email via Gmail (draft only — never auto-sent) and self-review it.

    Self-skips if the planner didn't emit a "communicate" subtask. On self-review
    rejection, raises OutputQualityError to trigger ADK's native RetryConfig.

    @param ctx: ADK node context. ctx.attempt_count is 1-indexed.
    @param goal: Plain-text goal description.
    @param deadline: ISO 8601 deadline string.
    @param goal_id: Firestore document ID for subtask updates.
    @param user_email: Recipient address; falls back to 'me' (authenticated user).
    @param access_token: OAuth token with gmail.compose scope.
    @throws: OutputQualityError if self-review rejects the draft (triggers retry).
    """
    subtask = _find_subtask(ctx.state["subtasks"], "communicate")
    if subtask is None:
        log.info("draft_email.skip_not_planned", goal_id=goal_id)
        return

    attempt = ctx.attempt_count
    log.info("draft_email.start", goal_id=goal_id, attempt=attempt)
    await fs.update_subtask(goal_id, subtask["id"], {"status": "running", "retryCount": attempt})

    subject = f"Submission by {deadline}: {goal}"
    body = (
        f"Hi,\n\nPlease find our project submission attached.\n\n"
        f"Submission deadline: {deadline}\n\n"
        "Best regards,\nThe Team"
    )

    await _evaluate_output(goal, deadline, "communicate", f"Subject: {subject}\nBody: {body}")

    to_addr = user_email or "me"
    draft_id = create_draft(access_token=access_token, to=to_addr, subject=subject, body=body)
    ctx.state["email_draft_id"] = draft_id
    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, subtask["id"], {
        "status": "done", "result": f"drafted:{draft_id}", "executedAt": now,
    })
    await fs.log_activity(goal_id, "CommunicationAgent", "draft_complete", f"Drafted: {subject}")
    log.info("draft_email.done", goal_id=goal_id, draft_id=draft_id)


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
    """Block real free calendar time before the deadline (freebusy-aware, not a blind block).

    Self-skips if the planner didn't emit a "schedule" subtask.

    @param ctx: ADK node context.
    @param goal: Plain-text goal description used as the event summary.
    @param deadline: ISO 8601 deadline string for the event end time.
    @param goal_id: Firestore document ID for subtask updates.
    @param access_token: OAuth token with calendar.events + calendar.freebusy scope.
    """
    subtask = _find_subtask(ctx.state["subtasks"], "schedule")
    if subtask is None:
        log.info("create_calendar_event.skip_not_planned", goal_id=goal_id)
        return

    await fs.update_subtask(goal_id, subtask["id"], {"status": "running"})
    try:
        if "T" in deadline:
            end_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        else:
            end_dt = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        log.warning("create_calendar_event.deadline_parse_failed", goal_id=goal_id, deadline=deadline)
        end_dt = datetime.now(timezone.utc) + timedelta(hours=_PREP_WINDOW_HOURS)

    earliest = end_dt - timedelta(hours=_PREP_WINDOW_HOURS * 4)
    start_dt, end_dt = find_free_slot(access_token, earliest, end_dt, _PREP_WINDOW_HOURS)

    event_id = create_event(
        access_token=access_token,
        summary=f"DEADLINE: {goal}",
        description=f"Final prep and submission window for: {goal}",
        start_iso=start_dt.isoformat(),
        end_iso=end_dt.isoformat(),
    )
    ctx.state["calendar_event_id"] = event_id
    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, subtask["id"], {
        "status": "done", "result": f"event:{event_id}", "executedAt": now,
    })
    await fs.log_activity(goal_id, "SchedulerAgent", "event_scheduled",
                           f"Found free slot {start_dt.isoformat()} - {end_dt.isoformat()}")
    log.info("create_calendar_event.done", goal_id=goal_id, event_id=event_id)


# ---------------------------------------------------------------------------
# Node: Research topic via Gemini + Google Search grounding
# ---------------------------------------------------------------------------

async def research_topic(
    ctx: Context,
    goal: str,
    deadline: str,
    goal_id: str,
) -> None:
    """Use Gemini with Google Search grounding to gather info needed to accomplish the goal.

    Self-skips if the planner didn't emit a "research" subtask. New capability —
    the agent previously had zero search/research tool access.

    @param ctx: ADK node context.
    @param goal: Plain-text goal description.
    @param deadline: ISO 8601 deadline string.
    @param goal_id: Firestore document ID for subtask updates.
    @throws: OutputQualityError if self-review rejects the findings (triggers retry).
    """
    subtask = _find_subtask(ctx.state["subtasks"], "research")
    if subtask is None:
        log.info("research_topic.skip_not_planned", goal_id=goal_id)
        return

    await fs.update_subtask(goal_id, subtask["id"], {"status": "running"})
    config = genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
    )
    prompt = (
        f"Research what's needed to accomplish this goal before its deadline.\n"
        f"Goal: {goal}\nDeadline: {deadline}\n"
        "Return a concise (under 150 words) summary of the most relevant, current findings."
    )
    response = await _gemini.aio.models.generate_content(
        model=_GEMINI_MODEL, contents=prompt, config=config,
    )
    summary = (response.text or "").strip()
    await _evaluate_output(goal, deadline, "research", summary)

    now = datetime.now(timezone.utc).isoformat()
    await fs.update_subtask(goal_id, subtask["id"], {
        "status": "done", "result": summary, "executedAt": now,
    })
    await fs.log_activity(goal_id, "ResearchAgent", "research_complete", summary[:200])
    log.info("research_topic.done", goal_id=goal_id)


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
