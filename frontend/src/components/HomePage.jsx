import { useEffect, useRef, useState } from "react";
import {
  Search, FileText, BarChart2, ChevronDown, ChevronRight,
  Shield, Zap, MapPin, ArrowRight, GraduationCap, Repeat, Award,
  Target, Sparkles, TrendingUp, CheckCircle,
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

  const count = jobCount ? jobCount.toLocaleString() : "70,000";
  const countShort = jobCount ? `${Math.floor(jobCount / 1000)}K+` : "70K+";

  const scrollToGuide = () => {
    guideRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="font-body w-full bg-white">

      {/* ════════════════════════════════════════════════════════════════════
          HERO - Full-bleed with background photo overlay
      ════════════════════════════════════════════════════════════════════ */}
      <section className="hero-noise relative min-h-[520px] overflow-hidden sm:min-h-[580px]">
        {/* Background photo - Singapore professionals */}
        <div
          className="absolute inset-0 bg-cover bg-center bg-no-repeat"
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1600880292203-757bb62b4baf?w=1920&q=80&auto=format&fit=crop')" }}
        />
        {/* Gradient overlay - warm navy */}
        <div className="absolute inset-0 bg-gradient-to-r from-[#1e293b] via-[#1e293b]/90 to-[#1e293b]/50" />

        <div className="relative mx-auto flex max-w-6xl items-center px-6 py-24 sm:py-32 lg:px-8">
          <div className="max-w-xl">
            <h1 className="font-display text-4xl leading-tight tracking-tight text-white sm:text-5xl lg:text-[3.5rem]">
              Navigate your career{" "}
              <span className="text-sky-400">with clarity.</span>
            </h1>
            <p className="mt-5 text-base leading-relaxed text-slate-300 sm:text-lg">
              Search {count}+ Singapore job listings. Score your resume against real ATS criteria. Tailor every bullet point to the role you want.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-6 py-3 text-sm font-semibold text-white shadow-md shadow-sky-900/20 transition hover:bg-sky-500"
              >
                Start Exploring <ArrowRight size={15} />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-lg border border-white/20 bg-white/5 px-6 py-3 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/15"
              >
                Score My Resume
              </button>
            </div>
            <p className="mt-5 text-xs tracking-wide text-slate-400">No sign-up required to get started</p>
          </div>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          ACTION CARDS - Find a Job, Build Your Resume, Explore the Market
      ════════════════════════════════════════════════════════════════════ */}
      <section className="relative z-10 mx-auto -mt-12 max-w-5xl px-6">
        <Reveal>
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              {
                icon: Search,
                label: "Find a Job",
                desc: "Search and filter across Singapore's top job portals in one place.",
                tab: "scraper",
                iconBg: "bg-sky-50 text-sky-600",
                hoverBorder: "hover:border-sky-200",
              },
              {
                icon: FileText,
                label: "Build Your Resume",
                desc: "Score, optimize, and tailor your resume for any role you target.",
                tab: "resume",
                iconBg: "bg-teal-50 text-teal-600",
                hoverBorder: "hover:border-teal-200",
              },
              {
                icon: BarChart2,
                label: "Explore the Market",
                desc: "Discover trending skills, salary benchmarks, and in-demand roles.",
                tab: "analytics",
                iconBg: "bg-amber-50 text-amber-600",
                hoverBorder: "hover:border-amber-200",
              },
            ].map((c) => (
              <button
                key={c.tab}
                type="button"
                onClick={() => onNavigate(c.tab)}
                className={`group flex flex-col items-start rounded-2xl border border-gray-200 bg-white p-6 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${c.hoverBorder}`}
              >
                <div className={`rounded-lg p-2.5 ${c.iconBg}`}>
                  <c.icon size={20} strokeWidth={1.8} />
                </div>
                <h3 className="mt-3 text-[15px] font-semibold text-[#1e293b]">{c.label}</h3>
                <p className="mt-1 flex-1 text-sm leading-relaxed text-gray-500">{c.desc}</p>
                <span className="mt-3 flex items-center gap-1 text-xs font-medium text-gray-400 transition group-hover:text-sky-600">
                  Get started <ChevronRight size={13} />
                </span>
              </button>
            ))}
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
          HOW IT WORKS - 3 steps with product screenshot mockups
      ════════════════════════════════════════════════════════════════════ */}
      <section ref={guideRef} className="mt-24 scroll-mt-16">
        <div className="mx-auto max-w-5xl px-6">
          <Reveal>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-600">How it works</p>
            <h2 className="font-display mt-2 text-3xl text-[#1e293b] sm:text-4xl">Three steps to a stronger application</h2>
          </Reveal>

          {/* Step 1 - Search with precision */}
          <Reveal className="mt-16">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
                  <Target size={13} /> Step 1
                </div>
                <h3 className="font-display mt-4 text-2xl text-[#1e293b]">Search with precision</h3>
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
                          <span key={s} className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-medium text-sky-600">{s}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </ScreenshotFrame>
            </div>
          </Reveal>

          {/* Step 2 - Know where you stand */}
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
                        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-[#1e293b]">87</span>
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
                        <div className="mt-0.5 h-1.5 rounded-full bg-gray-100"><div className="h-1.5 w-[84%] rounded-full bg-teal-500" /></div>
                      </div>
                      <div>
                        <div className="flex justify-between text-[10px]"><span className="text-gray-500">Competencies</span><span className="font-semibold text-gray-700">80%</span></div>
                        <div className="mt-0.5 h-1.5 rounded-full bg-gray-100"><div className="h-1.5 w-[80%] rounded-full bg-amber-500" /></div>
                      </div>
                    </div>
                  </div>
                </ScreenshotFrame>
              </div>
              <div className="order-1 lg:order-2">
                <div className="inline-flex items-center gap-2 rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">
                  <Sparkles size={13} /> Step 2
                </div>
                <h3 className="font-display mt-4 text-2xl text-[#1e293b]">Know where you stand</h3>
                <p className="mt-3 text-sm leading-relaxed text-gray-500">
                  Upload your resume and get an instant breakdown across Impact, Presentation, and Competencies. See matched keywords, missing gaps, and exactly where to improve.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-teal-600 transition hover:text-teal-500"
                >
                  Score my resume <ArrowRight size={14} />
                </button>
              </div>
            </div>
          </Reveal>

          {/* Step 3 - Tailor with confidence */}
          <Reveal className="mt-24">
            <div className="grid items-center gap-10 lg:grid-cols-2">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                  <TrendingUp size={13} /> Step 3
                </div>
                <h3 className="font-display mt-4 text-2xl text-[#1e293b]">Tailor with confidence</h3>
                <p className="mt-3 text-sm leading-relaxed text-gray-500">
                  One click transforms your resume for any role. Every bullet optimized, every keyword placed. Download as PDF or DOCX and apply with confidence.
                </p>
                <button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-amber-600 transition hover:text-amber-500"
                >
                  Start tailoring <ArrowRight size={14} />
                </button>
              </div>
              <ScreenshotFrame title="Tailored Resume">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[9px] font-bold text-teal-700">MATCHED</span>
                    <div className="flex gap-1">
                      {["Python", "Agile", "SQL"].map((k) => (
                        <span key={k} className="rounded bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600">{k}</span>
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
                  <div className="rounded-lg border-l-2 border-teal-400 bg-teal-50/50 p-2.5 text-[11px] leading-relaxed text-gray-600">
                    Developed and deployed a deep learning model (ResNet-50) for chamber and wafer misplacement detection...
                  </div>
                </div>
              </ScreenshotFrame>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ════════════════════════════════════════════════════════════════════
          PERSONAS - Fresh Graduate, Career Switcher, Senior Professional
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal className="mt-28">
        <section className="bg-slate-50 py-16">
          <div className="mx-auto max-w-5xl px-6">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-600">Who is this for</p>
            <h2 className="font-display mt-2 text-3xl text-[#1e293b]">Built for every stage of your career</h2>
            <div className="mt-10 grid gap-6 sm:grid-cols-3">
              {[
                {
                  icon: GraduationCap,
                  title: "Fresh Graduate",
                  desc: "Understand what employers look for. Get your first resume right and learn how ATS systems filter applications before yours reaches a recruiter.",
                  iconBg: "bg-sky-100 text-sky-600",
                },
                {
                  icon: Repeat,
                  title: "Career Switcher",
                  desc: "See which of your skills transfer to a new industry. Identify the gaps you need to fill, discover where to upskill, and reframe your experience.",
                  iconBg: "bg-teal-100 text-teal-600",
                },
                {
                  icon: Award,
                  title: "Senior Professional",
                  desc: "Fine-tune every bullet point for executive roles. Ensure your experience passes ATS filters at top companies and articulates real impact.",
                  iconBg: "bg-amber-100 text-amber-600",
                },
              ].map((p) => (
                <div key={p.title} className="rounded-2xl border border-gray-200 bg-white p-6">
                  <div className={`inline-flex rounded-lg p-2 ${p.iconBg}`}>
                    <p.icon size={20} strokeWidth={1.8} />
                  </div>
                  <h4 className="mt-3 text-[15px] font-semibold text-[#1e293b]">{p.title}</h4>
                  <p className="mt-2 text-sm leading-relaxed text-gray-500">{p.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ════════════════════════════════════════════════════════════════════
          STATS - Dynamic job count, sources, skills tracked
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal className="py-16">
        <div className="mx-auto grid max-w-4xl grid-cols-2 gap-8 px-6 sm:grid-cols-4">
          {[
            { value: countShort, label: "Job Listings" },
            { value: "5", label: "Job Sources" },
            { value: "1,500+", label: "Skills Tracked" },
            { value: "Nightly", label: "Data Refresh" },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <div className="font-display text-3xl text-[#1e293b]">{s.value}</div>
              <div className="mt-1 text-sm text-gray-400">{s.label}</div>
            </div>
          ))}
        </div>
      </Reveal>

      {/* ════════════════════════════════════════════════════════════════════
          TRUST SIGNALS
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="border-t border-gray-100 bg-white py-14">
          <div className="mx-auto max-w-4xl px-6">
            <div className="grid gap-6 sm:grid-cols-3">
              {[
                {
                  icon: MapPin,
                  title: "Built for Singapore job seekers",
                  desc: "Skills taxonomy and resume conventions tailored to the SG job market.",
                },
                {
                  icon: Zap,
                  title: "AI-powered insights",
                  desc: "Smart scoring, keyword extraction, and resume tailoring driven by machine learning.",
                },
                {
                  icon: Shield,
                  title: "Free to use",
                  desc: "Browse jobs, score your resume, and explore market insights at no cost.",
                },
              ].map((t) => (
                <div key={t.title} className="flex items-start gap-3">
                  <div className="flex-shrink-0 rounded-md bg-sky-50 p-2">
                    <t.icon size={16} className="text-sky-600" />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-[#1e293b]">{t.title}</div>
                    <div className="mt-0.5 text-xs leading-relaxed text-gray-500">{t.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </Reveal>

      {/* ════════════════════════════════════════════════════════════════════
          CTA FOOTER - Final call to action
      ════════════════════════════════════════════════════════════════════ */}
      <Reveal>
        <section className="bg-[#1e293b] py-20">
          <div className="mx-auto max-w-3xl px-6 text-center">
            <h2 className="font-display text-2xl text-white sm:text-3xl">Ready to make your next move?</h2>
            <p className="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-slate-400">
              Join job seekers across Singapore using smarter tools to stand out in a competitive market.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-6 py-3 text-sm font-semibold text-white shadow-md shadow-sky-900/30 transition hover:bg-sky-500"
              >
                Get Started <ArrowRight size={15} />
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-lg border border-white/20 bg-white/5 px-6 py-3 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/15"
              >
                Score My Resume
              </button>
            </div>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-slate-500">
              {["No sign-up required", "Resume stays private", "Singapore-focused"].map((item) => (
                <span key={item} className="flex items-center gap-1.5">
                  <CheckCircle size={12} className="text-sky-500" />
                  {item}
                </span>
              ))}
            </div>
          </div>
        </section>
      </Reveal>
    </div>
  );
}
