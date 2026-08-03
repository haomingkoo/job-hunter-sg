import { useState, useEffect, useLayoutEffect, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Briefcase, Loader2, LogOut, ChevronLeft } from "lucide-react";

import {
  API_BASE,
  AUTH_EXPIRED_EVENT,
  AUTH_SYNC_KEY,
  apiFetch,
  bindResumeDraftStorageToUser,
  broadcastAuthChange,
  clearResumeDraftStorage,
} from "./lib/api.js";

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
import ResumeTab from "./components/ResumeTab.jsx";
import RecruitmentTeamPanel from "./components/RecruitmentTeamPanel.jsx";

const AUTH_LINK_TOKEN_NAMES = ["reset_token", "verify_token"];
const APP_TABS = new Set(["team", "jobs", "resume", "stories", "tracker", "reminders", "analytics", "power", "account"]);

export function readActiveTab(hash = window.location.hash) {
  const fragment = hash.replace(/^#/, "");
  const candidate = fragment.includes("=")
    ? new URLSearchParams(fragment).get("tab")
    : fragment;
  return APP_TABS.has(candidate) ? candidate : "home";
}

export function readAuthLinkTokens(href = window.location.href) {
  const url = new URL(href);
  const hashParams = new URLSearchParams(url.hash.slice(1));
  return Object.fromEntries(
    AUTH_LINK_TOKEN_NAMES.map((name) => [name, hashParams.get(name) || url.searchParams.get(name) || ""]),
  );
}

export function removeAuthLinkTokensFromUrl(names = AUTH_LINK_TOKEN_NAMES) {
  const url = new URL(window.location.href);
  const hashParams = new URLSearchParams(url.hash.slice(1));
  let changed = false;
  let hashChanged = false;

  names.forEach((name) => {
    if (url.searchParams.has(name)) {
      url.searchParams.delete(name);
      changed = true;
    }
    if (hashParams.has(name)) {
      hashParams.delete(name);
      changed = true;
      hashChanged = true;
    }
  });

  if (!changed) return;
  if (hashChanged) url.hash = hashParams.toString();
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

export default function JobHunterSG() {
  const [activeTab, setActiveTab] = useState(readActiveTab);
  const [trackedJobs, setTrackedJobs] = useState([]);
  const [trackedJobsError, setTrackedJobsError] = useState("");
  const [selectedJob, setSelectedJob] = useState(null);
  const [openTrackedJobId, setOpenTrackedJobId] = useState(null);

  // Scroll state for glassmorphism header
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const [user, setUser] = useState(null);
  const activeUserIdRef = useRef(null);
  const identityGenerationRef = useRef(0);
  activeUserIdRef.current = user?.id ?? null;
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [authGeneration, setAuthGeneration] = useState(0);
  const [authConfig, setAuthConfig] = useState(null);
  const [cloudflareIdentityReady, setCloudflareIdentityReady] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authLinkTokens] = useState(readAuthLinkTokens);
  const [resetToken, setResetToken] = useState(authLinkTokens.reset_token);
  const [verifyToken, setVerifyToken] = useState(authLinkTokens.verify_token);

  // Layout effects run before the app's fetch effects, so link secrets cannot
  // leak into later requests or remain visible while verification is running.
  useLayoutEffect(() => removeAuthLinkTokensFromUrl(), []);

  const clearAuthToken = useCallback((name) => {
    if (name === "reset_token") setResetToken("");
    if (name === "verify_token") setVerifyToken("");
    removeAuthLinkTokensFromUrl([name]);
  }, []);

  useEffect(() => {
    if (resetToken || verifyToken) setShowAuthModal(true);
  }, [resetToken, verifyToken]);

  useEffect(() => {
    const handleAuthExpired = (event) => {
      if (event.detail?.reason === "required") {
        setAuthLoading(false);
        setShowAuthModal(true);
        return;
      }
      identityGenerationRef.current += 1;
      bindResumeDraftStorageToUser(null);
      setUser(null);
      setToken(null);
      setTrackedJobs([]);
      setTrackedJobsError("");
      setAuthLoading(false);
      setActiveTab("home");
      setShowAuthModal(false);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
  }, []);

  useEffect(() => {
    const handleAuthStorage = (event) => {
      if (
        (event.key !== "token" && event.key !== AUTH_SYNC_KEY)
        || (event.storageArea && event.storageArea !== localStorage)
      ) return;
      identityGenerationRef.current += 1;
      clearResumeDraftStorage();
      setUser(null);
      setTrackedJobs([]);
      setTrackedJobsError("");
      setCloudflareIdentityReady(false);
      setAuthLoading(false);
      const isLoginSignal = event.key === AUTH_SYNC_KEY && event.newValue?.startsWith("login:");
      setToken(event.key === "token" ? event.newValue : localStorage.getItem("token"));
      if (isLoginSignal) setAuthGeneration((generation) => generation + 1);
      setActiveTab("home");
      setShowAuthModal(false);
    };
    window.addEventListener("storage", handleAuthStorage);
    return () => window.removeEventListener("storage", handleAuthStorage);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/api/auth/config`);
        if (!resp.ok) throw new Error(`Auth config failed (${resp.status})`);
        const data = await resp.json();
        if (!cancelled) setAuthConfig(data);
      } catch {
        // Local development remains usable if an older backend is briefly running.
        if (!cancelled) setAuthConfig({ mode: "password" });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Resolve either an app JWT account or a Cloudflare Access account on mount.
  useEffect(() => {
    if (!authConfig) return undefined;
    let cancelled = false;
    const expectedGeneration = identityGenerationRef.current;
    const isCurrentIdentity = () => (
      !cancelled && identityGenerationRef.current === expectedGeneration
    );
    setAuthLoading(true);
    (async () => {
      try {
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const resp = await fetch(`${API_BASE}/api/auth/me`, { headers, credentials: "include" });
        if (resp.status === 401) {
          if (token) {
            if (isCurrentIdentity()) {
              localStorage.removeItem("token");
              clearResumeDraftStorage();
              identityGenerationRef.current += 1;
              setUser(null);
              setTrackedJobs([]);
              setTrackedJobsError("");
              setActiveTab("home");
              setShowAuthModal(false);
              setToken(null);
              setAuthLoading(false);
            }
          } else if (isCurrentIdentity()) {
            bindResumeDraftStorageToUser(null);
          }
          if (authConfig.mode === "cloudflare") {
            const data = await resp.json().catch(() => ({}));
            if (isCurrentIdentity()) {
              setCloudflareIdentityReady(data.detail === "Account registration required");
            }
          }
          return;
        }
        if (!resp.ok) throw new Error(`Account lookup failed (${resp.status})`);
        const data = await resp.json();
        if (isCurrentIdentity()) {
          bindResumeDraftStorageToUser(data.id);
          setUser(data);
          if (authConfig.mode === "cloudflare") setCloudflareIdentityReady(true);
        }
      } catch {
        if (token && isCurrentIdentity()) localStorage.removeItem("token");
        if (isCurrentIdentity() && token) {
          identityGenerationRef.current += 1;
          clearResumeDraftStorage();
          setUser(null);
          setTrackedJobs([]);
          setTrackedJobsError("");
          setActiveTab("home");
          setShowAuthModal(false);
          setToken(null);
          setAuthLoading(false);
        }
      } finally {
        if (isCurrentIdentity()) setAuthLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authConfig, token, authGeneration]);

  const refreshJobs = useCallback(async () => {
    const expectedUserId = activeUserIdRef.current;
    const expectedGeneration = identityGenerationRef.current;
    if (expectedUserId === null) return;
    try {
      const resp = await apiFetch("/api/tracked");
      const data = await resp.json();
      if (
        activeUserIdRef.current !== expectedUserId
        || identityGenerationRef.current !== expectedGeneration
      ) return;
      setTrackedJobs(Array.isArray(data) ? data : data.jobs || []);
      setTrackedJobsError("");
    } catch (err) {
      if (
        activeUserIdRef.current !== expectedUserId
        || identityGenerationRef.current !== expectedGeneration
      ) return;
      setTrackedJobsError(err.message || "Could not refresh tracked jobs.");
    }
  }, []);

  useEffect(() => {
    if (user) refreshJobs();
  }, [user, refreshJobs]);

  const handleAuth = (authUser, authToken) => {
    identityGenerationRef.current += 1;
    bindResumeDraftStorageToUser(authUser.id);
    setTrackedJobs([]);
    setTrackedJobsError("");
    setUser(authUser);
    setToken(authToken);
    if (!authToken) broadcastAuthChange("login");
  };

  const handleLogout = async () => {
    try {
      if (authConfig?.mode === "password" && token) {
        await apiFetch("/api/auth/logout", { method: "POST", timeoutMs: 3000 });
      }
    } catch {
      // Local sign-out still completes if the backend is unavailable.
    } finally {
      identityGenerationRef.current += 1;
      localStorage.removeItem("token");
      broadcastAuthChange("logout");
      clearResumeDraftStorage();
      setUser(null);
      setToken(null);
      setTrackedJobs([]);
      setTrackedJobsError("");
      setActiveTab("home");
      setCloudflareIdentityReady(false);
      if (authConfig?.mode === "cloudflare" && authConfig.cloudflare_logout_url) {
        window.location.assign(authConfig.cloudflare_logout_url);
      }
    }
  };

  const handleAccountDeleted = (logoutUrl) => {
    identityGenerationRef.current += 1;
    localStorage.removeItem("token");
    broadcastAuthChange("logout");
    clearResumeDraftStorage();
    setUser(null);
    setToken(null);
    setTrackedJobs([]);
    setTrackedJobsError("");
    setActiveTab("home");
    setCloudflareIdentityReady(false);
    const destination = logoutUrl || authConfig?.cloudflare_logout_url;
    if (destination) window.location.assign(destination);
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
    const url = tab === "home"
      ? `${window.location.pathname}${window.location.search}`
      : `#${tab}`;
    window.history.pushState({ tab }, "", url);
  };

  useEffect(() => {
    const handlePopState = () => {
      setActiveTab(readActiveTab());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

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
          authConfig={authConfig || { mode: "password" }}
          cloudflareIdentityReady={cloudflareIdentityReady}
          initialResetToken={resetToken}
          initialVerifyToken={verifyToken}
          onResetComplete={() => clearAuthToken("reset_token")}
          onVerifyComplete={() => clearAuthToken("verify_token")}
          onAuth={(authUser, authToken) => {
            handleAuth(authUser, authToken);
            setShowAuthModal(false);
            clearAuthToken("reset_token");
            clearAuthToken("verify_token");
          }}
          onClose={() => {
            setShowAuthModal(false);
            clearAuthToken("reset_token");
            clearAuthToken("verify_token");
          }}
        />
      )}

      {isHome ? (
        <HomePage
          onNavigate={navigateTo}
        />
      ) : (
        <>
          <Nav active={activeTab} setActive={navigateTo} />
          <AnimatePresence mode="wait">
            <motion.div
              key={`${activeTab}:${user?.id ?? "anonymous"}`}
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
              {activeTab === "team" && (
                user ? (
                  <RecruitmentTeamPanel
                    user={user}
                    setActiveTab={navigateTo}
                    onOpenApplication={async (trackedJobId) => {
                      await refreshJobs();
                      setOpenTrackedJobId(trackedJobId);
                      navigateTo("tracker");
                    }}
                    onTailorJob={(job) => {
                      setSelectedJob({
                        ...job,
                        id: job.job_id,
                        url: job.source?.url || "",
                        source: job.source?.source || "",
                      });
                      navigateTo("resume");
                    }}
                  />
                ) : (
                  <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="AI Recruitment Team" />
                )
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
                  <TrackerTab
                    jobs={trackedJobs}
                    loadError={trackedJobsError}
                    refreshJobs={refreshJobs}
                    setActiveTab={navigateTo}
                    openJobId={openTrackedJobId}
                    onOpenJobHandled={() => setOpenTrackedJobId(null)}
                  />
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
                  <AccountTab
                    user={user}
                    authMode={authConfig?.mode || "password"}
                    onLogout={handleLogout}
                    onAccountDeleted={handleAccountDeleted}
                    setActiveTab={navigateTo}
                  />
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
