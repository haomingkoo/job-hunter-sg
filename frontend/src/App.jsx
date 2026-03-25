import { useState, useEffect, useCallback } from "react";
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
import TierBadge from "./components/TierBadge.jsx";
import ResumeTab from "./components/ResumeTab.jsx";

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════════════════

export default function JobHunterSG() {
  const [activeTab, setActiveTab] = useState("home");
  const [trackedJobs, setTrackedJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);

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
  };

  // Loading state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={28} className="animate-spin text-blue-600 mx-auto" />
          <p className="text-sm text-gray-400 mt-3">Loading...</p>
        </div>
      </div>
    );
  }

  const isHome = activeTab === "home";

  return (
    <div className="min-h-screen bg-gray-50">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className={`sticky top-0 z-50 border-b transition-colors ${isHome ? "bg-slate-900 border-slate-800" : "bg-white border-gray-200"}`}>
        <div className="mx-auto max-w-7xl flex items-center justify-between px-4 sm:px-6 h-14">
          <button
            type="button"
            onClick={() => navigateTo("home")}
            className={`flex items-center gap-2 text-base font-bold transition ${isHome ? "text-white" : "text-gray-900 hover:text-blue-600"}`}
          >
            <Briefcase size={18} />
            Job Hunter SG
          </button>

          <div className="flex items-center gap-3">
            {!isHome && (
              <button
                type="button"
                onClick={() => navigateTo("home")}
                className="hidden sm:flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition"
              >
                <ChevronLeft size={14} />
                Home
              </button>
            )}
            {user ? (
              <div className="flex items-center gap-3">
                <div className="hidden sm:flex items-center gap-2 text-sm">
                  <span className={`font-medium ${isHome ? "text-white" : "text-gray-700"}`}>{user.name}</span>
                  <TierBadge tier={user.tier} />
                </div>
                <button
                  onClick={handleLogout}
                  className={`transition ${isHome ? "text-slate-400 hover:text-white" : "text-gray-400 hover:text-gray-600"}`}
                  title="Sign out"
                >
                  <LogOut size={16} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowAuthModal(true)}
                className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-blue-500"
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
          <div className="mx-auto max-w-7xl p-4 sm:p-6">
            {activeTab === "scraper" && (
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
                <TrackerTab user={user} jobs={trackedJobs} refreshJobs={refreshJobs} />
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
            {activeTab === "account" && (
              user ? (
                <AccountTab user={user} onLogout={handleLogout} />
              ) : (
                <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Account Settings" />
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}
