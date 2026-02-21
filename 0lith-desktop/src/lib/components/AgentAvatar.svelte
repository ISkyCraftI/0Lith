<script lang="ts">
  interface Props {
    color: string;
    emoji: string;
    size?: number;
  }

  let { color, emoji, size = 32 }: Props = $props();
</script>

<div
  class="agent-avatar"
  style="width: {size}px; height: {size}px; background: {color}20; border: 2px solid {color}; font-size: {size * 0.45}px;"
>
  {emoji}
</div>

<style>
  .agent-avatar {
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
</style>
