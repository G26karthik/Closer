from typing import Any

from google.cloud import firestore

from config import cfg

_GOALS_COLLECTION = "goals"
_SUBTASKS_COLLECTION = "subtasks"

_db: firestore.AsyncClient | None = None


def _get_db() -> firestore.AsyncClient:
    global _db
    if _db is None:
        _db = firestore.AsyncClient(project=cfg.FIRESTORE_PROJECT_ID)
    return _db


async def create_goal(goal_id: str, goal: str, deadline: str, user_id: str) -> None:
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).set({
        "text": goal, "deadline": deadline, "userId": user_id,
        "createdAt": firestore.SERVER_TIMESTAMP, "status": "planning",
    })


async def create_subtasks(goal_id: str, subtasks: list[dict[str, Any]]) -> None:
    db = _get_db()
    batch = db.batch()
    for subtask in subtasks:
        ref = db.collection(_GOALS_COLLECTION).document(goal_id).collection(_SUBTASKS_COLLECTION).document(subtask["id"])
        batch.set(ref, {
            "title": subtask["title"], "type": subtask["type"], "status": "pending",
            "retryCount": 0, "needsHuman": subtask.get("needsHuman", False),
            "executedAt": None, "result": None,
        })
    await batch.commit()


async def update_subtask(goal_id: str, subtask_id: str, data: dict[str, Any]) -> None:
    db = _get_db()
    ref = db.collection(_GOALS_COLLECTION).document(goal_id).collection(_SUBTASKS_COLLECTION).document(subtask_id)
    await ref.set(data, merge=True)


async def update_goal(goal_id: str, data: dict[str, Any]) -> None:
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).update(data)


async def store_hitl_interrupt(goal_id: str, interrupt_id: str, payload: dict[str, Any]) -> None:
    db = _get_db()
    await db.collection(_GOALS_COLLECTION).document(goal_id).update({
        "hitlInterruptId": interrupt_id, "hitlPayload": payload, "status": "awaiting_human",
    })
