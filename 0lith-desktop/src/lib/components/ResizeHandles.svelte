<script lang="ts">
    import { getCurrentWindow } from "@tauri-apps/api/window";

    const win = getCurrentWindow();

    // ResizeDirection is not re-exported by @tauri-apps/api/window, so define locally.
    const Dir = {
        North: "North", South: "South", East: "East", West: "West",
        NorthEast: "NorthEast", NorthWest: "NorthWest",
        SouthEast: "SouthEast", SouthWest: "SouthWest",
    } as const;
    type Dir = typeof Dir[keyof typeof Dir];

    function resize(dir: Dir) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (win as any).startResizeDragging(dir);
    }
</script>

<!-- Edge handles -->
<div class="rh rh-n"  role="none" onmousedown={() => resize(Dir.North)}></div>
<div class="rh rh-s"  role="none" onmousedown={() => resize(Dir.South)}></div>
<div class="rh rh-e"  role="none" onmousedown={() => resize(Dir.East)}></div>
<div class="rh rh-w"  role="none" onmousedown={() => resize(Dir.West)}></div>
<!-- Corner handles -->
<div class="rh rh-ne" role="none" onmousedown={() => resize(Dir.NorthEast)}></div>
<div class="rh rh-nw" role="none" onmousedown={() => resize(Dir.NorthWest)}></div>
<div class="rh rh-se" role="none" onmousedown={() => resize(Dir.SouthEast)}></div>
<div class="rh rh-sw" role="none" onmousedown={() => resize(Dir.SouthWest)}></div>

<style>
    .rh {
        position: fixed;
        z-index: 10000;
    }

    /* Edge handles — 5px thick, corners excluded */
    .rh-n  { top: 0;    left: 10px; right: 10px;  height: 5px; cursor: n-resize; }
    .rh-s  { bottom: 0; left: 10px; right: 10px;  height: 5px; cursor: s-resize; }
    .rh-e  { right: 0;  top: 10px;  bottom: 10px; width: 5px;  cursor: e-resize; }
    .rh-w  { left: 0;   top: 10px;  bottom: 10px; width: 5px;  cursor: w-resize; }

    /* Corner handles — 10×10px */
    .rh-ne { top: 0;    right: 0;  width: 10px; height: 10px; cursor: ne-resize; }
    .rh-nw { top: 0;    left: 0;   width: 10px; height: 10px; cursor: nw-resize; }
    .rh-se { bottom: 0; right: 0;  width: 10px; height: 10px; cursor: se-resize; }
    .rh-sw { bottom: 0; left: 0;   width: 10px; height: 10px; cursor: sw-resize; }
</style>
