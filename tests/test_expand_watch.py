"""Playlist/channel expand enqueue and channel watch checks."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.errors import PermanentDownloadError
from lones_vdl.media import ProbeResult, StreamInfo
from lones_vdl.platform.url_router import classify_url, classify_youtube_url
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


def test_classify_youtube_url() -> None:
    assert classify_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "video"
    assert classify_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxx") == "video"
    assert classify_youtube_url("https://www.youtube.com/playlist?list=PLxx") == "playlist"
    assert classify_youtube_url("https://www.youtube.com/@SomeHandle") == "channel"
    assert classify_youtube_url("https://www.youtube.com/channel/UCabcdef") == "channel"


def test_classify_twitch_urls() -> None:
    vod = classify_url("https://www.twitch.tv/videos/123456789")
    assert vod.platform == "twitch"
    assert vod.kind == "video"
    assert vod.content_kind == "vod"
    assert vod.hint_id == "123456789"

    clip = classify_url("https://clips.twitch.tv/FunnyClip-abc")
    assert clip.platform == "twitch"
    assert clip.content_kind == "clip"
    assert clip.hint_id == "FunnyClip-abc"

    channel = classify_url("https://www.twitch.tv/some_streamer")
    assert channel.kind == "channel"
    assert channel.hint_id == "some_streamer"

    try:
        classify_url("https://www.twitch.tv/some_streamer/clips")
        raise AssertionError("expected clips listing to fail")
    except PermanentDownloadError as exc:
        assert exc.code == "unsupported_url"


def _wait(client: TestClient, job_id: str, headers: dict[str, str]) -> dict:
    for _ in range(80):
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"completed", "failed", "duplicate"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_playlist_expand_skips_archived(tmp_env: Settings) -> None:
    entries = [
        PlaylistEntry(
            video_id="vidAAAAAAA",
            url="https://www.youtube.com/watch?v=vidAAAAAAA",
            title="Alpha",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        ),
        PlaylistEntry(
            video_id="vidBBBBBBB",
            url="https://www.youtube.com/watch?v=vidBBBBBBB",
            title="Beta",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        ),
    ]
    # Archive first video alone
    adapter_one = FakeYtdlpAdapter(video_id="vidAAAAAAA", title="Alpha")
    app = create_app(tmp_env, adapter=adapter_one, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=vidAAAAAAA"},
            headers=headers,
        )
        assert r.status_code == 202
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"

    # Per-video downloads need matching video_id on the adapter used by children.
    class MultiAdapter(FakeYtdlpAdapter):
        def __init__(self) -> None:
            super().__init__(playlist_entries=entries, list_kind="playlist")

        def extract_info(self, url: str):  # noqa: ANN001
            vid = "vidBBBBBBB" if "vidBBBBBBB" in url else "vidAAAAAAA"
            self.video_id = vid
            self.title = "Beta" if vid == "vidBBBBBBB" else "Alpha"
            return super().extract_info(url)

        def download(self, url: str, *, output_dir, quality_preference: str):  # noqa: ANN001
            vid = "vidBBBBBBB" if "vidBBBBBBB" in url else "vidAAAAAAA"
            self.video_id = vid
            self.title = "Beta" if vid == "vidBBBBBBB" else "Alpha"
            return super().download(
                url, output_dir=output_dir, quality_preference=quality_preference
            )

    app = create_app(tmp_env, adapter=MultiAdapter(), media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/playlist?list=PLtest"},
            headers=headers,
        )
        assert r.status_code == 202
        parent = _wait(client, r.json()["id"], headers)
        assert parent["status"] == "completed"
        assert parent["job_kind"] == "playlist"
        assert "enqueued 1" in (parent["error_message"] or "")
        assert "skipped 1" in (parent["error_message"] or "")

        # Allow child job to finish
        for _ in range(80):
            jobs = client.get("/api/jobs?limit=20", headers=headers).json()
            videos = client.get("/api/videos", headers=headers).json()
            if len(videos) >= 2 and all(
                j["status"] in {"completed", "failed", "duplicate", "expanding"}
                or j["job_kind"] in {"playlist", "channel"}
                for j in jobs
                if j["job_kind"] == "video"
            ):
                if all(
                    j["status"] in {"completed", "failed", "duplicate"}
                    for j in jobs
                    if j.get("job_kind") == "video"
                ):
                    break
            time.sleep(0.05)
        videos = client.get("/api/videos", headers=headers).json()
        ids = {v["platform_video_id"] for v in videos}
        assert ids == {"vidAAAAAAA", "vidBBBBBBB"}


def test_channel_watch_check_enqueues_new(tmp_env: Settings) -> None:
    entries_v1 = [
        PlaylistEntry(
            video_id="watchVid001",
            url="https://www.youtube.com/watch?v=watchVid001",
            title="One",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        )
    ]
    entries_v2 = [
        *entries_v1,
        PlaylistEntry(
            video_id="watchVid002",
            url="https://www.youtube.com/watch?v=watchVid002",
            title="Two",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        ),
    ]

    class ChannelAdapter(FakeYtdlpAdapter):
        def __init__(self) -> None:
            super().__init__(list_kind="channel", playlist_entries=entries_v1)
            self.phase = 1

        def list_entries(self, url: str):  # noqa: ANN001
            self.playlist_entries = entries_v1 if self.phase == 1 else entries_v2
            return super().list_entries(url)

        def extract_info(self, url: str):  # noqa: ANN001
            self.video_id = "watchVid002" if "watchVid002" in url else "watchVid001"
            self.title = "Two" if self.video_id == "watchVid002" else "One"
            return super().extract_info(url)

        def download(self, url: str, *, output_dir, quality_preference: str):  # noqa: ANN001
            self.video_id = "watchVid002" if "watchVid002" in url else "watchVid001"
            self.title = "Two" if self.video_id == "watchVid002" else "One"
            return super().download(
                url, output_dir=output_dir, quality_preference=quality_preference
            )

    adapter = ChannelAdapter()
    app = create_app(tmp_env, adapter=adapter, media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={
                "url": "https://www.youtube.com/@TestChannel",
                "watch_new": True,
            },
            headers=headers,
        )
        assert r.status_code == 202
        parent = _wait(client, r.json()["id"], headers)
        assert parent["status"] == "completed"
        assert parent["job_kind"] == "channel"

        for _ in range(80):
            videos = client.get("/api/videos", headers=headers).json()
            if any(v["platform_video_id"] == "watchVid001" for v in videos):
                break
            time.sleep(0.05)

        channels = client.get("/api/channels", headers=headers).json()
        assert channels
        assert channels[0]["watching"] is True

        adapter.phase = 2
        checked = client.post("/api/channels/check-watched", headers=headers)
        assert checked.status_code == 200
        body = checked.json()
        assert body[0]["enqueued"] == 1

        for _ in range(80):
            videos = client.get("/api/videos", headers=headers).json()
            ids = {v["platform_video_id"] for v in videos}
            if ids >= {"watchVid001", "watchVid002"}:
                break
            time.sleep(0.05)
        videos = client.get("/api/videos", headers=headers).json()
        ids = {v["platform_video_id"] for v in videos}
        assert ids >= {"watchVid001", "watchVid002"}
