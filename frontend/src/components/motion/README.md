# Feature motion components

Lightweight, dependency-free motion for the four AIPCC features that should be **code, not video**
(sharper, controllable, weightless).

These animate for everyone, matching the ambient video loops — see `public/video/manifest.md`.
The single reduced-motion gate in the app is the intro's full-screen flash. The opt-out rule is
left commented in `motion.css` if you change your mind.

## Components
- `RagDissolve` — report generation (RAG)
- `AnomalyScan` — anomaly detection
- `IntegritySeal` — file integrity / FIM ("SEALED")
- `ChatWaveform` — talk-to-your-data chat

## Usage
```jsx
import { RagDissolve, AnomalyScan, IntegritySeal, ChatWaveform } from "@/components/motion";

<RagDissolve />
<AnomalyScan />
<IntegritySeal />
<ChatWaveform />
```

Each renders a fixed-height (150px) stage; wrap it in your own card. Pass `className` to restyle.

## Theming
Colors come from CSS variables on `.fm` (`--fm-cyan`, `--fm-amber`, `--fm-red`, `--fm-green`, `--fm-bg`, …).
Override them in your theme to match the final palette — default is cyan-blue + amber/red alerts on near-black.

## Quick look
Open `preview.html` in a browser to see all four running (no build step).

## Note
These pair with the Higgsfield-generated clips (intro / hero / object / environment / threat-intel globe).
Video handles the big cinematic moments; these handle the small in-UI feature beats.
