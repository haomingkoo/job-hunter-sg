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

    def __init__(self, message: str, *, decision: RecoveryDecision):
        super().__init__(message)
        self.failure_type = decision.failure_type
        self.failure_code = decision.failure_code
        self.retryable = decision.retryable
        self.recovery_action = decision.recovery_action
        self.retry_after_seconds = decision.retry_after_seconds
        self.decision = decision


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
