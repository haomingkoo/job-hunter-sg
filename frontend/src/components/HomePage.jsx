import { useEffect, useRef, useState, useCallback } from "react";
import {
  Search, FileText, BarChart2, ChevronDown, ChevronRight,
  Shield, Zap, MapPin, ArrowRight, GraduationCap, Repeat, Award,
  Target, Sparkles, TrendingUp, CheckCircle, Briefcase, Users,
  Clock, Star, BarChart, Layers,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

/* ─── Scroll-triggered reveal with staggered children ──────────────────────── */
function Reveal({ children, className = "", delay = 0 }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setTimeout(() => {
            el.style.opacity = "1";
            el.style.transform = "translateY(0)";
          }, delay);
          obs.unobserve(el);
        }
      },
      { threshold: 0.1 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [delay]);
  return (
    <div
      ref={ref}
      className={className}
      style={{ opacity: 0, transform: "translateY(32px)", transition: `opacity 0.8s cubic-bezier(0.16,1,0.3,1), transform 0.8s cubic-bezier(0.16,1,0.3,1)` }}
    >
      {children}
    </div>
  );
}

/* ─── Animated counter ─────────────────────────────────────────────────────── */
function AnimatedCount({ target, suffix = "", duration = 1800 }) {
  const ref = useRef(null);
  const [value, setValue] = useState(0);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting && !started.current) {
          started.current = true;
          const start = performance.now();
          const animate = (now) => {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            setValue(Math.floor(eased * target));
            if (progress < 1) requestAnimationFrame(animate);
            else setValue(target);
          };
          requestAnimationFrame(animate);
          obs.unobserve(el);
        }
      },
      { threshold: 0.3 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [target, duration]);
  return <span ref={ref}>{value.toLocaleString()}{suffix}</span>;
}

/* ─── Premium screenshot frame with depth ──────────────────────────────────── */
function AppFrame({ title, children, className = "" }) {
  return (
    <div className={`relative rounded-2xl border border-white/10 bg-gradient-to-b from-slate-800/90 to-slate-900/95 p-1 shadow-2xl shadow-black/30 backdrop-blur-sm ${className}`}>
      <div className="absolute -inset-px rounded-2xl bg-gradient-to-b from-white/[0.08] to-transparent pointer-events-none" />
      <div className="rounded-xl bg-slate-900/80 overflow-hidden">
        <div className="flex items-center gap-1.5 border-b border-white/[0.06] px-4 py-2.5">
          <span className="h-2 w-2 rounded-full bg-rose-400/80" />
          <span className="h-2 w-2 rounded-full bg-amber-400/80" />
          <span className="h-2 w-2 rounded-full bg-emerald-400/80" />
          <span className="ml-3 text-[10px] font-medium text-slate-500">{title}</span>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════
   HOMEPAGE - Editorial Luxe
═══════════════════════════════════════════════════════════════════════════════ */

export default function HomePage({ onNavigate }) {
  const [jobCount, setJobCount] = useState(null);
  const guideRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiFetch("/api/jobs?page=1&per_page=1");
        const d = await r.json();
        if (!cancelled && d.total) setJobCount(d.total);
      } catch { /* fallback */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const count = jobCount != null ? jobCount.toLocaleString() : "70,000";
  const countNum = jobCount || 70000;

  const scrollToGuide = useCallback(() => {
    guideRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  return (
    <div className="font-body w-full">

      {/* ═══════ HERO ═══════════════════════════════════════════════════════════
          Cinematic full-bleed with layered gradients and animated text
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="hero-noise relative min-h-[600px] overflow-hidden sm:min-h-[680px] lg:min-h-[720px]">
        {/* Background photo */}
        <div
          className="absolute inset-0 bg-cover bg-center bg-no-repeat scale-105"
          style={{
            backgroundImage: "url('https://images.unsplash.com/photo-1600880292203-757bb62b4baf?w=1920&q=80&auto=format&fit=crop')",
            animation: "heroZoom 20s ease-in-out infinite alternate",
          }}
        />
        {/* Multi-layer gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-r from-[#0f172a] via-[#0f172a]/95 to-[#0f172a]/40" />
        <div className="absolute inset-0 bg-gradient-to-t from-[#0f172a] via-transparent to-[#0f172a]/30" />
        {/* Subtle radial glow */}
        <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse 60% 50% at 25% 50%, rgba(56,189,248,0.08) 0%, transparent 70%)" }} />

        <div className="relative mx-auto flex max-w-6xl items-center px-6 py-28 sm:py-36 lg:px-8 lg:py-40">
          <div className="max-w-2xl">
            {/* Eyebrow */}
            <div
              className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/[0.08] px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.15em] text-sky-300 backdrop-blur-sm"
              style={{ animation: "fadeSlideUp 0.6s ease-out both" }}
            >
              <MapPin size={12} /> Singapore Job Market Intelligence
            </div>

            {/* Headline with gradient shimmer */}
            <h1
              className="font-display mt-6 text-[2.75rem] leading-[1.1] tracking-tight text-white sm:text-[3.5rem] lg:text-[4rem]"
              style={{ animation: "fadeSlideUp 0.8s ease-out 0.15s both" }}
            >
              Your career move,{" "}
              <span
                className="bg-gradient-to-r from-sky-300 via-cyan-200 to-sky-400 bg-clip-text text-transparent"
                style={{
                  backgroundSize: "200% 100%",
                  animation: "shimmer 3s ease-in-out infinite",
                }}
              >
                optimized.
              </span>
            </h1>

            <p
              className="mt-6 max-w-lg text-[1.05rem] leading-relaxed text-slate-300/90"
              style={{ animation: "fadeSlideUp 0.8s ease-out 0.3s both" }}
            >
              Search {count}+ Singapore jobs. Score your resume against real ATS systems. Tailor every bullet to the role you want.
            </p>

            <div
              className="mt-9 flex flex-wrap items-center gap-4"
              style={{ animation: "fadeSlideUp 0.8s ease-out 0.45s both" }}
            >
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="group relative inline-flex items-center gap-2.5 overflow-hidden rounded-xl bg-sky-500 px-7 py-3.5 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition-all duration-300 hover:bg-sky-400 hover:shadow-xl hover:shadow-sky-500/30 hover:-translate-y-0.5"
              >
                <span className="relative z-10 flex items-center gap-2.5">
                  Search Jobs <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-xl border border-white/15 bg-white/[0.06] px-7 py-3.5 text-sm font-semibold text-white backdrop-blur-md transition-all duration-300 hover:bg-white/[0.12] hover:border-white/25 hover:-translate-y-0.5"
              >
                Score My Resume
              </button>
            </div>

            <p
              className="mt-6 text-[13px] tracking-wide text-slate-500"
              style={{ animation: "fadeSlideUp 0.8s ease-out 0.6s both" }}
            >
              No sign-up required to get started
            </p>
          </div>
        </div>

        {/* Bottom fade */}
        <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-white to-transparent" />
      </section>

      {/* ═══════ ACTION CARDS ═════════════════════════════════════════════════
          Glassmorphism cards overlapping the hero
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="relative z-10 mx-auto -mt-16 max-w-5xl px-6">
        <div className="grid gap-5 sm:grid-cols-3">
          {[
            {
              icon: Search, label: "Find a Job",
              desc: "Search and filter across Singapore's top job portals, enriched with ATS-extracted skill tags.",
              tab: "scraper", accent: "sky",
            },
            {
              icon: FileText, label: "Build Your Resume",
              desc: "Score against real ATS criteria. Get line-by-line coaching and one-click tailoring for any role.",
              tab: "resume", accent: "teal",
            },
            {
              icon: BarChart2, label: "Explore the Market",
              desc: "Discover trending skills, top job titles, and sector breakdowns across the Singapore market.",
              tab: "analytics", accent: "amber",
            },
          ].map((c, i) => {
            const colors = {
              sky: { iconBg: "bg-sky-500/10 text-sky-400", border: "hover:border-sky-400/30", glow: "group-hover:shadow-sky-500/10" },
              teal: { iconBg: "bg-teal-500/10 text-teal-400", border: "hover:border-teal-400/30", glow: "group-hover:shadow-teal-500/10" },
              amber: { iconBg: "bg-amber-500/10 text-amber-400", border: "hover:border-amber-400/30", glow: "group-hover:shadow-amber-500/10" },
            }[c.accent];
            return (
              <Reveal key={c.tab} delay={i * 100}>
                <button
                  type="button"
                  onClick={() => onNavigate(c.tab)}
                  className={`group relative flex h-full flex-col items-start rounded-2xl border border-gray-200/80 bg-white p-7 text-left shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-xl ${colors.border} ${colors.glow}`}
                >
                  <div className={`rounded-xl p-3 ${colors.iconBg}`}>
                    <c.icon size={22} strokeWidth={1.7} />
                  </div>
                  <h3 className="mt-4 text-base font-semibold text-slate-900">{c.label}</h3>
                  <p className="mt-2 flex-1 text-[13px] leading-relaxed text-gray-500">{c.desc}</p>
                  <span className="mt-4 flex items-center gap-1.5 text-xs font-semibold text-gray-400 transition-colors group-hover:text-sky-500">
                    Get started <ChevronRight size={13} className="transition-transform group-hover:translate-x-0.5" />
                  </span>
                </button>
              </Reveal>
            );
          })}
        </div>

        {/* Scroll bridge */}
        <Reveal delay={400} className="mt-14 text-center">
          <button
            type="button"
            onClick={scrollToGuide}
            className="group inline-flex flex-col items-center gap-2 text-xs font-semibold uppercase tracking-[0.15em] text-gray-400 transition hover:text-sky-500"
          >
            Learn how it works
            <ChevronDown size={18} style={{ animation: "fadeSlideUp 1.5s ease-in-out 0s 3" }} />
          </button>
        </Reveal>
      </section>

      {/* ═══════ HOW IT WORKS ═════════════════════════════════════════════════
          3 steps with rich product mockups on dark frames
      ═══════════════════════════════════════════════════════════════════════ */}
      <section ref={guideRef} className="mt-28 scroll-mt-16">
        <div className="mx-auto max-w-6xl px-6">
          <Reveal>
            <div className="text-center">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-500">How it works</p>
              <h2 className="font-display mt-3 text-3xl text-slate-900 sm:text-4xl">Three steps to a stronger application</h2>
              <p className="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-gray-500">
                From discovery to delivery, every tool is designed to give you an edge in Singapore's competitive job market.
              </p>
            </div>
          </Reveal>

          {/* Step 1 */}
          <Reveal className="mt-20">
            <div className="grid items-center gap-12 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-sky-50 px-3.5 py-1.5 text-xs font-bold text-sky-600">
                  <Target size={13} /> Step 01
                </div>
                <h3 className="font-display mt-5 text-[1.65rem] text-slate-900">Search with precision</h3>
                <p className="mt-4 text-[15px] leading-relaxed text-gray-500">
                  Smart filters across {count}+ roles from MyCareersFuture, Careers@Gov, and more. Every listing is enriched with ATS-extracted skill requirements so you know exactly what employers want.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("scraper")}
                  className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-sky-600 transition hover:text-sky-500 hover:gap-3"
                >
                  Try it now <ArrowRight size={14} />
                </button>
              </div>
              <AppFrame title="jobhunter.kooexperience.com/search">
                <div className="space-y-3">
                  {/* Search bar mockup */}
                  <div className="flex items-center gap-2 rounded-lg bg-slate-800/60 px-3 py-2">
                    <Search size={14} className="text-slate-500" />
                    <span className="text-[12px] text-slate-400">Software Engineer, Singapore</span>
                  </div>
                  {/* Filter pills */}
                  <div className="flex flex-wrap gap-1.5">
                    {["Full-time", "3-5 yrs", "Technology", "$5K-8K"].map((t) => (
                      <span key={t} className="rounded-full bg-sky-500/15 px-2.5 py-1 text-[10px] font-medium text-sky-300">{t}</span>
                    ))}
                  </div>
                  {/* Job cards mockup */}
                  {[
                    { title: "Senior Software Engineer", company: "DBS Bank", skills: ["Python", "AWS", "SQL"], salary: "$8,000 - $12,000" },
                    { title: "Data Analyst", company: "GovTech", skills: ["Tableau", "Python", "R"], salary: "$5,500 - $8,000" },
                  ].map((job) => (
                    <div key={job.title} className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3.5">
                      <div className="text-[12px] font-semibold text-slate-200">{job.title}</div>
                      <div className="mt-0.5 text-[11px] text-slate-500">{job.company} &middot; {job.salary}</div>
                      <div className="mt-2 flex gap-1.5">
                        {job.skills.map((s) => (
                          <span key={s} className="rounded-full bg-sky-400/10 px-2 py-0.5 text-[9px] font-medium text-sky-300">{s}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </AppFrame>
            </div>
          </Reveal>

          {/* Step 2 */}
          <Reveal className="mt-28">
            <div className="grid items-center gap-12 lg:grid-cols-2">
              <div className="order-2 lg:order-1">
                <AppFrame title="jobhunter.kooexperience.com/resume">
                  <div className="flex items-start gap-5">
                    {/* Score gauge */}
                    <div className="text-center shrink-0">
                      <div className="relative mx-auto h-[72px] w-[72px]">
                        <svg viewBox="0 0 36 36" className="h-[72px] w-[72px] -rotate-90">
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="2" />
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="#38bdf8" strokeWidth="2" strokeDasharray="85 100" strokeLinecap="round" />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-white">87</span>
                      </div>
                      <div className="mt-1.5 text-[9px] font-medium uppercase tracking-wider text-slate-500">ATS Score</div>
                    </div>
                    {/* Dimension bars */}
                    <div className="flex-1 space-y-3 pt-1">
                      {[
                        { label: "Impact", pct: 91, color: "bg-sky-400" },
                        { label: "Presentation", pct: 84, color: "bg-teal-400" },
                        { label: "Competencies", pct: 80, color: "bg-amber-400" },
                      ].map((d) => (
                        <div key={d.label}>
                          <div className="flex justify-between text-[10px]">
                            <span className="text-slate-400">{d.label}</span>
                            <span className="font-semibold text-slate-300">{d.pct}%</span>
                          </div>
                          <div className="mt-1 h-1.5 rounded-full bg-white/[0.06]">
                            <div className={`h-1.5 rounded-full ${d.color}`} style={{ width: `${d.pct}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </AppFrame>
              </div>
              <div className="order-1 lg:order-2">
                <div className="inline-flex items-center gap-2 rounded-full bg-teal-50 px-3.5 py-1.5 text-xs font-bold text-teal-600">
                  <Sparkles size={13} /> Step 02
                </div>
                <h3 className="font-display mt-5 text-[1.65rem] text-slate-900">Know where you stand</h3>
                <p className="mt-4 text-[15px] leading-relaxed text-gray-500">
                  Upload your resume and get an instant breakdown across Impact, Presentation, and Competencies. See matched keywords, identify gaps, and know exactly where to improve.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-teal-600 transition hover:text-teal-500 hover:gap-3"
                >
                  Score my resume <ArrowRight size={14} />
                </button>
              </div>
            </div>
          </Reveal>

          {/* Step 3 */}
          <Reveal className="mt-28">
            <div className="grid items-center gap-12 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3.5 py-1.5 text-xs font-bold text-amber-600">
                  <TrendingUp size={13} /> Step 03
                </div>
                <h3 className="font-display mt-5 text-[1.65rem] text-slate-900">Tailor with confidence</h3>
                <p className="mt-4 text-[15px] leading-relaxed text-gray-500">
                  One click transforms your resume for any role. Every bullet optimized, every keyword placed strategically. Download as PDF or DOCX and apply with confidence.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-6 inline-flex items-center gap-2 text-sm font-semibold text-amber-600 transition hover:text-amber-500 hover:gap-3"
                >
                  Start tailoring <ArrowRight size={14} />
                </button>
              </div>
              <AppFrame title="jobhunter.kooexperience.com/tailor">
                <div className="space-y-3">
                  {/* Keyword match display */}
                  <div className="flex items-center gap-2.5">
                    <span className="rounded-md bg-teal-500/20 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-teal-300">Matched</span>
                    <div className="flex gap-1.5">
                      {["Python", "Agile", "SQL", "AWS"].map((k) => (
                        <span key={k} className="rounded-full bg-teal-400/10 px-2 py-0.5 text-[10px] font-medium text-teal-300">{k}</span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <span className="rounded-md bg-rose-500/20 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-rose-300">Missing</span>
                    <div className="flex gap-1.5">
                      {["Cloud", "CI/CD"].map((k) => (
                        <span key={k} className="rounded-full bg-rose-400/10 px-2 py-0.5 text-[10px] font-medium text-rose-300">{k}</span>
                      ))}
                    </div>
                  </div>
                  {/* Bullet examples */}
                  <div className="mt-1 space-y-2">
                    <div className="rounded-lg border-l-2 border-sky-400/60 bg-sky-400/[0.06] p-3 text-[11px] leading-relaxed text-slate-300">
                      Led the global Conversion Accelerator Program, integrating <span className="font-semibold text-sky-300">automation</span> to optimize fab yield across 4 fabs...
                    </div>
                    <div className="rounded-lg border-l-2 border-teal-400/60 bg-teal-400/[0.06] p-3 text-[11px] leading-relaxed text-slate-300">
                      Developed and deployed a <span className="font-semibold text-teal-300">deep learning model</span> (ResNet-50) for wafer misplacement detection...
                    </div>
                  </div>
                </div>
              </AppFrame>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ═══════ PERSONAS ═════════════════════════════════════════════════════
          Who this is for - distinct visual identity per persona
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="mt-32">
        <div className="relative overflow-hidden bg-gradient-to-b from-slate-50 to-white py-20">
          {/* Subtle pattern */}
          <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(circle at 1px 1px, #1e293b 1px, transparent 0)", backgroundSize: "32px 32px" }} />
          <div className="relative mx-auto max-w-6xl px-6">
            <Reveal>
              <div className="text-center">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-500">Who is this for</p>
                <h2 className="font-display mt-3 text-3xl text-slate-900 sm:text-4xl">Built for every stage of your career</h2>
              </div>
            </Reveal>
            <div className="mt-14 grid gap-8 sm:grid-cols-3">
              {[
                {
                  icon: GraduationCap, title: "Fresh Graduates",
                  desc: "Understand what employers look for. Get your first resume right and learn how ATS systems filter your application before it reaches a recruiter.",
                  gradient: "from-sky-500/10 to-sky-500/[0.02]", iconBg: "bg-sky-100 text-sky-600", borderHover: "hover:border-sky-200",
                },
                {
                  icon: Repeat, title: "Career Switchers",
                  desc: "See which skills transfer to a new industry. Identify gaps, discover where to upskill, and reframe your experience for a different sector.",
                  gradient: "from-teal-500/10 to-teal-500/[0.02]", iconBg: "bg-teal-100 text-teal-600", borderHover: "hover:border-teal-200",
                },
                {
                  icon: Award, title: "Senior Professionals",
                  desc: "Fine-tune every bullet for executive roles. Ensure your experience passes ATS filters at top companies and articulates real, measurable impact.",
                  gradient: "from-amber-500/10 to-amber-500/[0.02]", iconBg: "bg-amber-100 text-amber-600", borderHover: "hover:border-amber-200",
                },
              ].map((p, i) => (
                <Reveal key={p.title} delay={i * 120}>
                  <div className={`group h-full rounded-2xl border border-gray-200 bg-gradient-to-b ${p.gradient} p-7 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg ${p.borderHover}`}>
                    <div className={`inline-flex rounded-xl p-3 ${p.iconBg} transition-transform group-hover:scale-110`}>
                      <p.icon size={22} strokeWidth={1.7} />
                    </div>
                    <h4 className="mt-5 text-base font-semibold text-slate-900">{p.title}</h4>
                    <p className="mt-3 text-[13px] leading-relaxed text-gray-500">{p.desc}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ═══════ STATS ════════════════════════════════════════════════════════
          Animated counters with premium styling
      ═══════════════════════════════════════════════════════════════════════ */}
      <Reveal className="py-20">
        <div className="mx-auto max-w-5xl px-6">
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {[
              { value: countNum, suffix: "+", label: "Job Listings", icon: Briefcase },
              { value: 5, suffix: "", label: "Job Sources", icon: Layers },
              { value: 1500, suffix: "+", label: "Skills Tracked", icon: Star },
              { value: 24, suffix: "h", label: "Data Refresh", icon: Clock },
            ].map((s, i) => (
              <Reveal key={s.label} delay={i * 80}>
                <div className="group text-center">
                  <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-400 transition-colors group-hover:bg-sky-50 group-hover:text-sky-500">
                    <s.icon size={18} strokeWidth={1.7} />
                  </div>
                  <div className="font-display text-3xl text-slate-900 sm:text-4xl">
                    <AnimatedCount target={s.value} suffix={s.suffix} />
                  </div>
                  <div className="mt-1.5 text-xs font-medium uppercase tracking-wider text-gray-400">{s.label}</div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </Reveal>

      {/* ═══════ TRUST SIGNALS ════════════════════════════════════════════════ */}
      <Reveal>
        <section className="border-y border-gray-100 bg-white py-16">
          <div className="mx-auto max-w-5xl px-6">
            <div className="grid gap-8 sm:grid-cols-3">
              {[
                {
                  icon: MapPin, title: "Built for Singapore",
                  desc: "Skills taxonomy and resume conventions tailored specifically to the Singapore job market.",
                },
                {
                  icon: Zap, title: "Intelligent scoring",
                  desc: "Smart keyword extraction, resume scoring, and one-click tailoring powered by advanced language models.",
                },
                {
                  icon: Shield, title: "Private and free",
                  desc: "Your resume stays on your device. Browse jobs, score resumes, and explore market insights at no cost.",
                },
              ].map((t) => (
                <div key={t.title} className="flex items-start gap-4">
                  <div className="flex-shrink-0 rounded-xl bg-slate-100 p-3 text-slate-500">
                    <t.icon size={18} strokeWidth={1.7} />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{t.title}</div>
                    <div className="mt-1 text-[13px] leading-relaxed text-gray-500">{t.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ CTA FOOTER ══════════════════════════════════════════════════
          Premium gradient section with depth
      ═══════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="relative overflow-hidden bg-[#0f172a] py-24">
          {/* Ambient glow */}
          <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse 50% 80% at 50% 0%, rgba(56,189,248,0.12) 0%, transparent 60%)" }} />
          <div className="absolute inset-0 hero-noise" />
          <div className="relative mx-auto max-w-3xl px-6 text-center">
            <h2 className="font-display text-3xl text-white sm:text-4xl">
              Ready to make your next move?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-slate-400">
              Join job seekers across Singapore using smarter tools to stand out in a competitive market.
            </p>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="group relative inline-flex items-center gap-2.5 rounded-xl bg-sky-500 px-8 py-4 text-sm font-semibold text-white shadow-lg shadow-sky-500/25 transition-all duration-300 hover:bg-sky-400 hover:shadow-xl hover:shadow-sky-500/30 hover:-translate-y-0.5"
              >
                Get Started <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-xl border border-white/15 bg-white/[0.06] px-8 py-4 text-sm font-semibold text-white backdrop-blur-md transition-all duration-300 hover:bg-white/[0.12] hover:border-white/25"
              >
                Score My Resume
              </button>
            </div>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-[13px] text-slate-500">
              {["No sign-up required", "Resume stays private", "Singapore-focused"].map((item) => (
                <span key={item} className="flex items-center gap-2">
                  <CheckCircle size={14} className="text-sky-400/60" />
                  {item}
                </span>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ KEYFRAME ANIMATIONS ═════════════════════════════════════════ */}
      <style>{`
        @keyframes fadeSlideUp {
          from { opacity: 0; transform: translateY(24px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shimmer {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        @keyframes heroZoom {
          from { transform: scale(1.05); }
          to { transform: scale(1.12); }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            transition-duration: 0.01ms !important;
          }
        }
      `}</style>
    </div>
  );
}
