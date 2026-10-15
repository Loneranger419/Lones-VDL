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
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    throw new Error("Unauthorized — check your API token");
  }
  return res;
}

export async function listVideos(q?: string): Promise<VideoSummary[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  const qs = params.toString();
  const res = await apiFetch(`/api/videos${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Failed to list videos (${res.status})`);
  return res.json();
}

export async function getVideo(platform: string, id: string): Promise<VideoDetail> {
  const res = await apiFetch(`/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to load video (${res.status})`);
  return res.json();
}

export function mediaUrl(platform: string, id: string, variant: "play" | "original" = "play"): string {
  const token = encodeURIComponent(getToken());
  return `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/media?variant=${variant}&token=${token}`;
}

export function thumbnailUrl(platform: string, id: string): string {
  const token = encodeURIComponent(getToken());
  return `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}/thumbnail?token=${token}`;
}
