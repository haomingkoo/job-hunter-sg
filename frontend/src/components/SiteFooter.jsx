import { API_BASE } from "../lib/api.js";
import { PRIVACY_CONTACT_EMAIL } from "../lib/constants.js";

const linkClass = "underline-offset-2 hover:text-[#384959] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#88BDF2] rounded";

export default function SiteFooter() {
  return (
    <footer className="border-t border-[#BDDDFC]/30 bg-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-5 text-xs text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p>Job Hunter SG is run by Koo Haoming (individual, Singapore).</p>
        <nav aria-label="Legal" className="flex flex-wrap gap-x-4 gap-y-1">
          <a href={`${API_BASE}/api/privacy`} target="_blank" rel="noopener" className={linkClass}>Privacy</a>
          <a href={`${API_BASE}/api/terms`} target="_blank" rel="noopener" className={linkClass}>Terms</a>
          <a href={`mailto:${PRIVACY_CONTACT_EMAIL}`} className={linkClass}>{PRIVACY_CONTACT_EMAIL}</a>
        </nav>
      </div>
    </footer>
  );
}
