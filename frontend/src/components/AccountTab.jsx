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
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><User size={18} /> Account</h2>
        <p className="text-sm text-gray-500 mt-1">Manage your account, view usage, and upgrade your plan.</p>
      </div>

      {/* User Info */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Profile</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Name</div>
            <div className="text-gray-800 font-medium">{user?.name || "\u2014"}</div>
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Email</div>
            <div className="text-gray-800">{user?.email || "\u2014"}</div>
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Tier</div>
            <TierBadge tier={user?.tier} />
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Member Since</div>
            <div className="text-gray-800">{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "\u2014"}</div>
          </div>
        </div>
      </div>

      {/* Usage Stats */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Usage</h3>
        {usageLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Loading usage...</div>
        ) : usage ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-blue-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800">{usage.searches_today ?? 0}</div>
              <div className="text-xs text-gray-500 mt-1">Searches Today</div>
              {usage.searches_limit != null && (
                <div className="text-xs text-gray-400 mt-0.5">/ {usage.searches_limit} limit</div>
              )}
            </div>
            <div className="bg-purple-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800">{usage.tracked_jobs ?? 0}</div>
              <div className="text-xs text-gray-500 mt-1">Tracked Jobs</div>
              {usage.tracked_limit != null && (
                <div className="text-xs text-gray-400 mt-0.5">/ {usage.tracked_limit >= 999999 ? "Unlimited" : usage.tracked_limit} limit</div>
              )}
            </div>
            <div className="bg-green-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800 capitalize">{usage.tier || user?.tier || "free"}</div>
              <div className="text-xs text-gray-500 mt-1">Current Tier</div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-400">Could not load usage data.</div>
        )}
      </div>

      {/* Tier Comparison */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Plan Comparison</h3>
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 text-xs uppercase">Feature</th>
                <th className="text-center px-4 py-3 text-gray-500 text-xs uppercase">Free</th>
                <th className="text-center px-4 py-3 text-xs uppercase text-indigo-600">AISG (Free)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <tr>
                <td className="px-4 py-3 text-gray-700">Job Searching</td>
                <td className="px-4 py-3 text-center text-gray-600">Unlimited</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">AI Reviews / day</td>
                <td className="px-4 py-3 text-center text-gray-600">3</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">50</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">Tracked jobs</td>
                <td className="px-4 py-3 text-center text-gray-600">Upgrade required</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">CSV Export</td>
                <td className="px-4 py-3 text-center text-gray-400"><X size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">ATS Checker</td>
                <td className="px-4 py-3 text-center text-gray-600">Basic</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Full</td>
              </tr>
            </tbody>
          </table>
        </div>

        {!isPro && (
          <div className="mt-4 bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <Star size={20} className="text-indigo-600" />
              <h4 className="font-semibold text-gray-800">Upgrade to AISG Tier</h4>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Upgrade to get 50 AI reviews/day, unlimited tracked jobs, CSV export, and full ATS analysis.
            </p>
            <p className="text-sm text-gray-500">
              Have questions? Send us a message below or reach out directly.
            </p>
          </div>
        )}
      </div>

      {/* Contact */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Get in Touch</h3>

        <div className="flex flex-wrap gap-3 mb-5">
          <span className="text-sm text-gray-500">Send us a message below or email us through the contact form.</span>
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
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Email" type="email" value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <textarea placeholder="Your message..." value={contactForm.message} onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" rows={3} />
          <button type="submit" disabled={contactSending || !contactForm.message.trim()}
            className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
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
