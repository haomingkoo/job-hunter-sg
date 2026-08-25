"""Stable recruitment-team module errors."""

from .recovery import RecoveryDecision, classify_failure


class RecruitmentTeamError(RuntimeError):
    pass


class ThreadNotFound(RecruitmentTeamError):
    pass


class ResumeVersionNotFound(RecruitmentTeamError):
    pass


class InvalidCommand(RecruitmentTeamError):
    pass


class ServiceUnavailable(RecruitmentTeamError):
    """A recruitment dependency failed with one deterministic recovery decision."""

    def __init__(self, message: str, *, decision: RecoveryDecision, detail: dict | None = None):
        super().__init__(message)
        self.failure_type = decision.failure_type
        self.failure_code = decision.failure_code
        self.retryable = decision.retryable
        self.recovery_action = decision.recovery_action
        self.retry_after_seconds = decision.retry_after_seconds
        self.decision = decision
        self.detail = dict(detail or {})


class RunConcurrencyExceeded(ServiceUnavailable):
    """A user or process already occupies the configured model-run capacity."""

    def __init__(self, message: str):
        super().__init__(
            message,
            decision=classify_failure("capacity_exceeded", attempts_remaining=True),
        )


class DiscoveryUnavailable(ServiceUnavailable):
    pass


class CandidateProfilingUnavailable(ServiceUnavailable):
    pass


class RoleProfilingUnavailable(ServiceUnavailable):
    pass


class TargetAssessmentUnavailable(ServiceUnavailable):
    pass


class ConversationUnavailable(ServiceUnavailable):
    pass


def safe_terminal_error_payload(error: BaseException) -> dict:
    """Return the user-safe terminal payload, preferring its durable decision."""

    durable = getattr(error, "recruitment_terminal_payload", None)
    if isinstance(durable, dict):
        return durable
    payload = {
        "error_type": type(error).__name__,
        "message": (
            str(error)
            if isinstance(error, RecruitmentTeamError)
            else "The recruitment team could not complete this turn."
        ),
    }
    if isinstance(error, ServiceUnavailable):
        payload.update({
            "failure_type": error.failure_type,
            "failure_code": error.failure_code,
            "retryable": error.retryable,
            "recovery_action": error.recovery_action,
        })
        if error.retry_after_seconds is not None:
            payload["retry_after_seconds"] = error.retry_after_seconds
        payload.update({
            key: value
            for key, value in error.detail.items()
            if key in {
                "attempted_stage",
                "correction_scope",
                "partial_artifact_id",
                "alternatives",
                "tool_name",
            }
        })
        if error.detail.get("validation_code"):
            # Import lazily so the stable error types do not depend on the
            # role-profile persistence module during import.
            from .role_profile_store import public_role_validation_code

            payload["validation_code"] = public_role_validation_code(
                str(error.detail["validation_code"])
            )
    return payload
