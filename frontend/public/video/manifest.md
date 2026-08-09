# Video assets — manifest & usage rules

7 clips, one slot each. Everything is 720p (source limit), audio stripped, `faststart` enabled,
MP4 (H.264) + WebM (VP9) per clip, plus a poster JPG. All loopers are crossfade-looped —
first frame matches last frame, so they cycle without a visible jump.

## The restraint rules (this is the point — read before adding motion)

1. **Never two moving things visible at once.** One clip per viewport, ever. If the hero loop is
   playing, no other video or looping animation is on screen.
2. **Motion goes behind content, never beside it.** Backgrounds only, at reduced opacity
   (`opacity: .35–.5`) with a dark overlay so text stays readable.
3. **Autoplay must be `muted playsinline loop` + `preload="none"`** and paused when off-screen
   (IntersectionObserver). Otherwise mobile battery and scroll perf take the hit.
4. **Ambient loops keep playing under `prefers-reduced-motion`.** Slow drifting particles behind a
   scrim are not the kind of motion that setting targets (parallax, auto-scroll, large zoom/pan), and
   gating them to a static JPG costs the whole feel for little real benefit.
   **One exception — the intro.** `intro-shield` goes luminance 0.1 → 253, a full-screen black-to-white
   flash. That's photosensitivity, not taste (WCAG 2.3.1 is Level A). Reduced-motion users skip the
   intro and land directly on the site. Everyone else sees it.
5. **Poster always set.** The video is progressive enhancement; the poster is the real first paint.

## Files

| File | Slot | Length | Notes |
|---|---|---|---|
| `intro-shield` | ENTER → site transition | 5.0s | **Plays once, not a loop.** Starts pure black (lum 0.1), ends near-white (lum 253) — cut to the site on that white frame. |
| `intro-shield-endframe.jpg` | first painted frame of the site | — | Use as the bright wash the app fades in from, so the video→DOM cut is invisible. |
| `hero-desktop` | landing hero background (≥768px) | 4.2s | Drifting cyan particles. Calmest option — safest behind a headline. |
| `hero-mobile` | landing hero background (<768px) | 4.2s | Vertical 720×1280. Dark top third = put the headline there. |
| `object-core` | one feature/product section | 4.2s | Faceted crystal "data core." The showpiece — use in exactly one place. |
| `threat-globe` | dashboard / threat-intel section | 5.0s | Plexus sphere. Functional, not decorative — reads as a real threat map. |
| `backdrop-spires` | one atmospheric section break | 4.2s | Held in reserve. Only if a section genuinely needs air. |
| `loading-ring` | loading / empty states | 3.2s | Rotating ring. Beats a CSS spinner; keep it small. |

## Not optimized (raw originals kept in `~/Downloads/higgs/aipcc`)
`intro reveal 1/3/4`, `hero loop 1/3`, `object 1`, `backdrop 1/3`, `threat intel` (neon shields),
`ambient` variants. Deliberately excluded to avoid a flashy, noisy site. Pull one in only if a
chosen clip fails in context — swap, don't add.

## Reference implementation

```jsx
<video
  className="absolute inset-0 h-full w-full object-cover opacity-40"
  poster="/video/hero-desktop-poster.jpg"
  autoPlay muted loop playsInline preload="none"
>
  <source src="/video/hero-desktop.webm" type="video/webm" />
  <source src="/video/hero-desktop.mp4"  type="video/mp4"  />
</video>
<div className="absolute inset-0 bg-[#070a12]/70" />  {/* readability scrim */}
```

WebM first — it's 20–70% smaller and Chrome/Firefox take it; Safari falls back to the MP4.
Ambient loops need no reduced-motion guard; they play for everyone.

Intro gate (the only reduced-motion check in the app):

```jsx
const skipIntro = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// skipIntro === true  → mount the app directly, no flash
// skipIntro === false → play /video/intro-shield.mp4, then cut on its white end-frame
```

## Related
In-UI feature beats (RAG, anomaly, FIM seal, chat waveform) are **code**, not video —
see `frontend/src/components/motion/`. They're weightless and don't count against rule #1
the way a video does, but rule #2 still applies.
