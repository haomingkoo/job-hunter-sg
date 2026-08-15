import { useEffect, useMemo, useState } from "react";
import { Copy, Download, FileText, Loader2, Search } from "lucide-react";

import { apiFetch, downloadBlob } from "../lib/api.js";

const timestamp = (document) => new Date(document.updated_at || document.created_at || 0).getTime();

export function filterDocuments(documents, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return documents;
  return documents.filter((document) => [
    document.type,
    document.label,
    document.company,
    document.role,
  ].some((value) => String(value || "").toLowerCase().includes(needle)));
}

export default function DocumentsTab({ onOpenResume }) {
  const [documents, setDocuments] = useState([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([apiFetch("/api/resume/versions"), apiFetch("/api/tracked")])
      .then(async ([resumeResponse, trackedResponse]) => {
        const [resumes, applications] = await Promise.all([
          resumeResponse.json(),
          trackedResponse.json(),
        ]);
        if (cancelled) return;
        const resumeDocuments = (Array.isArray(resumes) ? resumes : []).map((resume) => ({
          ...resume,
          documentId: `resume:${resume.id}`,
          type: "resume",
          role: resume.job_title,
          company: resume.job_company,
        }));
        const coverLetters = (Array.isArray(applications) ? applications : []).flatMap((application) => {
          const letter = application.role_metadata?.cover_letter;
          if (!letter?.content) return [];
          return [{
            ...letter,
            documentId: `cover-letter:${application.id}`,
            type: "cover letter",
            label: `Cover letter for ${application.role}`,
            role: application.role,
            company: application.company,
          }];
        });
        setDocuments([...resumeDocuments, ...coverLetters].sort((left, right) => timestamp(right) - timestamp(left)));
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Documents could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const visibleDocuments = useMemo(() => filterDocuments(documents, query), [documents, query]);

  const copyLetter = async (document) => {
    await navigator.clipboard.writeText(document.content);
    setCopiedId(document.documentId);
  };

  const downloadLetter = (document) => {
    const safe = `${document.company}_${document.role}`.replace(/[^a-zA-Z0-9]+/g, "_");
    downloadBlob(new Blob([document.content], { type: "text/plain;charset=utf-8" }), `Cover_Letter_${safe}.txt`);
  };

  if (loading) return <div className="flex items-center gap-2 py-16 text-[#6A89A7]"><Loader2 className="animate-spin" size={18} /> Loading documents...</div>;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-2xl font-bold text-[#384959]">Documents</h2>
        <p className="mt-1 text-sm text-[#6A89A7]">Saved resume versions and the latest cover letter for each tracked application.</p>
      </div>
      <label className="flex max-w-xl items-center gap-2 rounded-lg border border-[#BDDDFC]/40 bg-white px-3 py-2">
        <Search size={16} className="text-[#6A89A7]" />
        <input aria-label="Search documents" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search type, label, company, or role" className="w-full bg-transparent text-sm outline-none" />
      </label>
      {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {!error && visibleDocuments.length === 0 && <div className="rounded-xl border border-dashed border-[#BDDDFC] p-10 text-center text-sm text-[#6A89A7]">No matching documents.</div>}
      <div className="grid gap-4 md:grid-cols-2">
        {visibleDocuments.map((document) => (
          <article key={document.documentId} className="rounded-xl border border-[#BDDDFC]/40 bg-white p-4 shadow-sm">
            <div className="flex items-start gap-3">
              <FileText size={18} className="mt-0.5 text-[#6A89A7]" />
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">{document.type}</div>
                <h3 className="mt-1 truncate font-semibold text-[#384959]">{document.label}</h3>
                {(document.company || document.role) && <p className="mt-1 text-xs text-[#6A89A7]">{[document.role, document.company].filter(Boolean).join(" at ")}</p>}
              </div>
            </div>
            {document.type === "resume" ? (
              <button type="button" onClick={() => onOpenResume(document.id)} className="mt-4 rounded-lg bg-[#384959] px-3 py-2 text-xs font-medium text-white">Open resume</button>
            ) : (
              <details className="mt-4">
                <summary className="cursor-pointer text-sm font-medium text-[#384959]">View cover letter</summary>
                <p className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-[#f7fafc] p-3 text-sm leading-relaxed text-[#384959]">{document.content}</p>
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={() => copyLetter(document)} className="flex items-center gap-1 rounded-lg border border-[#BDDDFC] px-3 py-2 text-xs text-[#384959]"><Copy size={13} /> {copiedId === document.documentId ? "Copied" : "Copy"}</button>
                  <button type="button" onClick={() => downloadLetter(document)} className="flex items-center gap-1 rounded-lg border border-[#BDDDFC] px-3 py-2 text-xs text-[#384959]"><Download size={13} /> Download .txt</button>
                </div>
              </details>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
