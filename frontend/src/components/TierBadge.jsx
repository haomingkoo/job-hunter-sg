export default function TierBadge({ tier }) {
  if (tier === "pro" || tier === "admin") {
    return <span className="bg-[#88BDF2]/20 text-[#384959] px-2 py-0.5 rounded-full text-xs font-semibold">Pro</span>;
  }
  return <span className="bg-[#BDDDFC]/10 text-[#6A89A7] px-2 py-0.5 rounded-full text-xs font-semibold">Free</span>;
}
