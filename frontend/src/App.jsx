import { useState, useEffect, useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Briefcase, Loader2, LogOut, ChevronLeft } from "lucide-react";

import { apiFetch, clearResumeDraftStorage } from "./lib/api.js";

import Nav from "./components/Nav.jsx";
import AuthModal from "./components/AuthModal.jsx";
import AuthPrompt from "./components/AuthPrompt.jsx";
import HomePage from "./components/HomePage.jsx";
import ScraperTab from "./components/ScraperTab.jsx";
import PowerTab from "./components/PowerTab.jsx";
import TrackerTab from "./components/TrackerTab.jsx";
import AnalyticsTab from "./components/AnalyticsTab.jsx";
import RemindersTab from "./components/RemindersTab.jsx";
import AccountTab from "./components/AccountTab.jsx";
import StoriesTab from "./components/StoriesTab.jsx";
import TierBadge from "./components/TierBadge.jsx";
import ResumeTab from "./components/ResumeTab.jsx";

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════════════════

export default function JobHunterSG() {
  const [activeTab, setActiveTab] = useState("home");
  const [trackedJobs, setTrackedJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);

  // Scroll state for glassmorphism header
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Auth state
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [authLoading, setAuthLoading] = useState(true);
  const [showAuthModal, setShowAuthModal] = useState(false);

  // Validate token on mount
  useEffect(() => {
    if (!token) {
      setAuthLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/auth/me");
        const data = await resp.json();
        if (!cancelled) setUser(data);
      } catch {
        localStorage.removeItem("token");
        if (!cancelled) setToken(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // Load tracked jobs once authenticated
  const refreshJobs = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/tracked");
      const data = await resp.json();
      setTrackedJobs(Array.isArray(data) ? data : data.jobs || []);
    } catch {
      setTrackedJobs([]);
    }
  }, []);

  useEffect(() => {
    if (user) refreshJobs();
  }, [user, refreshJobs]);

  // Usage meter
  const [usageData, setUsageData] = useState(null);
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/usage");
        const data = await resp.json();
        if (!cancelled) setUsageData(data);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const handleAuth = (authUser, authToken) => {
    setUser(authUser);
    setToken(authToken);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    clearResumeDraftStorage();
    setUser(null);
    setToken(null);
    setTrackedJobs([]);
    setActiveTab("home");
  };

  const handleTrackJob = async (payload) => {
    await apiFetch("/api/tracked", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshJobs();
  };

  const handleUpdateJob = async (id, updates) => {
    await apiFetch(`/api/tracked/${id}`, {
      method: "PUT",
      body: JSON.stringify(updates),
    });
    await refreshJobs();
  };

  const navigateTo = (tab) => {
    setActiveTab(tab);
    window.scrollTo({ top: 0, behavior: "smooth" });
    // Push to browser history so Back button goes to home, not leaves site
    if (tab !== "home") {
      window.history.pushState({ tab }, "", `#${tab}`);
    }
  };

  // Handle browser back button
  useEffect(() => {
    const handlePopState = () => {
      setActiveTab("home");
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Loading state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={28} className="animate-spin text-[#88BDF2] mx-auto" />
          <p className="text-sm text-[#6A89A7] mt-3">Loading...</p>
        </div>
      </div>
    );
  }

  const isHome = activeTab === "home";

  return (
    <div className="min-h-screen bg-[#f0f4f8]">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className={`sticky top-0 z-50 border-b transition-all duration-300 ${
        isHome
          ? `${scrolled ? "bg-[#384959]/90 backdrop-blur-md shadow-md" : "bg-[#384959]"} border-[#2d3a47]`
          : `${scrolled ? "bg-white/80 backdrop-blur-md shadow-sm" : "bg-white"} border-[#BDDDFC]/30`
      }`}>
        <div className="mx-auto max-w-7xl flex items-center justify-between px-4 sm:px-6 h-14">
          <button
            type="button"
            onClick={() => navigateTo("home")}
            className={`flex items-center gap-2 text-base font-bold transition ${isHome ? "text-white" : "text-[#384959] hover:text-[#88BDF2]"}`}
          >
            <Briefcase size={18} />
            Job Hunter SG
          </button>

          <div className="flex items-center gap-3">
            {!isHome && (
              <button
                type="button"
                onClick={() => navigateTo("home")}
                className="hidden sm:flex items-center gap-1 text-xs text-[#6A89A7] hover:text-[#384959] transition"
              >
                <ChevronLeft size={14} />
                Home
              </button>
            )}
            {user ? (
              <div className="flex items-center gap-3">
                <div className="hidden sm:flex items-center gap-2 text-sm">
                  <span className={`font-medium ${isHome ? "text-white" : "text-[#384959]"}`}>{user.name}</span>
                  <TierBadge tier={user.tier} />
                </div>
                <button
                  onClick={handleLogout}
                  className={`transition ${isHome ? "text-[#6A89A7] hover:text-white" : "text-[#6A89A7] hover:text-[#384959]"}`}
                  title="Sign out"
                >
                  <LogOut size={16} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowAuthModal(true)}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${isHome ? "bg-[#88BDF2] text-[#1f2831] hover:bg-[#BDDDFC]" : "bg-[#384959] text-white hover:bg-[#2d3a47]"}`}
              >
                Sign In
              </button>
            )}
          </div>
        </div>
      </header>

      {showAuthModal && (
        <AuthModal
          onAuth={(authUser, authToken) => { handleAuth(authUser, authToken); setShowAuthModal(false); }}
          onClose={() => setShowAuthModal(false)}
        />
      )}

      {/* ── Content ────────────────────────────────────────────────────── */}
      {isHome ? (
        <HomePage
          onNavigate={navigateTo}
          onSignIn={() => setShowAuthModal(true)}
          user={user}
        />
      ) : (
        <>
          <Nav active={activeTab} setActive={navigateTo} />
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
              className="mx-auto max-w-7xl p-4 sm:p-6"
            >
              {activeTab === "jobs" && (
                <ScraperTab
                  user={user}
                  trackedJobs={trackedJobs}
                  onTrack={handleTrackJob}
                  setActiveTab={navigateTo}
                  setSelectedJob={setSelectedJob}
                  onSignIn={() => setShowAuthModal(true)}
                />
              )}
              {activeTab === "power" && (
                user ? (
                  <PowerTab onTrack={handleTrackJob} setSelectedJob={setSelectedJob} setActiveTab={navigateTo} />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Power Match" />
                )
              )}
              {activeTab === "tracker" && (
                user ? (
                  <TrackerTab user={user} jobs={trackedJobs} refreshJobs={refreshJobs} setActiveTab={navigateTo} />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Application Tracker" />
                )
              )}
              {activeTab === "analytics" && <AnalyticsTab />}
              {activeTab === "reminders" && (
                user ? (
                  <RemindersTab jobs={trackedJobs} onUpdateJob={handleUpdateJob} />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Follow-up Reminders" />
                )
              )}
              {activeTab === "resume" && <ResumeTab selectedJob={selectedJob} user={user} setActiveTab={navigateTo} />}
              {activeTab === "stories" && (
                user ? (
                  <StoriesTab user={user} />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Interview Story Bank" />
                )
              )}
              {activeTab === "account" && (
                user ? (
                  <AccountTab user={user} onLogout={handleLogout} />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Account Settings" />
                )
              )}
            </motion.div>
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
