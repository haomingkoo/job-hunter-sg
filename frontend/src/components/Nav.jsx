// Four top-level sections; each tab id is still its own URL hash.
export const NAV_GROUPS = [
  {
    id: "jobs",
    label: "Jobs",
    tabs: [
      { id: "jobs", label: "Search" },
      { id: "power", label: "Smart Match" },
      { id: "team", label: "Recruitment team" },
      { id: "analytics", label: "Market insights" },
    ],
  },
  {
    id: "resume",
    label: "Resume",
    tabs: [
      { id: "resume", label: "Resume" },
      { id: "documents", label: "Documents" },
      { id: "stories", label: "Interview stories" },
    ],
  },
  {
    id: "applications",
    label: "Applications",
    tabs: [
      { id: "tracker", label: "Tracker" },
      { id: "reminders", label: "Reminders" },
    ],
  },
  { id: "account", label: "Account", tabs: [{ id: "account", label: "Account" }] },
];

export const groupForTab = (tabId) => NAV_GROUPS.find((group) => group.tabs.some((tab) => tab.id === tabId));

export function PrimaryNav({ active, setActive, className = "" }) {
  const current = groupForTab(active);
  return (
    <nav aria-label="Sections" className={className}>
      <ul className="flex">
        {NAV_GROUPS.map((group) => {
          const isActive = current?.id === group.id;
          return (
            <li key={group.id} className="flex-1 md:flex-none">
              <button
                type="button"
                onClick={() => setActive(group.tabs[0].id)}
                aria-current={isActive ? "page" : undefined}
                className={`relative flex min-h-11 w-full items-center justify-center whitespace-nowrap px-3 text-sm font-medium transition-colors focus-visible:-outline-offset-2 md:px-4 ${
                  isActive ? "text-ink" : "text-muted hover:text-ink"
                }`}
              >
                {group.label}
                {isActive && <span aria-hidden="true" className="absolute inset-x-3 bottom-0 h-0.5 bg-accent" />}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function SubNav({ active, setActive }) {
  const group = groupForTab(active);
  if (!group || group.tabs.length < 2) return null;
  return (
    <nav aria-label={`${group.label} pages`} className="border-b border-line bg-paper">
      <ul className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-2 sm:px-4" style={{ scrollbarWidth: "none" }}>
        {group.tabs.map((tab) => {
          const isActive = tab.id === active;
          return (
            <li key={tab.id} className="shrink-0">
              <button
                type="button"
                onClick={() => setActive(tab.id)}
                aria-current={isActive ? "page" : undefined}
                className={`flex min-h-11 items-center whitespace-nowrap px-3 text-sm transition-colors focus-visible:-outline-offset-2 ${
                  isActive ? "font-semibold text-ink" : "text-muted hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
