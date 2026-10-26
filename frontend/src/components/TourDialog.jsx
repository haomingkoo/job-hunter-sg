import { useEffect, useRef } from "react";
import { X } from "lucide-react";

export function wantsTour(search = window.location.search) {
  return new URLSearchParams(search).get("tour") === "1";
}

// Quiet trigger plus a native <dialog> player; ?tour=1 opens it on load.
export default function TourDialog() {
  const dialogRef = useRef(null);
  const triggerRef = useRef(null);
  const videoRef = useRef(null);

  const open = () => dialogRef.current?.showModal?.();

  useEffect(() => {
    if (wantsTour()) open();
  }, []);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={open}
        className="min-h-11 text-sm font-semibold text-accent underline-offset-2 hover:underline"
      >
        ▶ 30-second tour
      </button>
      <dialog
        ref={dialogRef}
        aria-labelledby="tour-heading"
        onClose={() => {
          videoRef.current?.pause();
          triggerRef.current?.focus();
        }}
        onClick={(event) => {
          if (event.target === dialogRef.current) dialogRef.current.close();
        }}
        className="tour-dialog w-[calc(100%-2rem)] max-w-[960px] rounded-2xl border border-line bg-white p-0 text-ink shadow-xl backdrop:bg-ink/60"
      >
        <div className="p-4 sm:p-5">
          <div className="mb-3 flex items-center justify-between gap-4">
            <h2 id="tour-heading" className="text-base font-semibold text-ink">Job Hunter SG in 30 seconds</h2>
            <button
              type="button"
              aria-label="Close tour"
              onClick={() => dialogRef.current?.close()}
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink"
            >
              <X size={20} aria-hidden="true" />
            </button>
          </div>
          <video
            ref={videoRef}
            controls
            preload="none"
            playsInline
            poster="/media/job-poster.jpg"
            className="aspect-video w-full rounded-md bg-paper"
          >
            <source src="/media/job.webm" type="video/webm" />
            <source src="/media/job.mp4" type="video/mp4" />
          </video>
          <p className="mt-2 text-xs text-muted">Music: Sascha Ende, ende.app (CC BY 4.0)</p>
        </div>
      </dialog>
    </>
  );
}
