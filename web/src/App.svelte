<script lang="ts">
  import {
    channelThumbnailUrl,
    clearToken,
    enqueueJob,
    filterCookies,
    formatUploadDate,
    getConfig,
    getToken,
    getVideo,
    isActiveJob,
    listChannels,
    listJobs,
    listRelated,
    listVideos,
    mediaUrl,
    refreshIncompleteMetadata,
    rescanArchive,
    setChannelFavorite,
    setToken,
    thumbnailUrl,
    verifyIntegrity,
    type Channel,
    type Job,
    type PublicConfig,
    type RescanReport,
    type VerifyReport,
    type VideoDetail,
    type VideoSummary,
  } from "./lib/api";

  type Mode = "view" | "download";
  type DownloadTab = "library" | "jobs" | "integrity";
  type SortField = "upload_date" | "title";

  let tokenInput = $state(getToken());
  let authed = $state(Boolean(getToken()));
  let mode = $state<Mode>("view");
  let downloadTab = $state<DownloadTab>("library");
  let query = $state("");
  let videos = $state<VideoSummary[]>([]);
  let channels = $state<Channel[]>([]);
  let selectedChannelIds = $state<string[]>([]);
  let sort = $state<SortField>("upload_date");
  let order = $state<"asc" | "desc">("desc");
  let watching = $state<VideoDetail | null>(null);
  let related = $state<VideoSummary[]>([]);
  let upNext = $state<VideoSummary[]>([]);
  let selected = $state<VideoDetail | null>(null);
  let jobs = $state<Job[]>([]);
  let config = $state<PublicConfig | null>(null);
  let enqueueUrl = $state("");
  let quality = $state("best");
  let enqueueBusy = $state(false);
  let enqueueMsg = $state("");
  let cookieBusy = $state(false);
  let cookieMsg = $state("");
  let integrityBusy = $state(false);
  let refreshBusy = $state(false);
  let refreshMsg = $state("");
  let verifyReport = $state<VerifyReport | null>(null);
  let rescanReport = $state<RescanReport | null>(null);
  let error = $state("");
  let loading = $state(false);

  async function saveToken() {
    setToken(tokenInput.trim());
    authed = Boolean(getToken());
    error = "";
    selected = null;
    watching = null;
    await bootstrap();
  }

  function logout() {
    clearToken();
    tokenInput = "";
    authed = false;
    videos = [];
    jobs = [];
    channels = [];
    selected = null;
    watching = null;
    config = null;
  }

  async function bootstrap() {
    if (!authed) return;
    loading = true;
    error = "";
    try {
      config = await getConfig();
      quality = config.default_quality || "best";
      await Promise.all([refreshVideos(), refreshChannels(), refreshJobs()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function refreshVideos() {
    videos = await listVideos({
      q: query.trim() || undefined,
      channelIds: selectedChannelIds.length ? selectedChannelIds : undefined,
      sort,
      order,
      limit: 200,
    });
  }

  async function refreshChannels() {
    channels = await listChannels();
  }

  async function refreshJobs() {
    jobs = await listJobs();
  }

  function toggleChannel(channelId: string) {
    if (selectedChannelIds.includes(channelId)) {
      selectedChannelIds = selectedChannelIds.filter((id) => id !== channelId);
    } else {
      selectedChannelIds = [...selectedChannelIds, channelId];
    }
    void refreshVideos().catch((err) => (error = String(err)));
  }

  async function toggleFavorite(ch: Channel, event: MouseEvent) {
    event.stopPropagation();
    error = "";
    try {
      await setChannelFavorite(ch.platform, ch.channel_id, !ch.favorited, ch.channel);
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function openWatch(v: VideoSummary) {
    mode = "view";
    loading = true;
    error = "";
    try {
      watching = await getVideo(v.platform, v.platform_video_id);
      related = await listRelated(v.platform, v.platform_video_id);
      const pool = videos.filter(
        (item) =>
          !(
            item.platform === v.platform && item.platform_video_id === v.platform_video_id
          ),
      );
      const relatedKeys = new Set(related.map((r) => `${r.platform}:${r.platform_video_id}`));
      upNext = pool.filter((item) => !relatedKeys.has(`${item.platform}:${item.platform_video_id}`)).slice(0, 8);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      watching = null;
      related = [];
      upNext = [];
    } finally {
      loading = false;
    }
  }

  function closeWatch() {
    watching = null;
    related = [];
    upNext = [];
  }

  async function openInDownload(v: VideoSummary | VideoDetail) {
    mode = "download";
    downloadTab = "library";
    loading = true;
    error = "";
    try {
      selected = await getVideo(v.platform, v.platform_video_id);
      videos = await listVideos({ limit: 200, sort: "archived_at", order: "desc" });
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      selected = null;
    } finally {
      loading = false;
    }
  }

  async function openVideo(v: VideoSummary) {
    downloadTab = "library";
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
      downloadTab = "jobs";
      await refreshJobs();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      enqueueBusy = false;
    }
  }

  async function runCookieFilter() {
    if (!config?.cookies_configured) return;
    const platforms = (config.cookie_platforms ?? ["youtube"]).join(", ");
    const ok = confirm(
      `Filter the cookies file to only ${platforms} domains?\n\n` +
        "A .bak backup will be written next to the cookies file. Cookie values are never shown in the UI.",
    );
    if (!ok) return;
    cookieBusy = true;
    cookieMsg = "";
    error = "";
    try {
      const result = await filterCookies();
      cookieMsg =
        `Kept ${result.cookies_after} of ${result.cookies_before} cookies` +
        ` (removed ${result.cookies_removed}) for ${result.platforms.join(", ")}.`;
      config = await getConfig();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      cookieBusy = false;
    }
  }

  async function runVerify() {
    integrityBusy = true;
    error = "";
    try {
      verifyReport = await verifyIntegrity();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      integrityBusy = false;
    }
  }

  async function runRescan() {
    integrityBusy = true;
    error = "";
    try {
      rescanReport = await rescanArchive();
      await Promise.all([refreshVideos(), refreshChannels()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      integrityBusy = false;
    }
  }

  async function runRefreshIncomplete() {
    refreshBusy = true;
    refreshMsg = "";
    error = "";
    try {
      const results = await refreshIncompleteMetadata();
      const ok = results.filter((r) => r.status === "ok").length;
      const partial = results.filter((r) => r.status === "partial").length;
      const failed = results.filter((r) => r.status === "failed").length;
      refreshMsg = `Refreshed ${results.length}: ${ok} ok, ${partial} partial, ${failed} failed.`;
      await Promise.all([refreshVideos(), refreshChannels()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      refreshBusy = false;
    }
  }

  function stubVideoFromJob(job: Job): VideoSummary {
    return {
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
      channel: null,
      channel_id: null,
      upload_date: null,
      metadata_incomplete: false,
      metadata_gaps: [],
    };
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
            await Promise.all([refreshVideos(), refreshChannels()]);
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
      <button type="submit">Open archive</button>
    </form>
    {#if error}<p class="error">{error}</p>{/if}
  </main>
{:else}
  <div class="layout" class:view-wide={mode === "view"}>
    <header>
      <div>
        <h1>Lones-VDL</h1>
        <p class="sub">
          {#if config}
            Archive: <code>{config.archive_root}</code>
            · concurrency {config.download_concurrency}
            · cookies {config.cookies_configured
              ? `yes (${config.cookie_count ?? "?"} for ${config.cookie_platforms.join(", ")})`
              : "no"}
          {:else}
            Archive library
          {/if}
        </p>
      </div>
      <div class="header-actions">
        <div class="mode-toggle" role="group" aria-label="App mode">
          <button type="button" class:active={mode === "view"} onclick={() => (mode = "view")}
            >View</button
          >
          <button
            type="button"
            class:active={mode === "download"}
            onclick={() => (mode = "download")}>Download</button
          >
        </div>
        {#if config?.cookies_configured && mode === "download"}
          <button type="button" class="ghost" disabled={cookieBusy} onclick={() => void runCookieFilter()}>
            {cookieBusy ? "Filtering…" : "Filter cookies"}
          </button>
        {/if}
        <button type="button" class="ghost" onclick={logout}>Clear token</button>
      </div>
    </header>
    {#if cookieMsg && mode === "download"}<p class="ok cookie-msg">{cookieMsg}</p>{/if}
    {#if error}<p class="error">{error}</p>{/if}

    {#if mode === "view"}
      {#if watching}
        <section class="watch">
          <div class="watch-toolbar">
            <button type="button" class="ghost" onclick={closeWatch}>← Back</button>
            <button
              type="button"
              class="ghost"
              onclick={() => {
                if (watching) void openInDownload(watching);
              }}>Open in Download</button
            >
          </div>
          <h2>{watching.title ?? watching.platform_video_id}</h2>
          <p class="meta">
            {watching.channel ?? "Unknown channel"}
            · {formatUploadDate(watching.upload_date)}
            · archived {watching.archived_at}
            {#if watching.metadata_incomplete}
              · <span class="warn">incomplete metadata ({watching.metadata_gaps.join(", ")})</span>
            {/if}
          </p>

          {#if watching.playback?.mode === "unavailable"}
            <p class="warn">Not browser-playable without re-encoding: {watching.playback.reason}</p>
          {:else if watching.playback}
            <video
              controls
              playsinline
              autoplay
              src={mediaUrl(watching.platform, watching.platform_video_id, "play")}
            >
              <track kind="captions" />
            </video>
            <p class="muted">
              Playback: {watching.playback.mode}
              {#if watching.playback.container}({watching.playback.container}){/if}
              — {watching.playback.reason}
            </p>
          {/if}

          <div class="watch-columns">
            <div>
              <h3>More from channel</h3>
              {#if related.length === 0}
                <p class="muted">No other videos from this channel in the archive.</p>
              {:else}
                <ul class="rail">
                  {#each related as v (v.id)}
                    <li>
                      <button type="button" onclick={() => void openWatch(v)}>
                        {#if v.has_thumbnail}
                          <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                        {:else}
                          <div class="thumb-fallback"></div>
                        {/if}
                        <span>
                          <strong>{v.title ?? v.platform_video_id}</strong>
                          <small>{formatUploadDate(v.upload_date)}</small>
                        </span>
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
            <div>
              <h3>Up next</h3>
              {#if upNext.length === 0}
                <p class="muted">Nothing else in the current browse list.</p>
              {:else}
                <ul class="rail">
                  {#each upNext as v (v.id)}
                    <li>
                      <button type="button" onclick={() => void openWatch(v)}>
                        {#if v.has_thumbnail}
                          <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                        {:else}
                          <div class="thumb-fallback"></div>
                        {/if}
                        <span>
                          <strong>{v.title ?? v.platform_video_id}</strong>
                          <small
                            >{v.channel ?? "Unknown"} · {formatUploadDate(v.upload_date)}</small
                          >
                        </span>
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
          </div>
        </section>
      {:else}
        <div class="view-home">
          <aside class="channels">
            <div class="channels-head">
              <h2>Channels</h2>
              {#if selectedChannelIds.length}
                <button
                  type="button"
                  class="linkish"
                  onclick={() => {
                    selectedChannelIds = [];
                    void refreshVideos().catch((err) => (error = String(err)));
                  }}>Clear</button
                >
              {/if}
            </div>
            <p class="muted tiny">Multi-select is OR. Favorites stay on top.</p>
            {#if channels.length === 0}
              <p class="muted">No channels yet.</p>
            {:else}
              <ul>
                {#each channels as ch (`${ch.platform}:${ch.channel_id}`)}
                  <li>
                    <button
                      type="button"
                      class:active={selectedChannelIds.includes(ch.channel_id)}
                      onclick={() => toggleChannel(ch.channel_id)}
                    >
                      <img
                        class="channel-avatar"
                        src={channelThumbnailUrl(ch.platform, ch.channel_id)}
                        alt=""
                        onerror={(e) => {
                          const img = e.currentTarget as HTMLImageElement;
                          img.style.visibility = "hidden";
                        }}
                      />
                      <span class="channel-name">{ch.channel ?? ch.channel_id}</span>
                      <span class="muted count">{ch.video_count}</span>
                    </button>
                    <button
                      type="button"
                      class="fav"
                      class:on={ch.favorited}
                      title={ch.favorited ? "Unfavorite" : "Favorite"}
                      aria-label={ch.favorited ? "Unfavorite channel" : "Favorite channel"}
                      onclick={(e) => void toggleFavorite(ch, e)}
                    >
                      {ch.favorited ? "★" : "☆"}
                    </button>
                  </li>
                {/each}
              </ul>
            {/if}
          </aside>

          <section class="browse">
            <div class="browse-toolbar">
              <input
                type="search"
                placeholder="Search title, channel, id…"
                bind:value={query}
                onkeydown={(e) => {
                  if (e.key === "Enter") void refreshVideos().catch((err) => (error = String(err)));
                }}
              />
              <select
                bind:value={sort}
                onchange={() => void refreshVideos().catch((err) => (error = String(err)))}
              >
                <option value="upload_date">Upload date</option>
                <option value="title">Title A–Z</option>
              </select>
              <select
                bind:value={order}
                onchange={() => void refreshVideos().catch((err) => (error = String(err)))}
              >
                <option value="desc">Descending</option>
                <option value="asc">Ascending</option>
              </select>
              <button
                type="button"
                onclick={() => void refreshVideos().catch((err) => (error = String(err)))}
                >Refresh</button
              >
            </div>

            {#if loading}<p class="muted">Loading…</p>{/if}
            {#if videos.length === 0 && !loading}
              <p class="muted">No archived videos match. Switch to Download to enqueue.</p>
            {:else}
              <div class="grid">
                {#each videos as v (v.id)}
                  <button type="button" class="card" onclick={() => void openWatch(v)}>
                    {#if v.has_thumbnail}
                      <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                    {:else}
                      <div class="thumb-fallback wide"></div>
                    {/if}
                    <strong>{v.title ?? v.platform_video_id}</strong>
                    <small
                      >{v.channel ?? "Unknown channel"} · {formatUploadDate(v.upload_date)}</small
                    >
                    {#if v.metadata_incomplete}
                      <span class="badge-warn">Incomplete</span>
                    {/if}
                  </button>
                {/each}
              </div>
            {/if}
          </section>
        </div>
      {/if}
    {:else}
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
        <button
          type="button"
          class:active={downloadTab === "library"}
          onclick={() => (downloadTab = "library")}>Library</button
        >
        <button
          type="button"
          class:active={downloadTab === "jobs"}
          onclick={() => (downloadTab = "jobs")}>Jobs ({jobs.length})</button
        >
        <button
          type="button"
          class:active={downloadTab === "integrity"}
          onclick={() => (downloadTab = "integrity")}>Integrity</button
        >
      </nav>

      {#if downloadTab === "integrity"}
        <section class="integrity">
          <p class="muted">
            Verify compares on-disk media to <code>checksums.json</code>. Rescan rebuilds the index
            from sidecars. Refresh incomplete re-fetches missing browse fields via yt-dlp.
          </p>
          <div class="toolbar">
            <button type="button" disabled={integrityBusy} onclick={() => void runVerify()}
              >{integrityBusy ? "Working…" : "Verify checksums"}</button
            >
            <button
              type="button"
              class="ghost"
              disabled={integrityBusy}
              onclick={() => void runRescan()}>Rescan / import from disk</button
            >
            <button
              type="button"
              class="ghost"
              disabled={refreshBusy}
              onclick={() => void runRefreshIncomplete()}
              >{refreshBusy ? "Refreshing…" : "Refresh incomplete metadata"}</button
            >
          </div>
          {#if refreshMsg}<p class="ok">{refreshMsg}</p>{/if}

          {#if verifyReport}
            <h2>
              Verify: {verifyReport.ok}/{verifyReport.checked} ok · {verifyReport.issue_count} issue{verifyReport.issue_count === 1
                ? ""
                : "s"}
            </h2>
            {#if verifyReport.issues.length === 0}
              <p class="ok">All checked items look healthy.</p>
            {:else}
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Item</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {#each verifyReport.issues as issue (`${issue.platform}:${issue.platform_video_id}:${issue.status}`)}
                    <tr>
                      <td><span class="status status-failed">{issue.status}</span></td>
                      <td>{issue.platform}/{issue.platform_video_id}</td>
                      <td class="warn">{issue.detail}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            {/if}
          {/if}

          {#if rescanReport}
            <h2>
              Rescan: scanned {rescanReport.scanned} · imported {rescanReport.imported} · updated {rescanReport.updated}
              · errors {rescanReport.errors}
            </h2>
            {#if rescanReport.missing_from_disk.length}
              <p class="warn">
                In DB but missing on disk: {rescanReport.missing_from_disk.join(", ")}
              </p>
            {/if}
          {/if}
        </section>
      {:else if downloadTab === "jobs"}
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
                          onclick={() => void openVideo(stubVideoFromJob(job))}
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
                      class:incomplete={v.metadata_incomplete}
                      onclick={() => void openVideo(v)}
                    >
                      {#if v.has_thumbnail}
                        <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                      {/if}
                      <span>
                        <strong>{v.title ?? v.platform_video_id}</strong>
                        <small>
                          {v.platform} · {v.platform_video_id}
                          {#if v.metadata_incomplete}
                            · <span class="warn">incomplete ({v.metadata_gaps.join(", ")})</span>
                          {/if}
                        </small>
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
              <div class="detail-actions">
                <button
                  type="button"
                  class="ghost"
                  onclick={() => {
                    if (selected) void openWatch(selected);
                  }}>Open in View</button
                >
              </div>
              <h2>{selected.title ?? selected.platform_video_id}</h2>
              <p class="meta">
                {selected.platform} / {selected.platform_video_id} · archived {selected.archived_at}
              </p>
              {#if selected.metadata_incomplete}
                <p class="warn incomplete-banner">
                  Incomplete metadata: {selected.metadata_gaps.join(", ") || "unknown gaps"}. Use
                  Integrity → Refresh incomplete metadata.
                </p>
              {/if}

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
                <dl class="meta-grid">
                  {#each Object.entries(selected.source_metadata).filter(([k]) =>
                    [
                      "channel",
                      "channel_id",
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
  .layout.view-wide {
    max-width: 90rem;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
    gap: 1rem;
  }
  .header-actions {
    display: flex;
    gap: 0.5rem;
    flex-shrink: 0;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .mode-toggle {
    display: inline-flex;
    border: 1px solid #2a3542;
    border-radius: 8px;
    overflow: hidden;
  }
  .mode-toggle button {
    border-radius: 0;
    background: #151c24;
    color: #c5d0db;
    border: 0;
  }
  .mode-toggle button.active {
    background: #3d8bfd;
    color: #041018;
  }
  .cookie-msg {
    margin: -0.5rem 0 1rem;
  }
  h1,
  h2,
  h3 {
    margin: 0;
    font-weight: 650;
    letter-spacing: -0.02em;
  }
  h2 {
    font-size: 1.05rem;
    margin-bottom: 0.5rem;
  }
  h3 {
    font-size: 0.95rem;
    margin: 1rem 0 0.5rem;
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
  .toolbar,
  .browse-toolbar,
  .watch-toolbar,
  .detail-actions {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
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
  .view-home {
    display: grid;
    grid-template-columns: minmax(14rem, 18rem) 1fr;
    gap: 1rem;
  }
  @media (max-width: 900px) {
    .view-home {
      grid-template-columns: 1fr;
    }
  }
  .channels {
    border: 1px solid #2a3542;
    border-radius: 8px;
    background: #121820;
    padding: 0.75rem;
    max-height: 75vh;
    overflow: auto;
  }
  .channels-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .channels ul {
    list-style: none;
    margin: 0.75rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .channels li {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 0.25rem;
  }
  .channels li > button:first-child {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.55rem;
    text-align: left;
    background: #151c24;
    color: inherit;
    border: 1px solid #2a3542;
    font-weight: 500;
    padding: 0.4rem 0.55rem;
  }
  .channels li > button:first-child.active {
    border-color: #3d8bfd;
  }
  .channel-avatar {
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 50%;
    object-fit: cover;
    background: #0a0e12;
    flex-shrink: 0;
  }
  .channels .fav {
    background: transparent;
    color: #3a4554;
    border: 1px solid transparent;
    padding: 0.35rem 0.45rem;
    opacity: 0.45;
  }
  .channels .fav:hover {
    opacity: 0.85;
    color: #9aa7b5;
    border-color: #2a3542;
  }
  .channels .fav.on {
    opacity: 1;
    color: #ffcc66;
    border-color: #2a3542;
  }
  .channel-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .channels .count {
    flex-shrink: 0;
  }
  .tiny {
    font-size: 0.8rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
    gap: 0.85rem;
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    text-align: left;
    background: #151c24;
    color: inherit;
    border: 1px solid #2a3542;
    padding: 0.55rem;
    font-weight: 500;
  }
  .card img,
  .thumb-fallback.wide {
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
    border-radius: 4px;
    background: #0a0e12;
  }
  .thumb-fallback {
    width: 5.5rem;
    height: 3.1rem;
    border-radius: 4px;
    background: #0a0e12;
    flex-shrink: 0;
  }
  .card strong {
    font-size: 0.92rem;
    line-height: 1.3;
  }
  .card small {
    color: #9aa7b5;
  }
  .badge-warn {
    align-self: flex-start;
    font-size: 0.75rem;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    background: #3b2a14;
    color: #ffcc66;
  }
  .watch video,
  .detail video {
    width: 100%;
    max-height: 70vh;
    background: #000;
    border-radius: 8px;
  }
  .watch-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  @media (max-width: 900px) {
    .watch-columns {
      grid-template-columns: 1fr;
    }
  }
  .rail {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .rail button {
    width: 100%;
    display: flex;
    gap: 0.75rem;
    text-align: left;
    background: #151c24;
    color: inherit;
    border: 1px solid #2a3542;
    font-weight: 500;
  }
  .rail img {
    width: 5.5rem;
    height: 3.1rem;
    object-fit: cover;
    border-radius: 4px;
    background: #0a0e12;
  }
  .rail strong {
    display: block;
  }
  .rail small {
    color: #9aa7b5;
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
  .list button.incomplete {
    border-color: #a67c2d;
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
  .incomplete-banner {
    padding: 0.6rem 0.75rem;
    border: 1px solid #a67c2d;
    border-radius: 6px;
    background: #2a2114;
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
  .meta-grid {
    display: grid;
    grid-template-columns: 8rem 1fr;
    gap: 0.35rem 0.75rem;
  }
  .meta-grid dt {
    color: #9aa7b5;
  }
  .meta-grid dd {
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
