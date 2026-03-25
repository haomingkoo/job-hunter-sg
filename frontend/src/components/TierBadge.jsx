export default function TierBadge({ tier }) {
  if (tier === "pro" || tier === "admin") {
    return <span className="bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full text-xs font-semibold">Pro</span>;
  }
  return <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full text-xs font-semibold">Free</span>;
}
