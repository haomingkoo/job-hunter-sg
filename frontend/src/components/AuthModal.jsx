import { useEffect, useMemo, useRef, useState } from "react";
import { X, Briefcase, Loader2, Mail, KeyRound, ShieldCheck } from "lucide-react";
import { API_BASE } from "../lib/api.js";

async function readAuthError(resp) {
  const text = await resp.text();
  try {
    const payload = JSON.parse(text);
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
    if (typeof payload.message === "string") return payload.message;
  } catch {
    // fall through
  }
  return text || `Request failed (${resp.status})`;
}

export default function AuthModal({
  onAuth,
  onClose,
  authConfig = { mode: "password" },
  cloudflareIdentityReady = false,
  initialResetToken = "",
  initialVerifyToken = "",
  onResetComplete,
  onVerifyComplete,
}) {
  const [mode, setMode] = useState(initialVerifyToken ? "verify" : initialResetToken ? "reset" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [resetToken, setResetToken] = useState(initialResetToken || "");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (initialResetToken) {
      setResetToken(initialResetToken);
      setMode("reset");
      setError("");
      setSuccess("");
    }
  }, [initialResetToken]);

  useEffect(() => {
    if (!initialVerifyToken) return;
    setMode("verify");
    setError("");
    setSuccess("");
  }, [initialVerifyToken]);

  const copy = useMemo(() => {
    if (mode === "verify") {
      return {
        title: "Verify your email",
        subtitle: "Choose the password for this account.",
        icon: Mail,
      };
    }
    if (mode === "signup-sent") {
      return {
        title: "Check your email",
        subtitle: "Open the verification link to activate your account.",
        icon: Mail,
      };
    }
    if (authConfig.mode === "cloudflare") {
      return {
        title: "Continue with Cloudflare",
        subtitle: "Verify your email, then create your Job Hunter SG account.",
        icon: ShieldCheck,
      };
    }
    if (mode === "signup") {
      return {
        title: "Create your account",
        subtitle: "Save applications, resumes, matches, and alert preferences.",
        icon: Briefcase,
      };
    }
    if (mode === "forgot") {
      return {
        title: "Reset your password",
        subtitle: "We will email a reset link if the account exists.",
        icon: Mail,
      };
    }
    if (mode === "reset") {
      return {
        title: "Choose a new password",
        subtitle: "Use at least 8 characters.",
        icon: KeyRound,
      };
    }
    return {
      title: "Welcome back",
      subtitle: "Sign in to continue your job search workspace.",
      icon: Briefcase,
    };
  }, [authConfig.mode, loading, mode]);

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError("");
    setSuccess("");
    setAcceptedTerms(false);
    setPassword("");
    setNewPassword("");
    setConfirmPassword("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      if (mode === "verify") {
        if (!initialVerifyToken) throw new Error("Verification link is missing. Request a new email.");
        if (password !== confirmPassword) throw new Error("Passwords do not match.");
        const resp = await fetch(`${API_BASE}/api/auth/verify-email`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: initialVerifyToken,
            password,
            name,
            accepted_terms: acceptedTerms,
          }),
        });
        if (!resp.ok) throw new Error(await readAuthError(resp));
        const data = await resp.json();
        if (!mountedRef.current) return;
        localStorage.setItem("token", data.token);
        onVerifyComplete?.();
        onAuth(data.user, data.token);
        return;
      }

      if (mode === "forgot") {
        const resp = await fetch(`${API_BASE}/api/auth/forgot-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        if (!resp.ok) throw new Error(await readAuthError(resp));
        if (!mountedRef.current) return;
        setSuccess("If that email is registered, a reset link has been sent.");
        return;
      }

      if (mode === "reset") {
        if (!resetToken) throw new Error("Reset link is missing. Request a new password reset email.");
        if (newPassword !== confirmPassword) throw new Error("Passwords do not match.");
        const resp = await fetch(`${API_BASE}/api/auth/reset-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: resetToken, password: newPassword }),
        });
        if (!resp.ok) throw new Error(await readAuthError(resp));
        if (!mountedRef.current) return;
        setSuccess("Password updated. Sign in with your new password.");
        setResetToken("");
        setNewPassword("");
        setConfirmPassword("");
        setMode("login");
        onResetComplete?.();
        return;
      }

      if (authConfig.mode === "cloudflare") {
        const resp = await fetch(`${API_BASE}/api/auth/cloudflare/register`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, accepted_terms: acceptedTerms }),
        });
        if (!resp.ok) throw new Error(await readAuthError(resp));
        const data = await resp.json();
        if (!mountedRef.current) return;
        localStorage.removeItem("token");
        onAuth(data, null);
        return;
      }

      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body = mode === "login" ? { email, password } : { email, password, name, accepted_terms: acceptedTerms };
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const message = await readAuthError(resp);
        if (mode === "login" && resp.status === 403) {
          setPassword("");
          setMode("signup-sent");
          setError(message);
          return;
        }
        throw new Error(message);
      }
      if (mode === "signup") {
        const data = await resp.json();
        if (!mountedRef.current) return;
        setPassword("");
        setMode("signup-sent");
        setSuccess(data.message || "Check your email for a verification link before signing in.");
        return;
      }
      const data = await resp.json();
      if (!mountedRef.current) return;
      localStorage.setItem("token", data.token);
      onAuth(data.user, data.token);
    } catch (err) {
      if (mountedRef.current) setError(err.message);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  const resendVerification = async () => {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/api/auth/resend-verification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!resp.ok) throw new Error(await readAuthError(resp));
      await resp.json();
      if (!mountedRef.current) return;
      setSuccess("If your account is awaiting verification, a new link has been sent.");
    } catch (err) {
      if (mountedRef.current) setError(err.message);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  const Icon = copy.icon;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999] p-4 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8 relative">
        {onClose && <button type="button" aria-label="Close" onClick={onClose} className="absolute top-4 right-4 text-[#6A89A7] hover:text-[#384959]"><X size={20} /></button>}
        <div className="text-center mb-6">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Icon size={24} className="text-[#384959]" />
            <h1 className="text-xl font-bold text-[#384959]">Job Hunter SG</h1>
          </div>
          <p className="text-sm font-medium text-[#384959]">{copy.title}</p>
          <p className="text-xs text-[#6A89A7] mt-1">{copy.subtitle}</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {error}
          </div>
        )}
        {success && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-lg p-3 mb-4">
            {success}
          </div>
        )}

        {mode === "signup-sent" ? (
          <div className="space-y-3">
            <button
              type="button"
              disabled={loading}
              onClick={resendVerification}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#384959] py-2.5 text-sm font-medium text-white transition hover:bg-[#2d3a47] disabled:opacity-50"
            >
              {loading && <Loader2 size={14} className="animate-spin" />}
              Resend Verification Email
            </button>
            <button
              type="button"
              onClick={() => switchMode("login")}
              className="w-full text-sm font-medium text-[#384959] hover:underline"
            >
              Back to Sign In
            </button>
          </div>
        ) : authConfig.mode === "cloudflare" && authConfig.cloudflare_login_url && !cloudflareIdentityReady ? (
          <a
            href={authConfig.cloudflare_login_url}
            className="block w-full rounded-lg bg-[#384959] py-2.5 text-center text-sm font-medium text-white transition hover:bg-[#2d3a47]"
          >
            Continue with Cloudflare
          </a>
        ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {(mode === "signup" || mode === "verify" || authConfig.mode === "cloudflare") && (
            <input
              type="text" aria-label="Full name" placeholder="Full Name" value={name}
              onChange={(e) => setName(e.target.value)} required
              autoComplete="name"
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {authConfig.mode === "password" && (mode === "login" || mode === "signup" || mode === "forgot") && (
            <input
              type="email" aria-label="Email" placeholder="Email" value={email}
              onChange={(e) => setEmail(e.target.value)} required
              autoComplete="email"
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {authConfig.mode === "password" && (mode === "login" || mode === "signup" || mode === "verify") && (
            <input
              type="password" aria-label="Password" placeholder={mode === "verify" ? "Choose password" : "Password"} value={password}
              onChange={(e) => setPassword(e.target.value)} required minLength={8}
              autoComplete={mode === "signup" || mode === "verify" ? "new-password" : "current-password"}
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {authConfig.mode === "password" && mode === "verify" && (
            <input
              type="password" aria-label="Confirm password" placeholder="Confirm password" value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)} required minLength={8}
              autoComplete="new-password"
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {authConfig.mode === "password" && mode === "reset" && (
            <>
              <input
                type="password" aria-label="New password" placeholder="New password" value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)} required minLength={8}
                autoComplete="new-password"
                className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
              />
              <input
                type="password" aria-label="Confirm new password" placeholder="Confirm new password" value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)} required minLength={8}
                autoComplete="new-password"
                className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
              />
            </>
          )}

          {(mode === "signup" || mode === "verify" || authConfig.mode === "cloudflare") && (
            <label className="flex items-start gap-3 rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3 text-left">
              <input
                type="checkbox"
                checked={acceptedTerms}
                onChange={(e) => setAcceptedTerms(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[#384959]"
                required
              />
              <span className="text-xs leading-relaxed text-[#6A89A7]">
                I agree to the{" "}
                <button type="button" onClick={() => window.open(`${API_BASE}/api/terms`, "_blank")} className="font-medium text-[#384959] hover:underline">
                  Terms
                </button>{" "}
                and{" "}
                <button type="button" onClick={() => window.open(`${API_BASE}/api/privacy`, "_blank")} className="font-medium text-[#384959] hover:underline">
                  Privacy Notice
                </button>
                . Job alerts are optional and must be enabled separately.
              </span>
            </label>
          )}

          <button type="submit" disabled={loading}
            className="w-full bg-[#384959] text-white py-2.5 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-50 transition flex items-center justify-center gap-2 active:scale-[0.98]">
            {loading && <Loader2 size={14} className="animate-spin" />}
            {authConfig.mode === "cloudflare" && "Create Account"}
            {authConfig.mode === "password" && mode === "login" && "Sign In"}
            {mode === "signup" && "Create Account"}
            {mode === "verify" && "Activate Account"}
            {mode === "forgot" && "Send Reset Link"}
            {mode === "reset" && "Update Password"}
          </button>
        </form>
        )}

        {(mode === "signup" || (authConfig.mode === "cloudflare" && (cloudflareIdentityReady || !authConfig.cloudflare_login_url))) && (
          <p className="text-xs text-[#6A89A7] text-center mt-3">
            This is a hobby project. Resume feedback, job matching, and alerts are informational and may be wrong.
          </p>
        )}

        {authConfig.mode === "password" && mode !== "verify" && mode !== "signup-sent" && (
        <div className="text-center mt-4 space-y-2">
          {mode === "login" && (
            <button onClick={() => switchMode("forgot")} className="block w-full text-sm text-[#6A89A7] hover:text-[#384959] hover:underline">
              Forgot password?
            </button>
          )}
          {(mode === "forgot" || mode === "reset") && (
            <button onClick={() => switchMode("login")} className="text-sm text-[#384959] hover:underline">
              Back to sign in
            </button>
          )}
          {(mode === "login" || mode === "signup") && (
            <button onClick={() => switchMode(mode === "login" ? "signup" : "login")}
              className="text-sm text-[#384959] hover:underline">
              {mode === "login" ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
            </button>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
