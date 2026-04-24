import { useState } from "react";
import { X, Briefcase, Loader2 } from "lucide-react";
import { API_BASE } from "../lib/api.js";

export default function AuthModal({ onAuth, onClose }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body = mode === "login" ? { email, password } : { email, password, name };
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Request failed (${resp.status})`);
      }
      const data = await resp.json();
      localStorage.setItem("token", data.token);
      onAuth(data.user, data.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999] p-4 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8 relative">
        {onClose && <button onClick={onClose} className="absolute top-4 right-4 text-[#6A89A7] hover:text-[#6A89A7]"><X size={20} /></button>}
        <div className="text-center mb-6">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Briefcase size={24} className="text-[#384959]" />
            <h1 className="text-xl font-bold text-[#384959]">Job Hunter SG</h1>
          </div>
          <p className="text-sm text-[#6A89A7]">
            {mode === "login" ? "Welcome back" : "Create your free account"}
          </p>
          <p className="text-xs text-[#6A89A7] mt-1">Save your applications, get unlimited AI reviews, and track your progress</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {error}
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
          <input
            type="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)} required
            autoComplete="email"
            className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
          />
          <input
            type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className="w-full border border-[#BDDDFC]/30 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
          />
          <button type="submit" disabled={loading}
            className="w-full bg-[#384959] text-white py-2.5 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-50 transition flex items-center justify-center gap-2">
            {loading && <Loader2 size={14} className="animate-spin" />}
            {mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {mode === "signup" && (
          <p className="text-xs text-[#6A89A7] text-center mt-3">
            By signing up, you agree that we store your resume data solely to personalise your coaching experience. We never sell, share, or use your data for any other purpose.{" "}
            <button onClick={() => window.open(`${API_BASE}/api/privacy`, "_blank")} className="text-[#88BDF2] hover:underline">Privacy Notice</button>
          </p>
        )}

        <div className="text-center mt-4">
          <button onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}
            className="text-sm text-[#384959] hover:underline">
            {mode === "login" ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
