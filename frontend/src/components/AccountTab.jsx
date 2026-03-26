import { useState, useEffect } from "react";
import { User, LogOut, Mail, Star, X, CheckCircle, Loader2 } from "lucide-react";
import { apiFetch } from "../lib/api.js";
import TierBadge from "./TierBadge.jsx";

export default function AccountTab({ user, onLogout }) {
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [contactForm, setContactForm] = useState({ name: user?.name || "", email: user?.email || "", message: "" });
  const [contactSending, setContactSending] = useState(false);
  const [contactSent, setContactSent] = useState(false);
  const [contactError, setContactError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/usage");
        const data = await resp.json();
        if (!cancelled) setUsage(data);
      } catch {
        // Non-critical: usage display will show fallback
      } finally {
        if (!cancelled) setUsageLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const sendContact = async (e) => {
    e.preventDefault();
    if (!contactForm.message.trim()) return;
    setContactSending(true);
    setContactError("");
    try {
      await apiFetch("/api/contact", {
        method: "POST",
        body: JSON.stringify(contactForm),
      });
      setContactSent(true);
      setContactForm({ ...contactForm, message: "" });
    } catch (err) {
      setContactError(err.message);
    } finally {
      setContactSending(false);
    }
  };

  const isPro = user?.tier === "pro" || user?.tier === "admin";

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-5">
        <h2 className="font-semibold text-[#384959] flex items-center gap-2"><User size={18} /> Account</h2>
        <p className="text-sm text-[#6A89A7] mt-1">Manage your account, view usage, and upgrade your plan.</p>
      </div>

      {/* User Info */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Profile</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Name</div>
            <div className="text-[#384959] font-medium">{user?.name || "\u2014"}</div>
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Email</div>
            <div className="text-[#384959]">{user?.email || "\u2014"}</div>
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Tier</div>
            <TierBadge tier={user?.tier} />
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Member Since</div>
            <div className="text-[#384959]">{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "\u2014"}</div>
          </div>
        </div>
      </div>

      {/* Usage Stats */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Usage</h3>
        {usageLoading ? (
          <div className="flex items-center gap-2 text-sm text-[#6A89A7]"><Loader2 size={14} className="animate-spin" /> Loading usage...</div>
        ) : usage ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-blue-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959]">{usage.searches_today ?? 0}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Searches Today</div>
              {usage.searches_limit != null && (
                <div className="text-xs text-[#6A89A7] mt-0.5">/ {usage.searches_limit} limit</div>
              )}
            </div>
            <div className="bg-purple-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959]">{usage.tracked_jobs ?? 0}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Tracked Jobs</div>
              {usage.tracked_limit != null && (
                <div className="text-xs text-[#6A89A7] mt-0.5">/ {usage.tracked_limit >= 999999 ? "Unlimited" : usage.tracked_limit} limit</div>
              )}
            </div>
            <div className="bg-green-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959] capitalize">{usage.tier || user?.tier || "free"}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Current Tier</div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-[#6A89A7]">Could not load usage data.</div>
        )}
      </div>

      {/* Tier Comparison */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Plan Comparison</h3>
        <div className="overflow-hidden rounded-lg border border-[#BDDDFC]/30">
          <table className="w-full text-sm">
            <thead className="bg-[#f0f4f8]">
              <tr>
                <th className="text-left px-4 py-3 text-[#6A89A7] text-xs uppercase">Feature</th>
                <th className="text-center px-4 py-3 text-[#6A89A7] text-xs uppercase">Free</th>
                <th className="text-center px-4 py-3 text-xs uppercase text-[#384959]">AISG (Free)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#BDDDFC]/20">
              <tr>
                <td className="px-4 py-3 text-[#384959]">Job Searching</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">Unlimited</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">AI Requests / day</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">500</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Resume Builder Chat</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Cover Letter Generator</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Smart Match (RAG)</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Tracked Jobs</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">Sign in required</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">ATS Scoring</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        {!isPro && (
          <div className="mt-4 bg-gradient-to-r from-indigo-50 to-purple-50 border border-[#BDDDFC]/30 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <Star size={20} className="text-[#384959]" />
              <h4 className="font-semibold text-[#384959]">Upgrade to AISG Tier</h4>
            </div>
            <p className="text-sm text-[#6A89A7] mb-3">
              Sign in with an AISG account for unlimited AI requests, job tracking, and saved resume versions.
            </p>
            <p className="text-sm text-[#6A89A7]">
              Have questions? Send us a message below or reach out directly.
            </p>
          </div>
        )}
      </div>

      {/* Contact */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Get in Touch</h3>

        <div className="flex flex-wrap gap-3 mb-5">
          <span className="text-sm text-[#6A89A7]">Send us a message below or email us through the contact form.</span>
        </div>

        {contactSent && (
          <div className="bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg p-3 mb-4">
            Message sent! We will get back to you soon.
          </div>
        )}
        {contactError && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {contactError}
          </div>
        )}

        <form onSubmit={sendContact} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input placeholder="Name" value={contactForm.name} onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
              className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Email" type="email" value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
              className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
          </div>
          <textarea placeholder="Your message..." value={contactForm.message} onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })}
            className="w-full border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" rows={3} />
          <button type="submit" disabled={contactSending || !contactForm.message.trim()}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-40 transition">
            {contactSending ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
            Send Message
          </button>
        </form>
      </div>

      {/* Logout */}
      <button onClick={onLogout}
        className="flex items-center gap-2 border border-red-200 text-red-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-50 transition w-full justify-center">
        <LogOut size={14} /> Sign Out
      </button>
    </div>
  );
}
