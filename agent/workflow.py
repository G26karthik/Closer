from pydantic import BaseModel

from google.adk.workflow import START, FunctionNode, RetryConfig, Workflow

from agent.errors import EmailValidationError
from agent.nodes import create_calendar_event, draft_email, plan_goal, request_human_decision


class CloserState(BaseModel):
    goal: str = ""
    deadline: str = ""
    user_id: str = ""
    user_email: str = ""
    goal_id: str = ""
    access_token: str = ""
    subtasks: list[dict] = []
    email_draft_id: str = ""
    calendar_event_id: str = ""
    human_decision: str = ""


_plan_node = FunctionNode(func=plan_goal, name="plan_goal", state_schema=CloserState)
_email_node = FunctionNode(
    func=draft_email, name="draft_email", state_schema=CloserState,
    retry_config=RetryConfig(max_attempts=2, initial_delay=1.0, exceptions=[EmailValidationError]),
)
_calendar_node = FunctionNode(func=create_calendar_event, name="create_calendar_event", state_schema=CloserState)
_hitl_node = FunctionNode(func=request_human_decision, name="request_human_decision", rerun_on_resume=True, state_schema=CloserState)

closer_workflow = Workflow(
    name="closer_workflow",
    state_schema=CloserState,
    edges=[(START, _plan_node, _email_node, _calendar_node, _hitl_node)],
)
