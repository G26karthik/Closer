"""
@file firestore_client.py
@description Async Firestore helpers for the Closer task graph.
@module closer.tools.firestore_client

Collections:
  goals/{goalId}                — goal document
  goals/{goalId}/subtasks/{id}  — subtask documents
  goals/{goalId}/activity/{id}  — agent-decision event log (Activity Feed)
"""
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from config import cfg
from tools.time_utils import parse_deadline

# Collection name constants — update here if the schema changes.
_GOALS_COLLECTION = "goals"
_SUBTASKS_COLLECTION = "subtasks"
_ACTIVITY_COLLECTION = "activity"

_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    """Return (or lazily create) the shared Firestore async client.

    @returns: Singleton AsyncClient connected to the configured GCP project.
    """
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project=cfg.FIRESTORE_PROJECT_ID)
    return _db


async def create_goal(goal_id: str, goal: str, deadline: str, user_id: str) -> None:
    """Create a new goal document in Firestore with status 'planning'.

    @param goal_id: UUID string used as the Firestore document ID.
    @param goal: Plain-text goal description.
    @param deadline: ISO 8601 deadline string.
    @param user_id: Caller's user ID stored for Firestore security rule checks.
    """
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).set({
        "text": goal,
        "deadline": deadline,
        "userId": user_id,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "status": "planning",
    })


async def create_subtasks(goal_id: str, subtasks: list[dict[str, Any]]) -> None:
    """Write all subtask documents for a goal in a single batch commit.

    @param goal_id: Parent goal document ID.
    @param subtasks: List of subtask dicts with keys: id, title, type, needsHuman.
    """
    db = _get_db()
    batch = db.batch()
    for subtask in subtasks:
        ref = (
            db.collection(_GOALS_COLLECTION).document(goal_id)
            .collection(_SUBTASKS_COLLECTION).document(subtask["id"])
        )
        batch.set(ref, {
            "title": subtask["title"],
            "type": subtask["type"],
            "status": "pending",
            "retryCount": 0,
            "needsHuman": subtask.get("needsHuman", False),
            "executedAt": None,
            "result": None,
        })
    await batch.commit()


async def update_subtask(goal_id: str, subtask_id: str, data: dict[str, Any]) -> None:
    """Merge-update a subtask document.

    @param goal_id: Parent goal document ID.
    @param subtask_id: Subtask document ID (one of the fixed IDs in nodes.py).
    @param data: Fields to merge into the existing document.
    """
    db = _get_db()
    ref = (
        db.collection(_GOALS_COLLECTION).document(goal_id)
        .collection(_SUBTASKS_COLLECTION).document(subtask_id)
    )
    await ref.set(data, merge=True)


async def update_goal(goal_id: str, data: dict[str, Any]) -> None:
    """Update specific fields on a goal document.

    @param goal_id: Goal document ID.
    @param data: Fields to update (uses Firestore update, not set — document must exist).
    """
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).update(data)


async def store_hitl_interrupt(goal_id: str, interrupt_id: str, payload: dict[str, Any]) -> None:
    """Store HITL interrupt metadata on the goal document for the frontend to read.

    @param goal_id: Goal document ID.
    @param interrupt_id: ADK interrupt ID returned by create_request_input_event.
    @param payload: Decision options to render in the dashboard decision card.
    """
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).update({
        "hitlInterruptId": interrupt_id,
        "hitlPayload": payload,
        "status": "awaiting_human",
    })


async def log_activity(goal_id: str, actor: str, decision: str, reason: str) -> None:
    """Append a structured agent-decision event for the frontend Activity Feed.

    Mirrors the structlog call already made at each node's call site — same
    data, two sinks (structured logs for ops, Firestore for the live UI).

    @param goal_id: Parent goal document ID.
    @param actor: Which agent made the decision (e.g. "PlannerAgent", "SchedulerAgent").
    @param decision: Short machine-readable decision tag (e.g. "plan_complete").
    @param reason: Human-readable one-line explanation shown in the UI.
    """
    db = _get_db()
    ref = (
        db.collection(_GOALS_COLLECTION).document(goal_id)
        .collection(_ACTIVITY_COLLECTION)
    )
    await ref.add({
        "actor": actor,
        "decision": decision,
        "reason": reason,
        "ts": firestore.SERVER_TIMESTAMP,
    })


async def list_active_goals_for_monitor() -> list[dict[str, Any]]:
    """Return all goal docs (with their IDs) still in-flight, for the proactive monitor sweep.

    Sorted by ascending time-to-deadline so the caller processes the most
    time-critical goals first. Goals with an unparseable or missing deadline
    sort last rather than raising.

    @returns: List of dicts, each containing all goal fields plus `id`, sorted by priority.
    """
    db = _get_db()
    query = db.collection(_GOALS_COLLECTION).where(
        filter=firestore.FieldFilter("status", "in", ["executing", "awaiting_human"])
    )
    docs = [doc async for doc in query.stream()]
    goals = [{**doc.to_dict(), "id": doc.id} for doc in docs]
    _NO_DEADLINE = datetime.max.replace(tzinfo=timezone.utc)
    goals.sort(key=lambda g: parse_deadline(g.get("deadline")) or _NO_DEADLINE)
    return goals
