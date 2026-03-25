import { useEffect, useRef, useState } from "react";
import {
  Search, FileText, BarChart2, ChevronDown, ChevronRight,
  Shield, Eye, MapPin, ArrowRight, GraduationCap, Repeat, Award,
  Target, Sparkles, TrendingUp,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

// ── Scroll-triggered reveal ─────────────────────────────────────────────────
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
      { threshold: 0.12 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [delay]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ opacity: 0, transform: "translateY(24px)", transition: "opacity 0.7s ease, transform 0.7s ease" }}
    >
      {children}
    </div>
  );
}

// ── Screenshot placeholder ──────────────────────────────────────────────────
function ScreenshotFrame({ title, children }) {
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-lg">
      <div className="flex items-center gap-1.5 border-b border-gray-100 bg-gray-50 px-3 py-2">
        <span className="h-2.5 w-2.5 rounded-full bg-red-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
        <span className="ml-2 text-[10px] text-gray-400">{title}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════

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
      } catch { /* fallback */ }
    })();
    return () => { c = true; };
  }, []);

  const count = jobCount ? jobCount.toLocaleString() : "70,000";
  const countShort = jobCount ? `${Math.floor(jobCount / 1000)}K+` : "70K+";

  const scrollToGuide = () => {
    guideRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="font-body w-full bg-white">

      {/* ════════════════════════════════════════════════════════════════════
          HERO - Full-bleed with background image
      ════════════════════════════════════════════════════════════════════ */}
      <section className="hero-noise relative min-h-[520px] overflow-hidden bg-slate-900 sm:min-h-[560px]">
        {/* Background photo */}
        <div
          className="absolute inset-0 bg-cover bg-center bg-no-repeat"
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1920&q=80&auto=format&fit=crop')" }}
        />
        {/* Overlay: left-to-right gradient so text is readable, image peeks on right */}
        <div className="absolute inset-0 bg-gradient-to-r from-slate-900 via-slate-900/85 to-slate-900/40" />

        <div className="relative mx-auto flex max-w-6xl items-center px-6 py-24 sm:py-32 lg:px-8">
          <div className="max-w-xl">
            <h1 className="font-display text-4xl leading-tight tracking-tight text-white sm:text-5xl lg:text-[3.5rem]">
              Your career move,{" "}
              <span className="bg-gradient-to-r from-sky-400 to-cyan-300 bg-clip-text text-transparent">optimized.</span>
            </h1>
            <p className="mt-5 text-base leading-relaxed text-slate-300 sm:text-lg">
              Search {count}+ Singapore jobs. Score your resume against real ATS systems. Tailor every bullet to the role you want.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-sky-600/20 transition hover:bg-sky-500"
              >
                Search Jobs <ArrowRight size={15} />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-lg border border-white/20 bg-white/5 px-5 py-2.5 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/15"
              >
                Score My Resume
              </button>
            </div>
            <p className="mt-5 text-xs tracking-wide text-slate-500">No sign-up required to get started</p>
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          ACTION CARDS - 3 cards (no tracker)
      ════════════════════════════════════════════════════════════════════ */}
      <section className="relative z-10 mx-auto -mt-12 max-w-5xl px-6">
        <Reveal>
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              { icon: Search, label: "Find a Job", desc: "Search and filter across Singapore's top job portals", tab: "scraper", accent: "sky" },
              { icon: FileText, label: "Build Resume", desc: "Score, optimize, and tailor your resume for any role", tab: "resume", accent: "emerald" },
              { icon: BarChart2, label: "Explore Market", desc: "Discover trending skills and in-demand roles by sector", tab: "analytics", accent: "violet" },
            ].map((c) => {
              const bg = { sky: "bg-sky-50 text-sky-600", emerald: "bg-emerald-50 text-emerald-600", violet: "bg-violet-50 text-violet-600" };
              const hover = { sky: "hover:border-sky-200", emerald: "hover:border-emerald-200", violet: "hover:border-violet-200" };
              return (
                <button
                  key={c.tab}
                  type="button"
                  onClick={() => onNavigate(c.tab)}
                  className={`group flex flex-col items-start rounded-2xl border border-gray-200 bg-white p-6 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${hover[c.accent]}`}
                >
                  <div className={`rounded-lg p-2.5 ${bg[c.accent]}`}>
                    <c.icon size={20} strokeWidth={1.8} />
                  </div>
                  <h3 className="mt-3 text-[15px] font-semibold text-gray-900">{c.label}</h3>
                  <p className="mt-1 flex-1 text-sm leading-relaxed text-gray-500">{c.desc}</p>
                  <span className="mt-3 flex items-center gap-1 text-xs font-medium text-gray-400 transition group-hover:text-sky-600">
                    Get started <ChevronRight size={13} />
                  </span>
                </button>
              );
            })}
          </div>
        </Reveal>

        {/* Scroll bridge */}
        <Reveal delay={200} className="mt-10 text-center">
          <button
            type="button"
            onClick={scrollToGuide}
            className="inline-flex flex-col items-center gap-1 text-xs font-medium text-gray-400 transition hover:text-sky-600"
          >
            Learn how it works
            <ChevronDown size={16} className="animate-bounce" />
          </button>
        </Reveal>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          GUIDE - "How It Works" with product screenshots
      ════════════════════════════════════════════════════════════════════ */}
      <section ref={guideRef} className="mt-24 scroll-mt-16">
        <div className="mx-auto max-w-5xl px-6">
          <Reveal>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-600">How it works</p>
            <h2 className="font-display mt-2 text-3xl text-gray-900 sm:text-4xl">Three steps to a stronger application</h2>
          </Reveal>

          {/* Step 1 */}
          <Reveal className="mt-16">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
                  <Target size={13} /> Step 1
                </div>
                <h3 className="font-display mt-4 text-2xl text-gray-900">Search with precision</h3>
                <p className="mt-3 text-sm leading-relaxed text-gray-500">
                  Smart filters across {count}+ roles. Every listing is enriched with ATS-extracted skill requirements so you know exactly what employers are looking for before you apply.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("scraper")}
                  className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-sky-600 transition hover:text-sky-500"
                >
                  Try it now <ArrowRight size={14} />
                </button>
              </div>
              <ScreenshotFrame title="Job Search">
                <div className="space-y-3">
                  <div className="h-8 w-full rounded-lg bg-gray-100" />
                  <div className="flex gap-2">
                    {["Full-time", "Contract", "3-5 yrs"].map((t) => (
                      <span key={t} className="rounded-full bg-sky-50 px-3 py-1 text-[11px] font-medium text-sky-700">{t}</span>
                    ))}
                  </div>
                  {[1, 2].map((i) => (
                    <div key={i} className="rounded-xl border border-gray-100 p-3">
                      <div className="h-4 w-3/4 rounded bg-gray-200" />
                      <div className="mt-2 h-3 w-1/2 rounded bg-gray-100" />
                      <div className="mt-2 flex gap-1.5">
                        {["Python", "SQL", "AWS"].map((s) => (
                          <span key={s} className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-medium text-indigo-600">{s}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </ScreenshotFrame>
            </div>
          </Reveal>

          {/* Step 2 */}
          <Reveal className="mt-24">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div className="order-2 lg:order-1">
                <ScreenshotFrame title="Resume Score">
                  <div className="flex items-start gap-6">
                    <div className="text-center">
                      <div className="relative mx-auto h-20 w-20">
                        <svg viewBox="0 0 36 36" className="h-20 w-20 -rotate-90">
                          <circle cx="18" cy="18" r="16" fill="none" stroke="#e5e7eb" strokeWidth="2.5" />
                          <circle cx="18" cy="18" r="16" fill="none" stroke="#0284c7" strokeWidth="2.5" strokeDasharray="87 100" strokeLinecap="round" />
                        </svg>
                        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-gray-900">87</span>
                      </div>
                      <div className="mt-1 text-[10px] text-gray-400">ATS Score</div>
                    </div>
                    <div className="flex-1 space-y-2.5">
                      <div>
                        <div className="flex justify-between text-[10px]"><span className="text-gray-500">Impact</span><span className="font-semibold text-gray-700">91%</span></div>
                        <div className="mt-0.5 h-1.5 rounded-full bg-gray-100"><div className="h-1.5 w-[91%] rounded-full bg-sky-500" /></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-[10px]"><span className="text-gray-500">Presentation</span><span className="font-semibold text-gray-700">84%</span></div>
                        <div className="mt-0.5 h-1.5 rounded-full bg-gray-100"><div className="h-1.5 w-[84%] rounded-full bg-emerald-500" /></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-[10px]"><span className="text-gray-500">Competencies</span><span className="font-semibold text-gray-700">80%</span></div>
                        <div className="mt-0.5 h-1.5 rounded-full bg-gray-100"><div className="h-1.5 w-[80%] rounded-full bg-violet-500" /></div>
                      </div>
                    </div>
                  </div>
                </ScreenshotFrame>
              </div>
              <div className="order-1 lg:order-2">
                <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                  <Sparkles size={13} /> Step 2
                </div>
                <h3 className="font-display mt-4 text-2xl text-gray-900">Know where you stand</h3>
                <p className="mt-3 text-sm leading-relaxed text-gray-500">
                  Upload your resume and get an instant breakdown across Impact, Presentation, and Competencies. See matched keywords, missing gaps, and exactly where to improve.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-emerald-600 transition hover:text-emerald-500"
                >
                  Score my resume <ArrowRight size={14} />
                </button>
              </div>
            </div>
          </Reveal>

          {/* Step 3 */}
          <Reveal className="mt-24">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">
                  <TrendingUp size={13} /> Step 3
                </div>
                <h3 className="font-display mt-4 text-2xl text-gray-900">Tailor with confidence</h3>
                <p className="mt-3 text-sm leading-relaxed text-gray-500">
                  One click transforms your resume for any role. Every bullet optimized, every keyword placed. Download as PDF or DOCX and apply with confidence.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-violet-600 transition hover:text-violet-500"
                >
                  Start tailoring <ArrowRight size={14} />
                </button>
              </div>
              <ScreenshotFrame title="Tailored Resume">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[9px] font-bold text-emerald-700">MATCHED</span>
                    <div className="flex gap-1">
                      {["Python", "Agile", "SQL"].map((k) => (
                        <span key={k} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-600">{k}</span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[9px] font-bold text-rose-700">MISSING</span>
                    <div className="flex gap-1">
                      {["Cloud", "CI/CD"].map((k) => (
                        <span key={k} className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600">{k}</span>
                      ))}
                    </div>
                  </div>
                  <div className="mt-1 rounded-lg border-l-2 border-sky-400 bg-sky-50/50 p-2.5 text-[11px] leading-relaxed text-gray-600">
                    Led the global Conversion Accelerator Program, integrating AI and automation to optimize fab yield, traceability and cycle-time across 4 fabs...
                  </div>
                  <div className="rounded-lg border-l-2 border-emerald-400 bg-emerald-50/50 p-2.5 text-[11px] leading-relaxed text-gray-600">
                    Developed and deployed a deep learning model (ResNet-50) for chamber and wafer misplacement detection...
                  </div>
                </div>
              </ScreenshotFrame>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          PERSONAS - Who is this for
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal className="mt-28">
        <section className="bg-slate-50 py-16">
          <div className="mx-auto max-w-5xl px-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-600">Who is this for</p>
            <h2 className="font-display mt-2 text-3xl text-gray-900">Built for every stage of your career</h2>
            <div className="mt-10 grid gap-6 sm:grid-cols-3">
              {[
                { icon: GraduationCap, title: "Fresh Graduates", desc: "Understand what employers look for. Get your first resume right and learn how ATS systems filter applications.", color: "sky" },
                { icon: Repeat, title: "Career Switchers", desc: "See which of your skills transfer to a new industry. Identify the gaps you need to fill and where to upskill.", color: "emerald" },
                { icon: Award, title: "Senior Professionals", desc: "Fine-tune every bullet point. Ensure your experience passes ATS filters at top companies and stands out.", color: "violet" },
              ].map((p) => {
                const accent = { sky: "bg-sky-100 text-sky-600", emerald: "bg-emerald-100 text-emerald-600", violet: "bg-violet-100 text-violet-600" };
                return (
                  <div key={p.title} className="rounded-2xl border border-gray-200 bg-white p-6">
                    <div className={`inline-flex rounded-lg p-2 ${accent[p.color]}`}>
                      <p.icon size={20} strokeWidth={1.8} />
                    </div>
                    <h4 className="mt-3 text-[15px] font-semibold text-gray-900">{p.title}</h4>
                    <p className="mt-2 text-sm leading-relaxed text-gray-500">{p.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ════════════════════════════════════════════════════════════════════
          STATS
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal className="py-16">
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-8 px-6 sm:grid-cols-4">
          {[
            { value: countShort, label: "Job Listings" },
            { value: "1,500+", label: "Skills Tracked" },
            { value: "38", label: "Sectors Covered" },
            { value: "Nightly", label: "Data Refresh" },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <div className="font-display text-3xl text-gray-900">{s.value}</div>
              <div className="mt-1 text-sm text-gray-400">{s.label}</div>
            </div>
          ))}
        </div>
      </Reveal>

      {/* ════════════════════════════════════════════════════════════════════
          TRUST + CTA
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="border-t border-gray-100 bg-white py-16">
          <div className="mx-auto max-w-4xl px-6">
            <div className="grid gap-6 sm:grid-cols-3">
              {[
                { icon: Eye, title: "No sign-up required", desc: "Browse jobs and score your resume without creating an account." },
                { icon: Shield, title: "Resume stays private", desc: "Your data is never shared, sold, or used to train models." },
                { icon: MapPin, title: "Built for Singapore", desc: "Skills taxonomy and resume conventions tailored to the SG job market." },
              ].map((t) => (
                <div key={t.title} className="flex items-start gap-3">
                  <div className="flex-shrink-0 rounded-md bg-gray-100 p-2">
                    <t.icon size={16} className="text-gray-500" />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-gray-900">{t.title}</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-gray-500">{t.desc}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* Final CTA */}
            <div className="mt-14 text-center">
              <h2 className="font-display text-2xl text-gray-900 sm:text-3xl">Ready to make your move?</h2>
              <p className="mt-2 text-sm text-gray-500">Join job seekers across Singapore using smarter tools to stand out.</p>
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="mt-6 inline-flex items-center gap-2 rounded-lg bg-sky-600 px-6 py-3 text-sm font-semibold text-white shadow-md shadow-sky-600/20 transition hover:bg-sky-500"
              >
                Get Started <ArrowRight size={15} />
              </button>
            </div>
          </div>
        </section>
      </Reveal>
    </div>
  );
}
