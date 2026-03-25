import { useEffect, useRef, useState, useCallback } from "react";
import {
  Search, FileText, BarChart2, ChevronRight, ArrowRight,
  Shield, Zap, MapPin, GraduationCap, Repeat, Award,
  Target, Sparkles, TrendingUp, CheckCircle, Briefcase,
  Clock, Star, Layers, ChevronDown,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

/* ─── Reveal ──────────────────────────────────────────────────────────────── */
function Reveal({ children, className = "", delay = 0 }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setTimeout(() => { el.classList.add("revealed"); }, delay); obs.unobserve(el); } },
      { threshold: 0.08 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [delay]);
  return (
    <div ref={ref} className={`reveal-base ${className}`}>
      {children}
    </div>
  );
}

/* ─── Animated counter ────────────────────────────────────────────────────── */
function Counter({ target, suffix = "" }) {
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
            const p = Math.min((now - start) / 1600, 1);
            setValue(Math.floor((1 - Math.pow(1 - p, 3)) * target));
            if (p < 1) requestAnimationFrame(animate); else setValue(target);
          };
          requestAnimationFrame(animate);
          obs.unobserve(el);
        }
      },
      { threshold: 0.3 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [target]);
  return <span ref={ref}>{value.toLocaleString()}{suffix}</span>;
}

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function HomePage({ onNavigate }) {
  const [jobCount, setJobCount] = useState(null);
  const guideRef = useRef(null);

  useEffect(() => {
    let c = false;
    (async () => {
      try {
        const r = await apiFetch("/api/jobs?page=1&per_page=1");
        const d = await r.json();
        if (!c && d.total) setJobCount(d.total);
      } catch { /* */ }
    })();
    return () => { c = true; };
  }, []);

  const count = jobCount != null ? jobCount.toLocaleString() : "70,000";
  const countNum = jobCount || 70000;

  return (
    <div className="font-body w-full bg-[#fafbfc]">

      {/* ═══════ HERO ═════════════════════════════════════════════════════════
          Product-first hero. No stock photos. The UI IS the hero.
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden">
        {/* Background: subtle warm mesh gradient */}
        <div className="absolute inset-0 bg-gradient-to-br from-slate-50 via-white to-sky-50/40" />
        <div className="absolute top-0 right-0 w-[60%] h-[80%] opacity-30" style={{ background: "radial-gradient(ellipse at 70% 20%, rgba(56,189,248,0.15) 0%, transparent 60%)" }} />
        <div className="absolute bottom-0 left-0 w-[40%] h-[60%] opacity-20" style={{ background: "radial-gradient(ellipse at 20% 80%, rgba(20,184,166,0.12) 0%, transparent 60%)" }} />

        <div className="relative mx-auto max-w-6xl px-6 pt-16 pb-20 sm:pt-24 sm:pb-28 lg:pt-28 lg:pb-32">
          <div className="grid items-center gap-12 lg:grid-cols-[1fr_1.1fr]">
            {/* Left: copy */}
            <div className="max-w-xl">
              <div className="hero-stagger-1 inline-flex items-center gap-2 rounded-full border border-sky-200/60 bg-sky-50/80 px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-sky-600">
                <div className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse" />
                Helping Singapore professionals find meaningful work
              </div>

              <h1 className="hero-stagger-2 font-display mt-7 text-[2.5rem] leading-[1.08] tracking-tight text-slate-900 sm:text-[3.25rem] lg:text-[3.75rem]">
                Connecting you to your <span className="text-sky-600">dream job</span>
              </h1>

              <p className="hero-stagger-3 mt-5 text-lg leading-relaxed text-slate-500 sm:text-[1.15rem]">
                Your next chapter is out there. We search {count}+ Singapore listings, prepare your resume to stand out, and give you the confidence to go after the role you really want.
              </p>

              <div className="hero-stagger-4 mt-8 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onNavigate("scraper")}
                  className="group inline-flex items-center gap-2.5 rounded-xl bg-slate-900 px-6 py-3.5 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:bg-slate-800 hover:shadow-md active:scale-[0.97]"
                >
                  Find Your Role <ArrowRight size={15} className="transition-transform duration-200 group-hover:translate-x-0.5" />
                </button>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-6 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-all duration-200 hover:border-slate-300 hover:shadow-md active:scale-[0.97]"
                >
                  <Sparkles size={15} className="text-sky-500" /> Score My Resume
                </button>
              </div>

              <div className="hero-stagger-5 mt-6 flex items-center gap-5 text-[13px] text-slate-400">
                <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-emerald-400" /> Free to use</span>
                <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-emerald-400" /> No sign-up needed</span>
              </div>
            </div>

            {/* Right: product preview - the actual UI */}
            <div className="hero-stagger-3 relative">
              {/* Glow behind the card */}
              <div className="absolute -inset-4 rounded-3xl bg-gradient-to-br from-sky-100/50 via-transparent to-teal-100/30 blur-2xl" />

              <div className="relative rounded-2xl border border-slate-200/80 bg-white shadow-xl shadow-slate-200/50 overflow-hidden">
                {/* Browser chrome */}
                <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50/80 px-4 py-2.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
                  <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
                  <span className="h-2.5 w-2.5 rounded-full bg-slate-200" />
                  <div className="ml-3 flex-1 rounded-md bg-slate-100 px-3 py-1 text-[10px] text-slate-400">jobhunter.kooexperience.com</div>
                </div>

                <div className="p-5">
                  {/* Mini search bar */}
                  <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
                    <Search size={14} className="text-slate-400" />
                    <span className="text-[12px] text-slate-400">Software Engineer, Singapore</span>
                    <div className="ml-auto rounded-md bg-slate-900 px-3 py-1 text-[10px] font-semibold text-white">Search</div>
                  </div>

                  {/* Filter pills */}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {["Full-time", "3-5 yrs", "Technology", "$5K-8K"].map((t) => (
                      <span key={t} className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-0.5 text-[10px] font-medium text-sky-700">{t}</span>
                    ))}
                  </div>

                  {/* Job results */}
                  <div className="mt-4 space-y-2.5">
                    {[
                      { title: "Senior Software Engineer", company: "DBS Bank", loc: "Marina Bay", salary: "$8K-12K", skills: ["Python", "AWS", "Kubernetes"], score: 92 },
                      { title: "Product Manager", company: "Grab", loc: "One-North", salary: "$7K-10K", skills: ["Agile", "SQL", "Analytics"], score: 78 },
                      { title: "Data Analyst", company: "GovTech", loc: "Mapletree", salary: "$5K-8K", skills: ["Tableau", "Python", "R"], score: 85 },
                    ].map((job) => (
                      <div key={job.title} className="group rounded-xl border border-slate-100 p-3 transition hover:border-slate-200 hover:shadow-sm">
                        <div className="flex items-start justify-between">
                          <div>
                            <div className="text-[12px] font-semibold text-slate-800">{job.title}</div>
                            <div className="mt-0.5 text-[11px] text-slate-400">{job.company} &middot; {job.loc} &middot; {job.salary}</div>
                          </div>
                          <div className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${job.score >= 85 ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>
                            {job.score}% match
                          </div>
                        </div>
                        <div className="mt-2 flex gap-1">
                          {job.skills.map((s) => (
                            <span key={s} className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-medium text-slate-500">{s}</span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════ SOCIAL PROOF BAR ═════════════════════════════════════════════ */}
      <Reveal>
        <section className="border-y border-slate-100 bg-white py-6">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-center gap-x-10 gap-y-3 px-6 text-[13px] text-slate-400">
            <span>Data from:</span>
            {["MyCareersFuture", "Careers@Gov", "NodeFlair", "Indeed", "JobStreet"].map((s) => (
              <span key={s} className="font-semibold text-slate-500">{s}</span>
            ))}
          </div>
        </section>
      </Reveal>

      {/* ═══════ 3 PILLARS ════════════════════════════════════════════════════ */}
      <section className="py-20">
        <div className="mx-auto max-w-5xl px-6">
          <Reveal>
            <div className="text-center">
              <h2 className="font-display text-3xl text-slate-900 sm:text-[2.5rem]">Everything between you and your dream role</h2>
              <p className="mx-auto mt-3 max-w-2xl text-[15px] text-slate-500">From discovering the right opportunity to submitting a standout application, we have your back at every step.</p>
            </div>
          </Reveal>

          <div className="mt-14 grid gap-6 sm:grid-cols-3">
            {[
              {
                icon: Search, label: "Discover Opportunities",
                desc: "See every role that matches your ambitions, from 5 major Singapore job portals in one place. Know exactly what each employer is looking for.",
                tab: "scraper", accent: "sky",
              },
              {
                icon: FileText, label: "Prepare With Confidence",
                desc: "Understand how your resume stacks up. Get honest feedback, fill the gaps, and tailor your story for the role you want most.",
                tab: "resume", accent: "violet",
              },
              {
                icon: BarChart2, label: "Understand the Market",
                desc: "Know which skills are in demand, which sectors are growing, and where the opportunities are before you make your move.",
                tab: "analytics", accent: "teal",
              },
            ].map((c, i) => {
              const accents = {
                sky: { bg: "bg-sky-500", light: "bg-sky-50 text-sky-600 border-sky-100", ring: "group-hover:ring-sky-200" },
                violet: { bg: "bg-violet-500", light: "bg-violet-50 text-violet-600 border-violet-100", ring: "group-hover:ring-violet-200" },
                teal: { bg: "bg-teal-500", light: "bg-teal-50 text-teal-600 border-teal-100", ring: "group-hover:ring-teal-200" },
              }[c.accent];
              return (
                <Reveal key={c.tab} delay={i * 60}>
                  <button
                    type="button"
                    onClick={() => onNavigate(c.tab)}
                    className={`group flex h-full flex-col rounded-2xl border border-slate-200/80 bg-white p-6 text-left transition-all duration-200 hover:shadow-lg hover:ring-1 active:scale-[0.98] ${accents.ring}`}
                  >
                    <div className={`flex h-10 w-10 items-center justify-center rounded-xl border ${accents.light}`}>
                      <c.icon size={18} strokeWidth={1.8} />
                    </div>
                    <h3 className="mt-4 text-[15px] font-semibold text-slate-900">{c.label}</h3>
                    <p className="mt-2 flex-1 text-[13px] leading-relaxed text-slate-500">{c.desc}</p>
                    <span className="mt-4 flex items-center gap-1.5 text-xs font-semibold text-slate-400 transition group-hover:text-slate-600">
                      Try it <ChevronRight size={13} className="transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </button>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ═══════ HOW IT WORKS ═════════════════════════════════════════════════ */}
      <section ref={guideRef} className="scroll-mt-12 bg-white py-20">
        <div className="mx-auto max-w-5xl px-6">
          <Reveal>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-500">Your journey</p>
            <h2 className="font-display mt-2 text-3xl text-slate-900 sm:text-[2.25rem]">From searching to hired, step by step</h2>
          </Reveal>

          {/* Step 1 */}
          <Reveal className="mt-16">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-sky-100 text-[11px] font-bold text-sky-600">1</span>
                <h3 className="font-display mt-4 text-[1.5rem] text-slate-900">Explore what's out there</h3>
                <p className="mt-3 text-[14px] leading-relaxed text-slate-500">
                  Browse {count}+ roles across Singapore's top job portals. Every listing shows the skills employers actually care about, so you can focus your energy on the right opportunities.
                </p>
                <button type="button" onClick={() => onNavigate("scraper")} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-sky-600 transition hover:gap-3">
                  Try job search <ArrowRight size={14} />
                </button>
              </div>
              {/* Compact product mockup */}
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
                <div className="flex gap-2">
                  {["Full-time", "3-5 yrs", "$5K+", "Technology"].map((f) => (
                    <span key={f} className="rounded-full bg-white px-2.5 py-1 text-[10px] font-medium text-slate-600 shadow-sm border border-slate-100">{f}</span>
                  ))}
                </div>
                <div className="mt-3 space-y-2">
                  {[
                    { t: "Senior Software Engineer", c: "DBS Bank", s: ["Python", "AWS"] },
                    { t: "Data Analyst", c: "GovTech", s: ["SQL", "Tableau"] },
                  ].map((j) => (
                    <div key={j.t} className="rounded-lg bg-white p-3 shadow-sm border border-slate-100">
                      <div className="text-[11px] font-semibold text-slate-800">{j.t}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">{j.c}</div>
                      <div className="mt-1.5 flex gap-1">{j.s.map((s) => <span key={s} className="rounded bg-sky-50 px-1.5 py-0.5 text-[9px] font-medium text-sky-600">{s}</span>)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Reveal>

          {/* Step 2 */}
          <Reveal className="mt-20">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div className="order-2 lg:order-1">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 shadow-sm">
                  <div className="flex items-start gap-5">
                    <div className="text-center shrink-0">
                      <div className="relative h-[68px] w-[68px]">
                        <svg viewBox="0 0 36 36" className="h-[68px] w-[68px] -rotate-90">
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="#e2e8f0" strokeWidth="2.5" />
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="#0ea5e9" strokeWidth="2.5" strokeDasharray="85 100" strokeLinecap="round" />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-slate-900">87</span>
                      </div>
                      <div className="mt-1 text-[9px] font-semibold uppercase tracking-wider text-slate-400">ATS Score</div>
                    </div>
                    <div className="flex-1 space-y-2.5 pt-1">
                      {[
                        { l: "Impact", p: 91, c: "bg-sky-500" },
                        { l: "Presentation", p: 84, c: "bg-violet-500" },
                        { l: "Competencies", p: 80, c: "bg-teal-500" },
                      ].map((d) => (
                        <div key={d.l}>
                          <div className="flex justify-between text-[10px]"><span className="text-slate-500">{d.l}</span><span className="font-semibold text-slate-700">{d.p}%</span></div>
                          <div className="mt-0.5 h-1.5 rounded-full bg-slate-200"><div className={`h-1.5 rounded-full ${d.c}`} style={{ width: `${d.p}%` }} /></div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <div className="order-1 lg:order-2">
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-violet-100 text-[11px] font-bold text-violet-600">2</span>
                <h3 className="font-display mt-4 text-[1.5rem] text-slate-900">See how ready you are</h3>
                <p className="mt-3 text-[14px] leading-relaxed text-slate-500">
                  Upload your resume and find out honestly where you stand. See what's working, what's missing, and get clear guidance on how to close the gap.
                </p>
                <button type="button" onClick={() => onNavigate("resume")} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-violet-600 transition hover:gap-3">
                  Score my resume <ArrowRight size={14} />
                </button>
              </div>
            </div>
          </Reveal>

          {/* Step 3 */}
          <Reveal className="mt-20">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-teal-100 text-[11px] font-bold text-teal-600">3</span>
                <h3 className="font-display mt-4 text-[1.5rem] text-slate-900">Apply with confidence</h3>
                <p className="mt-3 text-[14px] leading-relaxed text-slate-500">
                  Tailor your resume to tell the right story for each role. Every bullet optimized, every keyword in place. Download and submit knowing you put your best foot forward.
                </p>
                <button type="button" onClick={() => onNavigate("resume")} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-teal-600 transition hover:gap-3">
                  Start tailoring <ArrowRight size={14} />
                </button>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 shadow-sm">
                <div className="flex items-center gap-2 mb-3">
                  <span className="rounded bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">MATCHED</span>
                  {["Python", "Agile", "SQL", "AWS"].map((k) => <span key={k} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] text-emerald-600">{k}</span>)}
                </div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="rounded bg-rose-100 px-2 py-0.5 text-[9px] font-bold text-rose-700">GAPS</span>
                  {["Cloud", "CI/CD"].map((k) => <span key={k} className="rounded bg-rose-50 px-1.5 py-0.5 text-[9px] text-rose-600">{k}</span>)}
                </div>
                <div className="space-y-1.5">
                  <div className="rounded-lg border-l-2 border-sky-400 bg-white p-2.5 text-[11px] leading-relaxed text-slate-600 shadow-sm">
                    Led global Conversion Accelerator Program, integrating <strong className="text-sky-700">automation</strong> to optimize fab yield across 4 fabs...
                  </div>
                  <div className="rounded-lg border-l-2 border-emerald-400 bg-white p-2.5 text-[11px] leading-relaxed text-slate-600 shadow-sm">
                    Deployed <strong className="text-emerald-700">deep learning</strong> model (ResNet-50) for wafer misplacement detection, reducing downtime 40%...
                  </div>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ═══════ PERSONAS ═════════════════════════════════════════════════════ */}
      <section className="py-20">
        <div className="mx-auto max-w-5xl px-6">
          <Reveal>
            <div className="text-center">
              <h2 className="font-display text-3xl text-slate-900 sm:text-[2.25rem]">Wherever you are in your journey</h2>
            </div>
          </Reveal>
          <div className="mt-12 grid gap-6 sm:grid-cols-3">
            {[
              { icon: GraduationCap, title: "Starting out", desc: "You've got the degree but not the experience. We help you understand what employers want and put together a resume that gets you through the door.", accent: "sky" },
              { icon: Repeat, title: "Making a change", desc: "Switching careers is scary. We show you which skills already transfer, where the gaps are, and how to tell your story in a way that makes sense to a new industry.", accent: "violet" },
              { icon: Award, title: "Aiming higher", desc: "You know your worth. We help you articulate it precisely, pass the ATS filters at top companies, and present your track record with the impact it deserves.", accent: "teal" },
            ].map((p, i) => {
              const a = { sky: "bg-sky-50 text-sky-600 border-sky-100", violet: "bg-violet-50 text-violet-600 border-violet-100", teal: "bg-teal-50 text-teal-600 border-teal-100" }[p.accent];
              return (
                <Reveal key={p.title} delay={i * 60}>
                  <div className="h-full rounded-2xl border border-slate-200/80 bg-white p-6 transition-all duration-200 hover:shadow-md">
                    <div className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border ${a}`}>
                      <p.icon size={18} strokeWidth={1.8} />
                    </div>
                    <h4 className="mt-4 text-[15px] font-semibold text-slate-900">{p.title}</h4>
                    <p className="mt-2 text-[13px] leading-relaxed text-slate-500">{p.desc}</p>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ═══════ STATS ════════════════════════════════════════════════════════ */}
      <section className="border-y border-slate-100 bg-white py-16">
        <div className="mx-auto max-w-4xl px-6">
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {[
              { v: countNum, s: "+", label: "Job Listings" },
              { v: 5, s: "", label: "Job Sources" },
              { v: 1500, s: "+", label: "Skills Tracked" },
              { v: 24, s: "h", label: "Data Refresh" },
            ].map((s, i) => (
              <Reveal key={s.label} delay={i * 50}>
                <div className="text-center">
                  <div className="font-display text-3xl text-slate-900"><Counter target={s.v} suffix={s.s} /></div>
                  <div className="mt-1 text-xs font-medium text-slate-400">{s.label}</div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════ TRUST ════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="py-16">
          <div className="mx-auto max-w-4xl px-6">
            <div className="grid gap-8 sm:grid-cols-3">
              {[
                { icon: MapPin, title: "Built for Singapore", desc: "Skills taxonomy and resume conventions tailored to the SG job market." },
                { icon: Zap, title: "Intelligent scoring", desc: "ATS keyword extraction, resume scoring, and one-click tailoring." },
                { icon: Shield, title: "Private and free", desc: "Your resume stays on your device. No data leaves your browser." },
              ].map((t) => (
                <div key={t.title} className="flex items-start gap-3.5">
                  <div className="flex-shrink-0 rounded-lg bg-slate-100 p-2.5 text-slate-500"><t.icon size={16} strokeWidth={1.8} /></div>
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{t.title}</div>
                    <div className="mt-0.5 text-[13px] leading-relaxed text-slate-500">{t.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ CTA ══════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="mx-6 mb-12 rounded-3xl bg-slate-900 py-16 sm:mx-8 lg:mx-auto lg:max-w-5xl">
          <div className="mx-auto max-w-2xl px-8 text-center">
            <h2 className="font-display text-2xl text-white sm:text-3xl">Your dream role is closer than you think</h2>
            <p className="mt-3 text-[15px] text-slate-400">Thousands of Singapore professionals have already taken the first step. Your turn.</p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <button type="button" onClick={() => onNavigate("scraper")} className="group inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3.5 text-sm font-semibold text-slate-900 shadow-sm transition-all duration-200 hover:shadow-md active:scale-[0.97]">
                Start Your Journey <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
              </button>
              <button type="button" onClick={() => onNavigate("resume")} className="rounded-xl border border-white/20 px-6 py-3.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-white/10 active:scale-[0.97]">
                Score My Resume
              </button>
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ STYLES ══════════════════════════════════════════════════════ */}
      <style>{`
        .reveal-base {
          opacity: 0;
          transform: translateY(16px);
          transition: opacity 0.5s cubic-bezier(0.23,1,0.32,1), transform 0.5s cubic-bezier(0.23,1,0.32,1);
        }
        .reveal-base.revealed {
          opacity: 1;
          transform: translateY(0);
        }
        .hero-stagger-1 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0s both; }
        .hero-stagger-2 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.08s both; }
        .hero-stagger-3 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.16s both; }
        .hero-stagger-4 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.24s both; }
        .hero-stagger-5 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.32s both; }
        @keyframes heroIn {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (prefers-reduced-motion: reduce) {
          .reveal-base { opacity: 1; transform: none; transition: none; }
          .reveal-base.revealed { transform: none; }
          [class*="hero-stagger"] { animation: none; opacity: 1; transform: none; }
        }
      `}</style>
    </div>
  );
}
