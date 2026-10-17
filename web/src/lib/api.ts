export type VideoSummary = {
  id: number;
  platform: string;
  platform_video_id: string;
  title: string | null;
  url: string;
  media_relpath: string;
  metadata_relpath: string;
  checksum_sha256: string | null;
  archived_at: string;
  has_thumbnail: boolean;
  channel: string | null;
  channel_id: string | null;
  upload_date: string | null;
  metadata_incomplete: boolean;
  metadata_gaps: string[];
  content_kind: string;
};

export type PlaybackInfo = {
  mode: "original" | "remux" | "unavailable";
  container: string | null;
  reason: string;
  video_codec: string | null;
  audio_codec: string | null;
  play_path: string | null;
  original_path: string | null;
};

export type VideoDetail = VideoSummary & {
  source_metadata: Record<string, unknown> | null;
  archive_metadata: Record<string, unknown> | null;
  playback: PlaybackInfo | null;
};

export type Channel = {
  platform: string;
  channel_id: string;
  channel: string | null;
  video_count: number;
  favorited: boolean;
  has_thumbnail: boolean;
  watching: boolean;
  last_checked_at: string | null;
  channel_url: string | null;
  creator_id: number | null;
  creator_name: string | null;
};

export type CreatorChannelRef = {
  platform: string;
  channel_id: string;
  channel: string | null;
  has_thumbnail: boolean;
};

export type Creator = {
  id: number;
  display_name: string;
  notes: string | null;
  created_at: string;
  channels: CreatorChannelRef[];
  avatar_platform: string | null;
  avatar_channel_id: string | null;
  has_thumbnail: boolean;
};

export type Job = {
  id: string;
  url: string;
  platform: string | null;
  platform_video_id: string | null;
  quality_preference: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  video_id: number | null;
  created_at: string;
  updated_at: string;
  attempts: number;
  watch_new?: boolean;
  job_kind?: string | null;
};

export type WatchCheckItem = {
  platform: string;
  channel_id: string;
  status: string;
  detail: string;
  enqueued: number;
  skipped: number;
};

export type PublicConfig = {
  default_quality: string;
  archive_root: string;
  download_concurrency: number;
  download_max_attempts: number;
  cookies_configured: boolean;
  cookie_platforms: string[];
  cookie_count: number | null;
  quality_presets: string[];
};

export type CookieFilterResult = {
  platforms: string[];
  domains_allowed: string[];
  cookies_before: number;
  cookies_after: number;
  cookies_removed: number;
  lines_before: number;
  lines_after: number;
  backup_path: string | null;
};

export type RefreshResult = {
  platform: string;
  platform_video_id: string;
  status: string;
  detail: string;
  gaps: string[];
};

export type ListVideosParams = {
  q?: string;
  /** `platform:channel_id` keys */
  channels?: string[];
  platforms?: string[];
  contentKinds?: string[];
  sort?: "upload_date" | "title" | "archived_at";
  order?: "asc" | "desc";
  incompleteOnly?: boolean;
  limit?: number;
};

export function channelKey(platform: string, channelId: string): string {
  return `${platform}:${channelId}`;
}

const TOKEN_KEY = "lones_vdl_api_token";

export function getToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    throw new Error("Unauthorized — check your API token");
  }
  return res;
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as {
      detail?: string | { detail?: string; code?: string; platform_video_id?: string };
    };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && typeof body.detail === "object") {
      const d = body.detail;
      if (d.detail) {
        return d.platform_video_id ? `${d.detail} (${d.platform_video_id})` : d.detail;
      }
    }
  } catch {
    /* ignore */
  }
  return `${fallback} (${res.status})`;
}

export async function getConfig(): Promise<PublicConfig> {
  const res = await apiFetch("/api/config");
  if (!res.ok) throw new Error(await readError(res, "Failed to load config"));
  return res.json();
}

export async function filterCookies(): Promise<CookieFilterResult> {
  const res = await apiFetch("/api/cookies/filter", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res, "Failed to filter cookies"));
  return res.json();
}

export async function listVideos(params: ListVideosParams = {}): Promise<VideoSummary[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  if (params.incompleteOnly) qs.set("incomplete_only", "true");
  if (params.limit != null) qs.set("limit", String(params.limit));
  for (const key of params.channels ?? []) {
    qs.append("channel", key);
  }
  for (const platform of params.platforms ?? []) {
    qs.append("platform", platform);
  }
  for (const kind of params.contentKinds ?? []) {
    qs.append("content_kind", kind);
  }
  const query = qs.toString();
  const res = await apiFetch(`/api/videos${query ? `?${query}` : ""}`);
  if (!res.ok) throw new Error(await readError(res, "Failed to list videos"));
  return res.json();
}

export async function listCreators(): Promise<Creator[]> {
  const res = await apiFetch("/api/creators");
  if (!res.ok) throw new Error(await readError(res, "Failed to list creators"));
  return res.json();
}

export async function createCreator(displayName: string, notes?: string | null): Promise<Creator> {
  const res = await apiFetch("/api/creators", {
    method: "POST",
    body: JSON.stringify({ display_name: displayName, notes: notes ?? null }),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to create creator"));
  return res.json();
}

export async function updateCreator(
  creatorId: number,
  body: {
    display_name?: string;
    notes?: string | null;
    avatar_platform?: string | null;
    avatar_channel_id?: string | null;
    clear_avatar?: boolean;
  },
): Promise<Creator> {
  const res = await apiFetch(`/api/creators/${creatorId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to update creator"));
  return res.json();
}

export async function deleteCreator(creatorId: number): Promise<void> {
  const res = await apiFetch(`/api/creators/${creatorId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res, "Failed to delete creator"));
}

export async function attachCreatorChannel(
  creatorId: number,
  platform: string,
  channelId: string,
): Promise<Creator> {
  const res = await apiFetch(`/api/creators/${creatorId}/channels`, {
    method: "PUT",
    body: JSON.stringify({ platform, channel_id: channelId }),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to attach channel"));
  return res.json();
}

export async function detachCreatorChannel(
  creatorId: number,
  platform: string,
  channelId: string,
): Promise<Creator> {
  const res = await apiFetch(
    `/api/creators/${creatorId}/channels/${encodeURIComponent(platform)}/${encodeURIComponent(channelId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to detach channel"));
  return res.json();
}

export async function listChannels(platform?: string): Promise<Channel[]> {
  const qs = platform ? `?platform=${encodeURIComponent(platform)}` : "";
  const res = await apiFetch(`/api/channels${qs}`);
  if (!res.ok) throw new Error(await readError(res, "Failed to list channels"));
  return res.json();
}

export async function setChannelFavorite(
  platform: string,
  channelId: string,
  favorited: boolean,
  channel?: string | null,
): Promise<Channel> {
  const res = await apiFetch(
    `/api/channels/${encodeURIComponent(platform)}/${encodeURIComponent(channelId)}/favorite`,
    {
      method: "PUT",
      body: JSON.stringify({ favorited, channel: channel ?? null }),
    },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to update favorite"));
  return res.json();
}

export async function setChannelWatch(
  platform: string,
  channelId: string,
  watching: boolean,
  opts?: { channel?: string | null; channelUrl?: string | null },
): Promise<Channel> {
  const res = await apiFetch(
    `/api/channels/${encodeURIComponent(platform)}/${encodeURIComponent(channelId)}/watch`,
    {
      method: "PUT",
      body: JSON.stringify({
        watching,
        channel: opts?.channel ?? null,
        channel_url: opts?.channelUrl ?? null,
      }),
    },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to update watch"));
  return res.json();
}

export async function checkWatchedChannels(): Promise<WatchCheckItem[]> {
  const res = await apiFetch("/api/channels/check-watched", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res, "Failed to check watched channels"));
  return res.json();
}

export async function getVideo(platform: string, id: string): Promise<VideoDetail> {
  const res = await apiFetch(
    `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}`,
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to load video"));
  return res.json();
}

export async function deleteVideo(platform: string, id: string): Promise<void> {
  const res = await apiFetch(
    `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to delete video"));
}

export async function listRelated(
  platform: string,
  id: string,
  limit = 12,
): Promise<VideoSummary[]> {
  const res = await apiFetch(
    `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/related?limit=${limit}`,
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to load related"));
  return res.json();
}

export async function refreshVideoMetadata(
  platform: string,
  id: string,
): Promise<RefreshResult> {
  const res = await apiFetch(
    `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/refresh`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to refresh metadata"));
  return res.json();
}

export async function refreshIncompleteMetadata(limit = 50): Promise<RefreshResult[]> {
  const res = await apiFetch(`/api/metadata/refresh-incomplete?limit=${limit}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to refresh incomplete metadata"));
  return res.json();
}

export async function listJobs(): Promise<Job[]> {
  const res = await apiFetch("/api/jobs");
  if (!res.ok) throw new Error(await readError(res, "Failed to list jobs"));
  return res.json();
}

export async function enqueueJob(
  url: string,
  qualityPreference: string,
  watchNew = false,
): Promise<Job> {
  const res = await apiFetch("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      url,
      quality_preference: qualityPreference,
      watch_new: watchNew,
    }),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to enqueue"));
  return res.json();
}

export type VerifyItem = {
  platform: string;
  platform_video_id: string;
  status: string;
  detail: string;
  expected_sha256: string | null;
  actual_sha256: string | null;
};

export type VerifyReport = {
  checked: number;
  ok: number;
  issue_count: number;
  issues: VerifyItem[];
};

export type RescanReport = {
  scanned: number;
  imported: number;
  updated: number;
  skipped: number;
  errors: number;
  missing_from_disk: string[];
  items: { platform: string; platform_video_id: string; action: string; detail: string }[];
};

export async function verifyIntegrity(): Promise<VerifyReport> {
  const res = await apiFetch("/api/integrity/verify", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res, "Verify failed"));
  return res.json();
}

export async function rescanArchive(): Promise<RescanReport> {
  const res = await apiFetch("/api/integrity/rescan", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res, "Rescan failed"));
  return res.json();
}

export function mediaUrl(
  platform: string,
  id: string,
  variant: "play" | "original" = "play",
): string {
  const token = encodeURIComponent(getToken());
  return `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/media?variant=${variant}&token=${token}`;
}

export function thumbnailUrl(platform: string, id: string): string {
  const token = encodeURIComponent(getToken());
  return `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/thumbnail?token=${token}`;
}

export function channelThumbnailUrl(platform: string, channelId: string): string {
  const token = encodeURIComponent(getToken());
  return `/api/channels/${encodeURIComponent(platform)}/${encodeURIComponent(channelId)}/thumbnail?token=${token}`;
}

export function creatorThumbnailUrl(creatorId: number): string {
  const token = encodeURIComponent(getToken());
  return `/api/creators/${creatorId}/thumbnail?token=${token}`;
}

export function isActiveJob(status: string): boolean {
  return status === "queued" || status === "downloading" || status === "expanding";
}

export function formatUploadDate(value: string | null | undefined): string {
  if (!value || !/^\d{8}$/.test(value)) return "Unknown date";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}
