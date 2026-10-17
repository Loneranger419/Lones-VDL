"""Creator hub linking and cross-platform related videos."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.media import ProbeResult, StreamInfo


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


def test_creator_hub_related_cross_platform(tmp_env: Settings) -> None:
    headers = {"Authorization": "Bearer test-token"}

    yt = FakeYtdlpAdapter(
        video_id="ytVideoAAAA",
        title="YT Video",
        channel="Creator YT",
        channel_id="UC_creator",
    )
    app = create_app(tmp_env, adapter=yt, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=ytVideoAAAA"},
            headers=headers,
        )
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"

    tw = FakeYtdlpAdapter(
        video_id="555555555",
        title="Twitch VOD",
        platform="twitch",
        channel="Creator TW",
        channel_id="creator_tw",
    )
    app = create_app(tmp_env, adapter=tw, media_processor=FakeMediaProcessor())
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.twitch.tv/videos/555555555"},
            headers=headers,
        )
        assert _wait(client, r.json()["id"], headers)["status"] == "completed"

        # Before linking: related stays same-channel only (none for YT alone)
        related = client.get(
            "/api/videos/youtube/ytVideoAAAA/related",
            headers=headers,
        ).json()
        assert related == []

        created = client.post(
            "/api/creators",
            json={"display_name": "The Creator"},
            headers=headers,
        )
        assert created.status_code == 201
        creator_id = created.json()["id"]

        attach_yt = client.put(
            f"/api/creators/{creator_id}/channels",
            json={"platform": "youtube", "channel_id": "UC_creator"},
            headers=headers,
        )
        assert attach_yt.status_code == 200
        attach_tw = client.put(
            f"/api/creators/{creator_id}/channels",
            json={"platform": "twitch", "channel_id": "creator_tw"},
            headers=headers,
        )
        assert attach_tw.status_code == 200
        assert len(attach_tw.json()["channels"]) == 2

        channels = client.get("/api/channels", headers=headers).json()
        by_key = {(c["platform"], c["channel_id"]): c for c in channels}
        assert by_key[("youtube", "UC_creator")]["creator_id"] == creator_id
        assert by_key[("twitch", "creator_tw")]["creator_name"] == "The Creator"

        related = client.get(
            "/api/videos/youtube/ytVideoAAAA/related",
            headers=headers,
        ).json()
        assert len(related) == 1
        assert related[0]["platform"] == "twitch"
        assert related[0]["platform_video_id"] == "555555555"

        renamed = client.patch(
            f"/api/creators/{creator_id}",
            json={"display_name": "Renamed Creator"},
            headers=headers,
        )
        assert renamed.status_code == 200
        assert renamed.json()["display_name"] == "Renamed Creator"

        avatar = client.patch(
            f"/api/creators/{creator_id}",
            json={"avatar_platform": "twitch", "avatar_channel_id": "creator_tw"},
            headers=headers,
        )
        assert avatar.status_code == 200
        assert avatar.json()["avatar_platform"] == "twitch"
        assert avatar.json()["avatar_channel_id"] == "creator_tw"
        assert any(
            ch["platform"] == "twitch" and ch["channel_id"] == "creator_tw"
            for ch in avatar.json()["channels"]
        )

        bad_avatar = client.patch(
            f"/api/creators/{creator_id}",
            json={"avatar_platform": "youtube", "avatar_channel_id": "UC_not_linked"},
            headers=headers,
        )
        assert bad_avatar.status_code == 400

        detached = client.delete(
            f"/api/creators/{creator_id}/channels/twitch/creator_tw",
            headers=headers,
        )
        assert detached.status_code == 200
        assert len(detached.json()["channels"]) == 1

        related = client.get(
            "/api/videos/youtube/ytVideoAAAA/related",
            headers=headers,
        ).json()
        assert related == []
