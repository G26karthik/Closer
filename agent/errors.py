"""
@file errors.py
@description Custom exception hierarchy for the Closer agent.
             ADK's RetryConfig catches specific exception types to decide
             whether to retry a FunctionNode — keep exceptions narrow.
@module closer.agent.errors
"""


class EmailValidationError(Exception):
    """Raised when a drafted email fails validation (missing deadline date).

    Caught by ADK RetryConfig on the draft_email node to trigger an automatic
    second attempt with the deadline included in the subject.
    """


class OutputQualityError(Exception):
    """Raised when the shared evaluator (agent/nodes.py:_evaluate_output) rejects
    a specialist's output as not satisfying the goal/deadline.

    Caught by ADK RetryConfig on specialist nodes to trigger a bounded retry
    with the rejection reason fed back into the regeneration prompt.
    """
