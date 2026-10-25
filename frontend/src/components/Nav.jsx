import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import {
  Search, Briefcase, Bell, FileText, BookOpen, Users,
  Target, BarChart2, User, FolderOpen,
} from "lucide-react";

export default function Nav({ active, setActive }) {
  const activeRef = useRef(null);
  const tabs = [
    { id: "team", label: "Recruitment Team", icon: Users },
    { id: "jobs", label: "Jobs", icon: Search },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "documents", label: "Documents", icon: FolderOpen },
    { id: "stories", label: "Stories", icon: BookOpen },
    { id: "tracker", label: "Applications", icon: Briefcase },
    { id: "reminders", label: "Reminders", icon: Bell },
    { id: "analytics", label: "Market Insights", icon: BarChart2 },
    { id: "power", label: "Smart Match", icon: Target },
    { id: "account", label: "Account", icon: User },
  ];

  // Keep the current tab visible when the strip scrolls on narrow screens.
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [active]);

  return (
    <div className="relative bg-white border-b border-[#BDDDFC]/50">
      <nav
        aria-label="Sections"
        className="mx-auto max-w-7xl flex overflow-x-auto scrollbar-hide [mask-image:linear-gradient(to_right,transparent,black_16px,black_calc(100%-24px),transparent)] lg:[mask-image:none]"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}
      >
        {tabs.map((t) => {
          const Icon = t.icon;
          const isActive = active === t.id;
          return (
            <button
              key={t.id}
              ref={isActive ? activeRef : null}
              type="button"
              onClick={() => setActive(t.id)}
              aria-current={isActive ? "page" : undefined}
              className={`relative flex min-h-11 items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors focus-visible:-outline-offset-2 ${
                isActive
                  ? "text-[#384959]"
                  : "text-muted hover:text-[#384959]"
              }`}
            >
              <Icon size={15} aria-hidden="true" />
              {t.label}
              {isActive && (
                <motion.div
                  layoutId="activeTab"
                  className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#384959] rounded-full"
                  transition={{ type: "spring", bounce: 0, duration: 0.35 }}
                />
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
