# AIPCC — Motion Analysis + Higgsfield Prompts (from your UI references)

## The through-line in everything you saved
Near-black backgrounds · one accent glow · oversized bold type bleeding off edges · a cinematic hero
that emerges from darkness · glass panels · a deliberate "enter the site" intro. This is a coherent dark
"security console" aesthetic. **Lock the palette:** cyan-blue primary, amber/red for alerts, near-black base.

## CRITICAL: generate video only for what code can't do
- **Build in code (GSAP / Framer Motion / CSS / WebGL) — do NOT generate:** kinetic/sliding/distorting text,
  page-enter transitions, glassmorphism, oversized-type-over-portrait, scroll effects, stat counters, card
  walls, hover image reveals.
- **Generate in Higgsfield — code can't cheaply fake these:** cinematic 3D object reveals, hero "signature
  object" footage, rich environment backdrops, character/creature hero shots, atmospheric loops.

---

## Motion-by-motion breakdown of your references

| Ref | What it is | What you get from it | Video or Code? |
|---|---|---|---|
| **1.mp4** | SHRGA — dark premium controller landing; product in a bordered frame, topographic wave lines on the sides, oversized specs, parts slide/expand on scroll | The whole dark-premium theme + signature-object reveal | Object reveal = **video**; frame/specs/waves = code |
| **2.mp4** | VEXO — light athletic; huge outline words slide across ("PEAK PERFORMANCE", "FRESH→NEXT", "FITS FOR YOU") | Kinetic scroll typography | **Code** (GSAP) |
| **3.mp4** | VR Boxxx — neon magenta/dark; 3D alpaca in VR goggles, "Explore without limits", phone mockup, split-image hover reveal | Neon-on-dark hero + character energy | Character/hero = **video**; hover reveal = code |
| **3.png** | proskills — giant "PORTFOLIO" cream type overlapping a face | Oversized-type-over-portrait vibe | **Code** + one portrait |
| **4.mp4** | Noomo Labs — light; huge distorting type DESIGN→DELIGHT→INSPIRE→ENGAGE, floating 3D jellyfish | Warping kinetic type + floating hero creature | Jellyfish = **video**; warping type = code |
| **4.jpg** | Sukhart — "HELLO I'M SUKHART" huge type + face built from words | Word-portrait / generative type | **Code** (generative) |
| **5.mp4** | Polysor — light fintech; text-format transitions on the 2nd page, phone mockups, FAQ | Second-page text choreography | **Code** |
| **5.jpg** | Ivann — dark green designer portfolio; 3D character, name behind, service cards | Character-behind-name layout | Character = image/3D; layout = code |
| **6.mp4** | SpaceX — dark space; rocket/satellite drifting, big stat counters (5/11/6 · 214/172/149), STARLINK | Space footage + big-number reveals | Space footage = **video**; counters = code |
| **6.png** | Dominic — dark portfolio; giant "Dominic" white type bleeding off bottom, portrait, orange accent, "Available for Work" pill | Oversized-name hero | **Code** + portrait |
| **6.jpg** | Adam — dark blue/cyan UI/UX portfolio; cyan glow, dashboard-style skill/portfolio panels | Cyan-glow dark dashboard look (close to AIPCC) | **Code** + glow |
| **7.mp4** | Audi RS e-tron GT — rings glow in → taillight bar lights up → car emerges from black → enters product page "01" | The "site opens up" intro you want | Car reveal = **video**; page-enter = code |
| **7.jpg** | Harun — dark minimal; "HARUN" bold, 3-image row, contact form | Minimal dark layout | **Code** |
| **8.mp4** | Tesla Cybertruck — vehicle floating in an asteroid/space field, cards float in, "UNBREAKABLE" split text, stats 0-60/500/+10K (vertical) | The "insane vibe": cinematic vehicle-in-environment + kinetic text | Environment + vehicle = **video**; text/UI = code |
| **8.jpg** | UIDesignz Supercell — heavy black type on yellow, game cards | Heavy display type (off-palette) | **Code** |
| **9.mp4** | turbotweak/Porsche — car front emerges from a black spotlight, crest, giant "SP" watermark, resolves to "Elevate Your Drive…" | Second "opens up" reveal: object from a spotlight | Object-from-dark = **video**; watermark/enter = code |
| **8.jpg,7.jpg,6.jpg,5.jpg** | Portfolio layouts (Harun / Adam / Ivann) | Layout + type references | **Code** |
| **1.jpg / 10.mp4** | Steary — visionOS-style glass streaming UI | Glassmorphism | **Code** (CSS glass) |
| **2.jpg** | Lunetra — dark-blue glass "Wallet Tech" fintech, glass cards, blue glow | Glass + blue glow on dark | **Code** + glass |
| **15.mp4** | OTON — AI product-image gen; dark rocky asteroid environment, morphing "OTN" logo, card-wall gallery "Your Next Big Idea Starts Here" | Rich rocky-dark environment backdrop + card wall | Environment = **video**; card wall/logo = code |
| **11/12.mp4** | Buttermax — yellow/black brutalist kinetic type, "REACH OUT" | Bold brutalist type (off-palette) | **Code** |
| **13.mp4** | Nulo — dark-red "Feed me with love" pet food | Dark editorial hero | **Code** |
| **14.mp4** | Diego — dark, pink accent, "Hi there I am Diego." bold, projects | Bold intro + project cards | **Code** |

---

## Higgsfield prompts — revised to match your taste + tailored to AIPCC

Global specs: **16:9** for desktop (regenerate favorites at **9:16** for mobile) · **seamless loop** where noted ·
**dark, no readable text, no legible UI** · slow, cinematic motion · **generate 2–3 takes each** (you can't come back).
Each block notes its recommended **length** and which reference it channels.

**Length cheat-sheet:** intros 5s (must end on a bright frame) · hero + object + backgrounds 5s, or the max your
model allows for a smoother loop · feature loops 3–4s · loading 2–3s. Shorter = easier to loop cleanly; go longer
only for slow drifting backgrounds. If your model only offers 4s/8s, round to the nearest.

### A. The "enter the site" intro reveal  ·  **Length: 5s** (end on a bright frame)  ← your #1 want (7.mp4 Audi, 9.mp4 turbotweak)
This plays after the user clicks ENTER, then your code transitions into the app.
- "In pure black, thin cyan light traces draw the outline of a glowing hexagonal security shield, the lines
  ignite and the shield forms and pulses once, then light rushes toward camera, cinematic, volumetric glow,
  no text, 16:9"
- "A dark void; a sleek abstract AI core — concentric glowing rings and a bright center — powers on from
  darkness, cyan energy racing along the rings, slow dramatic reveal, camera slowly pushing in, premium,
  no text, 16:9"
- "Camera flies slowly through a dark digital tunnel of thin glowing cyan grid lines toward a bright core,
  accelerating into light at the end (for a cut-to-site transition), cinematic, no text, 16:9"

### B. Hero background loop (behind the landing headline)  ·  **Length: 5s** (or model max, seamless loop)  ← SHRGA 1.mp4, Adam 6.jpg
- "Dark cybersecurity command-center atmosphere, slow-drifting streams of cyan and blue data particles in
  deep black space, subtle depth of field, faint topographic contour lines at the edges, seamless loop, no
  text, 16:9"
- "A glowing network mesh of interconnected nodes slowly pulsing, deep navy and cyan on near-black, particles
  drifting between nodes, minimal and premium, seamless loop, no text, 16:9"

### C. Signature-object reveal (a hero centerpiece)  ·  **Length: 5s** (seamless loop)  ← SHRGA 1.mp4, Audi 7.mp4, turbotweak 9.mp4
Your "product emerges from black" love — but the product is an abstract security object, not a car.
- "A dark studio void with a single spotlight; an abstract obsidian-and-glass shield object slowly rotates,
  cyan light refracting through its edges, cinematic product shot, shallow depth of field, seamless loop, no
  text, 16:9"
- "A floating faceted crystal 'data core' rotating slowly above a dark reflective floor, thin cyan internal
  light, particles drifting up, premium reveal, seamless loop, no text, 16:9"

### D. Environment backdrops (the 'insane vibe')  ·  **Length: 5–8s** (longer = slower, smoother drift)  ← SpaceX 6.mp4, Tesla 8.mp4, OTON 15.mp4
Great as full-bleed section backgrounds behind cards/stats.
- "Slow flythrough of a vast dark digital canyon made of glowing cyan wireframe rock formations, drifting
  data particles, cinematic and atmospheric, deep blacks, no text, 16:9"
- "A dark asteroid-like field of slowly floating obsidian fragments in deep space, faint cyan rim light,
  subtle parallax drift, cinematic, seamless loop, no text — also generate a 9:16 version"
- "Abstract dark rocky terrain under a faint cyan glow with slow atmospheric fog rolling through, moody and
  premium, seamless loop, no text, 16:9"

### E. Feature micro-loops (one idea each, behind feature cards)  ·  **Length: 3–4s** (seamless loop)  ← AIPCC features
- *RAG report generation:* "Abstract document pages dissolving into flowing cyan light particles that
  reassemble into a glowing structured panel, dark background, elegant, slow motion, seamless loop, no
  readable text, 16:9"
- *Threat intel / global reputation (SpaceX-globe energy):* "A dark globe made of faint glowing dots, pulses
  of light tracing arcs between points like tracking threats across a network, cyan with occasional amber
  flares, cinematic, seamless loop, no text, 16:9"
- *Anomaly detection:* "A calm field of blue moving particles where a few turn amber-red and pulse, isolated
  and highlighted, dark background, tense but clean, slow motion, seamless loop, no text, 16:9"
- *File integrity / FIM:* "A glowing digital lock assembling from geometric fragments, then a soft green seal
  pulse, dark background, premium, slow motion, seamless loop, no text, 16:9"
- *Chat / talk-to-data:* "A soft cyan waveform of light gently morphing into flowing particle streams on
  black, friendly and calm, seamless loop, no text, 16:9"

### F. Ambient login background (subtle, behind the form)  ·  **Length: 5s** (or model max, seamless loop)  ← Lunetra 2.jpg glass vibe
- "Very slow drifting dark gradient with faint hexagonal shield patterns fading in and out, deep blue-black,
  minimal, calm, seamless loop, no text, 16:9"

### G. Loading / empty-state micro-loops  ·  **Length: 2–3s** (tight seamless loop)
- "Minimal glowing cyan circular scanner sweep on black, a single arc rotating slowly, seamless loop, no
  text, 1:1"

---

## Time-boxed plan (you're doing A–D, maybe some E/F/G)
All of A–D is ~10 clips. If time is tight, do the **top prompt in each section** first — that's your whole
hero in 4 clips:
1. **A, prompt 1** — shield reveal (intro). 5s. Grab 3–4 takes; this one matters most.
2. **C, prompt 1** — obsidian/glass object rotate. 5s.
3. **D, prompt 1** — dark digital canyon flythrough. 5–8s. Reusable everywhere.
4. **B, prompt 1** — hero particle loop. 5s.

Then, if time remains: the 2nd prompt of A, then one from **E** (threat-intel globe is the best single pick),
then **F**. Skip **G** — a loading spinner is trivial to build in code.

Total-time guide: at ~5s each, even 10 clips is only ~50s of footage but many generation rounds — so favor
fewer prompts × more takes over many prompts × one take.

## Then build in code (any day, no Higgsfield needed)
Kinetic type (GSAP SplitText / Framer Motion), the click-ENTER page transition, glassmorphism panels,
oversized-type-over-portrait heroes, stat counters, card walls, scroll reveals. These are Phase 3 frontend
work — see AIPCC_CLAUDE_CODE_PROMPTS.md.
