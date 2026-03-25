import { useEffect, useRef, useState, useCallback } from "react";
import {
  Search, FileText, BarChart2, ArrowRight,
  Shield, Zap, MapPin, GraduationCap, Repeat, Award,
  Target, Sparkles, TrendingUp, CheckCircle,
  Heart, Compass, Star, Users, Briefcase, Clock,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

/* ─── Reveal ──────────────────────────────────────────────────────────────── */
function Reveal({ children, className = "", delay = 0 }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setTimeout(() => el.classList.add("revealed"), delay); obs.unobserve(el); } },
      { threshold: 0.08 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [delay]);
  return <div ref={ref} className={`reveal-base ${className}`}>{children}</div>;
}

/* ─── Counter ─────────────────────────────────────────────────────────────── */
function Counter({ target, suffix = "" }) {
  const ref = useRef(null);
  const [value, setValue] = useState(0);
  const started = useRef(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !started.current) {
        started.current = true;
        const t0 = performance.now();
        const step = (now) => {
          const p = Math.min((now - t0) / 1400, 1);
          setValue(Math.floor((1 - Math.pow(1 - p, 3)) * target));
          if (p < 1) requestAnimationFrame(step); else setValue(target);
        };
        requestAnimationFrame(step);
        obs.unobserve(el);
      }
    }, { threshold: 0.3 });
    obs.observe(el);
    return () => obs.disconnect();
  }, [target]);
  return <span ref={ref}>{value.toLocaleString()}{suffix}</span>;
}

/* ─── Decorative shapes (SVG) ─────────────────────────────────────────────── */
function Triangle({ className = "", color = "#e85d3a" }) {
  return (
    <svg className={className} width="28" height="24" viewBox="0 0 28 24" fill="none">
      <path d="M14 0L27.856 24H0.144L14 0Z" fill={color} />
    </svg>
  );
}
function Squiggle({ className = "", color = "#7c6ceb" }) {
  return (
    <svg className={className} width="32" height="16" viewBox="0 0 32 16" fill="none">
      <path d="M0 8C4 2 8 14 12 8C16 2 20 14 24 8C28 2 32 14 32 8" stroke={color} strokeWidth="2.5" strokeLinecap="round" fill="none" />
    </svg>
  );
}
function Dot({ className = "", color = "#7cb9e8" }) {
  return <div className={className} style={{ width: 14, height: 14, borderRadius: "50%", background: color }} />;
}

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function HomePage({ onNavigate }) {
  const [jobCount, setJobCount] = useState(null);

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
    <div className="font-body w-full homepage-grain" style={{ background: "#f5f0e8" }}>

      {/* ═══════ HERO ═════════════════════════════════════════════════════════
          Massive typography. The text IS the design.
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden px-6 pt-12 pb-8 sm:pt-20 sm:pb-12">
        <div className="relative mx-auto max-w-5xl">
          {/* Decorative shapes */}
          <Triangle className="hero-float absolute -top-2 right-[15%] rotate-12 opacity-80 hidden sm:block" color="#e85d3a" />
          <Squiggle className="hero-float absolute top-[30%] -right-4 rotate-6 opacity-70 hidden lg:block" color="#7c6ceb" />
          <Dot className="hero-float absolute top-[20%] left-[5%] hidden sm:block" color="#f5a623" />
          <Triangle className="hero-float absolute bottom-[20%] left-[8%] -rotate-45 opacity-60 hidden sm:block" color="#7c6ceb" />
          <Dot className="hero-float absolute bottom-[10%] right-[25%] hidden sm:block" color="#e85d3a" />

          {/* Main headline */}
          <div className="hero-stagger-1 text-center">
            <p className="text-[13px] font-medium tracking-wide text-stone-500">
              Singapore's career intelligence platform
            </p>
          </div>

          <h1 className="hero-stagger-2 font-display mt-6 text-center text-[3rem] leading-[0.95] tracking-tight text-stone-900 sm:text-[4.5rem] lg:text-[6rem]">
            Find work<br />
            <span className="relative inline-block">
              that
              <svg className="absolute -bottom-1 left-0 w-full" height="8" viewBox="0 0 200 8" preserveAspectRatio="none">
                <path d="M0 6C50 0 150 0 200 6" stroke="#7cb9e8" strokeWidth="3" fill="none" strokeLinecap="round" />
              </svg>
            </span>{" "}
            <span className="italic text-stone-500">matters</span>
          </h1>

          <p className="hero-stagger-3 mx-auto mt-8 max-w-xl text-center text-[1.05rem] leading-relaxed text-stone-500">
            We connect Singapore professionals to their dream roles. Search {count}+ listings, prepare your resume to stand out, and go after the career you deserve.
          </p>

          <div className="hero-stagger-4 mt-10 flex flex-wrap items-center justify-center gap-3">
            <button
              type="button"
              onClick={() => onNavigate("scraper")}
              className="inline-flex items-center gap-2.5 rounded-full bg-slate-900 px-7 py-3.5 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:bg-slate-800 hover:shadow-md active:scale-[0.97]"
            >
              Start exploring <ArrowRight size={15} />
            </button>
            <button
              type="button"
              onClick={() => onNavigate("resume")}
              className="inline-flex items-center gap-2 rounded-full border-2 border-stone-300 bg-transparent px-7 py-3.5 text-sm font-semibold text-stone-700 transition-all duration-200 hover:border-stone-400 hover:bg-stone-100/50 active:scale-[0.97]"
            >
              Score my resume
            </button>
          </div>

          <div className="hero-stagger-5 mt-6 flex items-center justify-center gap-5 text-[13px] text-stone-400">
            <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-emerald-500" /> Free to use</span>
            <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-emerald-500" /> No sign-up needed</span>
          </div>
        </div>
      </section>

      {/* ═══════ VALUE CARDS ══════════════════════════════════════════════════
          Floating tilted cards around bold text (Purpose Talent style)
      ═══════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="relative overflow-hidden px-6 py-16 sm:py-24">
          <div className="relative mx-auto max-w-4xl">
            {/* Big text in center */}
            <h2 className="font-display text-center text-[2rem] leading-[1.05] text-stone-900 sm:text-[3rem] lg:text-[3.5rem]">
              We love connecting<br />
              people who are
            </h2>

            {/* Floating value cards scattered around the text */}
            <div className="mt-12 flex flex-wrap justify-center gap-4">
              {[
                { icon: Compass, label: "Career-driven", desc: "Hungry for the next step", color: "#6b9bd2" },
                { icon: Heart, label: "Purpose-led", desc: "Want work that means something", color: "#c97b84" },
                { icon: Target, label: "Focused", desc: "Know what they're looking for", color: "#7cb9e8" },
                { icon: Star, label: "Ambitious", desc: "Ready to aim higher", color: "#8b7ec8" },
                { icon: TrendingUp, label: "Growing", desc: "Always learning and improving", color: "#6bb89f" },
                { icon: Users, label: "Collaborative", desc: "Thrive in great teams", color: "#c97b84" },
              ].map((v, i) => (
                <div
                  key={v.label}
                  className="group rounded-2xl border border-stone-200/60 bg-white px-5 py-4 shadow-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-1"
                  style={{ transform: `rotate(${(i % 2 === 0 ? -1 : 1) * (1 + i * 0.5)}deg)` }}
                >
                  <div className="flex items-center gap-2.5">
                    <v.icon size={18} style={{ color: v.color }} strokeWidth={2} />
                    <span className="text-sm font-bold text-stone-800">{v.label}</span>
                  </div>
                  <p className="mt-1 text-[12px] text-stone-400">{v.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ THREE PILLARS (dark section) ═════════════════════════════════
          Dark bg with white cards - like Purpose Talent's services section
      ═══════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="relative overflow-hidden bg-stone-900 py-20 sm:py-28">
          {/* Decorative shapes on dark bg */}
          <Triangle className="absolute top-12 left-[10%] opacity-40 hidden lg:block" color="#f5a623" />
          <Squiggle className="absolute bottom-16 right-[8%] opacity-30 hidden lg:block" color="#7c6ceb" />

          <div className="mx-auto max-w-5xl px-6">
            <div className="text-center">
              <p className="text-[12px] font-semibold uppercase tracking-[0.2em] text-stone-500">What we do</p>
              <h2 className="font-display mt-3 text-[2rem] text-white sm:text-[2.75rem]">
                Everything between you<br className="hidden sm:block" /> and your dream role
              </h2>
            </div>

            <div className="mt-14 grid gap-5 sm:grid-cols-3">
              {[
                {
                  icon: Search, num: "01", label: "Discover",
                  desc: "Search {count}+ roles from 5 Singapore portals. Every listing tagged with the skills employers want.",
                  tab: "scraper",
                },
                {
                  icon: FileText, num: "02", label: "Prepare",
                  desc: "Score your resume against real ATS criteria. Get honest feedback and tailor every bullet to stand out.",
                  tab: "resume",
                },
                {
                  icon: BarChart2, num: "03", label: "Understand",
                  desc: "See which skills are trending, which sectors are growing, and where your best opportunities lie.",
                  tab: "analytics",
                },
              ].map((c, i) => (
                <Reveal key={c.tab} delay={i * 80}>
                  <button
                    type="button"
                    onClick={() => onNavigate(c.tab)}
                    className="group flex h-full flex-col rounded-2xl bg-white p-7 text-left transition-all duration-200 hover:shadow-xl hover:-translate-y-1 active:scale-[0.98]"
                  >
                    <div className="flex items-center justify-between w-full">
                      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-500 transition-colors group-hover:bg-sky-50 group-hover:text-sky-600">
                        <c.icon size={20} strokeWidth={1.8} />
                      </div>
                      <span className="text-[11px] font-bold text-stone-300">{c.num}</span>
                    </div>
                    <h3 className="mt-5 text-xl font-bold text-stone-900">{c.label}</h3>
                    <p className="mt-2 flex-1 text-[13px] leading-relaxed text-stone-500">{c.desc.replace("{count}", count)}</p>
                    <span className="mt-5 inline-flex items-center gap-1.5 text-xs font-semibold text-stone-400 transition group-hover:text-sky-600">
                      Get started <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </button>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ HOW IT WORKS ═════════════════════════════════════════════════ */}
      <section className="py-20 sm:py-28 px-6">
        <div className="mx-auto max-w-5xl">
          <Reveal>
            <p className="text-[12px] font-semibold uppercase tracking-[0.2em] text-stone-400">Your journey</p>
            <h2 className="font-display mt-3 text-[2rem] text-stone-900 sm:text-[2.5rem]">
              From searching to hired
            </h2>
          </Reveal>

          {/* Step 1 */}
          <Reveal className="mt-16">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-[12px] font-bold text-sky-700">1</div>
                <h3 className="font-display mt-4 text-[1.5rem] text-stone-900">Explore what's out there</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-stone-500">
                  Browse {count}+ roles across Singapore's top job portals. Every listing shows what employers actually care about, so you focus on the right opportunities.
                </p>
                <button type="button" onClick={() => onNavigate("scraper")} className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-900 px-5 py-2.5 text-[13px] font-semibold text-white transition hover:bg-stone-800 active:scale-[0.97]">
                  Try it <ArrowRight size={13} />
                </button>
              </div>
              <div className="rounded-2xl border border-stone-200/60 bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2 rounded-lg bg-stone-50 px-3 py-2.5 border border-stone-100">
                  <Search size={14} className="text-stone-400" />
                  <span className="text-[12px] text-stone-400">Software Engineer, Singapore</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {["Full-time", "3-5 yrs", "Technology", "$5K+"].map((t) => (
                    <span key={t} className="rounded-full border border-stone-200 px-2.5 py-0.5 text-[10px] font-medium text-stone-600">{t}</span>
                  ))}
                </div>
                <div className="mt-3 space-y-2">
                  {[
                    { t: "Senior Software Engineer", c: "DBS Bank", s: ["Python", "AWS", "SQL"], match: 92 },
                    { t: "Data Analyst", c: "GovTech", s: ["Tableau", "Python"], match: 85 },
                  ].map((j) => (
                    <div key={j.t} className="rounded-xl border border-stone-100 p-3.5">
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="text-[12px] font-semibold text-stone-800">{j.t}</div>
                          <div className="text-[11px] text-stone-400 mt-0.5">{j.c}</div>
                        </div>
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-600">{j.match}%</span>
                      </div>
                      <div className="mt-2 flex gap-1">{j.s.map((s) => <span key={s} className="rounded bg-stone-100 px-1.5 py-0.5 text-[9px] font-medium text-stone-500">{s}</span>)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Reveal>

          {/* Step 2 */}
          <Reveal className="mt-24">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div className="order-2 lg:order-1">
                <div className="rounded-2xl border border-stone-200/60 bg-white p-6 shadow-sm">
                  <div className="flex items-start gap-5">
                    <div className="text-center shrink-0">
                      <div className="relative h-[72px] w-[72px]">
                        <svg viewBox="0 0 36 36" className="h-[72px] w-[72px] -rotate-90">
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="#e7e5e4" strokeWidth="2.5" />
                          <circle cx="18" cy="18" r="15.5" fill="none" stroke="#7cb9e8" strokeWidth="2.5" strokeDasharray="85 100" strokeLinecap="round" />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center text-xl font-bold text-stone-900">87</span>
                      </div>
                      <div className="mt-1.5 text-[9px] font-bold uppercase tracking-wider text-stone-400">Score</div>
                    </div>
                    <div className="flex-1 space-y-3 pt-1">
                      {[
                        { l: "Impact", p: 91, c: "bg-sky-400" },
                        { l: "Presentation", p: 84, c: "bg-violet-400" },
                        { l: "Competencies", p: 80, c: "bg-emerald-400" },
                      ].map((d) => (
                        <div key={d.l}>
                          <div className="flex justify-between text-[10px]"><span className="text-stone-400">{d.l}</span><span className="font-bold text-stone-600">{d.p}%</span></div>
                          <div className="mt-1 h-2 rounded-full bg-stone-100"><div className={`h-2 rounded-full ${d.c}`} style={{ width: `${d.p}%` }} /></div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <div className="order-1 lg:order-2">
                <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-violet-100 text-[12px] font-bold text-violet-700">2</div>
                <h3 className="font-display mt-4 text-[1.5rem] text-stone-900">See how ready you are</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-stone-500">
                  Upload your resume and find out honestly where you stand. See what's working, what's missing, and get clear guidance on closing the gap.
                </p>
                <button type="button" onClick={() => onNavigate("resume")} className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-900 px-5 py-2.5 text-[13px] font-semibold text-white transition hover:bg-stone-800 active:scale-[0.97]">
                  Score my resume <ArrowRight size={13} />
                </button>
              </div>
            </div>
          </Reveal>

          {/* Step 3 */}
          <Reveal className="mt-24">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-emerald-100 text-[12px] font-bold text-emerald-700">3</div>
                <h3 className="font-display mt-4 text-[1.5rem] text-stone-900">Apply with confidence</h3>
                <p className="mt-3 text-[15px] leading-relaxed text-stone-500">
                  Tailor your resume to tell the right story for each role. Every bullet optimized, every keyword placed. Download and submit knowing you put your best foot forward.
                </p>
                <button type="button" onClick={() => onNavigate("resume")} className="mt-5 inline-flex items-center gap-2 rounded-full bg-stone-900 px-5 py-2.5 text-[13px] font-semibold text-white transition hover:bg-stone-800 active:scale-[0.97]">
                  Start tailoring <ArrowRight size={13} />
                </button>
              </div>
              <div className="rounded-2xl border border-stone-200/60 bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2 mb-3">
                  <span className="rounded-md bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">MATCHED</span>
                  {["Python", "Agile", "SQL", "AWS"].map((k) => <span key={k} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-600">{k}</span>)}
                </div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="rounded-md bg-rose-100 px-2 py-0.5 text-[9px] font-bold text-rose-700">GAPS</span>
                  {["Cloud", "CI/CD"].map((k) => <span key={k} className="rounded bg-rose-50 px-1.5 py-0.5 text-[9px] font-medium text-rose-600">{k}</span>)}
                </div>
                <div className="space-y-2">
                  <div className="rounded-xl border-l-[3px] border-sky-400 bg-sky-50/30 p-3 text-[11px] leading-relaxed text-stone-600">
                    Led global Conversion Accelerator Program, integrating <strong className="text-sky-700">automation</strong> to optimize fab yield across 4 fabs...
                  </div>
                  <div className="rounded-xl border-l-[3px] border-emerald-400 bg-emerald-50/30 p-3 text-[11px] leading-relaxed text-stone-600">
                    Deployed <strong className="text-emerald-700">deep learning</strong> model (ResNet-50) for wafer misplacement detection, reducing downtime 40%...
                  </div>
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ═══════ PERSONAS ═════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="py-20 px-6">
          <div className="mx-auto max-w-5xl">
            <h2 className="font-display text-center text-[2rem] text-stone-900 sm:text-[2.5rem]">
              Wherever you are<br className="hidden sm:block" /> in your journey
            </h2>
            <div className="mt-14 grid gap-6 sm:grid-cols-3">
              {[
                { icon: GraduationCap, title: "Starting out", desc: "You've got the degree but not the experience. We help you understand what employers want and build a resume that gets through the door.", color: "#7cb9e8" },
                { icon: Repeat, title: "Making a change", desc: "Switching careers is scary. We show you which skills transfer, where the gaps are, and how to tell your story for a new industry.", color: "#7c6ceb" },
                { icon: Award, title: "Aiming higher", desc: "You know your worth. We help you articulate it precisely, pass ATS filters at top companies, and present your impact clearly.", color: "#e85d3a" },
              ].map((p, i) => (
                <Reveal key={p.title} delay={i * 60}>
                  <div className="group h-full rounded-2xl border border-stone-200/60 bg-white p-7 transition-all duration-200 hover:shadow-lg hover:-translate-y-1">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ backgroundColor: `${p.color}15` }}>
                      <p.icon size={20} strokeWidth={1.8} style={{ color: p.color }} />
                    </div>
                    <h4 className="mt-5 text-base font-bold text-stone-900">{p.title}</h4>
                    <p className="mt-2 text-[13px] leading-relaxed text-stone-500">{p.desc}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ STATS ════════════════════════════════════════════════════════ */}
      <section className="border-y border-stone-200/60 bg-white py-16 px-6">
        <div className="mx-auto max-w-4xl">
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            {[
              { v: countNum, s: "+", l: "Job Listings", icon: Briefcase },
              { v: 5, s: "", l: "Job Sources", icon: Search },
              { v: 1500, s: "+", l: "Skills Tracked", icon: Star },
              { v: 24, s: "h", l: "Data Refresh", icon: Clock },
            ].map((s, i) => (
              <Reveal key={s.l} delay={i * 50}>
                <div className="text-center">
                  <div className="font-display text-[2rem] text-stone-900 sm:text-[2.5rem]"><Counter target={s.v} suffix={s.s} /></div>
                  <div className="mt-1 text-[12px] font-medium text-stone-400">{s.l}</div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════ TRUST ════════════════════════════════════════════════════════ */}
      <Reveal className="py-16 px-6">
        <div className="mx-auto max-w-4xl">
          <div className="grid gap-8 sm:grid-cols-3">
            {[
              { icon: MapPin, title: "Built for Singapore", desc: "Skills taxonomy and resume conventions tailored to the SG job market." },
              { icon: Zap, title: "Intelligent scoring", desc: "ATS keyword extraction, resume scoring, and one-click tailoring." },
              { icon: Shield, title: "Private and free", desc: "Your resume stays on your device. No data leaves your browser." },
            ].map((t) => (
              <div key={t.title} className="flex items-start gap-3.5">
                <div className="flex-shrink-0 rounded-xl bg-white p-2.5 text-stone-500 border border-stone-200/60 shadow-sm"><t.icon size={16} strokeWidth={1.8} /></div>
                <div>
                  <div className="text-sm font-bold text-stone-900">{t.title}</div>
                  <div className="mt-0.5 text-[13px] leading-relaxed text-stone-500">{t.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Reveal>

      {/* ═══════ CTA ══════════════════════════════════════════════════════════
          Dark section with bold text (Purpose Talent style)
      ═══════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="relative overflow-hidden bg-stone-900 py-24 px-6">
          <Triangle className="absolute top-8 left-[15%] opacity-30" color="#f5a623" />
          <Squiggle className="absolute bottom-12 right-[12%] opacity-20" color="#7c6ceb" />

          <div className="relative mx-auto max-w-3xl text-center">
            <h2 className="font-display text-[2rem] text-white sm:text-[2.75rem] leading-[1.1]">
              Your dream role is<br />closer than you think
            </h2>
            <p className="mt-4 text-[15px] text-stone-400">
              Thousands of Singapore professionals have taken the first step. Your turn.
            </p>
            <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="group inline-flex items-center gap-2.5 rounded-full bg-sky-400 px-8 py-4 text-sm font-bold text-slate-900 shadow-sm transition-all duration-200 hover:bg-sky-300 hover:shadow-md active:scale-[0.97]"
              >
                Start your journey <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-full border-2 border-stone-600 px-8 py-4 text-sm font-semibold text-white transition-all duration-200 hover:border-stone-500 hover:bg-white/5 active:scale-[0.97]"
              >
                Score my resume
              </button>
            </div>
          </div>
        </section>
      </Reveal>

      {/* ═══════ STYLES ══════════════════════════════════════════════════════ */}
      <style>{`
        .homepage-grain {
          position: relative;
        }
        .homepage-grain::before {
          content: '';
          position: fixed;
          inset: 0;
          opacity: 0.035;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          pointer-events: none;
          z-index: 0;
        }
        .homepage-grain > * {
          position: relative;
          z-index: 1;
        }
        .reveal-base {
          opacity: 0;
          transform: translateY(20px);
          transition: opacity 0.5s cubic-bezier(0.23,1,0.32,1), transform 0.5s cubic-bezier(0.23,1,0.32,1);
        }
        .reveal-base.revealed {
          opacity: 1;
          transform: translateY(0);
        }
        .hero-stagger-1 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0s both; }
        .hero-stagger-2 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.1s both; }
        .hero-stagger-3 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.2s both; }
        .hero-stagger-4 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.3s both; }
        .hero-stagger-5 { animation: heroIn 0.6s cubic-bezier(0.23,1,0.32,1) 0.4s both; }
        @keyframes heroIn {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .hero-float {
          animation: float 4s ease-in-out infinite alternate;
        }
        @keyframes float {
          from { transform: translateY(0) rotate(var(--r, 0deg)); }
          to { transform: translateY(-8px) rotate(var(--r, 0deg)); }
        }
        @media (prefers-reduced-motion: reduce) {
          .reveal-base { opacity: 1; transform: none; transition: none; }
          [class*="hero-stagger"] { animation: none; opacity: 1; transform: none; }
          .hero-float { animation: none; }
        }
      `}</style>
    </div>
  );
}
