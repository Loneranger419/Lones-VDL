<script lang="ts">
  import {
    attachCreatorChannel,
    cancelJob,
    channelKey,
    channelThumbnailUrl,
    checkWatchedChannels,
    clearToken,
    createCreator,
    creatorThumbnailUrl,
    deleteCreator,
    deleteVideo,
    detachCreatorChannel,
    enqueueJob,
    filterCookies,
    formatUploadDate,
    getBrowseColumns,
    getConfig,
    getToken,
    getVideo,
    isActiveJob,
    isExpandJob,
    listChannels,
    listCreators,
    listJobs,
    listRelated,
    listVideos,
    mediaUrl,
    setBrowseColumns,
    refreshIncompleteMetadata,
    rescanArchive,
    setChannelFavorite,
    setChannelWatch,
    setToken,
    thumbnailUrl,
    updateCreator,
    verifyIntegrity,
    type Channel,
    type Creator,
    type Job,
    type PublicConfig,
    type RescanReport,
    type VerifyReport,
    type VideoDetail,
    type VideoSummary,
  } from "./lib/api";
  import PlatformIcon from "./lib/PlatformIcon.svelte";

  type Mode = "view" | "download";
  type DownloadTab = "library" | "jobs" | "integrity";
  type SortField = "upload_date" | "title";

  const VIEW_PAGE_SIZE = 32;
  const DOWNLOAD_LIST_LIMIT = 100;

  let tokenInput = $state(getToken());
  let authed = $state(Boolean(getToken()));
  let mode = $state<Mode>("view");
  let downloadTab = $state<DownloadTab>("library");
  let query = $state("");
  let videos = $state<VideoSummary[]>([]);
  let channels = $state<Channel[]>([]);
  let creators = $state<Creator[]>([]);
  /** Selected channel filters as `platform:channel_id`. */
  let selectedChannels = $state<string[]>([]);
  let platformFilter = $state<string>("");
  let contentKindFilter = $state<string>("");
  let sort = $state<SortField>("upload_date");
  let order = $state<"asc" | "desc">("desc");
  let browseColumns = $state(getBrowseColumns());
  let settingsOpen = $state(false);
  let hasMoreVideos = $state(false);
  let loadMoreBusy = $state(false);
  let watching = $state<VideoDetail | null>(null);
  let related = $state<VideoSummary[]>([]);
  let upNext = $state<VideoSummary[]>([]);
  let selected = $state<VideoDetail | null>(null);
  let jobs = $state<Job[]>([]);
  let config = $state<PublicConfig | null>(null);
  let enqueueUrl = $state("");
  let quality = $state("best");
  let watchNewOnEnqueue = $state(false);
  let enqueueBusy = $state(false);
  let enqueueMsg = $state("");
  let watchBusy = $state(false);
  let watchMsg = $state("");
  let cookieBusy = $state(false);
  let cookieMsg = $state("");
  let integrityBusy = $state(false);
  let refreshBusy = $state(false);
  let refreshMsg = $state("");
  let verifyReport = $state<VerifyReport | null>(null);
  let rescanReport = $state<RescanReport | null>(null);
  let error = $state("");
  let loading = $state(false);
  let newCreatorName = $state("");
  let creatorBusy = $state(false);
  let creatorMsg = $state("");
  let editingCreatorId = $state<number | null>(null);
  let editCreatorName = $state("");
  let attachChannelKey = $state("");

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
    creators = [];
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
      await Promise.all([refreshVideos(), refreshChannels(), refreshCreators(), refreshJobs()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  function videoListParams(offset = 0) {
    const pageSize = mode === "view" ? VIEW_PAGE_SIZE : DOWNLOAD_LIST_LIMIT;
    return {
      q: query.trim() || undefined,
      channels: selectedChannels.length ? selectedChannels : undefined,
      platforms: platformFilter ? [platformFilter] : undefined,
      contentKinds: contentKindFilter ? [contentKindFilter] : undefined,
      sort,
      order,
      limit: pageSize,
      offset,
    };
  }

  async function refreshVideos() {
    const page = await listVideos(videoListParams(0));
    videos = page;
    hasMoreVideos = mode === "view" && page.length >= VIEW_PAGE_SIZE;
  }

  async function loadMoreVideos() {
    if (!hasMoreVideos || loadMoreBusy) return;
    loadMoreBusy = true;
    error = "";
    try {
      const page = await listVideos(videoListParams(videos.length));
      videos = [...videos, ...page];
      hasMoreVideos = page.length >= VIEW_PAGE_SIZE;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loadMoreBusy = false;
    }
  }

  function updateBrowseColumns(value: string) {
    browseColumns = setBrowseColumns(Number(value));
  }

  async function refreshChannels() {
    channels = await listChannels();
  }

  async function refreshCreators() {
    creators = await listCreators();
  }

  async function refreshJobs() {
    jobs = await listJobs();
  }

  function toggleChannel(ch: Channel) {
    const key = channelKey(ch.platform, ch.channel_id);
    if (selectedChannels.includes(key)) {
      selectedChannels = selectedChannels.filter((id) => id !== key);
    } else {
      selectedChannels = [...selectedChannels, key];
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
      videos = await listVideos({
        limit: DOWNLOAD_LIST_LIMIT,
        sort: "archived_at",
        order: "desc",
      });
      hasMoreVideos = false;
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
      const job = await enqueueJob(url, quality, watchNewOnEnqueue);
      const kind = job.job_kind ? ` [${job.job_kind}]` : "";
      enqueueMsg = `Queued ${job.id.slice(0, 8)}… (${job.status})${kind}`;
      enqueueUrl = "";
      watchNewOnEnqueue = false;
      downloadTab = "jobs";
      await refreshJobs();
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      enqueueBusy = false;
    }
  }

  async function cancelOneJob(job: Job, batch: boolean) {
    const label = batch ? "Cancel this expand job and all its child downloads?" : "Cancel this job?";
    if (!confirm(label)) return;
    error = "";
    try {
      const result = await cancelJob(job.id, batch || isExpandJob(job));
      enqueueMsg = `Cancelled ${result.count} job(s).`;
      await refreshJobs();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
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

  async function confirmDelete(v: VideoSummary | VideoDetail) {
    const label = v.title ?? v.platform_video_id;
    const ok = confirm(
      `Delete “${label}” from the archive?\n\n` +
        "This removes the database entry and deletes media/sidecars on disk. This cannot be undone.",
    );
    if (!ok) return;
    loading = true;
    error = "";
    try {
      await deleteVideo(v.platform, v.platform_video_id);
      if (
        watching?.platform === v.platform &&
        watching.platform_video_id === v.platform_video_id
      ) {
        closeWatch();
      }
      if (
        selected?.platform === v.platform &&
        selected.platform_video_id === v.platform_video_id
      ) {
        selected = null;
      }
      await Promise.all([refreshVideos(), refreshChannels()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  async function toggleWatch(ch: Channel) {
    error = "";
    try {
      await setChannelWatch(ch.platform, ch.channel_id, !ch.watching, {
        channel: ch.channel,
        channelUrl: ch.channel_url,
      });
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function runCheckWatched() {
    watchBusy = true;
    watchMsg = "";
    error = "";
    try {
      const results = await checkWatchedChannels();
      const enqueued = results.reduce((n, r) => n + r.enqueued, 0);
      watchMsg =
        results.length === 0
          ? "No channels are set to watch."
          : `Checked ${results.length} channel(s); enqueued ${enqueued} new video(s).`;
      await Promise.all([refreshJobs(), refreshChannels(), refreshVideos()]);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      watchBusy = false;
    }
  }

  async function submitCreateCreator() {
    const name = newCreatorName.trim();
    if (!name) return;
    creatorBusy = true;
    creatorMsg = "";
    error = "";
    try {
      const created = await createCreator(name);
      newCreatorName = "";
      creatorMsg = `Created creator “${name}”.`;
      await refreshCreators();
      await refreshChannels();
      beginEditCreator(created);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  function beginEditCreator(c: Creator) {
    editingCreatorId = c.id;
    editCreatorName = c.display_name;
    attachChannelKey = "";
  }

  function cancelEditCreator() {
    editingCreatorId = null;
    editCreatorName = "";
    attachChannelKey = "";
  }

  function unlinkedChannelsForEdit(): Channel[] {
    if (editingCreatorId == null) return [];
    const linked = new Set(
      (creators.find((c) => c.id === editingCreatorId)?.channels ?? []).map((ch) =>
        channelKey(ch.platform, ch.channel_id),
      ),
    );
    return channels.filter((ch) => !linked.has(channelKey(ch.platform, ch.channel_id)));
  }

  async function saveCreatorName() {
    if (editingCreatorId == null) return;
    const name = editCreatorName.trim();
    if (!name) return;
    creatorBusy = true;
    creatorMsg = "";
    error = "";
    try {
      await updateCreator(editingCreatorId, { display_name: name });
      creatorMsg = "Creator renamed.";
      await refreshCreators();
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  async function attachChannelFromLibrary() {
    if (editingCreatorId == null || !attachChannelKey.includes(":")) return;
    const [platform, ...rest] = attachChannelKey.split(":");
    const channelId = rest.join(":");
    creatorBusy = true;
    creatorMsg = "";
    error = "";
    try {
      await attachCreatorChannel(editingCreatorId, platform, channelId);
      creatorMsg = `Linked ${platform}:${channelId}.`;
      attachChannelKey = "";
      await refreshCreators();
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  async function unlinkCreatorChannel(platform: string, channelId: string) {
    if (editingCreatorId == null) return;
    creatorBusy = true;
    creatorMsg = "";
    error = "";
    try {
      await detachCreatorChannel(editingCreatorId, platform, channelId);
      creatorMsg = `Unlinked ${platform}:${channelId}.`;
      await refreshCreators();
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  async function setCreatorAvatar(platform: string, channelId: string) {
    if (editingCreatorId == null) return;
    creatorBusy = true;
    creatorMsg = "";
    error = "";
    try {
      await updateCreator(editingCreatorId, {
        avatar_platform: platform,
        avatar_channel_id: channelId,
      });
      creatorMsg = "Creator thumbnail updated.";
      await refreshCreators();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  async function removeCreator(c: Creator) {
    if (!confirm(`Delete creator “${c.display_name}”? Channels stay archived.`)) return;
    creatorBusy = true;
    error = "";
    try {
      await deleteCreator(c.id);
      if (editingCreatorId === c.id) cancelEditCreator();
      await refreshCreators();
      await refreshChannels();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      creatorBusy = false;
    }
  }

  function kindLabel(kind: string | null | undefined): string {
    if (kind === "vod") return "VOD";
    if (kind === "clip") return "Clip";
    return "Video";
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
      content_kind: "video",
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
    <div class="brand">
      <img class="brand-mark" src="/icon.png" alt="" width="84" height="84" />
      <h1>Lone's VDL</h1>
    </div>
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
  <div
    class="layout"
    class:view-mode={mode === "view"}
    class:view-browse={mode === "view" && !watching}
  >
    <header>
      <div class="brand-block">
        <div class="brand">
          <img class="brand-mark" src="/icon.png" alt="" width="60" height="60" />
          <h1>Lone's VDL</h1>
        </div>
        {#if mode === "download"}
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
        {/if}
      </div>
      <div class="header-actions">
        <div class="mode-toggle" role="group" aria-label="App mode">
          <button
            type="button"
            class:active={mode === "view"}
            onclick={() => {
              mode = "view";
              void refreshVideos().catch((err) => (error = String(err)));
            }}>View</button
          >
          <button
            type="button"
            class:active={mode === "download"}
            onclick={() => {
              mode = "download";
              void refreshVideos().catch((err) => (error = String(err)));
            }}>Download</button
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
            <button
              type="button"
              class="danger"
              onclick={() => {
                if (watching) void confirmDelete(watching);
              }}>Delete</button
            >
          </div>
          <h2>{watching.title ?? watching.platform_video_id}</h2>
          <p class="meta meta-with-icon">
            <PlatformIcon platform={watching.platform} variant="inline" />
            <span>
              {watching.channel ?? "Unknown channel"}
              · {kindLabel(watching.content_kind)}
              · {formatUploadDate(watching.upload_date)}
              · archived {watching.archived_at}
              {#if watching.metadata_incomplete}
                · <span class="warn"
                  >incomplete metadata ({watching.metadata_gaps.join(", ")})</span
                >
              {/if}
            </span>
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
              <h3>More from creator / channel</h3>
              {#if related.length === 0}
                <p class="muted">No other videos from this channel in the archive.</p>
              {:else}
                <ul class="rail">
                  {#each related as v (v.id)}
                    <li>
                      <button type="button" onclick={() => void openWatch(v)}>
                        <span class="thumb-wrap compact">
                          {#if v.has_thumbnail}
                            <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                          {:else}
                            <div class="thumb-fallback"></div>
                          {/if}
                          <PlatformIcon platform={v.platform} variant="overlay" />
                        </span>
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
                        <span class="thumb-wrap compact">
                          {#if v.has_thumbnail}
                            <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                          {:else}
                            <div class="thumb-fallback"></div>
                          {/if}
                          <PlatformIcon platform={v.platform} variant="overlay" />
                        </span>
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
              {#if selectedChannels.length}
                <button
                  type="button"
                  class="linkish"
                  onclick={() => {
                    selectedChannels = [];
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
                      class:active={selectedChannels.includes(
                        channelKey(ch.platform, ch.channel_id),
                      )}
                      onclick={() => toggleChannel(ch)}
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
                      <span class="channel-name"
                        >{ch.creator_name ?? ch.channel ?? ch.channel_id}</span
                      >
                      <PlatformIcon platform={ch.platform} variant="inline" />
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
                bind:value={platformFilter}
                onchange={() => void refreshVideos().catch((err) => (error = String(err)))}
              >
                <option value="">All platforms</option>
                <option value="youtube">YouTube</option>
                <option value="twitch">Twitch</option>
              </select>
              <select
                bind:value={contentKindFilter}
                onchange={() => void refreshVideos().catch((err) => (error = String(err)))}
              >
                <option value="">All kinds</option>
                <option value="video">Video</option>
                <option value="vod">VOD</option>
                <option value="clip">Clip</option>
              </select>
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
              <button
                type="button"
                class="ghost"
                class:active={settingsOpen}
                onclick={() => (settingsOpen = !settingsOpen)}
                >Settings</button
              >
            </div>
            {#if settingsOpen}
              <div class="browse-settings">
                <label>
                  Columns
                  <select
                    value={String(browseColumns)}
                    onchange={(e) => updateBrowseColumns(e.currentTarget.value)}
                  >
                    {#each [2, 3, 4, 5, 6] as n}
                      <option value={String(n)}>{n}</option>
                    {/each}
                  </select>
                </label>
                <p class="muted tiny">Saved in a cookie on this browser/device.</p>
              </div>
            {/if}

            {#if loading}<p class="muted">Loading…</p>{/if}
            {#if videos.length === 0 && !loading}
              <p class="muted">No archived videos match. Switch to Download to enqueue.</p>
            {:else}
              <div class="grid" style={`--browse-cols: ${browseColumns}`}>
                {#each videos as v (v.id)}
                  <button type="button" class="card" onclick={() => void openWatch(v)}>
                    <span class="thumb-wrap">
                      {#if v.has_thumbnail}
                        <img src={thumbnailUrl(v.platform, v.platform_video_id)} alt="" />
                      {:else}
                        <div class="thumb-fallback wide"></div>
                      {/if}
                      <PlatformIcon platform={v.platform} variant="overlay" />
                    </span>
                    <strong>{v.title ?? v.platform_video_id}</strong>
                    <small
                      >{v.channel ?? "Unknown channel"} · {kindLabel(v.content_kind)} · {formatUploadDate(
                        v.upload_date,
                      )}</small
                    >
                    {#if v.metadata_incomplete}
                      <span class="badge-warn">Incomplete</span>
                    {/if}
                  </button>
                {/each}
              </div>
              {#if hasMoreVideos}
                <div class="load-more">
                  <button
                    type="button"
                    class="ghost"
                    disabled={loadMoreBusy}
                    onclick={() => void loadMoreVideos()}
                    >{loadMoreBusy ? "Loading…" : "Load more"}</button
                  >
                </div>
              {/if}
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
            placeholder="YouTube or Twitch video / VOD / clip / playlist / channel…"
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
        <label class="switch-row">
          <span class="switch" class:on={watchNewOnEnqueue}>
            <input type="checkbox" bind:checked={watchNewOnEnqueue} />
            <span class="switch-track" aria-hidden="true"><span class="switch-knob"></span></span>
          </span>
          <span class="switch-label"
            >Watch for new uploads / VODs (channel URLs only; turns off after enqueue)</span
          >
        </label>
        {#if enqueueMsg}<p class="ok">{enqueueMsg}</p>{/if}
      </section>

      <section class="creators">
        <h2>Creators</h2>
        <p class="muted tiny">
          Link the same person across YouTube and Twitch for related / up-next across sites. Edit a
          creator to attach existing library channels and pick a thumbnail.
        </p>
        <form
          class="enqueue-form"
          onsubmit={(e) => {
            e.preventDefault();
            void submitCreateCreator();
          }}
        >
          <input type="text" placeholder="Creator display name" bind:value={newCreatorName} required />
          <button type="submit" disabled={creatorBusy}>Create</button>
        </form>
        {#if creators.length}
          <ul class="creator-list">
            {#each creators as c (c.id)}
              <li class="creator-row">
                {#if c.has_thumbnail}
                  <img class="channel-avatar" src={creatorThumbnailUrl(c.id)} alt="" />
                {:else}
                  <div class="channel-avatar thumb-fallback"></div>
                {/if}
                <div class="creator-main">
                  <strong>{c.display_name}</strong>
                  <span class="muted tiny"
                    >{c.channels
                      .map((ch) => `${ch.platform}:${ch.channel ?? ch.channel_id}`)
                      .join(" · ") || "no channels"}</span
                  >
                </div>
                <button type="button" class="linkish" onclick={() => beginEditCreator(c)}
                  >Edit</button
                >
                <button type="button" class="linkish" onclick={() => void removeCreator(c)}
                  >Delete</button
                >
              </li>
            {/each}
          </ul>
        {/if}

        {#if editingCreatorId != null}
          {@const editing = creators.find((c) => c.id === editingCreatorId)}
          {#if editing}
            <div class="creator-edit">
              <h3>Edit {editing.display_name}</h3>
              <form
                class="enqueue-form"
                onsubmit={(e) => {
                  e.preventDefault();
                  void saveCreatorName();
                }}
              >
                <input type="text" bind:value={editCreatorName} required />
                <button type="submit" disabled={creatorBusy}>Save name</button>
                <button type="button" class="ghost" onclick={cancelEditCreator}>Close</button>
              </form>

              <h4>Linked channels</h4>
              {#if editing.channels.length === 0}
                <p class="muted tiny">None yet — attach from the library below.</p>
              {:else}
                <ul class="creator-channel-list">
                  {#each editing.channels as ch (`${ch.platform}:${ch.channel_id}`)}
                    <li>
                      {#if ch.has_thumbnail}
                        <img
                          class="channel-avatar"
                          src={channelThumbnailUrl(ch.platform, ch.channel_id)}
                          alt=""
                        />
                      {:else}
                        <div class="channel-avatar thumb-fallback"></div>
                      {/if}
                      <span
                        >{ch.channel ?? ch.channel_id}
                        <span class="platform-badge">{ch.platform}</span></span
                      >
                      <button
                        type="button"
                        class="linkish"
                        class:on={editing.avatar_platform === ch.platform &&
                          editing.avatar_channel_id === ch.channel_id}
                        disabled={creatorBusy || !ch.has_thumbnail}
                        onclick={() => void setCreatorAvatar(ch.platform, ch.channel_id)}
                        >{editing.avatar_platform === ch.platform &&
                        editing.avatar_channel_id === ch.channel_id
                          ? "Thumbnail"
                          : "Use thumb"}</button
                      >
                      <button
                        type="button"
                        class="linkish"
                        disabled={creatorBusy}
                        onclick={() => void unlinkCreatorChannel(ch.platform, ch.channel_id)}
                        >Unlink</button
                      >
                    </li>
                  {/each}
                </ul>
              {/if}

              <h4>Attach library channel</h4>
              {#if unlinkedChannelsForEdit().length === 0}
                <p class="muted tiny">All library channels are already linked (or none archived).</p>
              {:else}
                <form
                  class="enqueue-form"
                  onsubmit={(e) => {
                    e.preventDefault();
                    void attachChannelFromLibrary();
                  }}
                >
                  <select bind:value={attachChannelKey} required>
                    <option value="">— choose channel —</option>
                    {#each unlinkedChannelsForEdit() as ch (`avail-${ch.platform}:${ch.channel_id}`)}
                      <option value={channelKey(ch.platform, ch.channel_id)}
                        >{ch.platform}: {ch.channel ?? ch.channel_id} ({ch.video_count})</option
                      >
                    {/each}
                  </select>
                  <button type="submit" disabled={creatorBusy || !attachChannelKey}>Attach</button>
                </form>
              {/if}
            </div>
          {/if}
        {/if}
        {#if creatorMsg}<p class="ok">{creatorMsg}</p>{/if}
      </section>

      <section class="download-channels">
        <div class="channels-head">
          <h2>Channels</h2>
          <button
            type="button"
            class="ghost"
            disabled={watchBusy}
            onclick={() => void runCheckWatched()}
            >{watchBusy ? "Checking…" : "Check watched now"}</button
          >
        </div>
        <p class="muted tiny">
          Toggle watch to re-scan uploads/VODs periodically (and via Check now). Playlists and Twitch
          clips are one-shot only. Link channels to creators in the Creators section above.
        </p>
        {#if watchMsg}<p class="ok">{watchMsg}</p>{/if}
        {#if channels.length === 0}
          <p class="muted">No channels in the archive yet.</p>
        {:else}
          <ul class="download-channel-list">
            {#each channels as ch (`dl-${ch.platform}:${ch.channel_id}`)}
              <li>
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
                <span class="platform-badge">{ch.platform}</span>
                {#if ch.creator_name}
                  <span class="muted tiny">{ch.creator_name}</span>
                {/if}
                <span class="muted count">{ch.video_count}</span>
                <label class="switch-row compact" title="Watch for new uploads/VODs">
                  <span class="switch" class:on={ch.watching}>
                    <input
                      type="checkbox"
                      checked={ch.watching}
                      onchange={() => void toggleWatch(ch)}
                    />
                    <span class="switch-track" aria-hidden="true"
                      ><span class="switch-knob"></span></span
                    >
                  </span>
                  <span class="switch-label">Watch</span>
                </label>
                {#if ch.last_checked_at}
                  <small class="muted">checked {ch.last_checked_at}</small>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
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
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {#each jobs as job (job.id)}
                  <tr class:active-row={isActiveJob(job.status)}>
                    <td>
                      <span class="status status-{job.status}">{job.status}</span>
                      {#if job.job_kind}
                        <div class="muted tiny">{job.job_kind}</div>
                      {/if}
                    </td>
                    <td>
                      <div class="job-url" title={job.url}>{job.platform_video_id ?? job.url}</div>
                      {#if job.job_kind === "playlist" || job.job_kind === "channel"}
                        {#if job.error_message}<div class="muted tiny">{job.error_message}</div>{/if}
                      {:else if job.status === "completed" && job.platform && job.platform_video_id}
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
                      {#if job.error_message && job.status !== "cancelled"}
                        <details>
                          <summary class="warn"
                            >{job.error_code}: {job.error_message.split("\n")[0]}</summary
                          >
                          <pre class="error-full">{job.error_message}</pre>
                        </details>
                      {:else if job.status === "cancelled"}
                        <span class="muted tiny">cancelled</span>
                      {/if}
                    </td>
                    <td>
                      {#if isActiveJob(job.status)}
                        <button
                          type="button"
                          class="ghost danger-lite"
                          onclick={() => void cancelOneJob(job, isExpandJob(job))}
                          >{isExpandJob(job) ? "Cancel batch" : "Cancel"}</button
                        >
                      {:else if isExpandJob(job) && jobs.some(
                          (j) => j.parent_job_id === job.id && isActiveJob(j.status),
                        )}
                        <button
                          type="button"
                          class="ghost danger-lite"
                          onclick={() => void cancelOneJob(job, true)}>Cancel children</button
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
                <button
                  type="button"
                  class="danger"
                  onclick={() => {
                    if (selected) void confirmDelete(selected);
                  }}>Delete</button
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
  .brand {
    display: flex;
    align-items: center;
    gap: 0.7rem;
  }
  .brand-block .sub {
    margin-left: calc(3.75rem + 0.7rem);
  }
  .brand-mark {
    width: 3.75rem;
    height: 3.75rem;
    border-radius: 0.55rem;
    object-fit: cover;
    flex-shrink: 0;
    box-shadow: 0 0 0 1px rgba(196, 30, 30, 0.35);
  }
  .gate .brand-mark {
    width: 5.25rem;
    height: 5.25rem;
    border-radius: 0.7rem;
  }
  .gate .brand {
    margin-bottom: 0.75rem;
  }
  .layout {
    max-width: 72rem;
    margin: 0 auto;
    padding: 1.25rem;
  }
  .layout.view-mode {
    max-width: none;
    margin: 0;
  }
  .layout.view-browse {
    padding: 0;
    min-height: 100vh;
  }
  .layout.view-browse > header,
  .layout.view-browse > .error {
    padding: 1.25rem 1.25rem 0;
    margin-bottom: 0.75rem;
  }
  .layout.view-mode:not(.view-browse) {
    padding: 1.25rem;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
    gap: 1rem;
  }
  header .brand h1 {
    line-height: 1.1;
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
  .switch-row {
    display: inline-flex;
    align-items: center;
    gap: 0.65rem;
    margin-top: 0.75rem;
    color: #c5d0db;
    font-size: 0.9rem;
    cursor: pointer;
    width: fit-content;
    max-width: 100%;
  }
  .switch-row.compact {
    margin: 0;
    font-size: 0.85rem;
    flex-shrink: 0;
  }
  .switch-label {
    line-height: 1.3;
  }
  .switch {
    position: relative;
    display: inline-flex;
    flex-shrink: 0;
  }
  .switch input {
    position: absolute;
    opacity: 0;
    width: 0;
    height: 0;
  }
  .switch-track {
    width: 2.4rem;
    height: 1.25rem;
    border-radius: 999px;
    background: #3a4654;
    border: 1px solid #556273;
    display: inline-flex;
    align-items: center;
    padding: 0 0.15rem;
    transition: background 0.15s ease;
  }
  .switch-knob {
    width: 0.9rem;
    height: 0.9rem;
    border-radius: 50%;
    background: #e8eef5;
    transform: translateX(0);
    transition: transform 0.15s ease;
  }
  .switch.on .switch-track {
    background: #2f6fed;
    border-color: #2f6fed;
  }
  .switch.on .switch-knob {
    transform: translateX(1.05rem);
  }
  .danger-lite {
    color: #f0b4b4;
    border-color: #6a3a3a;
  }
  .status-cancelled {
    color: #c9a27a;
  }
  .download-channels {
    margin-bottom: 1rem;
    padding: 1rem;
    border: 1px solid #2a3542;
    border-radius: 8px;
    background: #121820;
  }
  .download-channel-list {
    list-style: none;
    margin: 0.75rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .download-channel-list li {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    flex-wrap: wrap;
    padding: 0.35rem 0;
    border-bottom: 1px solid #1c2530;
  }
  .status-expanding {
    background: #2a3340;
    color: #9ec5ff;
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
  button.danger {
    background: transparent;
    color: #ff8f8f;
    border: 1px solid #5a2a2a;
  }
  button.danger:hover {
    background: #3b1d1d;
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
    grid-template-columns: minmax(15rem, 17.5rem) 1fr;
    gap: 0;
    align-items: start;
    min-height: calc(100vh - 5rem);
  }
  @media (max-width: 900px) {
    .view-home {
      grid-template-columns: 1fr;
      min-height: 0;
    }
    .channels {
      position: static;
      height: auto;
      max-height: 40vh;
      border-right: 0;
      border-bottom: 1px solid #2a3542;
    }
  }
  .channels {
    position: sticky;
    top: 0;
    align-self: start;
    height: 100vh;
    max-height: 100vh;
    overflow: auto;
    border: 0;
    border-right: 1px solid #2a3542;
    border-radius: 0;
    background: #121820;
    padding: 0.85rem 0.75rem 1.25rem;
  }
  .browse {
    padding: 0 1.25rem 1.5rem;
    min-width: 0;
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
  .browse-toolbar .ghost.active {
    border-color: #3d8bfd;
    color: #e7ecf1;
  }
  .browse-settings {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem 1.25rem;
    margin: -0.35rem 0 1rem;
    padding: 0.65rem 0.75rem;
    border: 1px solid #2a3542;
    border-radius: 8px;
    background: #121820;
  }
  .browse-settings label {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: #c5d0db;
    font-size: 0.9rem;
  }
  .browse-settings select {
    flex: 0 0 auto;
    width: auto;
    min-width: 4.5rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(var(--browse-cols, 4), minmax(0, 1fr));
    gap: 0.85rem;
  }
  @media (max-width: 900px) {
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 600px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
  .load-more {
    display: flex;
    justify-content: center;
    margin: 1.25rem 0 0.5rem;
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
  .thumb-wrap {
    position: relative;
    display: block;
    width: 100%;
  }
  .thumb-wrap.compact {
    width: 5.5rem;
    flex-shrink: 0;
  }
  .card .thumb-wrap img,
  .card .thumb-wrap .thumb-fallback.wide,
  .thumb-fallback.wide {
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
    border-radius: 4px;
    background: #0a0e12;
    display: block;
  }
  .thumb-wrap.compact img,
  .thumb-wrap.compact .thumb-fallback {
    width: 5.5rem;
    height: 3.1rem;
    aspect-ratio: auto;
    object-fit: cover;
    border-radius: 4px;
    background: #0a0e12;
    display: block;
  }
  .meta-with-icon {
    display: flex;
    align-items: center;
    gap: 0.45rem;
  }
  .thumb-wrap.compact :global(.platform-icon.overlay) {
    width: 1.25rem;
    height: 1.25rem;
    top: 0.22rem;
    left: 0.22rem;
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
  .platform-badge {
    display: inline-block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.75;
    border: 1px solid color-mix(in srgb, currentColor 35%, transparent);
    border-radius: 3px;
    padding: 0.05rem 0.3rem;
  }

  .creator-tag,
  .attach-row {
    display: block;
    margin-top: 0.25rem;
  }

  .creator-list {
    list-style: none;
    padding: 0;
    margin: 0.75rem 0 0;
    display: grid;
    gap: 0.5rem;
  }

  .creator-list li,
  .creator-channel-list li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 0.75rem;
    align-items: center;
  }

  .creator-main {
    display: grid;
    gap: 0.15rem;
    flex: 1;
    min-width: 10rem;
  }

  .creator-edit {
    margin-top: 1rem;
    padding-top: 0.75rem;
    border-top: 1px solid color-mix(in srgb, currentColor 18%, transparent);
    display: grid;
    gap: 0.5rem;
  }

  .creator-edit h3,
  .creator-edit h4 {
    margin: 0.25rem 0 0;
  }

  .creator-channel-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 0.4rem;
  }

  .creator-channel-list .linkish.on {
    font-weight: 600;
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
    max-width: 22rem;
  }
  .error-cell details summary {
    cursor: pointer;
    list-style: disclosure-closed;
  }
  .error-cell details[open] summary {
    list-style: disclosure-open;
  }
  .error-full {
    margin: 0.35rem 0 0;
    padding: 0.45rem 0.55rem;
    max-height: 12rem;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.75rem;
    background: #151c24;
    border: 1px solid #2a3542;
    border-radius: 4px;
    color: #ffcc66;
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
