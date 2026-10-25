import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Search, Building2, BarChart2 } from "lucide-react";
import { apiFetch } from "../lib/api.js";

const EASE_OUT = [0.23, 1, 0.32, 1];
const LATEST_ROLE_COUNT = 4;

const heroItem = {
  hidden: { opacity: 0, y: 16 },
  visible: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.6, delay: i * 0.08, ease: EASE_OUT },
  }),
};

const primaryButton = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-[#384959] px-6 py-3 text-sm font-semibold text-white transition-[background-color,transform] duration-100 hover:bg-[#2d3a47] active:scale-[0.97]";
const secondaryButton = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-[#6A89A7]/40 bg-white px-6 py-3 text-sm font-semibold text-[#384959] transition-[border-color,transform] duration-100 hover:border-[#384959] active:scale-[0.97]";

export function parsePublicJobStats(payload) {
  const total = Number(payload?.total);
  const sources = payload?.filter_meta?.sources;
  if (!Number.isSafeInteger(total) || total < 0 || !Array.isArray(sources)) return null;
  return {
    jobCount: total,
    sourceCount: sources.filter((source) => Number(source?.count) > 0).length,
  };
}

function LatestRoles({ status, jobs, onNavigate }) {
  if (status === "unavailable") {
    return (
      <p className="rounded-2xl border border-[#BDDDFC]/60 bg-white p-6 text-sm text-muted">
        Latest roles could not load right now. You can still open the job search.
      </p>
    );
  }
  return (
    <div className="rounded-2xl border border-[#BDDDFC]/60 bg-white shadow-[0_12px_32px_-16px_rgba(56,73,89,0.25)]">
      <div className="flex items-center justify-between border-b border-[#BDDDFC]/40 px-5 py-3.5">
        <h2 className="text-sm font-semibold text-[#384959]">Newest roles</h2>
        <span className="text-xs text-muted">Updated nightly</span>
      </div>
      <ul className="divide-y divide-[#BDDDFC]/40" aria-busy={status === "loading"}>
        {status === "loading"
          ? Array.from({ length: LATEST_ROLE_COUNT }, (_, i) => (
            <li key={i} className="px-5 py-4">
              <div className="h-3.5 w-3/4 rounded bg-[#e3ecf5]" />
              <div className="mt-2 h-3 w-1/2 rounded bg-[#eef3f8]" />
            </li>
          ))
          : jobs.map((job) => (
            <li key={job.id}>
              <button
                type="button"
                onClick={() => onNavigate("jobs")}
                className="flex min-h-11 w-full items-start justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-[#f5f8fb]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[15px] font-semibold text-[#384959]">{job.title}</span>
                  <span className="mt-0.5 flex items-center gap-1.5 truncate text-[13px] text-muted">
                    <Building2 size={13} aria-hidden="true" className="shrink-0" />
                    <span className="truncate">{job.company}</span>
                  </span>
                </span>
                {job.salary && (
                  <span className="shrink-0 whitespace-nowrap text-[13px] font-medium tabular-nums text-[#384959]">{job.salary}</span>
                )}
              </button>
            </li>
          ))}
      </ul>
    </div>
  );
}

function Task({ title, children, action }) {
  return (
    <div>
      <h3 className="font-display text-[1.5rem] leading-tight tracking-[-0.01em] text-[#384959]">{title}</h3>
      <p className="mt-3 max-w-[46ch] text-[15px] leading-relaxed text-muted">{children}</p>
      {action}
    </div>
  );
}

export default function HomePage({ onNavigate }) {
  const [jobStats, setJobStats] = useState({ status: "loading", jobCount: null, sourceCount: null });
  const [latestJobs, setLatestJobs] = useState([]);

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
    ? jobStats.jobCount.toLocaleString()
    : null;
  const latestStatus = jobStats.status === "available" && latestJobs.length === 0 ? "unavailable" : jobStats.status;

  return (
    <div className="relative font-body w-full overflow-x-hidden bg-[#f0f4f8]">

      <section className="relative overflow-hidden px-6 pb-20 pt-16 sm:pt-24 lg:pb-28">
        <div className="relative mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 lg:grid-cols-[1.2fr_1fr]">
          <motion.div initial="hidden" animate="visible" className="min-w-0">
            <motion.h1 variants={heroItem} custom={0} className="font-display text-[2.75rem] leading-[1.05] tracking-[-0.02em] text-[#384959] sm:text-[3.5rem] lg:text-[4rem]">
              Find the role<br />that fits{" "}
              <span className="relative inline-block">
                <span className="relative z-10">you best</span>
                <motion.svg
                  aria-hidden="true"
                  className="absolute -bottom-1 left-0 z-0 w-full"
                  height="8" viewBox="0 0 200 8" preserveAspectRatio="none"
                >
                  <motion.path
                    d="M0 6C50 0 150 0 200 6"
                    stroke="#88BDF2" strokeWidth="3" fill="none" strokeLinecap="round"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ duration: 0.8, delay: 0.5, ease: EASE_OUT }}
                  />
                </motion.svg>
              </span>
            </motion.h1>

            <motion.p variants={heroItem} custom={1} className="mt-6 max-w-[34rem] text-[1.0625rem] leading-relaxed text-muted">
              Search {count ? `${count} current roles` : "current roles"} from MyCareersFuture and Careers@Gov, score your resume against a real posting, and tailor it without inventing experience.
            </motion.p>

            <motion.div variants={heroItem} custom={2} className="mt-8 flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => onNavigate("jobs")} className={primaryButton}>
                <Search size={15} aria-hidden="true" /> Search jobs
              </button>
              <button type="button" onClick={() => onNavigate("resume")} className={secondaryButton}>
                Score my resume
              </button>
            </motion.div>

            <motion.p variants={heroItem} custom={3} className="mt-5 text-[13px] text-muted">
              Free to use. Browsing jobs needs no account.
            </motion.p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2, ease: EASE_OUT }}
            className="min-w-0"
          >
            <LatestRoles status={latestStatus} jobs={latestJobs} onNavigate={onNavigate} />
          </motion.div>
        </div>
      </section>

      <section className="border-t border-[#BDDDFC]/50 bg-white px-6 py-20 sm:py-24">
        <div className="mx-auto max-w-5xl">
          <h2 className="font-display text-[2rem] leading-tight tracking-[-0.015em] text-[#384959] sm:text-[2.5rem]">From search to application</h2>

          <div className="mt-12 grid gap-12 md:grid-cols-3 md:gap-10">
            <Task
              title="Search current roles"
              action={<button type="button" onClick={() => onNavigate("jobs")} className={`mt-5 ${secondaryButton}`}>Search jobs</button>}
            >
              Browse {count ? `${count} roles` : "live roles"} from MyCareersFuture and Careers@Gov. Every listing shows the skills the employer asks for.
            </Task>
            <Task
              title="Score your resume"
              action={<button type="button" onClick={() => onNavigate("resume")} className={`mt-5 ${secondaryButton}`}>Score my resume</button>}
            >
              Upload your resume and see which of a posting's keywords it already covers and which are missing.
            </Task>
            <Task
              title="Tailor it to one posting"
              action={<button type="button" onClick={() => onNavigate("resume")} className={`mt-5 ${secondaryButton}`}>Tailor my resume</button>}
            >
              Rewrite your resume for a specific role, keeping every claim tied to your own experience. Download it and apply.
            </Task>
          </div>
        </div>
      </section>

      <section className="border-t border-[#BDDDFC]/50 bg-[#f0f4f8] px-6 py-14">
        <ul className="mx-auto grid max-w-5xl gap-8 sm:grid-cols-3">
          {[
            { title: "Built for Singapore", desc: "Skills taxonomy and resume conventions tailored to the SG job market." },
            { title: "Scoring you can check", desc: "ATS keyword extraction and resume scoring that show which words matched." },
            { title: "Private and free", desc: "Signed-in resume uploads are saved as private versions you explicitly choose for analysis and tailoring." },
          ].map((t) => (
            <li key={t.title}>
              <h3 className="text-sm font-bold text-[#384959]">{t.title}</h3>
              <p className="mt-1 max-w-[40ch] text-[13px] leading-relaxed text-muted">{t.desc}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="bg-[#384959] px-6 py-20">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="font-display text-[2rem] leading-[1.1] tracking-[-0.015em] text-white sm:text-[2.75rem]">
            Start with the roles open today
          </h2>
          <p className="mx-auto mt-4 max-w-[52ch] text-[15px] leading-relaxed text-[#d6e6f6]">
            Search current roles, test your fit, and keep every resume claim grounded in your own evidence.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => onNavigate("jobs")}
              className="inline-flex min-h-11 items-center gap-2 rounded-full bg-[#88BDF2] px-7 py-3 text-sm font-bold text-[#1f2831] transition-[background-color,transform] duration-100 hover:bg-[#BDDDFC] active:scale-[0.97]"
            >
              Search jobs
            </button>
            <button
              type="button"
              onClick={() => onNavigate("analytics")}
              className="inline-flex min-h-11 items-center gap-2 rounded-full border border-white/40 px-7 py-3 text-sm font-semibold text-white transition-[border-color,transform] duration-100 hover:border-white active:scale-[0.97]"
            >
              <BarChart2 size={15} aria-hidden="true" /> See market insights
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
