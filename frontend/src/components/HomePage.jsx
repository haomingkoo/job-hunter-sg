import { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import {
  Search, FileText, BarChart2, ArrowRight,
  Shield, Zap, MapPin, GraduationCap, Repeat, Award,
  CheckCircle, Briefcase, Clock, Star, ChevronDown,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

/* ─── Animation variants ──────────────────────────────────────────────────── */
const fadeUp = {
  hidden: { opacity: 0, y: 40 },
  visible: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.7, delay: i * 0.1, ease: [0.23, 1, 0.32, 1] },
  }),
};

const staggerContainer = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

const scaleIn = {
  hidden: { opacity: 0, scale: 0.92, y: 24 },
  visible: (i = 0) => ({
    opacity: 1, scale: 1, y: 0,
    transition: { duration: 0.6, delay: i * 0.08, ease: [0.23, 1, 0.32, 1] },
  }),
};

const slideFromRight = {
  hidden: { opacity: 0, x: 60 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.8, ease: [0.23, 1, 0.32, 1] } },
};

const slideFromLeft = {
  hidden: { opacity: 0, x: -60 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.8, ease: [0.23, 1, 0.32, 1] } },
};

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

/* ═══════════════════════════════════════════════════════════════════════════ */

export default function HomePage({ onNavigate }) {
  const [jobCount, setJobCount] = useState(null);
  const heroRef = useRef(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start start", "end start"] });
  const heroOpacity = useTransform(scrollYProgress, [0, 0.8], [1, 0]);
  const heroY = useTransform(scrollYProgress, [0, 0.8], [0, -60]);

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

  const count = jobCount != null ? jobCount.toLocaleString() : null;
  const countNum = jobCount || 72000;

  return (
    <div className="relative font-body w-full overflow-x-hidden bg-[#f0f4f8]">

      {/* ═══════ HERO ═══════════════════════════════════════════════════════
          Full viewport hero with parallax fade-out on scroll
      ═══════════════════════════════════════════════════════════════════════ */}
      <section ref={heroRef} className="relative min-h-[92vh] flex flex-col justify-center overflow-hidden px-6">
        {/* Ambient gradient orbs */}
        <div className="absolute top-[-15%] right-[-8%] w-[600px] h-[600px] rounded-full bg-[#88BDF2] opacity-[0.07] blur-[100px]" />
        <div className="absolute bottom-[-10%] left-[-5%] w-[500px] h-[500px] rounded-full bg-[#6A89A7] opacity-[0.05] blur-[80px]" />

        <motion.div style={{ opacity: heroOpacity, y: heroY }} className="relative mx-auto w-full max-w-6xl">
          <div className="grid items-center gap-8 lg:grid-cols-[1fr_1fr]">
            {/* Left: copy */}
            <motion.div initial="hidden" animate="visible" variants={staggerContainer}>
              <motion.p variants={fadeUp} custom={0} className="text-[13px] font-medium tracking-wide text-[#6A89A7]">
                AI-powered job search and resume tailoring for Singapore
              </motion.p>

              <motion.h1 variants={fadeUp} custom={1} className="font-display mt-6 text-[2.75rem] leading-[1.15] tracking-tight text-[#384959] sm:text-[3.5rem] lg:text-[4.25rem]">
                Find the role<br />that fits{" "}
                <span className="relative inline-block">
                  <span className="relative z-10">you best</span>
                  <motion.svg
                    className="absolute -bottom-1 left-0 w-full z-0"
                    height="8" viewBox="0 0 200 8" preserveAspectRatio="none"
                    initial={{ pathLength: 0, opacity: 0 }}
                    animate={{ pathLength: 1, opacity: 1 }}
                    transition={{ duration: 1, delay: 0.6, ease: [0.23, 1, 0.32, 1] }}
                  >
                    <motion.path
                      d="M0 6C50 0 150 0 200 6"
                      stroke="#88BDF2" strokeWidth="3" fill="none" strokeLinecap="round"
                      initial={{ pathLength: 0 }}
                      animate={{ pathLength: 1 }}
                      transition={{ duration: 0.8, delay: 0.8, ease: [0.23, 1, 0.32, 1] }}
                    />
                  </motion.svg>
                </span>
              </motion.h1>

              <motion.p variants={fadeUp} custom={2} className="mt-7 max-w-md text-[1.05rem] leading-relaxed text-[#6A89A7]">
                Search smarter. Apply stronger. Land the role you deserve.
              </motion.p>

              <motion.div variants={fadeUp} custom={3} className="mt-9 flex flex-wrap items-center gap-3">
                <motion.button
                  type="button"
                  onClick={() => onNavigate("jobs")}
                  whileHover={{ scale: 1.03, boxShadow: "0 8px 30px rgba(56,73,89,0.2)" }}
                  whileTap={{ scale: 0.97 }}
                  className="inline-flex items-center gap-2.5 rounded-full bg-[#384959] px-7 py-3.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#2d3a47]"
                >
                  Start exploring <ArrowRight size={15} />
                </motion.button>
                <motion.button
                  type="button"
                  onClick={() => onNavigate("resume")}
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  className="inline-flex items-center gap-2 rounded-full border-2 border-[#6A89A7]/30 bg-white/60 backdrop-blur-sm px-7 py-3.5 text-sm font-semibold text-[#384959] transition-colors hover:border-[#88BDF2]/50 hover:bg-white"
                >
                  Build my resume
                </motion.button>
              </motion.div>

              <motion.div variants={fadeUp} custom={4} className="mt-6 flex items-center gap-5 text-[13px] text-[#6A89A7]">
                <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-[#88BDF2]" /> Free to use</span>
                <span className="flex items-center gap-1.5"><CheckCircle size={13} className="text-[#88BDF2]" /> No sign-up needed</span>
              </motion.div>
            </motion.div>

            {/* Right: floating resume templates */}
            <motion.div
              initial={{ opacity: 0, x: 80, rotateY: -15 }}
              animate={{ opacity: 1, x: 0, rotateY: 0 }}
              transition={{ duration: 1, delay: 0.3, ease: [0.23, 1, 0.32, 1] }}
              className="relative hidden lg:block"
              style={{ perspective: "1200px" }}
            >
              {/* Resume 1 - front */}
              <motion.div
                animate={{ y: [0, -10, 0] }}
                transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
                className="absolute top-4 right-4 w-[260px] rounded-xl border border-[#BDDDFC]/50 bg-white p-5 shadow-xl"
                style={{ transform: "rotateY(-8deg) rotateX(2deg)", zIndex: 3 }}
              >
                <div className="border-b border-[#BDDDFC]/30 pb-3 mb-3">
                  <div className="text-[13px] font-bold text-[#384959]">Sarah Chen</div>
                  <div className="text-[10px] text-[#6A89A7] mt-0.5">Software Engineer</div>
                  <div className="text-[8px] text-[#6A89A7]/50 mt-1">sarah@email.com | +65 9123 4567</div>
                </div>
                <div className="text-[8px] font-bold uppercase tracking-wider text-[#6A89A7] mb-1.5">Experience</div>
                <div className="space-y-2">
                  <div>
                    <div className="flex justify-between"><span className="text-[9px] font-semibold text-[#384959]">Senior Engineer</span><span className="text-[8px] text-[#6A89A7]">2022-Present</span></div>
                    <div className="text-[8px] text-[#6A89A7]">DBS Bank</div>
                    <div className="mt-1 h-1 w-[85%] rounded-full bg-[#BDDDFC]/40" /><div className="mt-0.5 h-1 w-[70%] rounded-full bg-[#BDDDFC]/40" />
                  </div>
                  <div>
                    <div className="flex justify-between"><span className="text-[9px] font-semibold text-[#384959]">Engineer</span><span className="text-[8px] text-[#6A89A7]">2019-2022</span></div>
                    <div className="text-[8px] text-[#6A89A7]">GovTech</div>
                    <div className="mt-1 h-1 w-[90%] rounded-full bg-[#BDDDFC]/40" /><div className="mt-0.5 h-1 w-[65%] rounded-full bg-[#BDDDFC]/40" />
                  </div>
                </div>
                <div className="mt-3 text-[8px] font-bold uppercase tracking-wider text-[#6A89A7] mb-1">Skills</div>
                <div className="flex flex-wrap gap-1">
                  {["Python", "AWS", "React", "SQL"].map((s) => <span key={s} className="rounded bg-[#BDDDFC]/25 px-1.5 py-0.5 text-[7px] font-medium text-[#384959]">{s}</span>)}
                </div>
              </motion.div>

              {/* Resume 2 - behind */}
              <motion.div
                animate={{ y: [0, -8, 0] }}
                transition={{ duration: 6, repeat: Infinity, ease: "easeInOut", delay: 0.5 }}
                className="absolute top-16 right-[200px] w-[240px] rounded-xl border border-[#BDDDFC]/35 bg-white p-5 shadow-lg opacity-75"
                style={{ transform: "rotateY(-15deg) rotateX(3deg) translateZ(-40px)", zIndex: 2 }}
              >
                <div className="flex gap-3 border-b border-[#BDDDFC]/25 pb-3 mb-3">
                  <div className="h-8 w-8 rounded-full bg-[#BDDDFC]/50" />
                  <div>
                    <div className="text-[12px] font-bold text-[#384959]">James Lim</div>
                    <div className="text-[9px] text-[#6A89A7]">Product Manager</div>
                  </div>
                </div>
                <div className="space-y-1.5">
                  {[100, 85, 92, 70].map((w, i) => <div key={i} className="h-1.5 rounded-full bg-[#BDDDFC]/35" style={{ width: `${w}%` }} />)}
                </div>
              </motion.div>

              {/* Resume 3 - far back */}
              <motion.div
                animate={{ y: [0, -6, 0] }}
                transition={{ duration: 7, repeat: Infinity, ease: "easeInOut", delay: 1 }}
                className="absolute top-28 right-[370px] w-[220px] rounded-xl border border-[#BDDDFC]/25 bg-white p-4 shadow-md opacity-45"
                style={{ transform: "rotateY(-22deg) rotateX(4deg) translateZ(-80px)", zIndex: 1 }}
              >
                <div className="text-[11px] font-bold text-[#384959] mb-2">Aisha Rahman</div>
                <div className="text-[9px] text-[#6A89A7] mb-2">Data Analyst</div>
                <div className="space-y-1">
                  {[100, 80, 90].map((w, i) => <div key={i} className="h-1 rounded-full bg-[#BDDDFC]/35" style={{ width: `${w}%` }} />)}
                </div>
              </motion.div>

              {/* ATS Match badge */}
              <motion.div
                animate={{ y: [0, -8, 0] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                className="absolute top-0 right-0 rounded-xl bg-white border border-[#BDDDFC]/50 shadow-lg px-3 py-2 z-10"
              >
                <div className="text-[9px] font-medium text-[#6A89A7]">ATS Match</div>
                <div className="text-lg font-bold text-[#88BDF2]">92%</div>
              </motion.div>

              <div className="h-[380px] w-[560px]" />
            </motion.div>
          </div>
        </motion.div>

        {/* Scroll indicator - bouncing at bottom of hero */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.2, duration: 0.6 }}
          className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center"
        >
          <button
            type="button"
            onClick={() => document.getElementById("homepage-pillars")?.scrollIntoView({ behavior: "smooth" })}
            className="flex flex-col items-center gap-1.5 text-[#6A89A7] transition-opacity hover:opacity-60"
          >
            <span className="text-[11px] font-medium tracking-wider uppercase">Scroll to explore</span>
            <motion.div animate={{ y: [0, 6, 0] }} transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}>
              <ChevronDown size={20} />
            </motion.div>
          </button>
        </motion.div>
      </section>

      {/* ═══════ THREE PILLARS ═══════════════════════════════════════════════
          Dark section with 3 clickable cards - clear CTAs
      ═══════════════════════════════════════════════════════════════════════ */}
      <section id="homepage-pillars" className="relative overflow-hidden py-20 sm:py-28 bg-[#384959]">
        <div className="mx-auto max-w-5xl px-6">
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-80px" }}
            variants={staggerContainer}
            className="text-center"
          >
            <motion.p variants={fadeUp} className="text-[12px] font-semibold uppercase tracking-[0.2em] text-[#6A89A7]">What we do</motion.p>
            <motion.h2 variants={fadeUp} custom={1} className="font-display mt-3 text-[2rem] text-white sm:text-[2.75rem]">
              Everything between you<br className="hidden sm:block" /> and your dream role
            </motion.h2>
          </motion.div>

          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }}
            variants={staggerContainer}
            className="mt-14 grid gap-5 sm:grid-cols-3"
          >
            {[
              { icon: Search, num: "01", label: "Discover", desc: "Search {count}+ roles from MyCareersFuture and Careers@Gov. Every listing tagged with the skills employers want.", tab: "jobs" },
              { icon: FileText, num: "02", label: "Prepare", desc: "Score your resume against real ATS criteria. Get honest feedback and tailor every bullet to stand out.", tab: "resume" },
              { icon: BarChart2, num: "03", label: "Understand", desc: "See which skills are trending, which sectors are growing, and where your best opportunities lie.", tab: "analytics" },
            ].map((c, i) => (
              <motion.button
                key={c.tab}
                variants={scaleIn}
                custom={i}
                type="button"
                onClick={() => onNavigate(c.tab)}
                whileHover={{ y: -6, boxShadow: "0 20px 40px rgba(0,0,0,0.15)" }}
                whileTap={{ scale: 0.98 }}
                className="group flex h-full flex-col rounded-2xl bg-white p-7 text-left transition-colors"
              >
                <div className="flex items-center justify-between w-full">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#384959] text-white transition-colors group-hover:bg-[#88BDF2]">
                    <c.icon size={20} strokeWidth={1.8} />
                  </div>
                  <span className="text-[13px] font-bold text-[#384959]">{c.num}</span>
                </div>
                <h3 className="mt-5 text-xl font-bold text-[#384959]">{c.label}</h3>
                <p className="mt-2 flex-1 text-[13px] leading-relaxed text-[#6A89A7]">{c.desc.replace("{count}", count || "thousands of")}</p>
                <span className="mt-5 inline-flex items-center gap-1.5 rounded-full bg-[#384959] px-4 py-2 text-xs font-semibold text-white transition-colors group-hover:bg-[#88BDF2] group-hover:text-[#1f2831]">
                  Get started <ArrowRight size={12} className="transition-transform group-hover:translate-x-1" />
                </span>
              </motion.button>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ═══════ HOW IT WORKS ═══════════════════════════════════════════════
          Apple-style alternating sections with product mockups
      ═══════════════════════════════════════════════════════════════════════ */}
      <section className="py-20 sm:py-28 px-6">
        <div className="mx-auto max-w-5xl">
          <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-80px" }} variants={staggerContainer}>
            <motion.p variants={fadeUp} className="text-[12px] font-semibold uppercase tracking-[0.2em] text-[#6A89A7]">Your journey</motion.p>
            <motion.h2 variants={fadeUp} custom={1} className="font-display mt-3 text-[2rem] text-[#384959] sm:text-[2.5rem]">From searching to hired</motion.h2>
          </motion.div>

          {/* Step 1 */}
          <div className="mt-16 grid items-center gap-10 lg:grid-cols-2">
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromLeft}>
              <div className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#BDDDFC]/30 text-[13px] font-bold text-[#384959]">1</div>
              <h3 className="font-display mt-4 text-[1.5rem] text-[#384959]">Explore what's out there</h3>
              <p className="mt-3 text-[15px] leading-relaxed text-[#6A89A7]">
                Browse {count ? `${count}+` : "thousands of"} roles across Singapore's top job portals. Every listing shows what employers actually care about.
              </p>
              <motion.button
                type="button" onClick={() => onNavigate("jobs")}
                whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#384959] px-5 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-[#2d3a47]"
              >
                Try it <ArrowRight size={13} />
              </motion.button>
            </motion.div>
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromRight}>
              <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2 rounded-lg bg-[#f0f4f8] px-3 py-2.5 border border-[#BDDDFC]/20">
                  <Search size={14} className="text-[#6A89A7]" />
                  <span className="text-[12px] text-[#6A89A7]">Software Engineer, Singapore</span>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {["Full-time", "3-5 yrs", "Technology", "$5K+"].map((t) => (
                    <span key={t} className="rounded-full border border-[#BDDDFC]/30 px-2.5 py-0.5 text-[10px] font-medium text-[#384959]">{t}</span>
                  ))}
                </div>
                <div className="mt-3 space-y-2">
                  {[
                    { t: "Senior Software Engineer", c: "DBS Bank", s: ["Python", "AWS", "SQL"], match: 92 },
                    { t: "Data Analyst", c: "GovTech", s: ["Tableau", "Python"], match: 85 },
                  ].map((j) => (
                    <div key={j.t} className="rounded-xl border border-[#BDDDFC]/20 p-3.5 transition-colors hover:border-[#88BDF2]/30">
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="text-[12px] font-semibold text-[#384959]">{j.t}</div>
                          <div className="text-[11px] text-[#6A89A7] mt-0.5">{j.c}</div>
                        </div>
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-600">{j.match}%</span>
                      </div>
                      <div className="mt-2 flex gap-1">{j.s.map((s) => <span key={s} className="rounded bg-[#BDDDFC]/20 px-1.5 py-0.5 text-[9px] font-medium text-[#384959]">{s}</span>)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          </div>

          {/* Step 2 */}
          <div className="mt-24 grid items-center gap-10 lg:grid-cols-2">
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromLeft} className="order-2 lg:order-1">
              <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-6 shadow-sm">
                <div className="flex items-start gap-5">
                  <div className="text-center shrink-0">
                    <div className="relative h-[72px] w-[72px]">
                      <svg viewBox="0 0 36 36" className="h-[72px] w-[72px] -rotate-90">
                        <circle cx="18" cy="18" r="15.5" fill="none" stroke="#BDDDFC" strokeWidth="2.5" />
                        <circle cx="18" cy="18" r="15.5" fill="none" stroke="#88BDF2" strokeWidth="2.5" strokeDasharray="85 100" strokeLinecap="round" />
                      </svg>
                      <span className="absolute inset-0 flex items-center justify-center text-xl font-bold text-[#384959]">87</span>
                    </div>
                    <div className="mt-1.5 text-[9px] font-bold uppercase tracking-wider text-[#6A89A7]">Score</div>
                  </div>
                  <div className="flex-1 space-y-3 pt-1">
                    {[
                      { l: "Impact", p: 91, c: "bg-[#88BDF2]" },
                      { l: "Presentation", p: 84, c: "bg-[#6A89A7]" },
                      { l: "Competencies", p: 80, c: "bg-emerald-400" },
                    ].map((d) => (
                      <div key={d.l}>
                        <div className="flex justify-between text-[10px]"><span className="text-[#6A89A7]">{d.l}</span><span className="font-bold text-[#384959]">{d.p}%</span></div>
                        <div className="mt-1 h-2 rounded-full bg-[#BDDDFC]/20"><div className={`h-2 rounded-full ${d.c}`} style={{ width: `${d.p}%` }} /></div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromRight} className="order-1 lg:order-2">
              <div className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#88BDF2]/20 text-[13px] font-bold text-[#384959]">2</div>
              <h3 className="font-display mt-4 text-[1.5rem] text-[#384959]">See how ready you are</h3>
              <p className="mt-3 text-[15px] leading-relaxed text-[#6A89A7]">
                Upload your resume and find out honestly where you stand. See what's working, what's missing, and get clear guidance on closing the gap.
              </p>
              <motion.button
                type="button" onClick={() => onNavigate("resume")}
                whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#384959] px-5 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-[#2d3a47]"
              >
                Score my resume <ArrowRight size={13} />
              </motion.button>
            </motion.div>
          </div>

          {/* Step 3 */}
          <div className="mt-24 grid items-center gap-10 lg:grid-cols-2">
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromLeft}>
              <div className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-[13px] font-bold text-emerald-700">3</div>
              <h3 className="font-display mt-4 text-[1.5rem] text-[#384959]">Apply with confidence</h3>
              <p className="mt-3 text-[15px] leading-relaxed text-[#6A89A7]">
                Tailor your resume for each role. Every bullet optimised, every keyword placed. Download and submit knowing you put your best foot forward.
              </p>
              <motion.button
                type="button" onClick={() => onNavigate("resume")}
                whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
                className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#384959] px-5 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-[#2d3a47]"
              >
                Start tailoring <ArrowRight size={13} />
              </motion.button>
            </motion.div>
            <motion.div initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }} variants={slideFromRight}>
              <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
                <div className="flex items-center gap-2 mb-3">
                  <span className="rounded-md bg-emerald-100 px-2 py-0.5 text-[9px] font-bold text-emerald-700">MATCHED</span>
                  {["Python", "Agile", "SQL", "AWS"].map((k) => <span key={k} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-600">{k}</span>)}
                </div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="rounded-md bg-rose-100 px-2 py-0.5 text-[9px] font-bold text-rose-700">GAPS</span>
                  {["Cloud", "CI/CD"].map((k) => <span key={k} className="rounded bg-rose-50 px-1.5 py-0.5 text-[9px] font-medium text-rose-600">{k}</span>)}
                </div>
                <div className="space-y-2">
                  <div className="rounded-xl border-l-[3px] border-[#88BDF2] bg-[#BDDDFC]/10 p-3 text-[11px] leading-relaxed text-[#384959]">
                    Led global Conversion Accelerator Program, integrating <strong className="text-[#384959]">automation</strong> to optimise fab yield across 4 fabs...
                  </div>
                  <div className="rounded-xl border-l-[3px] border-emerald-400 bg-emerald-50/30 p-3 text-[11px] leading-relaxed text-[#384959]">
                    Deployed <strong className="text-emerald-700">deep learning</strong> model (ResNet-50) for wafer misplacement detection, reducing downtime 40%...
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ═══════ PERSONAS ═══════════════════════════════════════════════════ */}
      <section className="py-20 px-6 bg-white">
        <div className="mx-auto max-w-5xl">
          <motion.h2
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }}
            variants={fadeUp}
            className="font-display text-center text-[2rem] text-[#384959] sm:text-[2.5rem]"
          >
            Wherever you are<br className="hidden sm:block" /> in your journey
          </motion.h2>
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-60px" }}
            variants={staggerContainer}
            className="mt-14 grid gap-6 sm:grid-cols-3"
          >
            {[
              { icon: GraduationCap, title: "Starting out", desc: "You've got the degree but not the experience. We help you understand what employers want and build a resume that gets through the door.", color: "#88BDF2" },
              { icon: Repeat, title: "Making a change", desc: "Switching careers is scary. We show you which skills transfer, where the gaps are, and how to tell your story for a new industry.", color: "#6A89A7" },
              { icon: Award, title: "Aiming higher", desc: "You know your worth. We help you articulate it precisely, pass ATS filters at top companies, and present your impact clearly.", color: "#384959" },
            ].map((p, i) => (
              <motion.div
                key={p.title}
                variants={scaleIn}
                custom={i}
                whileHover={{ y: -6, boxShadow: "0 16px 40px rgba(56,73,89,0.1)" }}
                className="group h-full rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-7 transition-colors"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white" style={{ boxShadow: `0 0 0 1px ${p.color}20` }}>
                  <p.icon size={20} strokeWidth={1.8} style={{ color: p.color }} />
                </div>
                <h4 className="mt-5 text-base font-bold text-[#384959]">{p.title}</h4>
                <p className="mt-2 text-[13px] leading-relaxed text-[#6A89A7]">{p.desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ═══════ STATS ═══════════════════════════════════════════════════════ */}
      <section className="border-y border-[#BDDDFC]/20 bg-[#f0f4f8] py-16 px-6">
        <div className="mx-auto max-w-4xl">
          <motion.div
            initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-40px" }}
            variants={staggerContainer}
            className="grid grid-cols-2 gap-8 sm:grid-cols-4"
          >
            {[
              { v: countNum, s: "+", l: "Job Listings" },
              { v: 5, s: "", l: "Job Sources" },
              { v: 1500, s: "+", l: "Skills Tracked" },
              { v: 24, s: "h", l: "Data Refresh" },
            ].map((s, i) => (
              <motion.div key={s.l} variants={fadeUp} custom={i} className="text-center">
                <div className="font-display text-[2rem] text-[#384959] sm:text-[2.5rem]"><Counter target={s.v} suffix={s.s} /></div>
                <div className="mt-1 text-[12px] font-medium text-[#6A89A7]">{s.l}</div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ═══════ TRUST ═══════════════════════════════════════════════════════ */}
      <motion.section
        initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-40px" }}
        variants={staggerContainer}
        className="py-16 px-6 bg-white"
      >
        <div className="mx-auto max-w-4xl">
          <div className="grid gap-8 sm:grid-cols-3">
            {[
              { icon: MapPin, title: "Built for Singapore", desc: "Skills taxonomy and resume conventions tailored to the SG job market." },
              { icon: Zap, title: "Intelligent scoring", desc: "ATS keyword extraction, resume scoring, and one-click tailoring." },
              { icon: Shield, title: "Private and free", desc: "Your resume stays on your device. No data leaves your browser." },
            ].map((t, i) => (
              <motion.div key={t.title} variants={fadeUp} custom={i} className="flex items-start gap-3.5">
                <div className="flex-shrink-0 rounded-xl bg-[#f0f4f8] p-2.5 text-[#6A89A7] border border-[#BDDDFC]/30"><t.icon size={16} strokeWidth={1.8} /></div>
                <div>
                  <div className="text-sm font-bold text-[#384959]">{t.title}</div>
                  <div className="mt-0.5 text-[13px] leading-relaxed text-[#6A89A7]">{t.desc}</div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </motion.section>

      {/* ═══════ CTA ═══════════════════════════════════════════════════════ */}
      <section className="relative overflow-hidden py-24 px-6 bg-[#384959]">
        <motion.div
          initial="hidden" whileInView="visible" viewport={{ once: true, margin: "-40px" }}
          variants={staggerContainer}
          className="relative mx-auto max-w-3xl text-center"
        >
          <motion.h2 variants={fadeUp} className="font-display text-[2rem] text-white sm:text-[2.75rem] leading-[1.1]">
            Your dream role is<br />closer than you think
          </motion.h2>
          <motion.p variants={fadeUp} custom={1} className="mt-4 text-[15px] text-[#6A89A7]">
            Thousands of Singapore professionals have taken the first step. Your turn.
          </motion.p>
          <motion.div variants={fadeUp} custom={2} className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <motion.button
              type="button" onClick={() => onNavigate("jobs")}
              whileHover={{ scale: 1.03, boxShadow: "0 8px 30px rgba(136,189,242,0.3)" }}
              whileTap={{ scale: 0.97 }}
              className="group inline-flex items-center gap-2.5 rounded-full bg-[#88BDF2] px-8 py-4 text-sm font-bold text-[#1f2831] transition-colors hover:bg-[#BDDDFC]"
            >
              Start your journey <ArrowRight size={15} className="transition-transform group-hover:translate-x-1" />
            </motion.button>
            <motion.button
              type="button" onClick={() => onNavigate("resume")}
              whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}
              className="rounded-full border-2 border-[#6A89A7]/40 px-8 py-4 text-sm font-semibold text-white transition-colors hover:border-[#6A89A7] hover:bg-white/5"
            >
              Score my resume
            </motion.button>
          </motion.div>
        </motion.div>
      </section>
    </div>
  );
}
