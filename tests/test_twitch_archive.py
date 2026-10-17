"""Twitch VOD/clip archive, expand/watch, and filters."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.media import ProbeResult, StreamInfo
from lones_vdl.platform.ytdlp import PlaylistEntry


class FakeMediaProcessor:
    def probe(self, path):  # noqa: ANN001
        return ProbeResult(
            format_name="matroska,webm",
            streams=[StreamInfo("video", "av1"), StreamInfo("audio", "opus")],
        )

    def remux_copy(self, source, destination) -> None:  # noqa: ANN001
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"webm-bytes")


def _wait(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(80):
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"completed", "failed", "duplicate"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_twitch_vod_and_clip_archive_and_filters(tmp_env: Settings) -> None:
    headers = {"Authorization": "Bearer test-token"}

    vod_adapter = FakeYtdlpAdapter(
        video_id="987654321",
        title="Twitch VOD",
        platform="twitch",
        channel="CoolStreamer",
        channel_id="coolstreamer",
    )
    app = create_app(tmp_env, adapter=vod_adapter, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.twitch.tv/videos/987654321"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"
        assert r.json()["platform"] == "twitch"

    clip_adapter = FakeYtdlpAdapter(
        video_id="FunnyClipSlug",
        title="Twitch Clip",
        platform="twitch",
        channel="CoolStreamer",
        channel_id="coolstreamer",
        extractor="TwitchClips",
    )
    app = create_app(tmp_env, adapter=clip_adapter, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://clips.twitch.tv/FunnyClipSlug"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"

        all_videos = client.get("/api/videos", headers=headers).json()
        assert len(all_videos) == 2
        kinds = {v["platform_video_id"]: v["content_kind"] for v in all_videos}
        assert kinds["987654321"] == "vod"
        assert kinds["FunnyClipSlug"] == "clip"

        vods = client.get("/api/videos?platform=twitch&content_kind=vod", headers=headers).json()
        assert len(vods) == 1
        assert vods[0]["platform_video_id"] == "987654321"

        clips = client.get(
            "/api/videos?channel=twitch:coolstreamer&content_kind=clip",
            headers=headers,
        ).json()
        assert len(clips) == 1
        assert clips[0]["content_kind"] == "clip"

        assert (tmp_env.archive_root / "twitch" / "987654321" / "media.mkv").is_file()


def test_twitch_channel_expand_and_watch(tmp_env: Settings) -> None:
    entries_v1 = [
        PlaylistEntry(
            video_id="111111111",
            url="https://www.twitch.tv/videos/111111111",
            title="VOD One",
            channel="CoolStreamer",
            channel_id="coolstreamer",
            channel_url="https://www.twitch.tv/coolstreamer",
        )
    ]
    entries_v2 = [
        *entries_v1,
        PlaylistEntry(
            video_id="222222222",
            url="https://www.twitch.tv/videos/222222222",
            title="VOD Two",
            channel="CoolStreamer",
            channel_id="coolstreamer",
            channel_url="https://www.twitch.tv/coolstreamer",
        ),
    ]

    class TwitchAdapter(FakeYtdlpAdapter):
        def __init__(self) -> None:
            super().__init__(
                list_kind="channel",
                playlist_entries=entries_v1,
                platform="twitch",
                channel="CoolStreamer",
                channel_id="coolstreamer",
            )
            self.phase = 1

        def list_entries(self, url: str):  # noqa: ANN001
            self.playlist_entries = entries_v1 if self.phase == 1 else entries_v2
            return super().list_entries(url)

        def extract_info(self, url: str):  # noqa: ANN001
            self.video_id = "222222222" if "222222222" in url else "111111111"
            self.title = "VOD Two" if self.video_id == "222222222" else "VOD One"
            return super().extract_info(url)

        def download(self, url: str, *, output_dir, quality_preference: str):  # noqa: ANN001
            self.video_id = "222222222" if "222222222" in url else "111111111"
            self.title = "VOD Two" if self.video_id == "222222222" else "VOD One"
            return super().download(
                url, output_dir=output_dir, quality_preference=quality_preference
            )

    adapter = TwitchAdapter()
    app = create_app(tmp_env, adapter=adapter, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={
                "url": "https://www.twitch.tv/coolstreamer",
                "watch_new": True,
            },
            headers=headers,
        )
        assert r.status_code == 202
        parent = _wait(client, r.json()["id"], headers)
        assert parent["status"] == "completed"
        assert parent["job_kind"] == "channel"
        assert parent["platform"] == "twitch"

        for _ in range(80):
            videos = client.get("/api/videos", headers=headers).json()
            if any(v["platform_video_id"] == "111111111" for v in videos):
                break
            time.sleep(0.05)

        channels = client.get("/api/channels?platform=twitch", headers=headers).json()
        assert channels
        assert channels[0]["watching"] is True

        adapter.phase = 2
        checked = client.post("/api/channels/check-watched", headers=headers)
        assert checked.status_code == 200
        assert checked.json()[0]["enqueued"] == 1

        for _ in range(80):
            videos = client.get("/api/videos", headers=headers).json()
            ids = {v["platform_video_id"] for v in videos}
            if ids >= {"111111111", "222222222"}:
                break
            time.sleep(0.05)
        videos = client.get("/api/videos?content_kind=vod", headers=headers).json()
        ids = {v["platform_video_id"] for v in videos}
        assert ids >= {"111111111", "222222222"}
        assert all(v["content_kind"] == "vod" for v in videos)
