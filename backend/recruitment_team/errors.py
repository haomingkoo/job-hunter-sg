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
