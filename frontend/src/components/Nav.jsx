import { motion } from "framer-motion";
import {
  Search, Briefcase, Bell, FileText, BookOpen,
  Sparkles, BarChart2, User,
} from "lucide-react";

export default function Nav({ active, setActive }) {
  const tabs = [
    { id: "jobs", label: "Jobs", icon: Search },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "stories", label: "Stories", icon: BookOpen },
    { id: "tracker", label: "Applications", icon: Briefcase },
    { id: "analytics", label: "Market Insights", icon: BarChart2 },
    { id: "power", label: "Smart Match", icon: Sparkles },
    { id: "account", label: "Account", icon: User },
  ];
  return (
    <div className="relative bg-white border-b border-[#BDDDFC]/30">
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
              className={`relative flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors ${
                active === t.id
                  ? "text-[#384959]"
                  : "text-[#6A89A7] hover:text-[#384959]"
              }`}
            >
              <Icon size={15} />
              {t.label}
              {active === t.id && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#384959] rounded-full"
                  transition={{ type: "spring", stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
