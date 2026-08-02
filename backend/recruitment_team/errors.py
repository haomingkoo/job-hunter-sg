"""Stable recruitment-team module errors."""


class RecruitmentTeamError(RuntimeError):
    pass


class ThreadNotFound(RecruitmentTeamError):
    pass


class ResumeVersionNotFound(RecruitmentTeamError):
    pass


class InvalidCommand(RecruitmentTeamError):
    pass


class DiscoveryUnavailable(RecruitmentTeamError):
    pass


class ServiceUnavailable(RecruitmentTeamError):
    """A configured recruitment dependency could not complete the request."""

    def __init__(self, message: str, *, failure_type: str, retryable: bool):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable


class CandidateProfilingUnavailable(ServiceUnavailable):
    pass


class RoleProfilingUnavailable(ServiceUnavailable):
    pass


class TargetAssessmentUnavailable(ServiceUnavailable):
    pass


class ConversationUnavailable(ServiceUnavailable):
    pass
