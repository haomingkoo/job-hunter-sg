import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RecruitmentTeamPanel from "../RecruitmentTeamPanel.jsx";
import { apiFetch } from "../../lib/api.js";
import { streamRecruitmentCommand } from "../../lib/recruitmentTeamApi.js";

vi.mock("../../lib/api.js", () => ({ apiFetch: vi.fn() }));
vi.mock("../../lib/recruitmentTeamApi.js", () => ({
  streamRecruitmentCommand: vi.fn(),
}));

const response = (payload) => ({ json: async () => payload });

describe("RecruitmentTeamPanel", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("starts and continues one persisted recruitment conversation", async () => {
    let messageCount = 2;
    streamRecruitmentCommand.mockImplementation(async (path, body, onActivity) => {
      onActivity({
        sequence: messageCount === 2 ? 1 : 3,
        team_member: "coordinator",
        status: "running",
        summary: "Reviewing request.",
      });
      if (path.includes("/messages/stream")) {
        messageCount = 4;
        return { thread_id: "thread-1", run_id: "run-2", status: "completed" };
      }
      return { thread_id: "thread-1", run_id: "run-1", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "AI resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-1") {
        const messages = [
          { role: "user", content: "Find roles for me." },
          { role: "assistant", content: "I will focus on evidence-backed matches." },
          { role: "user", content: "Keep it in Singapore." },
          { role: "assistant", content: "I will keep the search in Singapore." },
        ];
        return response({
          thread_id: "thread-1",
          workflow_state: "exploring",
          case_facts: { resume_label: "AI resume" },
          messages: messages.slice(0, messageCount),
        });
      }
      if (path === "/api/recruitment-team/threads/thread-1/events") {
        return response([
          { sequence: 1, team_member: "coordinator", status: "running", summary: "Reviewing request." },
          { sequence: 2, team_member: "coordinator", status: "completed", summary: "Turn completed." },
        ]);
      }
      // refreshThread loads pending agent-drafted edits on every thread refresh.
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Find roles for me.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = textarea.closest("form");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will focus on evidence-backed matches.");
    expect(container.textContent).toContain("Turn completed.");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBe("thread-1");

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Keep it in Singapore.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will keep the search in Singapore.");
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-1/messages/stream",
      expect.objectContaining({ message: "Keep it in Singapore." }),
      expect.any(Function),
    );
  });

  it("starts a new conversation without resurrecting the old thread on the next render", async () => {
    let threadsFetchCount = 0;
    streamRecruitmentCommand.mockImplementation(async () => (
      { thread_id: "thread-1", run_id: "run-1", status: "completed" }
    ));
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "AI resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) {
        threadsFetchCount += 1;
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-1") {
        return response({
          thread_id: "thread-1",
          workflow_state: "exploring",
          case_facts: { resume_label: "AI resume" },
          messages: [{ role: "assistant", content: "I will focus on evidence-backed matches." }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-1/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Find roles for me.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.closest("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will focus on evidence-backed matches.");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBe("thread-1");
    const fetchesBeforeReset = threadsFetchCount;

    const newConversationButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Start new conversation");
    await act(async () => newConversationButton.click());

    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBeNull();
    expect(container.textContent).not.toContain("I will focus on evidence-backed matches.");
    // The empty state now offers a choice rather than an empty box: autopilot, or
    // say what you want. Either way it names the resume it will work from.
    expect(container.textContent).toContain("Find roles for me");
    expect(threadsFetchCount).toBe(fetchesBeforeReset);
  });

  it("discovers the latest owned thread without a browser pointer", async () => {
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads") {
        return response([{
          thread_id: "persisted-thread",
          resume_label: "Saved resume",
          last_message: "Welcome back.",
        }]);
      }
      if (path === "/api/recruitment-team/threads/persisted-thread") {
        return response({
          thread_id: "persisted-thread",
          workflow_state: "exploring",
          case_facts: { resume_label: "Saved resume" },
          messages: [{ role: "assistant", content: "Welcome back." }],
        });
      }
      if (path === "/api/recruitment-team/threads/persisted-thread/events") {
        return response([]);
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Welcome back.");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42"))
      .toBe("persisted-thread");
  });

  it("renders every persisted candidate-profile field and resumes a failed profile", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-profile");
    let completed = false;
    const fields = [
      {
        field_id: "credential_ca",
        category: "credential",
        statement: "Holds CA Singapore qualification.",
        evidence_support_score: 100,
        evidence_kind: "direct",
        score_reason: "The qualification is explicitly listed.",
        evidence_quotes: ["CA Singapore"],
      },
      {
        field_id: "stated_skill_python",
        category: "stated_skill",
        statement: "Lists Python as a skill.",
        evidence_support_score: 100,
        evidence_kind: "direct",
        score_reason: "The skills section lists Python; it does not prove use.",
        evidence_quotes: ["Python"],
      },
    ];
    streamRecruitmentCommand.mockImplementation(async (_path, _body, onActivity) => {
      onActivity({
        sequence: 3,
        team_member: "candidate_profiler",
        status: "running",
        summary: "Studying resume evidence.",
      });
      completed = true;
      return { thread_id: "thread-profile", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-profile") {
        return response({
          thread_id: "thread-profile",
          workflow_state: completed ? "profile_ready" : "exploring",
          case_facts: {
            resume_label: "Finance and AI resume",
            candidate_profile_artifact_id: "artifact-1",
            candidate_profile_status: completed ? "completed" : "failed",
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-profile/events") {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-profile/candidate-profile") {
        return response({
          artifact_id: "artifact-1",
          prompt_version: "candidate-evidence-profile-v3",
          decomposition_version: "semantic-section-record-v1",
          status: completed ? "completed" : "failed",
          profile: completed ? { fields } : null,
          error: completed ? null : {
            failed_scope_id: "experience_04",
            recovery: "Resume the candidate profile command.",
          },
        });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Profile paused at experience_04");
    const resumeButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Resume profile"));
    await act(async () => resumeButton.click());

    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-profile/candidate-profile/stream",
      expect.objectContaining({ idempotency_key: expect.any(String) }),
      expect.any(Function),
    );
    expect(container.textContent).toContain("Holds CA Singapore qualification.");
    expect(container.textContent).toContain("Lists Python as a skill.");
    expect(container.textContent).toContain("it does not prove use");
  });

  it("does not offer a second study while the automatic study is running", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-studying");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-studying") {
        return response({
          thread_id: "thread-studying",
          workflow_state: "exploring",
          case_facts: { candidate_profile_status: "running" },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-studying/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    const studyButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Studying resume");
    expect(studyButton).toBeDefined();
    expect(studyButton.disabled).toBe(true);
  });

  it("paginates a large candidate profile, strongest evidence first", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-paged");
    const fields = Array.from({ length: 30 }, (_, index) => ({
      field_id: `field_${index}`,
      category: "stated_skill",
      statement: `Field number ${index}.`,
      evidence_support_score: index,
      evidence_kind: "direct",
      score_reason: "reason",
      evidence_quotes: [],
    }));
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-paged") {
        return response({
          thread_id: "thread-paged",
          workflow_state: "profile_ready",
          case_facts: {
            candidate_profile_artifact_id: "artifact-paged",
            candidate_profile_status: "completed",
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-paged/events") return response([]);
      if (path === "/api/recruitment-team/threads/thread-paged/candidate-profile") {
        return response({ artifact_id: "artifact-paged", status: "completed", profile: { fields } });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain("Showing 25 of 30 fields");
    expect(container.textContent).toContain("Field number 29.");
    expect(container.textContent).not.toContain("Field number 4.");

    const showMoreButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Show 5 more"));
    await act(async () => showMoreButton.click());

    expect(container.textContent).toContain("Field number 4.");
  });

  it("searches current jobs and renders source-backed target actions", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-jobs");
    let selected = false;
    const job = {
      job_id: 101,
      title: "Applied AI Solution Architect",
      company: "Example Employer",
      location: "Singapore",
      salary: "$10,000 - $15,000",
      seniority: "Professional",
      source: {
        source: "MyCareersFuture",
        url: "https://example.test/jobs/101",
        posted_date: "2026-07-03",
        closing_date: "2026-08-03",
        availability: "current",
      },
      posting_variants: [{ job_id: 101 }],
    };
    const roleProfile = {
      profile_version: "role-success-v1",
      target_job_id: 101,
      sources: [{
        source_id: "target_job:101",
        source_type: "target_job",
        title: "Applied AI Solution Architect — Example Employer",
        url: "https://example.test/jobs/101",
        evidence_strength: "primary",
      }],
      criteria: [{
        criterion_id: "agent_reliability",
        category: "technical_skills",
        requirement_level: "required",
        statement: "Build and evaluate reliable agent systems.",
        source_ids: ["target_job:101"],
      }],
      candidate_evidence: [{
        criterion_id: "agent_reliability",
        alignment: "direct",
        resume_evidence_ids: ["block-1"],
        explanation: "The resume explicitly describes production agent evaluation.",
        confidence: 0.93,
        confidence_basis: "Directly cited resume evidence.",
      }],
      source_coverage: { taxonomy_match_quality: "unmatched" },
      clarification_question: "Which production reliability outcomes matter most?",
    };
    streamRecruitmentCommand.mockImplementation(async (_path, _body, onActivity) => {
      onActivity({
        sequence: 3,
        team_member: "job_researcher",
        status: "running",
        summary: "Searching current jobs.",
      });
      return { thread_id: "thread-jobs", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-jobs") {
        return response({
          thread_id: "thread-jobs",
          workflow_state: selected ? "target_selected" : "exploring",
          case_facts: {
            resume_label: "AI resume",
            recommendations: [job],
            match_rationales: [{
              job_id: 101,
              matched: [{
                statement: "Production agent reliability is directly relevant.",
                resume_quote: "Built reliable Python agent platforms",
              }],
              stretch: [],
              missing: ["Named cloud platform"],
              level_fit: "aligned",
              pay_position: "above_peer_median",
            }],
            shortlisted_job_ids: selected ? [101] : [],
            selected_target: selected ? job : null,
            role_success_profile: selected ? roleProfile : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-jobs/events") {
        return response([]);
      }
      if (path.endsWith("/jobs/101/select") && options.method === "POST") {
        selected = true;
        return response({ status: "completed" });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Applied AI Solution Architect");
    expect(container.textContent).toContain("MyCareersFuture");
    expect(container.textContent).toContain("Level: aligned · Pay: above peer median");
    expect(container.textContent).toContain("Production agent reliability is directly relevant.");
    expect(container.textContent).toContain("Built reliable Python agent platforms");
    expect(container.textContent).toContain("Named cloud platform");
    expect(container.textContent).toContain("StretchNone identified.");
    expect(container.querySelector('a[href="https://example.test/jobs/101"]')).not.toBeNull();

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "senior agentic AI Singapore");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const searchButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Search jobs"));
    await act(async () => searchButton.click());
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-jobs/jobs/search/stream",
      expect.objectContaining({ query: "senior agentic AI Singapore" }),
      expect.any(Function),
    );

    const selectButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Select target"));
    await act(async () => selectButton.click());
    expect(container.textContent).toContain("Selected target");
    expect(container.textContent).toContain("Role Success Profile");
    expect(container.textContent).toContain("Build and evaluate reliable agent systems.");
    expect(container.textContent).toContain("raw evidence confidence 93%");
    expect(container.textContent).toContain("Which production reliability outcomes matter most?");
  });

  it("runs and renders the judged multi-agent target assessment", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-assessment");
    let assessed = false;
    const roleProfile = {
      criteria: [],
      candidate_evidence: [],
      cited_resume_evidence: [],
      sources: [],
      source_coverage: { taxonomy_match_quality: "unmatched" },
    };
    streamRecruitmentCommand.mockImplementation(async (path, _body, onActivity) => {
      expect(path).toBe("/api/recruitment-team/threads/thread-assessment/assessment/stream");
      onActivity({
        sequence: 4,
        team_member: "recruiter",
        status: "completed",
        summary: "Recruiter screen completed.",
      });
      assessed = true;
      return { thread_id: "thread-assessment", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-assessment") {
        return response({
          thread_id: "thread-assessment",
          workflow_state: assessed ? "assessment_ready" : "target_selected",
          case_facts: {
            selected_target: { job_id: 101 },
            role_success_profile: roleProfile,
            target_assessment_artifact_id: assessed ? "assessment-1" : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-assessment/events") {
        return response(assessed ? [{
          sequence: 4,
          team_member: "recruiter",
          status: "completed",
          summary: "Recruiter screen completed.",
        }] : []);
      }
      if (path === "/api/recruitment-team/threads/thread-assessment/assessment") {
        return response({
          artifact_id: "assessment-1",
          status: "completed",
          specialist_runs: [{
            persona_id: "recruiter",
            status: "completed",
            attempt_count: 1,
            submission: {
              summary: "The role has directly cited evidence.",
              score: 88,
              score_reason: "The cited field supports the role criterion.",
            },
          }],
          synthesis: "Evidence-grounded target assessment.",
          judge: {
            disposition: "pass",
            score: 92,
            confidence: 90,
            score_reason: "Claims retain provenance and boundaries.",
            confidence_reason: "Every cited artifact was available to the judge.",
            strengths: ["The synthesis preserves canonical evidence IDs."],
            weaknesses: ["One interview validation step could be more specific."],
            evidence_gaps: ["Production ownership scope remains unverified."],
            rubric_scores: {
              evidence_grounding: 96,
              role_coverage: 90,
              decision_usefulness: 88,
              fairness_and_boundaries: 100,
            },
            deductions: [{
              rubric: "decision_usefulness",
              points: 8,
              reason: "The validation step is broad.",
            }],
          },
          correction: { attempted: true },
          execution_policy: {
            persona_pack_version: "recruitment-personas-v1",
            specialist_max_concurrency: 5,
            specialist_validation_attempts: 2,
            synthesis_validation_attempts: 2,
            judge_validation_attempts: 2,
            transport_retries: 0,
          },
        });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const assessButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Run assessment");
    await act(async () => assessButton.click());

    expect(container.textContent).toContain("Recruiter screen completed.");
    expect(container.textContent).toContain("The role has directly cited evidence.");
    expect(container.textContent).toContain("Evidence-grounded target assessment.");
    expect(container.textContent).toContain("output quality 92/100");
    expect(container.textContent).toContain("Score reason: Claims retain provenance and boundaries.");
    expect(container.textContent).toContain("Confidence basis: Every cited artifact was available");
    expect(container.textContent).toContain("Strength: The synthesis preserves canonical evidence IDs.");
    expect(container.textContent).toContain("Weakness: One interview validation step could be more specific.");
    expect(container.textContent).toContain("Evidence gap: Production ownership scope remains unverified.");
    expect(container.textContent).toContain("evidence grounding96/100");
    expect(container.textContent).toContain("Deduction · decision usefulness · 8 points");
    expect(container.textContent).toContain("one targeted correction was judged independently");
    // The execution-policy dump (validation attempts, transport retries, "no fallback
    // model") described knobs the runner does not enforce and meant nothing to a
    // candidate, so the panel now states what actually happened instead.
    expect(container.textContent).toContain("1 specialist reviewed this role against your evidence");
    expect(container.textContent).not.toContain("no fallback model");
  });

  it("hands off a completed target assessment to a resume-agent session", async () => {
    sessionStorage.clear();
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-handoff");
    let assessed = false;
    const roleProfile = {
      criteria: [],
      candidate_evidence: [],
      cited_resume_evidence: [],
      sources: [],
      source_coverage: { taxonomy_match_quality: "unmatched" },
    };
    streamRecruitmentCommand.mockImplementation(async (_path, _body, onActivity) => {
      onActivity({
        sequence: 4,
        team_member: "recruiter",
        status: "completed",
        summary: "Recruiter screen completed.",
      });
      assessed = true;
      return { thread_id: "thread-handoff", status: "completed" };
    });
    const handoffCalls = [];
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-handoff") {
        return response({
          thread_id: "thread-handoff",
          workflow_state: assessed ? "assessment_ready" : "target_selected",
          case_facts: {
            selected_target: { job_id: 101 },
            role_success_profile: roleProfile,
            target_assessment_artifact_id: assessed ? "assessment-1" : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-handoff/events") {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-handoff/assessment") {
        return response({
          artifact_id: "assessment-1",
          status: "completed",
          specialist_runs: [],
          synthesis: "Evidence-grounded target assessment.",
          judge: {
            disposition: "pass",
            score: 92,
            confidence: 90,
            score_reason: "reason",
            confidence_reason: "reason",
            strengths: [],
            weaknesses: [],
            evidence_gaps: [],
            rubric_scores: {},
            deductions: [],
          },
          correction: { attempted: false },
          execution_policy: {
            persona_pack_version: "recruitment-personas-v1",
            specialist_max_concurrency: 5,
            specialist_validation_attempts: 2,
            synthesis_validation_attempts: 2,
            judge_validation_attempts: 2,
            transport_retries: 0,
          },
        });
      }
      if (
        path === "/api/recruitment-team/threads/thread-handoff/resume-agent-handoff" &&
        options.method === "POST"
      ) {
        handoffCalls.push({ path, options });
        return response({ session_id: "resume-agent-session-9", status: "queued" });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    const setActiveTab = vi.fn();
    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} setActiveTab={setActiveTab} />);
    });

    expect(
      [...container.querySelectorAll("button")].some((button) =>
        button.textContent.includes("Draft resume edits for this job"),
      ),
    ).toBe(false);

    const assessButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Run assessment");
    await act(async () => assessButton.click());

    const handoffButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Draft resume edits for this job"));
    expect(handoffButton).not.toBeUndefined();

    await act(async () => handoffButton.click());

    expect(handoffCalls).toHaveLength(1);
    expect(sessionStorage.getItem("jh_resume_agent_session")).toBe("resume-agent-session-9");
    expect(sessionStorage.getItem("jh_resume_agent_autoopen")).toBe("1");
    expect(setActiveTab).toHaveBeenCalledWith("resume");
  });
});
