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
    { id: "reminders", label: "Reminders", icon: Bell },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "account", label: "Account", icon: User },
  ];
  return (
    <div className="relative">
      <nav className="flex border-b border-gray-200 bg-white sticky top-0 z-10 overflow-x-auto scrollbar-hide"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}>
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setActive(t.id)}
              className={`flex items-center gap-1.5 px-4 py-3.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${active === t.id ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
              <Icon size={15} />{t.label}
            </button>
          );
        })}
      </nav>
      {/* Scroll fade indicator for mobile */}
      <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white to-transparent pointer-events-none sm:hidden" />
    </div>
  );
}
