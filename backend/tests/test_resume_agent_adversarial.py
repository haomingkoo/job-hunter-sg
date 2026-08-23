"""Failure-injection regressions for the Resume Deep Agent."""

import json
import time

import pytest
from langchain_core.messages import AIMessage, ToolMessage


@pytest.mark.parametrize(
    ("patch", "expected_reason"),
    [
        ({"score": True}, "invalid_score"),
        ({"score": 101}, "invalid_score"),
        ({"strengths": []}, "invalid_strengths"),
        ({"weaknesses": [{"finding": "Gap", "source": "reviewer:unknown", "confidence": 0.8, "confidence_basis": "Test"}]}, "invalid_source"),
        ({"strengths": [{"finding": "Good", "source": "final_assessment", "confidence": 2, "confidence_basis": "Test"}]}, "invalid_confidence"),
        ({"evidence_gaps": "none"}, "invalid_evidence_gaps"),
    ],
)
def test_judge_rejects_adversarial_structured_outputs(patch, expected_reason):
    from resume_agent.judge import _parse

    output = {
        "verdict": "Useful but incomplete.",
        "requires_revision": False,
        "strengths": [{
            "finding": "Evidence is cited.",
            "source": "final_assessment",
            "confidence": 0.9,
            "confidence_basis": "Visible in the assessment.",
        }],
        "weaknesses": [{
            "finding": "One gap remains.",
            "category": "coverage",
            "severity": "non_blocking",
            "source": "reviewer:ats",
            "confidence": 0.8,
            "confidence_basis": "Visible in the reviewer evidence.",
        }],
        "score": 80,
        "reasoning": "One material omission.",
        "evidence_gaps": [],
    }
    output.update(patch)

    parsed, reason = _parse(json.dumps(output), {"final_assessment", "reviewer:ats"})

    assert parsed is None
    assert reason == expected_reason


def test_target_job_snapshot_without_database_id_is_not_general_mode():
    from resume_agent.session import _build_prompt

    prompt = _build_prompt({
        "message": "Review for this role",
        "job_context": {"title": "AI Engineer", "description": "Build agent systems"},
    })

    assert "target_job_data" in prompt
    assert "General strengthening mode" not in prompt


def test_prompts_reject_consensus_overreach_and_unsupported_keyword_replacement():
    from resume_agent.personas import _PERSONA_BY_NAME, _worker_system_prompt
    from resume_agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT

    hiring_prompt = _worker_system_prompt("hiring_manager", _PERSONA_BY_NAME["hiring_manager"][1])
    ats_prompt = _worker_system_prompt("ats", _PERSONA_BY_NAME["ats"][1])

    assert "Consensus is not proof" in ORCHESTRATOR_SYSTEM_PROMPT
    assert "led delivery" in hiring_prompt
    assert "end-to-end ownership" in hiring_prompt
    assert "stronger keyword" in ats_prompt
    assert "ask the user to confirm" in ats_prompt


def test_explicit_empty_job_snapshot_clears_prior_target_context():
    import resume_agent.session as agent_session

    class FakeAgent:
        def invoke(self, payload, config=None):
            return {"messages": [AIMessage(content="Reviewed.")]}

    session_id = "clear-target-context"
    owner = "clear-target-owner"
    first = {
        "session_id": session_id,
        "message": "Review for this job",
        "resume_text": "EXPERIENCE\n- Built an AI service",
        "job_id": 41,
        "job_context": {"title": "AI Engineer", "description": "Build AI services"},
    }
    list(agent_session.stream_chat_events(first, agent=FakeAgent(), owner_key=owner))
    list(agent_session.stream_chat_events({
        "session_id": session_id,
        "message": "Switch to a general review",
        "job_context": {},
    }, agent=FakeAgent(), owner_key=owner))

    state = agent_session.get_state(session_id, owner_key=owner)
    assert state["mode"] == "general"
    assert state["job_id"] is None
    assert state["job_context"] == {}


def test_explicit_empty_profile_context_does_not_restore_stale_profile():
    import resume_agent.session as agent_session

    class FakeAgent:
        def invoke(self, payload, config=None):
            return {"messages": [AIMessage(content="Reviewed.")]}

    session_id = "clear-profile-context"
    owner = "clear-profile-owner"
    list(agent_session.stream_chat_events({
        "session_id": session_id,
        "message": "Review",
        "resume_text": "EXPERIENCE\n- Built an AI service",
        "profile_context": "Public profile context",
    }, agent=FakeAgent(), owner_key=owner))
    list(agent_session.stream_chat_events({
        "session_id": session_id,
        "message": "Remove the profile context",
        "profile_context": "",
    }, agent=FakeAgent(), owner_key=owner))

    state = agent_session.get_state(session_id, owner_key=owner)
    assert state["profile_context"] == ""


def test_invalid_supplied_job_context_fails_visibly_instead_of_reusing_state():
    import resume_agent.session as agent_session

    events = list(agent_session.stream_chat_events({
        "session_id": "invalid-job-context",
        "message": "Review",
        "resume_text": "EXPERIENCE\n- Built a service",
        "job_context": "stale data please",
    }, agent=object(), owner_key="invalid-job-context-owner"))

    assert events[-2]["event"] == "error"
    assert events[-2]["message"] == "Job context must be an object."
    assert events[-1]["event"] == "done"


def test_chat_history_reports_exact_dropped_message_count(monkeypatch):
    import config
    import resume_agent.session as agent_session

    monkeypatch.setattr(config, "AGENT_CHAT_HISTORY_LIMIT", 2)
    state = agent_session._new_state("history-truncation")

    for index in range(5):
        agent_session._append_message(state, {"role": "user", "content": str(index)})

    assert [message["content"] for message in state["messages"]] == ["3", "4"]
    assert state["chat_history_dropped_count"] == 3


def test_pending_diff_collection_does_not_silently_truncate():
    import resume_agent.session as agent_session

    bullet_count = 35
    text_by_id = {f"bullet-{index}": f"Original {index}" for index in range(bullet_count)}
    meta_by_id = {
        bullet_id: {"section_key": "experience", "entry_id": f"entry-{index}"}
        for index, bullet_id in enumerate(text_by_id)
    }
    messages = [
        ToolMessage(
            name="propose_edit",
            tool_call_id=f"call-{index}",
            content=json.dumps({
                "accepted": True,
                "bullet_id": bullet_id,
                "rewrite": f"Improved {index}",
            }),
        )
        for index, bullet_id in enumerate(text_by_id)
    ]

    pending = agent_session._collect_pending_diffs(
        {"messages": messages},
        text_by_id,
        meta_by_id,
        [],
        "revision-1",
    )

    assert len(pending) == bullet_count


def test_judge_retry_contains_original_evidence_failed_output_and_error_code():
    from resume_agent.judge import judge_assessment

    valid = {
        "verdict": "The review is useful.",
        "requires_revision": False,
        "strengths": [{
            "finding": "It cites evidence.",
            "source": "final_assessment",
            "confidence": 0.9,
            "confidence_basis": "Visible in the write-up.",
        }],
        "weaknesses": [{
            "finding": "It misses one ATS detail.",
            "category": "coverage",
            "severity": "non_blocking",
            "source": "reviewer:ats",
            "confidence": 0.8,
            "confidence_basis": "Visible in supplied reviewer evidence.",
        }],
        "score": 82,
        "reasoning": "Strong overall with one omission.",
        "evidence_gaps": [],
    }

    class RepairingModel:
        def __init__(self):
            self.prompts = []

        def bind_tools(self, _tools, **_kwargs):
            return self

        def invoke(self, messages, config=None):
            self.prompts.append(messages[-1].content)
            if len(self.prompts) == 1:
                return AIMessage(content="REJECTED NON-JSON OUTPUT")
            return AIMessage(content="", tool_calls=[{
                "name": "submit_quality_judgment",
                "args": valid,
                "id": "judge-repair",
                "type": "tool_call",
            }])

    model = RepairingModel()
    run = judge_assessment(
        "ORIGINAL FINAL ASSESSMENT",
        [{"persona": "ats", "summary": "ATS evidence"}],
        [{"persona": "ats", "status": "success"}],
        resume_evidence={"blocks": [{"id": "b1", "text": "Original evidence"}]},
        job_context={"description": "Target evidence"},
        trace_id="judge-repair",
        model=model,
    )

    assert run["status"] == "success"
    assert run["attempt_count"] == 2
    assert "ORIGINAL FINAL ASSESSMENT" in model.prompts[1]
    assert "REJECTED NON-JSON OUTPUT" in model.prompts[1]
    assert "missing_tool_call" in model.prompts[1]


def test_deterministic_structure_contract_overrides_false_positive_judge_block():
    from resume_agent.judge import _reconcile_deterministic_structure

    assessment = "\n".join([
        "Summary", "Decision.", "Strengths", "- Evidence", "Weaknesses", "- Gap",
        "Independent reviewer score", "74/100", "Reasoning", "Calibrated.",
        "Next actions", "- Confirm impact",
    ])
    parsed = {
        "requires_revision": True,
        "weaknesses": [{
            "finding": "The aggregate score leaks internal scoring mechanics.",
            "category": "required_structure",
            "severity": "blocking",
        }],
    }

    reconciled = _reconcile_deterministic_structure(parsed, assessment)

    assert reconciled["requires_revision"] is False
    assert reconciled["weaknesses"][0]["severity"] == "non_blocking"
    assert reconciled["deterministic_contract_corrections"] == 1


def test_synthesis_is_revised_and_rechecked_when_judge_finds_evidence_error(monkeypatch):
    import resume_agent.session as agent_session

    completed = {
        "persona": "recruiter",
        "status": "success",
        "tool_spans": [],
        "assessment": {
            "persona": "recruiter",
            "summary": "One supported finding.",
            "category": "fit",
            "findings": [],
            "conflicts": [],
            "score": 70,
            "reasoning": "Evidence is limited.",
            "suggested_actions": [],
        },
    }
    initial_assessment = """Summary
All reviewers found missing metrics.
Strengths
- Delivery is visible.
Weaknesses
- Outcomes are not quantified.
Independent reviewer score
70/100
Reasoning
The claim overstates agreement.
Next actions
- Clarify the outcome.
"""
    revised_assessment = """Summary
One reviewer found missing metrics.
Strengths
- Delivery is visible.
Weaknesses
- Outcomes are not quantified.
Independent reviewer score
70/100
Reasoning
The evidence is limited.
Next actions
- Clarify the outcome.
"""
    synthesis_results = iter([
        ({"messages": [AIMessage(content=initial_assessment)]}, [
            {"kind": "llm", "worker": "orchestrator", "phase": "orchestrator", "status": "success"}
        ]),
        ({"messages": [AIMessage(content=revised_assessment)]}, [
            {"kind": "llm", "worker": "orchestrator", "phase": "orchestrator_revision", "status": "success"}
        ]),
    ])
    judge_results = iter([
        {
            "status": "success",
            "assessment": {
                "verdict": "Consensus is overstated.",
                "requires_revision": True,
                "strengths": [],
                "weaknesses": [{"finding": "Only one reviewer made the claim."}],
                "score": 70,
                "reasoning": "Attribution error.",
                "evidence_gaps": [],
            },
            "tool_spans": [{"kind": "llm", "worker": "quality_judge", "status": "success"}],
        },
        {
            "status": "success",
            "assessment": {
                "verdict": "Attribution is corrected.",
                "requires_revision": False,
                "strengths": [],
                "weaknesses": [],
                "score": 95,
                "reasoning": "Evidence is attributed accurately.",
                "evidence_gaps": [],
            },
            "tool_spans": [{"kind": "llm", "worker": "quality_judge", "status": "success"}],
        },
    ])
    monkeypatch.setattr(agent_session, "iter_persona_worker_runs", lambda *_args, **_kwargs: iter([completed]))
    monkeypatch.setattr(agent_session, "create_resume_agent", lambda **_kwargs: object())
    monkeypatch.setattr(agent_session, "_run_synthesis", lambda *_args, **_kwargs: next(synthesis_results))
    monkeypatch.setattr(agent_session, "judge_assessment", lambda *_args, **_kwargs: next(judge_results))

    events = list(agent_session.stream_chat_events({
        "session_id": "judge-revision-loop",
        "message": "Review this resume.",
        "resume_text": "EXPERIENCE\n- Led delivery",
    }, owner_key="judge-revision-owner"))
    state = agent_session.get_state("judge-revision-loop", owner_key="judge-revision-owner")

    assert any(event.get("content") == revised_assessment for event in events)
    assert state["synthesis_revision"]["attempted"] is True
    assert state["synthesis_revision"]["resolved"] is True
    assert state["judge_assessment"]["requires_revision"] is False
    assert [span.get("phase") for span in state["tool_spans"] if span.get("worker") == "orchestrator"] == [
        "orchestrator",
        "orchestrator_revision",
    ]


def test_revision_prompt_quotes_the_exact_offending_presentation_snippet(monkeypatch):
    import resume_agent.session as agent_session

    completed = {
        "persona": "recruiter",
        "status": "success",
        "tool_spans": [],
        "assessment": {
            "persona": "recruiter",
            "summary": "One supported finding.",
            "category": "fit",
            "findings": [],
            "conflicts": [],
            "score": 70,
            "reasoning": "Evidence is limited.",
            "suggested_actions": [],
        },
    }
    synthesis_results = iter([
        ({"messages": [AIMessage(content="Impact is strong, e.g., revenue grew under USD 100M.")]}, [
            {"kind": "llm", "worker": "orchestrator", "phase": "orchestrator", "status": "success"}
        ]),
        ({"messages": [AIMessage(content="Impact is strong with confirmed revenue growth.")]}, [
            {"kind": "llm", "worker": "orchestrator", "phase": "orchestrator_revision", "status": "success"}
        ]),
    ])
    judge_results = iter([
        {
            "status": "success",
            "assessment": {
                "verdict": "Uses a hypothetical example metric.",
                "requires_revision": True,
                "strengths": [],
                "weaknesses": [{"finding": "Example metric is not evidenced."}],
                "score": 60,
                "reasoning": "Presentation violation.",
                "evidence_gaps": [],
            },
            "tool_spans": [{"kind": "llm", "worker": "quality_judge", "status": "success"}],
        },
        {
            "status": "success",
            "assessment": {
                "verdict": "Clean.",
                "requires_revision": False,
                "strengths": [],
                "weaknesses": [],
                "score": 95,
                "reasoning": "No violations.",
                "evidence_gaps": [],
            },
            "tool_spans": [{"kind": "llm", "worker": "quality_judge", "status": "success"}],
        },
    ])
    recorded_prompts = []

    def fake_run_synthesis(*args, **kwargs):
        recorded_prompts.append(args[1])
        return next(synthesis_results)

    monkeypatch.setattr(agent_session, "iter_persona_worker_runs", lambda *_args, **_kwargs: iter([completed]))
    monkeypatch.setattr(agent_session, "create_resume_agent", lambda **_kwargs: object())
    monkeypatch.setattr(agent_session, "_run_synthesis", fake_run_synthesis)
    monkeypatch.setattr(agent_session, "judge_assessment", lambda *_args, **_kwargs: next(judge_results))

    list(agent_session.stream_chat_events({
        "session_id": "presentation-violation-revision",
        "message": "Review this resume.",
        "resume_text": "EXPERIENCE\n- Led delivery",
    }, owner_key="presentation-violation-owner"))

    assert len(recorded_prompts) == 2
    revision_prompt = recorded_prompts[1]
    assert 'example_marker: "e.g."' in revision_prompt
    assert "do not" in revision_prompt.lower()


def test_failed_quality_judge_prevents_assessment_publication(monkeypatch):
    import resume_agent.session as agent_session

    completed = {
        "persona": "recruiter",
        "status": "success",
        "tool_spans": [],
        "assessment": {
            "persona": "recruiter",
            "summary": "Supported finding.",
            "category": "fit",
            "findings": [],
            "conflicts": [],
            "score": 70,
            "reasoning": "Evidence is limited.",
            "suggested_actions": [],
        },
    }
    monkeypatch.setattr(agent_session, "iter_persona_worker_runs", lambda *_args, **_kwargs: iter([completed]))
    monkeypatch.setattr(agent_session, "create_resume_agent", lambda **_kwargs: object())
    monkeypatch.setattr(agent_session, "_run_synthesis", lambda *_args, **_kwargs: (
        {"messages": [AIMessage(content="Ungraded synthesis.")]},
        [],
    ))
    monkeypatch.setattr(agent_session, "judge_assessment", lambda *_args, **_kwargs: {
        "status": "error",
        "failure_type": "validation",
        "assessment": {},
        "tool_spans": [],
        "error": {"code": "invalid_weakness_category"},
    })

    events = list(agent_session.stream_chat_events({
        "session_id": "judge-failure-gate",
        "message": "Review this resume.",
        "resume_text": "EXPERIENCE\n- Led delivery",
    }, owner_key="judge-failure-owner"))
    state = agent_session.get_state("judge-failure-gate", owner_key="judge-failure-owner")

    assert any(event.get("event") == "judge_error" for event in events)
    assert any(event.get("event") == "error" for event in events)
    assert not any(event.get("event") == "token" for event in events)
    assert events[-1]["event"] == "done"
    assert state["status"] == "failed"
    assert state["review_status"] == "quality_blocked"
    assert state["response"] == ""
    assert state["tool_spans"][-1]["failure_code"] == "quality_judge_unavailable"


def test_background_run_fails_when_every_independent_reviewer_fails(monkeypatch):
    import resume_agent.session as agent_session

    failed_runs = [{
        "persona": persona,
        "status": "error",
        "failure_type": "timeout",
        "attempt_count": 2,
        "retryable": True,
        "partial_results": [],
        "tool_spans": [],
        "error": {"code": "model_error:APITimeoutError"},
    } for persona in ("recruiter", "ats", "skeptic", "hiring_manager", "market_researcher")]

    class DisclaimerAgent:
        def invoke(self, payload, config=None):
            return {"messages": [AIMessage(content="No specialist review completed.")]}

    monkeypatch.setattr(
        agent_session,
        "iter_persona_worker_runs",
        lambda *_args, **_kwargs: iter(failed_runs),
    )
    monkeypatch.setattr(agent_session, "create_resume_agent", lambda **_kwargs: DisclaimerAgent())
    monkeypatch.setattr(agent_session, "judge_assessment", lambda *_args, **_kwargs: {
        "status": "error",
        "tool_spans": [],
    })

    owner = "all-workers-fail-owner"
    assert agent_session.reserve_owner_run(owner)
    session_id = agent_session.start_background_review({
        "session_id": "all-workers-fail",
        "message": "Review",
        "resume_text": "EXPERIENCE\n- Built a service",
        "job_context": {"title": "Engineer"},
    }, owner)

    deadline = time.monotonic() + 2
    state = agent_session.get_state(session_id, owner_key=owner)
    while state["status"] in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(0.01)
        state = agent_session.get_state(session_id, owner_key=owner)

    assert state["review_status"] == "error"
    assert state["status"] == "failed"
    assert "No independent reviewer completed" in state["error"]


def test_deployment_gate_rejects_incomplete_worker_coverage():
    from scripts.validate_resume_agent_deployment import (
        SAMPLE_JOB,
        validate_terminal_state,
    )
    from resume_agent.contracts import TARGET_JOB_PERSONAS

    runs = [
        {"persona": persona, "status": "success"}
        for persona in set(TARGET_JOB_PERSONAS) - {"market_researcher"}
    ]
    state = {
        "status": "completed",
        "review_status": "success",
        "mode": "target_job",
        "job_context": SAMPLE_JOB,
        "response": "Looks plausible but market coverage is absent.",
        "worker_runs": runs,
        "judge_run": {"status": "success"},
        "judge_assessment": {"requires_revision": False},
        "tool_spans": [
            {"kind": "llm", "status": "success", "worker": "orchestrator"},
            {"kind": "tool", "status": "success", "name": "search_jobs"},
        ],
    }

    with pytest.raises(AssertionError, match="reviewer coverage mismatch"):
        validate_terminal_state(state)


def test_deployment_gate_requires_each_agentic_model_stage():
    from scripts.validate_resume_agent_deployment import (
        SAMPLE_JOB,
        validate_terminal_state,
    )
    from resume_agent.contracts import TARGET_JOB_PERSONAS

    state = {
        "status": "completed",
        "review_status": "success",
        "mode": "target_job",
        "job_context": SAMPLE_JOB,
        "response": "Complete-looking response.",
        "worker_runs": [
            {"persona": persona, "status": "success"}
            for persona in TARGET_JOB_PERSONAS
        ],
        "judge_run": {"status": "success"},
        "judge_assessment": {"requires_revision": False},
        "tool_spans": [
            {"kind": "llm", "status": "success", "worker": "orchestrator"},
            {"kind": "tool", "status": "success", "name": "search_jobs"},
        ],
    }

    with pytest.raises(AssertionError, match="missing successful model workers"):
        validate_terminal_state(state)
