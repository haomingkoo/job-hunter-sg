import { useState } from "react";

/** Pending edits; acceptance creates a new resume version. */
export default function ProposedEditsPanel({ edits, onAccept, onReject, onStartConversation, busy, result }) {
  const [rejecting, setRejecting] = useState(() => new Set());
  const pendingEdits = Array.isArray(edits) ? edits : [];

  if (pendingEdits.length === 0 && !result) return null;

  const applicable = pendingEdits.filter((edit) => edit.applicable);
  const stale = pendingEdits.filter((edit) => !edit.applicable);

  return (
    <section aria-labelledby="proposed-edits-title" className="mt-6 border-t border-[#DCE7F2] pt-5">
      {pendingEdits.length > 0 && <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="proposed-edits-title" className="text-sm font-semibold text-[#384959]">
            Suggested resume edits
          </h2>
          <p className="mt-0.5 text-xs text-[#4A6785]">
            {applicable.length} drafted from your own evidence. Accepting saves a new version and leaves
            your master resume untouched.
          </p>
        </div>
        {applicable.length > 0 && (
          <button
            type="button"
            onClick={() => onAccept(null)}
            disabled={busy}
            className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-semibold text-white transition-opacity disabled:opacity-40"
          >
            {busy ? "Saving" : `Accept all ${applicable.length}`}
          </button>
        )}
      </div>}

      {result && (
        <div role="status" className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          <span>
            Saved as “{result.label}”.{" "}
            {result.stale_edit_ids?.length > 0 &&
              `${result.stale_edit_ids.length} edit(s) were skipped because your resume had changed since they were drafted.`}
          </span>
          {onStartConversation && (
            <button
              type="button"
              onClick={() => onStartConversation(result.resume_version_id)}
              className="rounded-lg border border-emerald-700 px-2.5 py-1 font-semibold"
            >
              Start conversation with this version
            </button>
          )}
        </div>
      )}

      <ol className="mt-3 space-y-3">
        {applicable.map((edit) => (
          <li key={edit.id} className="rounded-2xl border border-[#DCE7F2] p-3">
            {edit.section_key && (
              <p className="text-[11px] font-semibold uppercase tracking-wide text-[#4A6785]">
                {edit.section_key.replaceAll("_", " ")}
              </p>
            )}
            <p className="mt-1.5 text-xs leading-relaxed text-[#4A6785] line-through decoration-rose-300">
              {edit.original}
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-[#33506B]">{edit.rewrite}</p>
            {(edit.evidence_refs || []).map((evidence) => (
              <blockquote
                key={evidence.evidence_id}
                className="mt-2 border-l-2 border-emerald-300 pl-2 text-xs leading-relaxed text-emerald-800"
              >
                Candidate confirmed: “{evidence.evidence_quote}”
              </blockquote>
            ))}
            <div className="mt-2 flex gap-2">
              <button
                type="button"
                onClick={() => onAccept([edit.id])}
                disabled={busy}
                className="rounded-lg border border-[#384959] px-2.5 py-1 text-[11px] font-medium text-[#384959] disabled:opacity-40"
              >
                Accept
              </button>
              <button
                type="button"
                onClick={() => {
                  setRejecting((prev) => new Set(prev).add(edit.id));
                  onReject([edit.id]);
                }}
                disabled={busy || rejecting.has(edit.id)}
                className="rounded-lg px-2.5 py-1 text-[11px] font-medium text-[#4A6785] hover:text-[#384959] disabled:opacity-40"
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ol>

      {stale.length > 0 && (
        <p className="mt-3 text-[11px] leading-relaxed text-[#4A6785]">
          {stale.length} further edit{stale.length === 1 ? " was" : "s were"} drafted against wording your
          resume no longer contains, so {stale.length === 1 ? "it is" : "they are"} not offered here.
        </p>
      )}
    </section>
  );
}
