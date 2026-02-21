# TASK: Animated 0Lith Eye Logo Component

## Context
Read CLAUDE.md first. 0Lith is a Tauri 2 + Svelte 5 (runes) app with 5 AI agents.
The logo is a rounded rectangle with an eye/pupil inside (see Logo_texture.png for reference).
We need this logo as a **programmable SVG component** that animates to simulate life.

## What to Build

### 1. `OLithEye.svelte` — Main Animated Logo Component

**Location**: `src/lib/components/OLithEye.svelte`

**SVG Structure** (reproduce the logo shape):
```
┌─────────────────┐  ← Outer rounded rectangle (stroke, no fill)
│  ┌─────────────┐│  ← Inner rounded rectangle (stroke, no fill)
│  │             ││
│  │     (◉)     ││  ← Eye: vertical ellipse (pupil)
│  │             ││
│  └─────────────┘│
└─────────────────┘
```

- Outer rect: rounded corners (~20% radius), thick white stroke, transparent fill
- Inner rect: rounded corners (~15% radius), thick white stroke, transparent fill
- Pupil: vertical ellipse centered, filled with agent color

**Props** (Svelte 5 $props):
```typescript
interface OLithEyeProps {
  size?: number;           // px, default 40
  agentColor?: string;     // hex color, default '#FFFFFF'
  agentId?: string;        // current active agent id
  animated?: boolean;      // enable animations, default true
  state?: 'idle' | 'thinking' | 'responding' | 'sleeping' | 'gaming';
}
```

### 2. Animations (CSS + Svelte transitions, NO external libs)

**IDLE state** — Subtle life simulation:
- Blink every 3-6 seconds (random interval, natural feel)
- Blink = pupil scaleY goes from 1 → 0.1 → 1 over ~150ms
- Occasional double-blink (10% chance)
- Pupil drifts slowly in small random directions (±2px), returns to center
- Breathing effect: inner rect very subtly scales (0.98 → 1.02) over 4s

**THINKING state** — Agent is processing:
- Pupil shrinks slightly (thinking hard)
- Pupil moves left-right rhythmically (like reading/scanning)
- Blink frequency decreases (focused)
- Subtle pulsing glow around inner rect in agent color

**RESPONDING state** — Agent is streaming tokens:
- Pupil dilates (bigger ellipse)
- Pupil tracks downward slowly (as if watching text appear)
- Normal blink rate resumes
- Inner rect has a soft glow in agent color

**SLEEPING state** — Gaming mode / inactive:
- Pupil is a thin horizontal line (eyes closed, scaleY: 0.1)
- Very slow breathing on inner rect
- No movement
- Occasional micro-twitch (dreaming)

**GAMING state** — Gaming mode active:
- Same as sleeping but with a tiny game controller icon or just the color goes to a dim gray
- Minimal animation to save resources

### 3. Agent Color Transitions

When the active agent changes, the pupil and glow color smoothly transition (300ms ease):
- Hodolith: #FFB02E (gold)
- Monolith: #181A1E (black)
- Aerolith: #43AA8B (teal green)
- Cryolith: #7BDFF2 (blue)
- Pyrolith: #BF0603 (red)
- No agent / system: #FFFFFF (white)
- Gaming mode: #6B7280 (gray, dimmed)

The stroke color of the rectangles stays white/light gray. Only the pupil fill and glow change.

### 4. Where It's Used

**A. Sidebar header** — Replace the current "0Lith v0.1" text logo:
- `<OLithEye size={32} agentColor={activeAgent.color} state={currentState} />`
- Next to the "0Lith" text
- Reflects the currently responding agent

**B. Chat welcome screen** — The big centered logo:
- `<OLithEye size={120} animated={true} state="idle" />`
- Idle animations visible, creates a living feel
- When user starts typing, pupil looks toward the input bar (track mouse/focus)

**C. Message bubbles** — Small icon per agent message:
- `<OLithEye size={24} agentColor={agent.color} animated={false} />`
- Static, no animation (too many instances would be heavy)
- Just shows the correct agent color

**D. System tray** — Future Phase 3:
- NOT this SVG component (system tray needs .ico/.png)
- But we'll generate static PNGs from this SVG for each agent color later

### 5. Implementation Notes

**Svelte 5 runes only**:
```svelte
<script lang="ts">
  let { size = 40, agentColor = '#FFFFFF', animated = true, state = 'idle' }: OLithEyeProps = $props();
  
  let pupilY = $state(0);
  let pupilX = $state(0);
  let blinkScale = $state(1);
  let isBlinking = $state(false);
  
  // Animation logic with $effect
  $effect(() => {
    if (!animated) return;
    // Setup intervals for blink, drift, etc.
    // Return cleanup function
  });
</script>
```

**Animation approach**:
- Use `$effect` for setting up/cleaning intervals
- CSS transitions for smooth property changes (transform, opacity)
- `requestAnimationFrame` for pupil drift (smooth, performant)
- CSS `@keyframes` for breathing effect
- NO external animation libraries (keep bundle small)
- All animations use `transform` and `opacity` (GPU-accelerated, no layout thrash)

**Performance**:
- The animated=false variant must be pure SVG with zero JS overhead
- Only ONE animated instance should run complex animations at a time (the sidebar or welcome screen, not both simultaneously)
- Use `will-change: transform` on animated elements
- Pause animations when window is not focused (`document.visibilitychange`)

### 6. SVG Template Reference

The logo proportions from the PNG:
```svg
<!-- Approximate proportions, adjust to look right -->
<svg viewBox="0 0 100 100" width={size} height={size}>
  <!-- Outer rounded rect -->
  <rect x="8" y="5" width="84" height="90" rx="18" ry="18" 
        fill="none" stroke="white" stroke-width="6"/>
  
  <!-- Inner rounded rect -->
  <rect x="20" y="17" width="60" height="66" rx="12" ry="12" 
        fill="none" stroke="white" stroke-width="5"/>
  
  <!-- Pupil (vertical ellipse) -->
  <ellipse cx="50" cy="50" rx="8" ry="16" 
           fill={agentColor}
           transform="translate({pupilX}, {pupilY}) scale(1, {blinkScale})"
           style="transition: fill 300ms ease" />
</svg>
```

### 7. Files to Create/Modify

**Create:**
- `src/lib/components/OLithEye.svelte` — The main component

**Modify:**
- `src/lib/components/Sidebar.svelte` — Replace text logo with `<OLithEye>` + "0Lith" text
- `src/App.svelte` or chat welcome screen — Use large animated `<OLithEye>` as centerpiece

### 8. Acceptance Criteria

- [x] SVG renders correctly at sizes 24, 32, 40, 80, 120
- [x] Agent color changes smoothly when switching agents
- [x] Idle: natural blinking (random 3-6s interval, 150ms blink duration)
- [x] Idle: subtle pupil drift
- [x] Thinking: scanning left-right motion + color glow
- [x] Responding: dilated pupil + downward tracking
- [x] Sleeping: closed eye (flat line)
- [x] animated=false renders static SVG with correct color, zero JS
- [x] No animation jank or layout shifts
- [x] Animations pause when tab/window is hidden
- [x] Works with warm dark gray theme (#282C33 background)