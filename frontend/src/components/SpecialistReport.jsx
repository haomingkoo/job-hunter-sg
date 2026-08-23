/**
 * One specialist's verdict on the target role.
 *
 * The submission carries strengths, weaknesses and evidence gaps alongside the summary.
 * Those are the actionable parts, so they are rendered rather than dropped.
 */

const PERSONA_NAMES = {
  recruiter: "Recruiter",
  hiring_manager: "Hiring manager",
  ats: "ATS and parsing",
  skeptic: "Evidence skeptic",
  market_researcher: "Market researcher",
  recruiter_screen_reviewer: "Recruiter screen",
  hiring_manager_reviewer: "Hiring manager",
  ats_parsing_reviewer: "ATS and parsing",
  evidence_skeptic_reviewer: "Evidence skeptic",
  target_market_reviewer: "Target-market analyst",
};

function personaName(personaId) {
  if (!personaId) return "Specialist";
  return PERSONA_NAMES[personaId] || personaId.replaceAll("_", " ");
}

function scoreTone(score) {
  if (score >= 70) return { bar: "bg-emerald-500", text: "text-emerald-800" };
  if (score >= 45) return { bar: "bg-amber-500", text: "text-amber-800" };
  return { bar: "bg-rose-500", text: "text-rose-800" };
}

function FindingList({ title, items, marker }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-3">
      <h4 className="text-[11px] font-semibold uppercase tracking-wide text-[#4A6785]">{title}</h4>
      <ul className="mt-1.5 space-y-1">
        {items.map((item) => {
          const statement = typeof item === "string" ? item : item.statement;
          const citations = typeof item === "string" ? [] : [
            ...(item.criterion_ids || []),
            ...(item.candidate_profile_field_ids || []),
            ...(item.resume_evidence_ids || []),
          ];
          return (
          <li key={statement} className="flex gap-2 text-xs leading-relaxed text-[#33506B]">
            <span aria-hidden="true" className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${marker}`} />
            <span>
              {statement}
              {citations.length > 0 && (
                <span className="mt-0.5 block font-mono text-[10px] text-[#6A89A7]">
                  {citations.join(" · ")}
                </span>
              )}
            </span>
          </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function SpecialistReport({ run }) {
  const submission = run.submission;

  if (!submission) {
    return (
      <article className="rounded-2xl border border-[#DCE7F2] p-4">
        <h3 className="text-sm font-semibold text-[#384959]">{personaName(run.persona_id)}</h3>
        <p className="mt-2 text-xs text-amber-800">
          This specialist did not return a verdict ({run.failure_type || "unknown reason"}, {run.attempt_count || 0}{" "}
          attempts). The rest of the assessment is unaffected.
        </p>
      </article>
    );
  }

  const score = Number(submission.score);
  const tone = scoreTone(score);
  const findings = submission.findings || [];
  const strengths = findings.length > 0
    ? findings.filter((item) => item.kind === "strength")
    : submission.strengths;
  const weaknesses = findings.length > 0
    ? findings.filter((item) => item.kind === "weakness")
    : submission.weaknesses;
  const evidenceGaps = findings.length > 0
    ? findings.filter((item) => item.kind === "evidence_gap")
    : submission.evidence_gaps;

  return (
    <article className="rounded-2xl border border-[#DCE7F2] p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#384959]">{personaName(submission.persona_id || run.persona_id)}</h3>
        {Number.isFinite(score) && (
          <div className="shrink-0 text-right">
            <span className={`text-sm font-bold tabular-nums ${tone.text}`}>{score}</span>
            <span className="text-[11px] text-[#4A6785]">/100</span>
            <div className="mt-1 h-1 w-20 overflow-hidden rounded-full bg-[#EDF3F9]">
              <div
                className={`h-full rounded-full ${tone.bar}`}
                style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {submission.summary && (
        <p className="mt-2 text-sm leading-relaxed text-[#33506B]">{submission.summary}</p>
      )}

      <FindingList title="Strengths" items={strengths} marker="bg-emerald-500" />
      <FindingList title="Weaknesses" items={weaknesses} marker="bg-rose-400" />
      <FindingList title="Evidence gaps" items={evidenceGaps} marker="bg-amber-500" />

      {submission.score_reason && (
        <p className="mt-3 border-t border-[#EDF3F9] pt-2 text-[11px] leading-relaxed text-[#4A6785]">
          {submission.score_reason}
        </p>
      )}

      {findings.length === 0 && [...(submission.criterion_ids || []), ...(submission.candidate_profile_field_ids || []), ...(submission.resume_evidence_ids || [])].length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Evidence citations">
          {[...(submission.criterion_ids || []), ...(submission.candidate_profile_field_ids || []), ...(submission.resume_evidence_ids || [])].map((citation) => (
            <span key={citation} className="rounded-md bg-[#EDF3F9] px-1.5 py-0.5 font-mono text-[10px] text-[#4A6785]">
              {citation}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}
