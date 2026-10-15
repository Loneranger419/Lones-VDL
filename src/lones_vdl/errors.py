"""Domain errors for download and archive operations."""

from __future__ import annotations


class LonesVdlError(Exception):
    """Base error with a stable machine-readable code."""

    code: str = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class TransientDownloadError(LonesVdlError):
    """Temporary failure (rate limit, network); may retry."""

    code = "transient"


class PermanentDownloadError(LonesVdlError):
    """Unavailable, private, or otherwise not downloadable."""

    code = "unavailable"


class DuplicateArchiveError(LonesVdlError):
    """Video is already archived."""

    code = "duplicate"

    def __init__(self, message: str, *, platform_video_id: str) -> None:
        super().__init__(message, code="duplicate")
        self.platform_video_id = platform_video_id


class AuthConfigError(LonesVdlError):
    """Cookies missing or rejected by the provider."""

    code = "auth_required"
