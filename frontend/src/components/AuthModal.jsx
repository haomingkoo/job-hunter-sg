import { useEffect, useMemo, useState } from "react";
import { X, Briefcase, Loader2, Mail, KeyRound } from "lucide-react";
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

export default function AuthModal({ onAuth, onClose, initialResetToken = "", onResetComplete }) {
  const [mode, setMode] = useState(initialResetToken ? "reset" : "login");
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

  useEffect(() => {
    if (initialResetToken) {
      setResetToken(initialResetToken);
      setMode("reset");
      setError("");
      setSuccess("");
    }
  }, [initialResetToken]);

  const copy = useMemo(() => {
    if (mode === "signup") {
      return {
        title: "Create your free account",
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
  }, [mode]);

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
      if (mode === "forgot") {
        const resp = await fetch(`${API_BASE}/api/auth/forgot-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        if (!resp.ok) throw new Error(await readAuthError(resp));
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
        setSuccess("Password updated. Sign in with your new password.");
        setResetToken("");
        setNewPassword("");
        setConfirmPassword("");
        setMode("login");
        onResetComplete?.();
        return;
      }

      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body = mode === "login" ? { email, password } : { email, password, name, accepted_terms: acceptedTerms };
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(await readAuthError(resp));
      const data = await resp.json();
      localStorage.setItem("token", data.token);
      onAuth(data.user, data.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const Icon = copy.icon;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999] p-4 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8 relative">
        {onClose && <button onClick={onClose} className="absolute top-4 right-4 text-[#6A89A7] hover:text-[#384959]"><X size={20} /></button>}
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

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "signup" && (
            <input
              type="text" placeholder="Full Name" value={name}
              onChange={(e) => setName(e.target.value)} required
              autoComplete="name"
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {(mode === "login" || mode === "signup" || mode === "forgot") && (
            <input
              type="email" placeholder="Email" value={email}
              onChange={(e) => setEmail(e.target.value)} required
              autoComplete="email"
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {(mode === "login" || mode === "signup") && (
            <input
              type="password" placeholder="Password" value={password}
              onChange={(e) => setPassword(e.target.value)} required minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
            />
          )}

          {mode === "reset" && (
            <>
              <input
                type="password" placeholder="New password" value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)} required minLength={8}
                autoComplete="new-password"
                className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
              />
              <input
                type="password" placeholder="Confirm new password" value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)} required minLength={8}
                autoComplete="new-password"
                className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
              />
            </>
          )}

          {mode === "signup" && (
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
            {mode === "login" && "Sign In"}
            {mode === "signup" && "Create Account"}
            {mode === "forgot" && "Send Reset Link"}
            {mode === "reset" && "Update Password"}
          </button>
        </form>

        {mode === "signup" && (
          <p className="text-xs text-[#6A89A7] text-center mt-3">
            This is a hobby project. Resume feedback, job matching, and alerts are informational and may be wrong.
          </p>
        )}

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
      </div>
    </div>
  );
}
