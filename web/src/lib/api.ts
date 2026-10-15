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
  attempts: number;
  created_at: string;
  updated_at: string;
};

export type PublicConfig = {
  default_quality: string;
  archive_root: string;
  download_concurrency: number;
  download_max_attempts: number;
  cookies_configured: boolean;
  quality_presets: string[];
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

export async function listVideos(q?: string): Promise<VideoSummary[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  const qs = params.toString();
  const res = await apiFetch(`/api/videos${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(await readError(res, "Failed to list videos"));
  return res.json();
}

export async function getVideo(platform: string, id: string): Promise<VideoDetail> {
  const res = await apiFetch(
    `/api/videos/${encodeURIComponent(platform)}/${encodeURIComponent(id)}`,
  );
  if (!res.ok) throw new Error(await readError(res, "Failed to load video"));
  return res.json();
}

export async function listJobs(): Promise<Job[]> {
  const res = await apiFetch("/api/jobs");
  if (!res.ok) throw new Error(await readError(res, "Failed to list jobs"));
  return res.json();
}

export async function enqueueJob(url: string, qualityPreference: string): Promise<Job> {
  const res = await apiFetch("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ url, quality_preference: qualityPreference }),
  });
  if (!res.ok) throw new Error(await readError(res, "Failed to enqueue"));
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

export function isActiveJob(status: string): boolean {
  return status === "queued" || status === "downloading";
}
