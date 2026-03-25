/**
 * Premium shimmer skeleton loader for job listing cards.
 * Matches the shape of real job cards in ScraperTab.
 */
export default function JobCardSkeleton({ count = 5 }) {
  const shimmerClass = "rounded bg-[#BDDDFC]/20 animate-shimmer";
  const shimmerStyle = {
    backgroundImage:
      "linear-gradient(90deg, transparent, rgba(189,221,252,0.3), transparent)",
    backgroundSize: "200% 100%",
  };

  return (
    <div className="space-y-4">
      {Array.from({ length: count }, (_, i) => (
        <div
          key={i}
          className="bg-white rounded-2xl border border-[#BDDDFC]/25 p-5"
          style={{ animationDelay: `${i * 80}ms` }}
        >
          {/* Title row */}
          <div className="flex items-center gap-2 mb-3">
            <div
              className={`${shimmerClass} h-4 w-2/3`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80}ms` }}
            />
            <div
              className={`${shimmerClass} h-4 w-12`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 40}ms` }}
            />
          </div>

          {/* Meta row: company, location, salary */}
          <div className="flex items-center gap-3 mb-3">
            <div
              className={`${shimmerClass} h-3 w-1/3`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 60}ms` }}
            />
            <div
              className={`${shimmerClass} h-3 w-1/4`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 80}ms` }}
            />
            <div
              className={`${shimmerClass} h-3 w-20`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 100}ms` }}
            />
          </div>

          {/* Description lines */}
          <div className="space-y-2 mb-4">
            <div
              className={`${shimmerClass} h-3 w-full`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 120}ms` }}
            />
            <div
              className={`${shimmerClass} h-3 w-5/6`}
              style={{ ...shimmerStyle, animationDelay: `${i * 80 + 140}ms` }}
            />
          </div>

          {/* Skill pills */}
          <div className="flex gap-2">
            {[16, 20, 14].map((w, j) => (
              <div
                key={j}
                className={`${shimmerClass} h-6 rounded-full`}
                style={{
                  ...shimmerStyle,
                  width: `${w * 4}px`,
                  animationDelay: `${i * 80 + 160 + j * 40}ms`,
                }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
