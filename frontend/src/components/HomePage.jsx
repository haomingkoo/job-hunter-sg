import { useEffect, useRef, useState } from "react";
import { Search, FileText, BarChart2, Briefcase, ChevronRight, Shield, Eye, MapPin } from "lucide-react";
import { apiFetch } from "../lib/api.js";

// ── Scroll-triggered fade-in ────────────────────────────────────────────────
function FadeInSection({ children, className = "", delay = 0 }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => el.classList.add("opacity-100", "translate-y-0"), delay);
          observer.unobserve(el);
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [delay]);
  return (
    <div ref={ref} className={`opacity-0 translate-y-6 transition-all duration-700 ease-out ${className}`}>
      {children}
    </div>
  );
}

// ── Action Card (equal height with flex) ────────────────────────────────────
function ActionCard({ icon: Icon, title, description, onClick, color = "blue" }) {
  const hoverBorder = {
    blue: "hover:border-blue-300",
    emerald: "hover:border-emerald-300",
    violet: "hover:border-violet-300",
    amber: "hover:border-amber-300",
  };
  const iconBg = {
    blue: "bg-blue-50 text-blue-600",
    emerald: "bg-emerald-50 text-emerald-600",
    violet: "bg-violet-50 text-violet-600",
    amber: "bg-amber-50 text-amber-600",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex h-full flex-col text-left rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 ${hoverBorder[color]}`}
    >
      <div className={`inline-flex items-center justify-center rounded-xl p-2.5 ${iconBg[color]}`}>
        <Icon size={22} strokeWidth={1.8} />
      </div>
      <h3 className="mt-3 text-base font-semibold text-gray-900">{title}</h3>
      <p className="mt-1.5 flex-1 text-sm leading-relaxed text-gray-500">{description}</p>
      <div className="mt-4 flex items-center gap-1 text-sm font-medium text-gray-400 group-hover:text-blue-600 transition-colors">
        Get started <ChevronRight size={14} />
      </div>
    </button>
  );
}

// ── Main HomePage ───────────────────────────────────────────────────────────
export default function HomePage({ onNavigate, onSignIn, user }) {
  const [jobCount, setJobCount] = useState(null);

  // Fetch dynamic job count on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/jobs?page=1&per_page=1");
        const data = await resp.json();
        if (!cancelled && data.total) {
          setJobCount(data.total);
        }
      } catch { /* use fallback */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const jobCountLabel = jobCount
    ? `${Math.floor(jobCount / 1000)}K+`
    : "70K+";

  return (
    <div className="w-full">
      {/* ── Hero with background image ──────────────────────────────────── */}
      <section className="relative overflow-hidden">
        {/* Background image */}
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage: "url('https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1920&q=80&auto=format&fit=crop')",
          }}
        />
        {/* Dark overlay for text readability */}
        <div className="absolute inset-0 bg-gradient-to-r from-slate-900/90 via-slate-900/80 to-slate-900/60" />

        <div className="relative mx-auto max-w-5xl px-6 py-20 sm:py-28">
          <div className="max-w-2xl">
            <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-6xl">
              Your career move,
              <br />
              <span className="bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent">
                optimized.
              </span>
            </h1>
            <p className="mt-5 text-lg leading-relaxed text-white/70 max-w-lg">
              Search {jobCount ? jobCount.toLocaleString() : "70,000"}+ Singapore jobs. Score your resume. Tailor every bullet to the role you want.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/30 transition hover:bg-blue-500 hover:shadow-blue-500/30"
              >
                Search Jobs
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-xl border border-white/25 bg-white/10 px-6 py-3 text-sm font-semibold text-white backdrop-blur-sm transition hover:bg-white/20"
              >
                Score My Resume
              </button>
            </div>
            <p className="mt-6 text-xs text-white/40">
              No sign-up required to get started
            </p>
          </div>
        </div>
      </section>

      {/* ── Action Hub ───────────────────────────────────────────────────── */}
      <FadeInSection className="mx-auto max-w-5xl px-6 -mt-10 relative z-10">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            { icon: Search, title: "Find a Job", desc: "Search and filter across Singapore's top job portals", tab: "scraper", color: "blue" },
            { icon: FileText, title: "Build Resume", desc: "Score, optimize, and tailor your resume for any role", tab: "resume", color: "emerald" },
            { icon: BarChart2, title: "Explore Market", desc: "Discover trending skills and in-demand roles", tab: "analytics", color: "violet" },
            { icon: Briefcase, title: "Track Apps", desc: "Manage your pipeline from applied to offer", tab: "tracker", color: "amber" },
          ].map((card) => (
            <ActionCard
              key={card.tab}
              icon={card.icon}
              title={card.title}
              description={card.desc}
              onClick={() => onNavigate(card.tab)}
              color={card.color}
            />
          ))}
        </div>
      </FadeInSection>

      {/* ── Stats Strip ──────────────────────────────────────────────────── */}
      <FadeInSection className="mt-20">
        <section className="mx-auto max-w-3xl px-6">
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            <div className="text-center">
              <div className="text-3xl font-bold tracking-tight text-gray-900">{jobCountLabel}</div>
              <div className="mt-1 text-sm text-gray-500">Job Listings</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold tracking-tight text-gray-900">1,500+</div>
              <div className="mt-1 text-sm text-gray-500">Skills Tracked</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold tracking-tight text-gray-900">38</div>
              <div className="mt-1 text-sm text-gray-500">Sectors Covered</div>
            </div>
            <div className="text-center">
              <div className="text-3xl font-bold tracking-tight text-gray-900">Nightly</div>
              <div className="mt-1 text-sm text-gray-500">Data Refresh</div>
            </div>
          </div>
        </section>
      </FadeInSection>

      {/* ── How It Works ─────────────────────────────────────────────────── */}
      <FadeInSection className="mt-24">
        <section className="mx-auto max-w-3xl px-6">
          <h2 className="text-2xl font-bold tracking-tight text-gray-900">How it works</h2>
          <p className="mt-2 text-sm text-gray-500">Three steps to a stronger application.</p>
          <div className="mt-10 space-y-8">
            {[
              { n: "1", title: "Search with precision", desc: "Smart filters across thousands of roles. Every listing enriched with ATS-extracted skill requirements so you know exactly what employers want." },
              { n: "2", title: "Know where you stand", desc: "Upload your resume and get an instant breakdown across Impact, Presentation, and Competencies. See matched keywords, missing gaps, and exactly where to improve." },
              { n: "3", title: "Tailor with confidence", desc: "One click transforms your resume for any role. Every bullet optimized, every keyword placed. Download as PDF or DOCX and apply with confidence." },
            ].map((step) => (
              <div key={step.n} className="flex gap-4">
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
                  {step.n}
                </div>
                <div>
                  <h4 className="text-base font-semibold text-gray-900">{step.title}</h4>
                  <p className="mt-1 text-sm leading-relaxed text-gray-500">{step.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </FadeInSection>

      {/* ── Trust Signals ────────────────────────────────────────────────── */}
      <FadeInSection className="mt-24 mb-16">
        <section className="mx-auto max-w-3xl px-6">
          <div className="grid gap-6 sm:grid-cols-3">
            {[
              { icon: Eye, title: "No sign-up required", desc: "Browse jobs and score your resume without creating an account." },
              { icon: Shield, title: "Resume stays private", desc: "Your data is never shared, sold, or used to train models." },
              { icon: MapPin, title: "Built for Singapore", desc: "Skills taxonomy and templates tailored to the SG job market." },
            ].map((item) => (
              <div key={item.title} className="flex items-start gap-3">
                <div className="flex-shrink-0 rounded-lg bg-gray-100 p-2">
                  <item.icon size={18} className="text-gray-500" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-gray-900">{item.title}</div>
                  <div className="mt-0.5 text-xs leading-relaxed text-gray-500">{item.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </FadeInSection>
    </div>
  );
}
