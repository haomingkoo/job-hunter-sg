import {
  Search, Briefcase, Bell, FileText,
  Sparkles, BarChart2, User,
} from "lucide-react";

export default function Nav({ active, setActive }) {
  const tabs = [
    { id: "scraper", label: "Jobs", icon: Search },
    { id: "power", label: "Power Match", icon: Sparkles },
    { id: "tracker", label: "Tracker", icon: Briefcase },
    { id: "analytics", label: "Insights", icon: BarChart2 },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "account", label: "Account", icon: User },
  ];
  return (
    <div className="relative bg-white border-b border-gray-200">
      <nav
        className="mx-auto max-w-7xl flex overflow-x-auto scrollbar-hide"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
      >
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setActive(t.id)}
              className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${
                active === t.id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              <Icon size={15} />
              {t.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
