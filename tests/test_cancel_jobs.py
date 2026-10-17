"""Cancel individual jobs and expand batches."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from tests.conftest import FakeYtdlpAdapter

from lones_vdl.app import create_app
from lones_vdl.config import Settings
from lones_vdl.db import Database
from lones_vdl.download.service import ArchiveService
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


def test_cancel_queued_job(tmp_env: Settings) -> None:
    db = Database(tmp_env.database_path)
    adapter = FakeYtdlpAdapter()
    svc = ArchiveService(
        db=db,
        archive_root=tmp_env.archive_root,
        adapter=adapter,
        max_workers=1,
        max_attempts=2,
    )
    try:
        job = svc.enqueue(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            auto_start=False,
        )
        cancelled = svc.cancel_job(job.id)
        assert len(cancelled) == 1
        assert cancelled[0].status == "cancelled"
        assert svc.process_next_queued() is None
    finally:
        svc.close()
        db.close()


def test_cancel_expand_batch_via_api(tmp_env: Settings) -> None:
    entries = [
        PlaylistEntry(
            video_id="cancelVid01",
            url="https://www.youtube.com/watch?v=cancelVid01",
            title="One",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        ),
        PlaylistEntry(
            video_id="cancelVid02",
            url="https://www.youtube.com/watch?v=cancelVid02",
            title="Two",
            channel="Test Channel",
            channel_id="UC_test_channel",
            channel_url="https://www.youtube.com/channel/UC_test_channel",
        ),
    ]

    class SlowChildAdapter(FakeYtdlpAdapter):
        def __init__(self) -> None:
            super().__init__(playlist_entries=entries, list_kind="playlist")

        def extract_info(self, url: str):  # noqa: ANN001
            time.sleep(0.2)
            self.video_id = "cancelVid02" if "cancelVid02" in url else "cancelVid01"
            return super().extract_info(url)

        def download(self, url: str, *, output_dir, quality_preference: str):  # noqa: ANN001
            time.sleep(0.2)
            self.video_id = "cancelVid02" if "cancelVid02" in url else "cancelVid01"
            return super().download(
                url, output_dir=output_dir, quality_preference=quality_preference
            )

    app = create_app(tmp_env, adapter=SlowChildAdapter(), media_processor=FakeMediaProcessor())
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        r = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/playlist?list=PLcancel"},
            headers=headers,
        )
        assert r.status_code == 202
        parent_id = r.json()["id"]

        # Wait until parent expands and children exist
        children: list[dict] = []
        for _ in range(80):
            jobs = client.get("/api/jobs?limit=20", headers=headers).json()
            parent = next(j for j in jobs if j["id"] == parent_id)
            children = [j for j in jobs if j.get("parent_job_id") == parent_id]
            if parent["status"] == "completed" and children:
                break
            time.sleep(0.05)
        assert children, "expected fan-out child jobs"

        active_children = [j for j in children if j["status"] in {"queued", "downloading"}]
        assert active_children

        cancelled = client.post(
            f"/api/jobs/{parent_id}/cancel",
            headers=headers,
        )
        assert cancelled.status_code == 200
        body = cancelled.json()
        assert body["count"] >= 1
        assert all(j["status"] == "cancelled" for j in body["cancelled"])

        jobs = client.get("/api/jobs?limit=20", headers=headers).json()
        still_active = [
            j
            for j in jobs
            if j.get("parent_job_id") == parent_id
            and j["status"] in {"queued", "downloading", "expanding"}
        ]
        assert still_active == []
