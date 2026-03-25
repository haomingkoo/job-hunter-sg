import { useState, useEffect, useCallback } from "react";
import { Briefcase, Loader2, LogOut } from "lucide-react";

import { apiFetch, clearResumeDraftStorage } from "./lib/api.js";

import Nav from "./components/Nav.jsx";
import AuthModal from "./components/AuthModal.jsx";
import AuthPrompt from "./components/AuthPrompt.jsx";
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
  const [activeTab, setActiveTab] = useState("scraper");
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
      // Non-critical: tracked jobs will be empty for unauthenticated users
      setTrackedJobs([]);
    }
  }, []);

  useEffect(() => {
    if (user) refreshJobs();
  }, [user, refreshJobs]);

  // Usage meter (item 7)
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
    setActiveTab("scraper");
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

  // Loading state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={32} className="animate-spin text-indigo-600 mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="w-full px-4 sm:px-6 lg:px-10">
        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold flex items-center gap-2"><Briefcase size={22} /> Job Hunter SG</h1>
              <p className="text-indigo-100 text-sm mt-1">Search SG jobs, track applications, and get AI-powered resume coaching.</p>
            </div>
            <div className="flex items-center gap-3">
              {user ? (
                <>
                  {usageData && (
                    <div className="bg-white/15 rounded-lg px-3 py-1.5 text-xs text-indigo-100 hidden sm:block">
                      {usageData.tracked_jobs} tracked{usageData.can_export ? " | Pro" : ""}
                    </div>
                  )}
                  <div className="text-right">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{user.name}</span>
                      <TierBadge tier={user.tier} />
                    </div>
                    <div className="text-indigo-200 text-xs">{user.email}</div>
                  </div>
                  <button onClick={handleLogout} className="text-indigo-200 hover:text-white transition" title="Sign out">
                    <LogOut size={18} />
                  </button>
                </>
              ) : (
                <button onClick={() => setShowAuthModal(true)}
                  className="bg-white/20 hover:bg-white/30 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
                  Sign In
                </button>
              )}
            </div>
          </div>
        </div>

        {showAuthModal && (
          <AuthModal onAuth={(authUser, authToken) => { handleAuth(authUser, authToken); setShowAuthModal(false); }} onClose={() => setShowAuthModal(false)} />
        )}

        <Nav active={activeTab} setActive={setActiveTab} />

        <div className="p-6">
          {activeTab === "scraper" && (
            <ScraperTab
              user={user}
              trackedJobs={trackedJobs}
              onTrack={handleTrackJob}
              setActiveTab={setActiveTab}
              setSelectedJob={setSelectedJob}
              onSignIn={() => setShowAuthModal(true)}
            />
          )}
          {activeTab === "power" && (
            user ? (
              <PowerTab
                onTrack={handleTrackJob}
                setSelectedJob={setSelectedJob}
                setActiveTab={setActiveTab}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Power Match" />
            )
          )}
          {activeTab === "tracker" && (
            user ? (
              <TrackerTab
                user={user}
                jobs={trackedJobs}
                refreshJobs={refreshJobs}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Application Tracker" />
            )
          )}
          {activeTab === "analytics" && <AnalyticsTab />}
          {activeTab === "reminders" && (
            user ? (
              <RemindersTab
                jobs={trackedJobs}
                onUpdateJob={handleUpdateJob}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Follow-up Reminders" />
            )
          )}
          {activeTab === "resume" && <ResumeTab selectedJob={selectedJob} user={user} setActiveTab={setActiveTab} />}
          {activeTab === "account" && (
            user ? (
              <AccountTab user={user} onLogout={handleLogout} />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Account Settings" />
            )
          )}
        </div>
      </div>
    </div>
  );
}
