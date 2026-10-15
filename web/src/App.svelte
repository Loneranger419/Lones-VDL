<script lang="ts">
  import {
    clearToken,
    getToken,
    getVideo,
    listVideos,
    mediaUrl,
    setToken,
    thumbnailUrl,
    type VideoDetail,
    type VideoSummary,
  } from "./lib/api";

  let tokenInput = $state(getToken());
  let authed = $state(Boolean(getToken()));
  let query = $state("");
  let videos = $state<VideoSummary[]>([]);
  let selected = $state<VideoDetail | null>(null);
  let error = $state("");
  let loading = $state(false);

  async function saveToken() {
    setToken(tokenInput.trim());
    authed = Boolean(getToken());
    error = "";
    selected = null;
    await refresh();
  }

  function logout() {
    clearToken();
    tokenInput = "";
    authed = false;
    videos = [];
    selected = null;
  }

  async function refresh() {
    if (!authed) return;
    loading = true;
    error = "";
    try {
      videos = await listVideos(query.trim() || undefined);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      videos = [];
    } finally {
      loading = false;
    }
  }

  async function openVideo(v: VideoSummary) {
    loading = true;
    error = "";
    try {
      selected = await getVideo(v.platform, v.platform_video_id);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      selected = null;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (authed) {
      void refresh();
    }
  });
</script>

{#if !authed}
  <main class="gate">
    <h1>Lones-VDL</h1>
    <p>Enter the API bearer token from your <code>.env</code> (<code>LONES_VDL_API_TOKEN</code>).</p>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        void saveToken();
      }}
    >
      <input type="password" bind:value={tokenInput} placeholder="API token" autocomplete="off" />
      <button type="submit">Open library</button>
    </form>
    {#if error}<p class="error">{error}</p>{/if}
  </main>
{:else}
  <div class="layout">
    <header>
      <div>
        <h1>Lones-VDL</h1>
        <p class="sub">Archive library</p>
      </div>
      <button type="button" class="ghost" onclick={logout}>Clear token</button>
    </header>

    <section class="toolbar">
      <input
        type="search"
        placeholder="Search title, id, url…"
        bind:value={query}
        onkeydown={(e) => {
          if (e.key === "Enter") void refresh();
        }}
      />
      <button type="button" onclick={() => void refresh()}>Search</button>
    </section>

    {#if error}<p class="error">{error}</p>{/if}
    {#if loading && !selected}<p class="muted">Loading…</p>{/if}

    <div class="split">
      <aside>
        {#if videos.length === 0 && !loading}
          <p class="muted">No archived videos yet.</p>
        {:else}
          <ul class="list">
            {#each videos as v (v.id)}
              <li>
                <button
                  type="button"
                  class:active={selected?.platform_video_id === v.platform_video_id}
                  onclick={() => void openVideo(v)}
                >
                  {#if v.has_thumbnail}
                    <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                  {/if}
                  <span>
                    <strong>{v.title ?? v.platform_video_id}</strong>
                    <small>{v.platform} · {v.platform_video_id}</small>
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </aside>

      <section class="detail">
        {#if !selected}
          <p class="muted">Select a video to view details and play.</p>
        {:else}
          <h2>{selected.title ?? selected.platform_video_id}</h2>
          <p class="meta">
            {selected.platform} / {selected.platform_video_id} · archived {selected.archived_at}
          </p>

          {#if selected.playback?.mode === "unavailable"}
            <p class="warn">
              Not browser-playable without re-encoding: {selected.playback.reason}
            </p>
            <p class="muted">Original file remains at <code>{selected.media_relpath}</code></p>
          {:else if selected.playback}
            <video
              controls
              playsinline
              src={mediaUrl(selected.platform, selected.platform_video_id, "play")}
            >
              <track kind="captions" />
            </video>
            <p class="muted">
              Playback: {selected.playback.mode}
              {#if selected.playback.container}
                ({selected.playback.container})
              {/if}
              — {selected.playback.reason}
            </p>
          {/if}

          {#if selected.source_metadata}
            <h3>Source metadata</h3>
            <dl class="grid">
              {#each Object.entries(selected.source_metadata).filter(([k]) => ["channel", "duration", "width", "height", "fps", "format", "vcodec", "acodec", "upload_date", "view_count"].includes(k)) as [key, value]}
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              {/each}
            </dl>
          {/if}

          <p>
            <a href={selected.url} target="_blank" rel="noreferrer">Original URL</a>
          </p>
        {/if}
      </section>
    </div>
  </div>
{/if}

<style>
  :global(body) {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: #0f1419;
    color: #e7ecf1;
  }
  :global(*) {
    box-sizing: border-box;
  }
  .gate {
    max-width: 28rem;
    margin: 4rem auto;
    padding: 0 1.25rem;
  }
  .gate form {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
  }
  .layout {
    max-width: 72rem;
    margin: 0 auto;
    padding: 1.25rem;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }
  h1 {
    margin: 0;
    font-weight: 650;
    letter-spacing: -0.02em;
  }
  .sub {
    margin: 0.25rem 0 0;
    color: #9aa7b5;
  }
  .toolbar {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }
  input {
    flex: 1;
    padding: 0.55rem 0.7rem;
    border: 1px solid #2a3542;
    border-radius: 6px;
    background: #151c24;
    color: inherit;
  }
  button {
    padding: 0.55rem 0.9rem;
    border: 0;
    border-radius: 6px;
    background: #3d8bfd;
    color: #041018;
    font-weight: 600;
    cursor: pointer;
  }
  button.ghost {
    background: transparent;
    color: #9aa7b5;
    border: 1px solid #2a3542;
  }
  .split {
    display: grid;
    grid-template-columns: minmax(16rem, 22rem) 1fr;
    gap: 1rem;
  }
  @media (max-width: 800px) {
    .split {
      grid-template-columns: 1fr;
    }
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .list button {
    width: 100%;
    display: flex;
    gap: 0.75rem;
    text-align: left;
    background: #151c24;
    color: inherit;
    border: 1px solid #2a3542;
    font-weight: 500;
  }
  .list button.active {
    border-color: #3d8bfd;
  }
  .list img {
    width: 5.5rem;
    height: 3.1rem;
    object-fit: cover;
    border-radius: 4px;
    background: #0a0e12;
  }
  .list strong {
    display: block;
  }
  .list small {
    color: #9aa7b5;
  }
  .detail video {
    width: 100%;
    max-height: 70vh;
    background: #000;
    border-radius: 8px;
  }
  .meta,
  .muted {
    color: #9aa7b5;
  }
  .error {
    color: #ff8f8f;
  }
  .warn {
    color: #ffcc66;
  }
  .grid {
    display: grid;
    grid-template-columns: 8rem 1fr;
    gap: 0.35rem 0.75rem;
  }
  .grid dt {
    color: #9aa7b5;
  }
  .grid dd {
    margin: 0;
  }
  a {
    color: #7eb6ff;
  }
  code {
    font-size: 0.9em;
  }
</style>
