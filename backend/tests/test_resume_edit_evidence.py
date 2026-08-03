from langchain_core.messages import AIMessage

from recruitment_team.resume_edit_evidence import (
    LangChainResumeEditEvidenceValidator,
    ResumeEditEvidenceRequest,
)


class _Model:
    def __init__(self, payload):
        self.payload = payload
        self.messages = None

    def bind_tools(self, tools, **kwargs):
        assert [tool.name for tool in tools] == ["submit_resume_edit_evidence_verdict"]
        assert kwargs["tool_choice"] == "submit_resume_edit_evidence_verdict"
        return self

    def invoke(self, messages):
        self.messages = messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "submit_resume_edit_evidence_verdict",
                    "args": self.payload,
                    "id": "edit-verdict-1",
                    "type": "tool_call",
                }
            ],
        )


def _request():
    return ResumeEditEvidenceRequest(
        original="Mentored 12 engineers in 8D and 5 Why methodologies.",
        supporting_evidence="",
        rewrite=(
            "Mentored 12 engineers in 8D and 5 Why methodologies; coached production teams on performance management."
        ),
    )


def test_edit_evidence_validator_rejects_unsupported_scope():
    model = _Model(
        {
            "supported": False,
            "unsupported_claims": ["coached production teams", "performance management"],
            "reason": "The evidence establishes mentoring, not production-team management.",
        }
    )

    result = LangChainResumeEditEvidenceValidator(model).validate(_request())

    assert result.supported is False
    assert result.unsupported_claims == ("coached production teams", "performance management")
    assert "job posting" in model.messages[0].content
    assert "coached production teams" in model.messages[1].content


def test_edit_evidence_validator_accepts_a_grounded_paraphrase():
    model = _Model(
        {
            "supported": True,
            "unsupported_claims": [],
            "reason": "The rewrite only paraphrases the supplied evidence.",
        }
    )
    request = ResumeEditEvidenceRequest(
        original="Mentored 12 engineers in 8D and 5 Why methodologies.",
        supporting_evidence="",
        rewrite="Coached 12 engineers in 8D and 5 Why methodologies.",
    )

    result = LangChainResumeEditEvidenceValidator(model).validate(request)

    assert result.supported is True
    assert result.unsupported_claims == ()


def test_edit_evidence_validator_fails_closed_without_a_verdict():
    class _NoVerdictModel(_Model):
        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[])

    result = LangChainResumeEditEvidenceValidator(_NoVerdictModel({})).validate(_request())

    assert result.supported is False
    assert result.failure_code == "missing_tool_call"
