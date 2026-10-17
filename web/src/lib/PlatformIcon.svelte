<script lang="ts">
  type Props = {
    platform: string;
    /** `inline` for channel rows; `overlay` for video thumbnails */
    variant?: "inline" | "overlay";
  };

  let { platform, variant = "inline" }: Props = $props();

  const label = $derived(
    platform === "youtube" ? "YouTube" : platform === "twitch" ? "Twitch" : platform,
  );
</script>

{#if platform === "youtube"}
  <svg class="platform-icon {variant}" viewBox="0 0 24 24" role="img" aria-label={label}>
    <title>{label}</title>
    <path
      fill="#FF0033"
      d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.4.6A3 3 0 0 0 .5 6.2 31.6 31.6 0 0 0 0 12a31.6 31.6 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.6 9.4.6 9.4.6s7.5 0 9.4-.6a3 3 0 0 0 2.1-2.1A31.6 31.6 0 0 0 24 12a31.6 31.6 0 0 0-.5-5.8z"
    />
    <path fill="#fff" d="M9.75 15.5v-7l6 3.5-6 3.5z" />
  </svg>
{:else if platform === "twitch"}
  <svg class="platform-icon {variant}" viewBox="0 0 24 24" role="img" aria-label={label}>
    <title>{label}</title>
    <path
      fill="#9146FF"
      d="M4.25 1 1.5 3.75v16H6.5V23l2.75-2.75h4.25L20.5 14V1H4.25zm14.5 12-3.25 3.25H11.5l-2.25 2.25V16.25H5.75V2.75h13v10.25z"
    />
    <path fill="#fff" d="M14.75 5.5h1.75v5.25H14.75zm-4.5 0H12v5.25H10.25z" />
  </svg>
{:else}
  <span class="platform-icon fallback {variant}" title={label}>{platform.slice(0, 2)}</span>
{/if}

<style>
  .platform-icon {
    display: block;
    flex-shrink: 0;
  }
  .platform-icon.inline {
    width: 1.05rem;
    height: 1.05rem;
    opacity: 0.9;
  }
  .platform-icon.overlay {
    position: absolute;
    top: 0.4rem;
    left: 0.4rem;
    width: 1.81rem;
    height: 1.81rem;
    opacity: 0.7;
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.75));
    pointer-events: none;
    z-index: 1;
  }
  .platform-icon.fallback {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #c5d0db;
    background: #1a222c;
    border: 1px solid #2a3542;
    border-radius: 3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .platform-icon.fallback.inline {
    width: 1.05rem;
    height: 1.05rem;
  }
  .platform-icon.fallback.overlay {
    width: 1.81rem;
    height: 1.81rem;
    opacity: 0.7;
  }
</style>
