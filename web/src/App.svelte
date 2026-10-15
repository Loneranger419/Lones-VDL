<script lang="ts">
  import {
    clearToken,
    enqueueJob,
    getConfig,
    getToken,
    getVideo,
    isActiveJob,
    listJobs,
    listVideos,
    mediaUrl,
    setToken,
    thumbnailUrl,
    type Job,
    type PublicConfig,
    type VideoDetail,
    type VideoSummary,
  } from "./lib/api";

  let tokenInput = $state(getToken());
  let authed = $state(Boolean(getToken()));
  let tab = $state<"library" | "jobs">("library");
  let query = $state("");
  let videos = $state<VideoSummary[]>([]);
  let selected = $state<VideoDetail | null>(null);
  let jobs = $state<Job[]>([]);
  let config = $state<PublicConfig | null>(null);
  let enqueueUrl = $state("");
  let quality = $state("best");
  let enqueueBusy = $state(false);
  let enqueueMsg = $state("");
  let error = $state("");
  let loading = $state(false);

  async function saveToken() {
    setToken(tokenInput.trim());
    authed = Boolean(getToken());
    error = "";
    selected = null;
    await bootstrap();
  }

  function logout() {
    clearToken();
    tokenInput = "";
    authed = false;
    videos = [];
    jobs = [];
    selected = null;
    config = null;
  }

  async function bootstrap() {
    if (!authed) return;
    loading = true;
    error = "";
    try {
      config = await getConfig();
      quality = config.default_quality || "best";
      await Promise.all([refreshVideos(), refreshJobs()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function refreshVideos() {
    videos = await listVideos(query.trim() || undefined);
  }

  async function refreshJobs() {
    jobs = await listJobs();
  }

  async function openVideo(v: VideoSummary) {
    tab = "library";
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

  async function submitEnqueue() {
    const url = enqueueUrl.trim();
    if (!url) return;
    enqueueBusy = true;
    enqueueMsg = "";
    error = "";
    try {
      const job = await enqueueJob(url, quality);
      enqueueMsg = `Queued ${job.id.slice(0, 8)}… (${job.status})`;
      enqueueUrl = "";
      tab = "jobs";
      await refreshJobs();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      enqueueBusy = false;
    }
  }

  $effect(() => {
    if (authed) {
      void bootstrap();
    }
  });

  $effect(() => {
    if (!authed) return;
    const hasActive = jobs.some((j) => isActiveJob(j.status));
    if (!hasActive) return;
    const id = setInterval(() => {
      void (async () => {
        try {
          const next = await listJobs();
          const wasActive = next.some((j) => isActiveJob(j.status));
          jobs = next;
          if (!wasActive) {
            await refreshVideos();
          }
        } catch (err) {
          error = err instanceof Error ? err.message : String(err);
        }
      })();
    }, 2000);
    return () => clearInterval(id);
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
        <p class="sub">
          {#if config}
            Archive: <code>{config.archive_root}</code>
            · concurrency {config.download_concurrency}
            · cookies {config.cookies_configured ? "yes" : "no"}
          {:else}
            Archive library
          {/if}
        </p>
      </div>
      <button type="button" class="ghost" onclick={logout}>Clear token</button>
    </header>

    <section class="enqueue">
      <h2>Add download</h2>
      <form
        class="enqueue-form"
        onsubmit={(e) => {
          e.preventDefault();
          void submitEnqueue();
        }}
      >
        <input
          type="url"
          placeholder="https://www.youtube.com/watch?v=…"
          bind:value={enqueueUrl}
          required
        />
        <select bind:value={quality} title="yt-dlp format preference">
          {#each config?.quality_presets ?? ["best"] as preset}
            <option value={preset}>{preset === "best" ? "best (default)" : preset}</option>
          {/each}
        </select>
        <button type="submit" disabled={enqueueBusy}>
          {enqueueBusy ? "Queueing…" : "Enqueue"}
        </button>
      </form>
      {#if enqueueMsg}<p class="ok">{enqueueMsg}</p>{/if}
    </section>

    <nav class="tabs">
      <button type="button" class:active={tab === "library"} onclick={() => (tab = "library")}
        >Library</button
      >
      <button type="button" class:active={tab === "jobs"} onclick={() => (tab = "jobs")}
        >Jobs ({jobs.length})</button
      >
    </nav>

    {#if error}<p class="error">{error}</p>{/if}

    {#if tab === "jobs"}
      <section class="jobs">
        <div class="toolbar">
          <button type="button" class="ghost" onclick={() => void refreshJobs()}>Refresh</button>
        </div>
        {#if jobs.length === 0}
          <p class="muted">No jobs yet.</p>
        {:else}
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Video</th>
                <th>Quality</th>
                <th>Attempts</th>
                <th>Updated</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {#each jobs as job (job.id)}
                <tr class:active-row={isActiveJob(job.status)}>
                  <td><span class="status status-{job.status}">{job.status}</span></td>
                  <td>
                    <div class="job-url" title={job.url}>{job.platform_video_id ?? job.url}</div>
                    {#if job.status === "completed" && job.platform && job.platform_video_id}
                      <button
                        type="button"
                        class="linkish"
                        onclick={() =>
                          void openVideo({
                            id: job.video_id ?? 0,
                            platform: job.platform!,
                            platform_video_id: job.platform_video_id!,
                            title: null,
                            url: job.url,
                            media_relpath: "",
                            metadata_relpath: "",
                            checksum_sha256: null,
                            archived_at: "",
                            has_thumbnail: false,
                          })}
                      >
                        Open in library
                      </button>
                    {/if}
                  </td>
                  <td><code class="tiny">{job.quality_preference}</code></td>
                  <td>{job.attempts}</td>
                  <td class="muted">{job.updated_at}</td>
                  <td class="error-cell">
                    {#if job.error_message}
                      <span class="warn" title={job.error_message}
                        >{job.error_code}: {job.error_message}</span
                      >
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {:else}
      <section class="toolbar">
        <input
          type="search"
          placeholder="Search title, id, url…"
          bind:value={query}
          onkeydown={(e) => {
            if (e.key === "Enter") void refreshVideos().catch((err) => (error = String(err)));
          }}
        />
        <button
          type="button"
          onclick={() => void refreshVideos().catch((err) => (error = String(err)))}
          >Search</button
        >
      </section>

      {#if loading && !selected}<p class="muted">Loading…</p>{/if}

      <div class="split">
        <aside>
          {#if videos.length === 0 && !loading}
            <p class="muted">No archived videos yet. Enqueue a URL above.</p>
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
                {#each Object.entries(selected.source_metadata).filter(([k]) =>
                  [
                    "channel",
                    "duration",
                    "width",
                    "height",
                    "fps",
                    "format",
                    "vcodec",
                    "acodec",
                    "upload_date",
                    "view_count",
                  ].includes(k),
                ) as [key, value]}
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
    {/if}
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
  h1,
  h2 {
    margin: 0;
    font-weight: 650;
    letter-spacing: -0.02em;
  }
  h2 {
    font-size: 1.05rem;
    margin-bottom: 0.5rem;
  }
  .sub {
    margin: 0.25rem 0 0;
    color: #9aa7b5;
    font-size: 0.9rem;
  }
  .enqueue {
    margin-bottom: 1rem;
    padding: 1rem;
    border: 1px solid #2a3542;
    border-radius: 8px;
    background: #121820;
  }
  .enqueue-form {
    display: grid;
    grid-template-columns: 1fr minmax(10rem, 16rem) auto;
    gap: 0.5rem;
  }
  @media (max-width: 800px) {
    .enqueue-form {
      grid-template-columns: 1fr;
    }
  }
  .tabs {
    display: flex;
    gap: 0.35rem;
    margin-bottom: 1rem;
  }
  .tabs button {
    background: #151c24;
    color: #c5d0db;
    border: 1px solid #2a3542;
  }
  .tabs button.active {
    border-color: #3d8bfd;
    color: #fff;
  }
  .toolbar {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }
  input,
  select {
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
  button:disabled {
    opacity: 0.6;
    cursor: wait;
  }
  button.ghost {
    background: transparent;
    color: #9aa7b5;
    border: 1px solid #2a3542;
  }
  button.linkish {
    background: none;
    border: 0;
    color: #7eb6ff;
    padding: 0;
    font-weight: 500;
    font-size: 0.85rem;
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
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
  }
  th,
  td {
    text-align: left;
    padding: 0.55rem 0.4rem;
    border-bottom: 1px solid #2a3542;
    vertical-align: top;
  }
  th {
    color: #9aa7b5;
    font-weight: 600;
  }
  .job-url {
    max-width: 18rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    border-radius: 4px;
    background: #2a3542;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .status-completed {
    background: #1d3b2a;
    color: #8dffb0;
  }
  .status-failed,
  .status-duplicate {
    background: #3b1d1d;
    color: #ffb4b4;
  }
  .status-queued,
  .status-downloading {
    background: #2a3340;
    color: #9ec5ff;
  }
  .active-row {
    background: #151c24;
  }
  .error-cell {
    max-width: 16rem;
  }
  .error-cell span {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
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
  .ok {
    color: #8dffb0;
    margin: 0.5rem 0 0;
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
  code.tiny {
    font-size: 0.75rem;
    word-break: break-all;
  }
</style>
