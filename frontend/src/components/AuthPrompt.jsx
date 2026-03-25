import { User } from "lucide-react";

export default function AuthPrompt({ onSignIn, featureName }) {
  return (
    <div className="text-center py-16">
      <User size={40} className="mx-auto mb-4 text-[#6A89A7]" />
      <h3 className="text-lg font-semibold text-[#384959] mb-2">Sign in to access {featureName}</h3>
      <p className="text-sm text-[#6A89A7] mb-6 max-w-md mx-auto">
        Create a free account or sign in with your @aisg.sg email to unlock this feature.
      </p>
      <button onClick={onSignIn}
        className="bg-[#384959] text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-[#2d3a47] transition">
        Sign In
      </button>
    </div>
  );
}
