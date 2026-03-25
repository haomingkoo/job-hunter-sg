export default function TierBadge({ tier }) {
  if (tier === "pro" || tier === "admin") {
    return <span className="bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full text-xs font-semibold">Pro</span>;
  }
  return <span className="bg-[#BDDDFC]/10 text-[#6A89A7] px-2 py-0.5 rounded-full text-xs font-semibold">Free</span>;
}
