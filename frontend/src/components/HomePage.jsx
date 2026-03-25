import { useEffect, useRef } from "react";
import { Search, FileText, BarChart2, Briefcase, ChevronRight, Shield, Eye, MapPin } from "lucide-react";

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

// ── Action Card ─────────────────────────────────────────────────────────────
function ActionCard({ icon: Icon, title, description, onClick, color = "blue" }) {
  const colorMap = {
    blue: "group-hover:bg-blue-50 group-hover:border-blue-200 text-blue-600",
    emerald: "group-hover:bg-emerald-50 group-hover:border-emerald-200 text-emerald-600",
    violet: "group-hover:bg-violet-50 group-hover:border-violet-200 text-violet-600",
    amber: "group-hover:bg-amber-50 group-hover:border-amber-200 text-amber-600",
  };
  const iconBg = {
    blue: "bg-blue-100 text-blue-600",
    emerald: "bg-emerald-100 text-emerald-600",
    violet: "bg-violet-100 text-violet-600",
    amber: "bg-amber-100 text-amber-600",
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group text-left w-full rounded-2xl border border-gray-200 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 ${colorMap[color]}`}
    >
      <div className={`inline-flex items-center justify-center rounded-xl p-3 ${iconBg[color]}`}>
        <Icon size={24} strokeWidth={1.8} />
      </div>
      <h3 className="mt-4 text-lg font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-500">{description}</p>
      <div className="mt-4 flex items-center gap-1 text-sm font-medium text-gray-400 group-hover:text-gray-600 transition-colors">
        Get started <ChevronRight size={14} />
      </div>
    </button>
  );
}

// ── Step Card ───────────────────────────────────────────────────────────────
function StepCard({ number, title, description }) {
  return (
    <div className="flex gap-5">
      <div className="flex-shrink-0">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">
          {number}
        </div>
      </div>
      <div>
        <h4 className="text-base font-semibold text-gray-900">{title}</h4>
        <p className="mt-1.5 text-sm leading-relaxed text-gray-500">{description}</p>
      </div>
    </div>
  );
}

// ── Stat ────────────────────────────────────────────────────────────────────
function Stat({ value, label }) {
  return (
    <div className="text-center">
      <div className="text-3xl font-bold tracking-tight text-gray-900">{value}</div>
      <div className="mt-1 text-sm text-gray-500">{label}</div>
    </div>
  );
}

// ── Main HomePage ───────────────────────────────────────────────────────────
export default function HomePage({ onNavigate, onSignIn, user }) {
  return (
    <div className="w-full">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900">
        {/* Subtle grid pattern overlay */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)",
            backgroundSize: "32px 32px",
          }}
        />
        <div className="relative mx-auto max-w-5xl px-6 py-20 sm:py-28">
          <div className="max-w-2xl">
            <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">
              Your career move,
              <br />
              <span className="text-blue-400">optimized.</span>
            </h1>
            <p className="mt-5 text-lg leading-relaxed text-blue-100/80">
              Search 70,000+ Singapore jobs. Score your resume against real ATS systems.
              Tailor every bullet to the role you want.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => onNavigate("scraper")}
                className="rounded-xl bg-blue-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-600/25 transition hover:bg-blue-500"
              >
                Search Jobs
              </button>
              <button
                type="button"
                onClick={() => onNavigate("resume")}
                className="rounded-xl border border-white/20 bg-white/10 px-6 py-3 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/20"
              >
                Score My Resume
              </button>
            </div>
            <p className="mt-6 text-xs text-blue-200/50">
              No sign-up required to get started
            </p>
          </div>
        </div>
      </section>

      {/* ── Action Hub ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-5xl px-6 -mt-8 relative z-10">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FadeInSection delay={0}>
            <ActionCard
              icon={Search}
              title="Find a Job"
              description="Search and filter across Singapore's leading job portals"
              onClick={() => onNavigate("scraper")}
              color="blue"
            />
          </FadeInSection>
          <FadeInSection delay={100}>
            <ActionCard
              icon={FileText}
              title="Build Resume"
              description="Score, optimize, and tailor your resume for any role"
              onClick={() => onNavigate("resume")}
              color="emerald"
            />
          </FadeInSection>
          <FadeInSection delay={200}>
            <ActionCard
              icon={BarChart2}
              title="Explore Market"
              description="Trending skills, in-demand roles, and industry insights"
              onClick={() => onNavigate("analytics")}
              color="violet"
            />
          </FadeInSection>
          <FadeInSection delay={300}>
            <ActionCard
              icon={Briefcase}
              title="Track Apps"
              description="Manage your pipeline from applied to offer"
              onClick={() => onNavigate("tracker")}
              color="amber"
            />
          </FadeInSection>
        </div>
      </section>

      {/* ── Stats Strip ──────────────────────────────────────────────────── */}
      <FadeInSection className="mt-20">
        <section className="mx-auto max-w-3xl px-6">
          <div className="grid grid-cols-2 gap-8 sm:grid-cols-4">
            <Stat value="70K+" label="Job Listings" />
            <Stat value="1,500+" label="Skills Tracked" />
            <Stat value="38" label="Sectors Covered" />
            <Stat value="Nightly" label="Data Refresh" />
          </div>
        </section>
      </FadeInSection>

      {/* ── How It Works ─────────────────────────────────────────────────── */}
      <FadeInSection className="mt-24">
        <section className="mx-auto max-w-3xl px-6">
          <h2 className="text-2xl font-bold tracking-tight text-gray-900">How it works</h2>
          <p className="mt-2 text-sm text-gray-500">Three steps to a stronger application.</p>
          <div className="mt-10 space-y-10">
            <StepCard
              number="1"
              title="Search with precision"
              description="Smart filters across 70,000+ roles. Every listing enriched with ATS-extracted skill requirements so you know exactly what employers want."
            />
            <StepCard
              number="2"
              title="Know where you stand"
              description="Upload your resume and get an instant breakdown across Impact, Presentation, and Competencies. See matched keywords, missing gaps, and exactly where to improve."
            />
            <StepCard
              number="3"
              title="Tailor with confidence"
              description="One click transforms your resume for any role. Every bullet optimized, every keyword placed. Download as PDF or DOCX and apply with confidence."
            />
          </div>
        </section>
      </FadeInSection>

      {/* ── Trust Signals ────────────────────────────────────────────────── */}
      <FadeInSection className="mt-24 mb-20">
        <section className="mx-auto max-w-3xl px-6">
          <div className="grid gap-6 sm:grid-cols-3">
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 rounded-lg bg-gray-100 p-2">
                <Eye size={18} className="text-gray-600" />
              </div>
              <div>
                <div className="text-sm font-semibold text-gray-900">No sign-up required</div>
                <div className="mt-0.5 text-xs text-gray-500">Browse jobs and score your resume without creating an account.</div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 rounded-lg bg-gray-100 p-2">
                <Shield size={18} className="text-gray-600" />
              </div>
              <div>
                <div className="text-sm font-semibold text-gray-900">Resume stays private</div>
                <div className="mt-0.5 text-xs text-gray-500">Your data is never shared, sold, or used to train models.</div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 rounded-lg bg-gray-100 p-2">
                <MapPin size={18} className="text-gray-600" />
              </div>
              <div>
                <div className="text-sm font-semibold text-gray-900">Built for Singapore</div>
                <div className="mt-0.5 text-xs text-gray-500">Skills taxonomy and resume conventions tailored to the SG job market.</div>
              </div>
            </div>
          </div>
        </section>
      </FadeInSection>
    </div>
  );
}
