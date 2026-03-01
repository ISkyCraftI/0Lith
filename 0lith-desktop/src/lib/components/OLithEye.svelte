<script lang="ts">
    type EyeState = "idle" | "thinking" | "responding" | "sleeping" | "gaming";

    interface OLithEyeProps {
        size?: number;
        agentColor?: string;
        agentId?: string;
        animated?: boolean;
        eyeState?: EyeState;
        clickable?: boolean;
        trackMouse?: boolean;
    }

    let {
        size = 40,
        agentColor = "#FFFFFF",
        animated = true,
        eyeState = "idle",
        clickable = false,
        trackMouse = false,
    }: OLithEyeProps = $props();

    // --- Pupil animation state ---
    let pupilX = $state(0);
    let pupilY = $state(0);
    let blinkScale = $state(1);
    let pupilScale = $state(1);
    let glowOpacity = $state(0);
    let twitchX = $state(0);
    let shaking = $state(false);

    // --- Click interaction ---
    function handleClick() {
        if (!clickable || shaking) return;
        shaking = true;
        blinkScale = 0.1;
        setTimeout(() => {
            blinkScale = 1;
            shaking = false;
        }, 600);
    }

    // --- Animation references ---
    let blinkTimer: ReturnType<typeof setTimeout> | null = null;
    let driftRAF: number | null = null;
    let scanTimer: ReturnType<typeof setInterval> | null = null;
    let respondTimer: ReturnType<typeof setInterval> | null = null;
    let sleepTwitchTimer: ReturnType<typeof setTimeout> | null = null;
    let isVisible = $state(true);
    let svgEl: SVGSVGElement;

    // --- Helpers ---
    function rand(min: number, max: number): number {
        return Math.random() * (max - min) + min;
    }

    function scheduleBlink() {
        if (!animated || !isVisible) return;
        const delay = rand(3000, 6000);
        blinkTimer = setTimeout(() => {
            doBlink();
            if (Math.random() < 0.1) {
                setTimeout(() => doBlink(), 250);
            }
            scheduleBlink();
        }, delay);
    }

    function doBlink() {
        blinkScale = 0.1;
        setTimeout(() => {
            blinkScale = 1;
        }, 150);
    }

    // Idle drift: small random pupil movement (only when NOT tracking mouse)
    function startDrift() {
        if (!animated || !isVisible || trackMouse) return;
        let targetX = 0;
        let targetY = 0;
        let currentX = 0;
        let currentY = 0;
        let nextMoveTime = performance.now() + rand(1500, 3500);

        function step(now: number) {
            if (eyeState !== "idle") return;
            if (now >= nextMoveTime) {
                targetX = rand(-5, 5);
                targetY = rand(-4, 4);
                nextMoveTime = now + rand(1500, 3500);
            }
            currentX += (targetX - currentX) * 0.04;
            currentY += (targetY - currentY) * 0.04;
            pupilX = currentX;
            pupilY = currentY;
            driftRAF = requestAnimationFrame(step);
        }
        driftRAF = requestAnimationFrame(step);
    }

    // Mouse tracking
    function startMouseTracking() {
        if (!trackMouse || !animated) return;
        function onMouseMove(e: MouseEvent) {
            if (!svgEl) return;
            const rect = svgEl.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const dx = e.clientX - centerX;
            const dy = e.clientY - centerY;
            const maxDist = 300;
            const clampedX = Math.max(-1, Math.min(1, dx / maxDist));
            const clampedY = Math.max(-1, Math.min(1, dy / maxDist));
            pupilX = clampedX * 10;
            pupilY = clampedY * 8;
        }
        document.addEventListener("mousemove", onMouseMove);
        return () => document.removeEventListener("mousemove", onMouseMove);
    }

    // Thinking: left-right scanning
    function startScan() {
        let phase = 0;
        scanTimer = setInterval(() => {
            phase += 0.08;
            pupilX = Math.sin(phase) * 8;
            pupilY = 0;
        }, 30);
    }

    // Responding: slow downward tracking + dilated pupil
    function startRespond() {
        let phase = 0;
        respondTimer = setInterval(() => {
            phase += 0.015;
            pupilY = Math.sin(phase) * 6;
            pupilX = 0;
        }, 30);
    }

    // Sleeping micro-twitch
    function scheduleTwitch() {
        if (!animated || !isVisible) return;
        sleepTwitchTimer = setTimeout(
            () => {
                twitchX = rand(-1, 1);
                setTimeout(() => {
                    twitchX = 0;
                }, 100);
                scheduleTwitch();
            },
            rand(4000, 10000),
        );
    }

    let mouseCleanup: (() => void) | null = null;

    function cleanupAll() {
        if (blinkTimer) {
            clearTimeout(blinkTimer);
            blinkTimer = null;
        }
        if (driftRAF) {
            cancelAnimationFrame(driftRAF);
            driftRAF = null;
        }
        if (scanTimer) {
            clearInterval(scanTimer);
            scanTimer = null;
        }
        if (respondTimer) {
            clearInterval(respondTimer);
            respondTimer = null;
        }
        if (sleepTwitchTimer) {
            clearTimeout(sleepTwitchTimer);
            sleepTwitchTimer = null;
        }
        if (mouseCleanup) {
            mouseCleanup();
            mouseCleanup = null;
        }

        pupilX = 0;
        pupilY = 0;
        blinkScale = 1;
        pupilScale = 1;
        glowOpacity = 0;
        twitchX = 0;
    }

    // --- Main animation effect ---
    $effect(() => {
        if (!animated) {
            cleanupAll();
            if (eyeState === "sleeping" || eyeState === "gaming") {
                blinkScale = 0.1;
            }
            return;
        }

        cleanupAll();

        if (eyeState === "idle") {
            blinkScale = 1;
            pupilScale = 1;
            glowOpacity = 0;
            scheduleBlink();
            if (trackMouse) {
                mouseCleanup = startMouseTracking() ?? null;
            } else {
                startDrift();
            }
        } else if (eyeState === "thinking") {
            blinkScale = 1;
            pupilScale = 0.75;
            glowOpacity = 0.6;
            startScan();
            blinkTimer = setTimeout(
                function thinkBlink() {
                    doBlink();
                    blinkTimer = setTimeout(thinkBlink, rand(5000, 8000));
                },
                rand(5000, 8000),
            );
        } else if (eyeState === "responding") {
            blinkScale = 1;
            pupilScale = 1.25;
            glowOpacity = 0.4;
            startRespond();
            scheduleBlink();
        } else if (eyeState === "sleeping") {
            blinkScale = 0.1;
            pupilScale = 1;
            glowOpacity = 0;
            scheduleTwitch();
        } else if (eyeState === "gaming") {
            blinkScale = 0.1;
            pupilScale = 1;
            glowOpacity = 0;
        }

        return () => cleanupAll();
    });

    // --- Pause on tab hidden ---
    $effect(() => {
        if (!animated) return;
        function onVisibility() {
            isVisible = document.visibilityState === "visible";
        }
        document.addEventListener("visibilitychange", onVisibility);
        return () =>
            document.removeEventListener("visibilitychange", onVisibility);
    });

    // --- Computed ---
    let fillColor = $derived(eyeState === "gaming" ? "#6B7280" : agentColor);

    let pupilTransform = $derived(
        `translate(${pupilX + twitchX}, ${pupilY}) scale(${pupilScale}, ${blinkScale * pupilScale})`,
    );
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<svg
    bind:this={svgEl}
    viewBox="0 0 80 100"
    width={size}
    height={size}
    class="olith-eye"
    class:animated
    class:shaking
    class:clickable
    onclick={handleClick}
    onkeydown={(e) => {
        if (e.key === "Enter" || e.key === " ") handleClick();
    }}
    role={clickable ? "button" : "img"}
    aria-label="0Lith Eye"
    tabindex={clickable ? 0 : undefined}
    xmlns="http://www.w3.org/2000/svg"
>
    <!-- Glow filter -->
    {#if animated && glowOpacity > 0}
        <defs>
            <filter
                id="glow-{size}"
                x="-50%"
                y="-50%"
                width="200%"
                height="200%"
            >
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                </feMerge>
            </filter>
        </defs>
    {/if}

    <!-- Outer rounded rectangle -->
    <rect
        x="5"
        y="3"
        width="70"
        height="94"
        rx="18"
        ry="18"
        fill="none"
        stroke={fillColor}
        stroke-width="5"
        opacity="0.9"
        style="transition: stroke 300ms ease;"
    />

    <!-- Glow outline (thinking/responding only) -->
    {#if animated && glowOpacity > 0}
        <rect
            x="5"
            y="3"
            width="70"
            height="94"
            rx="18"
            ry="18"
            fill="none"
            stroke={fillColor}
            stroke-width="2"
            opacity={glowOpacity}
            filter="url(#glow-{size})"
        />
    {/if}

    <!-- Pupil (vertical ellipse) -->
    <ellipse
        cx="40"
        cy="50"
        rx="8"
        ry="16"
        fill={fillColor}
        transform={pupilTransform}
        transform-origin="40 50"
        style="transition: fill 300ms ease; will-change: transform;"
    />
</svg>

<style>
    .olith-eye {
        display: block;
        flex-shrink: 0;
    }
    .olith-eye.clickable {
        cursor: pointer;
    }
    .olith-eye.shaking {
        animation: shake 0.6s ease;
    }
    @keyframes shake {
        0% {
            transform: translateX(0);
        }
        15% {
            transform: translateX(-4px) rotate(-3deg);
        }
        30% {
            transform: translateX(4px) rotate(3deg);
        }
        45% {
            transform: translateX(-3px) rotate(-2deg);
        }
        60% {
            transform: translateX(3px) rotate(2deg);
        }
        75% {
            transform: translateX(-1px) rotate(-1deg);
        }
        100% {
            transform: translateX(0) rotate(0);
        }
    }
</style>
