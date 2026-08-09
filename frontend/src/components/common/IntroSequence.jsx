import { useCallback, useEffect, useRef, useState } from "react";

const SESSION_KEY = "aipcc.intro-played";

/**
 * The `intro-shield` clip, played once per session on the way into the app.
 *
 * This is the app's only `prefers-reduced-motion` gate, and it is not a taste
 * call: the clip runs from luminance 0.1 to 253 — a full-screen black-to-white
 * flash — which is WCAG 2.3.1 territory. Reduced-motion users land straight on
 * the app. Everyone else can still skip it with a click or any key.
 *
 * See `public/video/manifest.md`.
 */
export function IntroSequence() {
  const videoRef = useRef(null);

  // Resolved once, in the initialiser. Deciding this inside an effect would
  // mean a first render that says "playing", then a synchronous setState to
  // correct it — a cascading render, and a visible flash for the users this
  // gate exists to protect.
  const [visible, setVisible] = useState(() => {
    let played = false;
    try {
      played = sessionStorage.getItem(SESSION_KEY) === "1";
    } catch {
      /* Storage unavailable — the intro simply plays again next time. */
    }
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    return !played && !reduced;
  });

  const finish = useCallback(() => {
    setVisible(false);
    try {
      sessionStorage.setItem(SESSION_KEY, "1");
    } catch {
      /* Storage unavailable. */
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    const skip = () => finish();
    window.addEventListener("keydown", skip);
    // A clip that cannot be dismissed is a clip that will be resented.
    const timeout = window.setTimeout(finish, 6000);
    return () => {
      window.removeEventListener("keydown", skip);
      window.clearTimeout(timeout);
    };
  }, [visible, finish]);

  if (!visible) return null;

  return (
    <div
      className="fixed inset-0 z-[200] bg-black"
      onClick={finish}
      role="presentation"
    >
      <video
        ref={videoRef}
        className="size-full object-cover"
        poster="/video/intro-shield-poster.jpg"
        autoPlay
        muted
        playsInline
        preload="auto"
        onEnded={finish}
        onError={finish}
      >
        <source src="/video/intro-shield.webm" type="video/webm" />
        <source src="/video/intro-shield.mp4" type="video/mp4" />
      </video>
      <button
        type="button"
        onClick={finish}
        className="eyebrow absolute bottom-8 right-8 rounded-md border border-white/25 bg-black/40 px-3 py-1.5 text-white/70 backdrop-blur transition-colors hover:border-white/50 hover:text-white"
      >
        Skip
      </button>
    </div>
  );
}
