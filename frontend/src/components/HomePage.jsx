import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { displayJobTitle, formatPostingDate } from "../lib/helpers.js";
import TourDialog from "./TourDialog.jsx";

const LATEST_ROLE_COUNT = 6;

export function parsePublicJobStats(payload) {
  const total = Number(payload?.total);
  const sources = payload?.filter_meta?.sources;
  if (!Number.isSafeInteger(total) || total < 0 || !Array.isArray(sources)) return null;
  return {
    jobCount: total,
    sourceCount: sources.filter((source) => Number(source?.count) > 0).length,
  };
}

function LatestRoles({ status, jobs, count, onNavigate }) {
  if (status === "unavailable") {
    return (
      <div className="rounded-[10px] border border-line bg-white px-5 py-6">
        <p className="text-sm text-ink">The newest postings could not load just now.</p>
        <button type="button" onClick={() => onNavigate("jobs")} className="mt-2 min-h-11 text-sm font-semibold text-accent underline-offset-2 hover:underline">
          Open the job search
        </button>
      </div>
    );
  }
  return (
    <section aria-labelledby="newest-heading" className="rounded-[10px] border border-line bg-white">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-5 py-3">
        <h2 id="newest-heading" className="text-base font-semibold text-ink">Newest postings</h2>
        <span className="text-xs text-muted">New jobs are added every night</span>
      </div>
      <ul className="divide-y divide-line" aria-busy={status === "loading"}>
        {status === "loading"
          ? Array.from({ length: LATEST_ROLE_COUNT }, (_, i) => (
            <li key={i} className="px-5 py-4" aria-hidden="true">
              <div className="h-3.5 w-3/4 rounded bg-paper" />
              <div className="mt-2 h-3 w-1/2 rounded bg-paper" />
            </li>
          ))
          : jobs.map((job) => {
            const posted = formatPostingDate(job.posted_date, { year: false });
            return (
              <li key={job.id}>
                <button
                  type="button"
                  onClick={() => onNavigate("jobs")}
                  className="grid min-h-11 w-full grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-5 py-3 text-left transition-colors hover:bg-tint focus-visible:-outline-offset-2"
                >
                  <span className="min-w-0 truncate text-base font-semibold text-ink">{displayJobTitle(job.title)}</span>
                  <span className="whitespace-nowrap text-right text-sm font-medium tabular-nums text-ink">{job.salary || ""}</span>
                  <span className="min-w-0 truncate text-sm text-muted">
                    {[job.company, job.location].filter(Boolean).join(" · ")}
                  </span>
                  <span className="whitespace-nowrap text-right text-xs tabular-nums text-muted">{posted && `Posted ${posted}`}</span>
                </button>
              </li>
            );
          })}
      </ul>
      {status === "available" && (
        <div className="border-t border-line px-5 py-2">
          <button type="button" onClick={() => onNavigate("jobs")} className="min-h-11 text-sm font-semibold text-accent underline-offset-2 hover:underline">
            {count ? `See all ${count} jobs` : "See all jobs"}
          </button>
        </div>
      )}
    </section>
  );
}

export default function HomePage({ onNavigate, onSearch }) {
  const [jobStats, setJobStats] = useState({ status: "loading", jobCount: null, sourceCount: null });
  const [latestJobs, setLatestJobs] = useState([]);
  const [searchText, setSearchText] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch(`/api/jobs?page=1&per_page=${LATEST_ROLE_COUNT}&sort=newest`);
        const d = await r.json();
        const parsed = parsePublicJobStats(d);
        if (cancelled) return;
        setJobStats(parsed ? { status: "available", ...parsed } : { status: "unavailable", jobCount: null, sourceCount: null });
        setLatestJobs(Array.isArray(d?.jobs) ? d.jobs.slice(0, LATEST_ROLE_COUNT) : []);
      } catch {
        if (!cancelled) setJobStats({ status: "unavailable", jobCount: null, sourceCount: null });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const count = jobStats.status === "available" && jobStats.jobCount > 0
    ? jobStats.jobCount.toLocaleString("en-SG")
    : null;
  const latestStatus = jobStats.status === "available" && latestJobs.length === 0 ? "unavailable" : jobStats.status;

  return (
    <div className="font-body w-full">
      <section className="px-4 pb-12 pt-10 sm:px-6 sm:pt-16">
        <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:grid-rows-[auto_1fr] lg:items-start">
          <div className="min-w-0 lg:col-start-1 lg:row-start-1 lg:pt-4">
            <h1 className="font-display text-[2.5rem] leading-[1.1] tracking-[-0.02em] text-ink">
              Find a job in Singapore
            </h1>
            <p className="mt-4 max-w-[46ch] text-base leading-relaxed text-muted">
              Search {count ? <span className="tabular-nums">{count}</span> : "the"} current postings from MyCareersFuture and Careers@Gov, then check your resume against the one you want.
            </p>

            <form
              role="search"
              className="mt-8 flex max-w-xl flex-col gap-2 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                onSearch(searchText.trim());
              }}
            >
              <label htmlFor="home-search" className="sr-only">Search jobs</label>
              <input
                id="home-search"
                type="search"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="Role, skill or company"
                enterKeyHint="search"
                className="min-h-12 min-w-0 flex-1 rounded-md border border-field bg-white px-4 text-base text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
              />
              <button
                type="submit"
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-md bg-accent px-6 text-base font-semibold text-white transition-colors hover:bg-accent-hover"
              >
                <Search size={16} aria-hidden="true" /> Search jobs
              </button>
            </form>
            <p className="mt-3 text-sm text-muted">Free. You can browse without an account.</p>
            <TourDialog />
          </div>

          <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1">
            <LatestRoles status={latestStatus} jobs={latestJobs} count={count} onNavigate={onNavigate} />
          </div>
          <div className="min-w-0 max-w-[46ch] border-t border-line pt-6 lg:col-start-1 lg:row-start-2">
            <h2 className="text-base font-semibold text-ink">Already have a posting in mind?</h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              Upload your resume to see which of the posting's skills it already covers, then rewrite it for that role using only your own experience.
            </p>
            <button
              type="button"
              onClick={() => onNavigate("resume")}
              className="mt-2 min-h-11 text-sm font-semibold text-accent underline-offset-2 hover:underline"
            >
              Check my resume
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
