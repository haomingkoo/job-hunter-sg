import { API_BASE } from "../lib/api.js";
import { PRIVACY_CONTACT_EMAIL } from "../lib/constants.js";

const linkClass = "inline-flex min-h-6 items-center rounded-sm underline-offset-2 hover:text-ink hover:underline";

// Shared kooexperience footer: identical wording on every app.
export default function SiteFooter() {
  return (
    <footer className="border-t border-line bg-white">
      <nav aria-label="Site" className="mx-auto max-w-7xl px-4 py-5 text-sm text-muted sm:px-6">
        <ul className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <li>© 2026 Haoming Koo</li>
          <li aria-hidden="true">·</li>
          <li><a href={`${API_BASE}/api/privacy`} className={linkClass}>Privacy</a></li>
          <li aria-hidden="true">·</li>
          <li><a href={`${API_BASE}/api/terms`} className={linkClass}>Terms</a></li>
          <li aria-hidden="true">·</li>
          <li>
            Contact (<a href={`mailto:${PRIVACY_CONTACT_EMAIL}`} className={linkClass}>{PRIVACY_CONTACT_EMAIL}</a>)
          </li>
          <li aria-hidden="true">·</li>
          <li>
            More projects → <a href="https://kooexperience.com/" className={linkClass}>kooexperience.com</a>
          </li>
        </ul>
      </nav>
    </footer>
  );
}
