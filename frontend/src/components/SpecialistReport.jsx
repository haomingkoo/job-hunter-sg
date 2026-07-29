/**
 * One specialist's verdict on the target role.
 *
 * The submission carries strengths, weaknesses and evidence gaps alongside the summary.
 * Those are the actionable parts, so they are rendered rather than dropped.
 */

const PERSONA_NAMES = {
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
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-xs leading-relaxed text-[#33506B]">
            <span aria-hidden="true" className={`mt-1.5 h-1 w-1 shrink-0 rounded-full ${marker}`} />
            <span>{item}</span>
          </li>
        ))}
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

      <FindingList title="Strengths" items={submission.strengths} marker="bg-emerald-500" />
      <FindingList title="Weaknesses" items={submission.weaknesses} marker="bg-rose-400" />
      <FindingList title="Evidence gaps" items={submission.evidence_gaps} marker="bg-amber-500" />

      {submission.score_reason && (
        <p className="mt-3 border-t border-[#EDF3F9] pt-2 text-[11px] leading-relaxed text-[#4A6785]">
          {submission.score_reason}
        </p>
      )}
    </article>
  );
}
