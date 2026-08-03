import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../../lib/api.js";
import TrackerTab, { getPipelineStatusMove } from "../TrackerTab.jsx";

vi.mock("../../lib/api.js", () => ({
  API_BASE: "",
  apiFetch: vi.fn(),
  downloadBlob: vi.fn(),
}));

function setField(field, value) {
  const setter = Object.getOwnPropertyDescriptor(field.constructor.prototype, "value")?.set;
  setter.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("TrackerTab workspace creation", () => {
  let container;
  let root;
  let refreshJobs;

  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({});
    vi.stubGlobal("fetch", vi.fn());
    refreshJobs = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("creates a workspace from pasted job description", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const pasteButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Paste JD"));
    await act(async () => {
      pasteButton.click();
    });

    await act(async () => {
      setField(container.querySelector("input[placeholder='Company *']"), "GovTech");
      setField(container.querySelector("input[placeholder='Role *']"), "Senior AI Engineer");
      setField(container.querySelector("input[placeholder='Source URL']"), "https://example.com/jobs/1");
      setField(
        container.querySelector("textarea[placeholder='Paste job description *']"),
        "Build agentic workflows for public-sector digital services.",
      );
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save"));
    await act(async () => {
      saveButton.click();
    });

    expect(apiFetch).toHaveBeenCalledTimes(1);
    const [path, options] = apiFetch.mock.calls[0];
    expect(path).toBe("/api/applications/workspaces");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toMatchObject({
      company: "GovTech",
      title: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      follow_up_date: "",
      notes: "",
    });
    expect(refreshJobs).toHaveBeenCalledTimes(1);
  });

  it("shows a clear error before submitting a workspace without job description", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const pasteButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Paste JD"));
    await act(async () => {
      pasteButton.click();
    });

    await act(async () => {
      setField(container.querySelector("input[placeholder='Company *']"), "GovTech");
      setField(container.querySelector("input[placeholder='Role *']"), "Senior AI Engineer");
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save"));
    await act(async () => {
      saveButton.click();
    });

    expect(container.textContent).toContain("Job description is required to create a workspace.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("opens a workspace detail view from a tracked application", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    expect(apiFetch).toHaveBeenCalledWith("/api/applications/workspaces/123");
    expect(container.textContent).toContain("Application Workspace");
    expect(container.textContent).toContain("Senior AI Engineer at GovTech");
    expect(container.textContent).toContain("Build agentic workflows for public-sector digital services.");
    expect(container.textContent).toContain("Saved");
    expect(container.textContent).toContain("Version #7");
    expect(container.textContent).toContain("Agent review not run yet.");
    expect(container.textContent).toContain("No submitted resume recorded yet.");
  });

  it("opens the selected recruitment application directly and shows durable pipeline context", async () => {
    const onOpenJobHandled = vi.fn();
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue({
      id: 7001,
      company: "Example Semiconductor",
      title: "Operations Manager",
      role: "Operations Manager",
      job_description: "Lead fab operations transformation.",
      source_url: "https://example.test/jobs/7001",
      source: "MyCareersFuture",
      status: "saved",
      date_applied: null,
      follow_up_date: null,
      notes: "Call recruiter on Friday",
      scraped_job_id: 101,
      resume_version_id: 7,
      role_metadata: {
        contacts: [{ name: "Hiring Manager", details: "SEMICON introduction" }],
        activity: [{ type: "contact_added", recorded_at: "2026-08-01T00:00:00Z" }],
        recruitment_pipeline: {
          fit_evidence: { matched: [{ statement: "Operations leadership" }], stretch: [], missing: ["Tool assembly"] },
          next_action: { label: "Review the evidence, tailor the resume, then manage the application workspace" },
          activity: [{ action: "selected", recorded_at: "2026-08-03T00:00:00Z" }],
        },
      },
      stage_history: [{ stage: "saved", date: "2026-08-03", source: "created", notes: "" }],
      created_at: "2026-08-03T00:00:00Z",
      updated_at: "2026-08-03T00:00:00Z",
    }) });

    await act(async () => {
      root.render(
        <TrackerTab
          jobs={[{
            id: 7001,
            company: "Example Semiconductor",
            role: "Operations Manager",
            date_applied: null,
            status: "saved",
            source: "MyCareersFuture",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
          openJobId={7001}
          onOpenJobHandled={onOpenJobHandled}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(apiFetch).toHaveBeenCalledWith("/api/applications/workspaces/7001");
    expect(onOpenJobHandled).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Review the evidence, tailor the resume, then manage the application workspace");
    expect(container.textContent).toContain("1 matched · 0 stretch · 1 missing");
    expect(container.textContent).toContain("Hiring Manager · SEMICON introduction");
    expect(container.textContent).toContain("Call recruiter on Friday");
    expect(container.textContent).toContain("contact added");
    expect(container.textContent).toContain("selected");
  });

  it("builds and reloads source-backed research, interview prep, compensation, and negotiation", async () => {
    const workspace = {
      id: 808,
      company: "Example Semiconductor",
      title: "Manufacturing Manager",
      role: "Manufacturing Manager",
      job_description: "Lead semiconductor manufacturing transformation with SPC.",
      source_url: "https://example.test/jobs/808",
      source: "MyCareersFuture",
      status: "saved",
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [],
    };
    const researched = {
      ...workspace,
      role_metadata: {
        application_research: {
          status: "partial",
          source_statuses: [
            { source: "public_job_corpus", status: "complete" },
            { source: "mom_occupational_wages_2025", status: "complete" },
            { source: "community_and_employer_reviews", status: "valid_empty" },
          ],
          role_company_brief: {
            freshness: "stale",
            company: { current_posting_count: 2 },
            role: {
              comparable_titles: [{ title: "Fab Operations Manager" }],
              ats_terms: [{ term: "spc", confidence: "high", observed_in_postings: 2 }],
            },
            sources: [{
              url: "https://example.test/jobs/808",
              publisher: "MyCareersFuture",
              source_type: "job_posting",
              confidence: "high",
              freshness: "stale",
              retrieved_at: "2026-06-01T00:00:00Z",
              evidence_note: "Exact selected posting snapshot.",
            }],
          },
          interview_pack: {
            confidence_note: "Preparation clusters, not guaranteed questions.",
            source_state: "stale",
            answer_formats: ["STAR", "XYZ"],
            questions: [{
              cluster: "technical",
              confidence: "high",
              question: "Tell me about a time you applied SPC.",
              sources: [{
                url: "https://example.test/jobs/808",
                source_type: "job_posting",
                retrieved_at: "2026-06-01T00:00:00Z",
                evidence_note: "Exact selected posting snapshot.",
              }],
              answer_scaffold: {
                evidence_quote: "Used SPC to stabilize manufacturing processes.",
                steps: ["Situation and task", "Action", "Result and reflection"],
              },
            }],
          },
          compensation_brief: {
            comparison_rule: "Definitions remain separate and are never silently averaged.",
            comparison_state: "multiple_incompatible_observations",
            observations: [
              { kind: "employer_posting", value: "$8,000 - $10,000", data_date: "2026-08-01" },
              {
                kind: "mom_occupational_wages",
                occupation: "Manufacturing manager",
                data_date: "June 2025",
                basic_wage: { p25: 7000, median: 9000, p75: 11000 },
                gross_wage: { p25: 7200, median: 9300, p75: 11500 },
              },
            ],
            recruiter_guide_leads: [{
              publisher: "Hays Singapore",
              publication_date: "2026",
              source_url: "https://example.test/hays-guide",
              status: "source_lead",
              evidence_note: "Public guide landing page; figures were not copied.",
            }],
          },
        },
      },
    };
    const rehearsed = {
      ...researched,
      role_metadata: {
        ...researched.role_metadata,
        negotiation: {
          rounds: [{
            scenario: "The recruiter says base is fixed.",
            created_at: "2026-08-03T00:00:00Z",
            coach_response: {
              opening: "Confirm which package definition is being discussed.",
              walk_away_guidance: "No walk-away point was supplied, so none was invented.",
              anchor_options: [{
                kind: "user_authorized",
                label: "Written offer",
                value: "$9,000 monthly base",
                definition: "Monthly base excluding bonus",
                source_type: "user_supplied",
                data_date: "2026-08-02",
              }],
              questions: ["Which package definition applies?"],
              trade_offs: ["Protect role scope before conceding elsewhere."],
              concessions: ["Trade one lower-priority term only for a confirmed return."],
            },
          }],
        },
      },
    };
    apiFetch
      .mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) })
      .mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(researched) })
      .mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(rehearsed) });

    await act(async () => {
      root.render(
        <TrackerTab
          jobs={[{ id: 808, company: workspace.company, role: workspace.role, status: "saved", source: workspace.source }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });
    await act(async () => {
      container.querySelector("button[aria-label='Open workspace for Example Semiconductor Manufacturing Manager']").click();
    });

    const researchButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Build research pack"));
    await act(async () => {
      researchButton.click();
    });

    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/applications/workspaces/808/research-pack",
      { method: "POST", body: "{}" },
    );
    expect(container.textContent).toContain("public job corpus: complete");
    expect(container.textContent).toContain("community and employer reviews: valid empty");
    expect(container.textContent).toContain("Evidence: stale");
    expect(container.textContent).toContain("spc");
    expect(container.textContent).toContain("Used SPC to stabilize manufacturing processes.");
    expect(container.textContent).toContain("Answer formats: STAR / XYZ");
    expect(container.textContent).toContain("Exact selected posting snapshot.");
    expect(container.textContent).toContain("$8,000 - $10,000");
    expect(container.textContent).toContain("Monthly basic S$7,000 / S$9,000 / S$11,000");
    expect(container.textContent).toContain("multiple incompatible observations");
    expect(container.textContent).toContain("Hays Singapore · 2026 · source lead");

    const evidenceDateInput = Array.from(container.querySelectorAll("label"))
      .find((label) => label.textContent.includes("Evidence date"))
      .querySelector("input");
    await act(async () => {
      setField(container.querySelector("textarea[placeholder^='Priorities']"), "Role scope\nBase salary");
      setField(container.querySelector("input[placeholder='Authorized evidence label']"), "Written offer");
      setField(container.querySelector("input[placeholder='Observed value']"), "$9,000 monthly base");
      setField(container.querySelector("input[placeholder='Definition / package basis']"), "Monthly base excluding bonus");
      setField(container.querySelector("input[placeholder='Authorized source URL (optional)']"), "https://example.test/offer");
      setField(evidenceDateInput, "2026-08-02");
      setField(
        container.querySelector("textarea[placeholder='What did the recruiter or hiring manager say?']"),
        "The recruiter says base is fixed.",
      );
    });
    const rehearseButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save and rehearse"));
    await act(async () => {
      rehearseButton.click();
    });

    const request = JSON.parse(apiFetch.mock.calls.at(-1)[1].body);
    expect(apiFetch.mock.calls.at(-1)[0]).toBe(
      "/api/applications/workspaces/808/negotiation/rehearse",
    );
    expect(request).toMatchObject({
      priorities: ["Role scope", "Base salary"],
      scenario: "The recruiter says base is fixed.",
      walk_away_point: "",
      authorized_evidence: [{
        label: "Written offer",
        value: "$9,000 monthly base",
        definition: "Monthly base excluding bonus",
        source_url: "https://example.test/offer",
        data_date: "2026-08-02",
      }],
    });
    expect(container.textContent).toContain("No walk-away point was supplied, so none was invented.");
    expect(container.textContent).toContain("Written offer");
    expect(container.textContent).toContain("Which package definition applies?");
    expect(container.textContent).toContain("Protect role scope before conceding elsewhere.");
    expect(container.textContent).toContain("Trade one lower-priority term only for a confirmed return.");
  });

  it("runs a linked resume through Deep Agent with a clear loading state", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [],
    };
    const reviewedWorkspace = {
      ...workspace,
      role_metadata: {
        agent_review: {
          debate_summary: {
            roles: ["recruiter"],
            final_recommendation: "Lead with verified delivery impact.",
            confidence: "high",
          },
        },
      },
    };
    let finishReview;
    const reviewResponse = new Promise((resolve) => {
      finishReview = () => resolve({ json: vi.fn().mockResolvedValue(reviewedWorkspace) });
    });
    apiFetch
      .mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) })
      .mockReturnValueOnce(reviewResponse);

    await act(async () => {
      root.render(
        <TrackerTab
          jobs={[{ id: 123, company: "GovTech", role: "Senior AI Engineer", status: "saved", source: "Other" }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });
    await act(async () => {
      container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']").click();
    });

    const runButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Run Deep Agent review"));
    await act(async () => {
      runButton.click();
    });

    expect(container.querySelector("[role='status']").textContent).toContain("20–40 seconds");
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/applications/workspaces/123/agent-review",
      { method: "POST", body: "{}" },
    );

    await act(async () => {
      finishReview();
      await reviewResponse;
    });
    expect(container.textContent).toContain("Lead with verified delivery impact.");
    expect(container.querySelector("[role='status']")).toBeNull();
  });

  it("groups tracked applications by status in board view", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[
            {
              id: 123,
              company: "GovTech",
              role: "Senior AI Engineer",
              date_applied: "2026-07-04",
              status: "saved",
              source: "Other",
            },
            {
              id: 124,
              company: "Grab",
              role: "ML Engineer",
              date_applied: "2026-07-03",
              status: "interview",
              source: "Referral",
            },
          ]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const boardButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Board"));
    await act(async () => {
      boardButton.click();
    });

    const savedColumn = container.querySelector("[data-pipeline-column='saved']");
    const interviewColumn = container.querySelector("[data-pipeline-column='interview']");
    const appliedColumn = container.querySelector("[data-pipeline-column='applied']");
    expect(savedColumn.textContent).toContain("GovTech");
    expect(savedColumn.textContent).toContain("Senior AI Engineer");
    expect(interviewColumn.textContent).toContain("Grab");
    expect(interviewColumn.textContent).toContain("ML Engineer");
    expect(appliedColumn.textContent).toContain("Drop here");
  });

  it("shows outcome counts in the tracker dashboard", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[
            { id: 1, company: "A", role: "Engineer", date_applied: "2026-07-04", status: "applied", source: "Other" },
            { id: 2, company: "B", role: "Engineer", date_applied: "2026-07-04", status: "screening", source: "Other" },
            { id: 3, company: "C", role: "Engineer", date_applied: "2026-07-04", status: "final_round", source: "Other" },
            { id: 4, company: "D", role: "Engineer", date_applied: "2026-07-04", status: "accepted", source: "Other" },
            { id: 5, company: "E", role: "Engineer", date_applied: "2026-07-04", status: "rejected", source: "Other" },
            { id: 6, company: "F", role: "Engineer", date_applied: "2026-07-04", status: "withdrawn", source: "Other" },
            { id: 7, company: "G", role: "Engineer", date_applied: "2026-07-04", status: "no_response", source: "Other" },
          ]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const outcomeValue = (key) => container.querySelector(`[data-outcome-count='${key}'] div`).textContent;
    expect(outcomeValue("submitted")).toBe("1");
    expect(outcomeValue("interview")).toBe("2");
    expect(outcomeValue("offer")).toBe("1");
    expect(outcomeValue("rejected")).toBe("1");
    expect(outcomeValue("withdrawn")).toBe("1");
    expect(outcomeValue("no_response")).toBe("1");
  });

  it("maps a board drop to a status update target", () => {
    const active = { data: { current: { jobId: 123, status: "saved" } } };

    expect(getPipelineStatusMove(active, { id: "status:interview" })).toEqual({
      jobId: 123,
      nextStatus: "interview",
    });
    expect(getPipelineStatusMove(active, { id: "status:saved" })).toBeNull();
    expect(getPipelineStatusMove(active, { id: "status:not_real" })).toBeNull();
    expect(getPipelineStatusMove(active, null)).toBeNull();
  });

  it("shows a saved debate summary in the workspace detail view", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {
        agent_review: {
          debate_summary: {
            roles: ["recruiter", "ats", "skeptic"],
            key_disagreements: ["ATS wants more keyword coverage; skeptic wants proof first."],
            final_recommendation: "Revise one bullet, then rerun review.",
            confidence: "medium",
            trace_id: "trace-123",
          },
        },
      },
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    expect(container.textContent).toContain("Debate summary");
    expect(container.textContent).toContain("Revise one bullet, then rerun review.");
    expect(container.textContent).toContain("recruiter");
    expect(container.textContent).toContain("ATS wants more keyword coverage; skeptic wants proof first.");
    expect(container.textContent).toContain("Confidence: medium, trace ID: trace-123");
  });

  it("uploads a submitted resume artifact from the workspace detail view", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    const uploadedWorkspace = {
      ...workspace,
      role_metadata: {
        submitted_resume: {
          filename: "submitted.pdf",
          submitted_date: "2026-07-04",
          notes: "Submitted through company portal.",
          word_count: 42,
        },
      },
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(uploadedWorkspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    const file = new File(["resume"], "submitted.pdf", { type: "application/pdf" });
    const fileInput = container.querySelector("input[type='file']");
    Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
    await act(async () => {
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
      setField(container.querySelector("input[placeholder='Submitted resume notes']"), "Submitted through company portal.");
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save submitted resume"));
    await act(async () => {
      saveButton.click();
    });

    expect(apiFetch).toHaveBeenCalledTimes(2);
    const [url, options] = apiFetch.mock.calls[1];
    expect(url).toBe("/api/applications/workspaces/123/submitted-resume");
    expect(options.method).toBe("POST");
    expect(options.body.get("file")).toBe(file);
    expect(options.body.get("notes")).toBe("Submitted through company portal.");
    expect(container.textContent).toContain("submitted.pdf");
    expect(container.textContent).toContain("2026-07-04 - 42 words");
  });
});
