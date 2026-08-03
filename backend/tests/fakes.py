from recruitment_team.resume_edit_evidence import ResumeEditEvidenceResult


class AllowingEditEvidenceValidator:
    def validate(self, request):
        return ResumeEditEvidenceResult(supported=True, reason="Supported by the test fixture.")
