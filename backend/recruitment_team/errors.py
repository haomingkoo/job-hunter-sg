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


class CandidateProfilingUnavailable(RecruitmentTeamError):
    def __init__(self, message: str, *, failure_type: str, retryable: bool):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable


class RoleProfilingUnavailable(RecruitmentTeamError):
    def __init__(self, message: str, *, failure_type: str, retryable: bool):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable


class TargetAssessmentUnavailable(RecruitmentTeamError):
    def __init__(self, message: str, *, failure_type: str, retryable: bool):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable


class ConversationUnavailable(RecruitmentTeamError):
    """A conversational turn ended without a reply the candidate can be shown.

    Must be listed in http_routes._raise_http_error's isinstance tuple: that
    mapping matches by explicit type and ends in a bare `raise`, so a new
    *Unavailable nobody adds there becomes a 500 instead of a 503.
    """

    def __init__(self, message: str, *, failure_type: str, retryable: bool):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable
