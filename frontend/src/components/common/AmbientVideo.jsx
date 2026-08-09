import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/**
 * Background video, per the hard rules in `public/video/manifest.md`.
 *
 * The rules are enforced here rather than trusted to each call site:
 * `muted playsinline loop preload="none"`, a poster as the real first paint,
 * reduced opacity, a readability scrim, and pausing whenever the clip scrolls
 * out of view. Rule 1 — never two moving things on screen at once — is the one
 * the component cannot enforce; that stays a routing decision.
 *
 * Ambient loops play for everyone. The single reduced-motion gate in the app
 * is the intro flash, in `IntroSequence`.
 */
export function AmbientVideo({ clip, className, opacity = "opacity-40", scrim = "bg-void/70" }) {
  const ref = useRef(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;

    // Off-screen playback costs battery and scroll performance for nothing.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) video.play().catch(() => {});
        else video.pause();
      },
      { threshold: 0.05 },
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}>
      <video
        ref={ref}
        className={cn("size-full object-cover", opacity)}
        poster={`/video/${clip}-poster.jpg`}
        autoPlay
        muted
        loop
        playsInline
        preload="none"
        aria-hidden="true"
      >
        {/* WebM first: 20–70% smaller, and Safari falls through to the MP4. */}
        <source src={`/video/${clip}.webm`} type="video/webm" />
        <source src={`/video/${clip}.mp4`} type="video/mp4" />
      </video>
      <div className={cn("absolute inset-0", scrim)} />
    </div>
  );
}
