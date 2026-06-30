"""
@file monitor.py
@description Proactive deadline-risk monitor. Runs outside the ADK Runner/session
             lifecycle — direct Firestore + Gemini + tool client calls only, so it
             never re-enters a paused HITL workflow session. Triggered by Cloud
             Scheduler hitting POST /internal/tick on a fixed interval.
@module closer.agent.monitor
"""
from datetime import datetime, timedelta, timezone

from google import genai

from config import cfg
from logger import get_logger
from tools import firestore_client as fs
from tools.time_utils import parse_deadline

log = get_logger(__name__)

_gemini = genai.Client(api_key=cfg.GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-3.5-flash"

# A goal is "at risk" if less than this many hours remain before its deadline
# and it hasn't reached a terminal status yet.
_RISK_WINDOW_HOURS = 4

# Minimum gap between monitor interventions on the same goal. Without this, every
# scheduler tick re-fires Gemini and spams the activity feed for a goal that stays
# at-risk for hours. Bounded stop condition, not open-ended retry.
_MIN_RECHECK_MINUTES = 30


def _is_at_risk(goal: dict) -> bool:
    """Pure function: does this goal need monitor intervention right now?

    @param goal: Firestore goal doc dict with at least `deadline` and `status`.
    @returns: True if deadline is within _RISK_WINDOW_HOURS and goal isn't done/error.
    """
    if goal.get("status") in ("done", "error"):
        return False
    deadline = parse_deadline(goal.get("deadline"))
    if deadline is None:
        return False
    return deadline - datetime.now(timezone.utc) < timedelta(hours=_RISK_WINDOW_HOURS)


async def check_and_intervene(goal_id: str, goal: dict) -> None:
    """Re-evaluate one at-risk goal and decide an autonomous intervention.

    Isolated per-goal: a failure here must not block other goals' ticks (caller
    in api.py wraps each call in its own try/except).

    @param goal_id: Firestore goal document ID.
    @param goal: Already-fetched goal doc dict (avoids a second read in the caller's loop).
    """
    if not _is_at_risk(goal):
        return

    last_check = parse_deadline(goal.get("lastMonitorCheck"))
    if last_check is not None and datetime.now(timezone.utc) - last_check < timedelta(minutes=_MIN_RECHECK_MINUTES):
        return  # already intervened recently — avoid duplicate Gemini calls and activity-feed spam

    prompt = f"""An autonomous deadline-management agent is monitoring this goal, which is
running behind schedule.

Goal: {goal.get('text', '')}
Deadline: {goal.get('deadline', '')}
Current status: {goal.get('status', '')}

In one sentence, state the single most useful intervention right now (e.g. "send a
reminder escalation", "the deadline is essentially unreachable, flag for human review").
Return ONLY that sentence."""

    response = await _gemini.aio.models.generate_content(model=_GEMINI_MODEL, contents=prompt)
    decision = (response.text or "").strip()

    await fs.update_goal(goal_id, {
        "riskState": "at_risk",
        "lastMonitorCheck": datetime.now(timezone.utc).isoformat(),
    })
    await fs.log_activity(goal_id, "MonitorAgent", "intervention", decision)
    log.info("monitor.intervened", goal_id=goal_id, decision=decision)
