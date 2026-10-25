import { LockKeyhole } from "lucide-react";

export default function AuthPrompt({ onSignIn, featureName }) {
  return (
    <div className="mx-auto max-w-lg rounded-2xl border border-[#BDDDFC]/50 bg-white px-6 py-12 text-center">
      <LockKeyhole size={28} aria-hidden="true" className="mx-auto mb-4 text-[#6A89A7]" />
      <h2 className="text-lg font-semibold text-[#384959]">Sign in to use {featureName}</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted">
        {featureName} keeps your work in your account. Sign in, or create a free account.
      </p>
      <button
        type="button"
        onClick={onSignIn}
        className="mt-6 inline-flex min-h-11 items-center rounded-lg bg-[#384959] px-6 text-sm font-medium text-white transition hover:bg-[#2d3a47] active:scale-[0.97]"
      >
        Sign In
      </button>
    </div>
  );
}
