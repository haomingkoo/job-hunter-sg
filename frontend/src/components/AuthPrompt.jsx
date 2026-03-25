import { User } from "lucide-react";

export default function AuthPrompt({ onSignIn, featureName }) {
  return (
    <div className="text-center py-16">
      <User size={40} className="mx-auto mb-4 text-gray-300" />
      <h3 className="text-lg font-semibold text-gray-700 mb-2">Sign in to access {featureName}</h3>
      <p className="text-sm text-gray-500 mb-6 max-w-md mx-auto">
        Create a free account or sign in with your @aisg.sg email to unlock this feature.
      </p>
      <button onClick={onSignIn}
        className="bg-indigo-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition">
        Sign In
      </button>
    </div>
  );
}
