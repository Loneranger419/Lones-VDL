"""Map yt-dlp output to actionable error kinds. String matching is unavoidable: yt-dlp's CLI
reports failures only as text. Keep needles lowercase and specific."""

from __future__ import annotations

from enum import StrEnum


class ErrorKind(StrEnum):
    COOKIES_MISSING = "cookies_missing"  # YouTube wants a signed-in session; no cookies set
    COOKIES_INVALID = "cookies_invalid"  # cookies rotated/expired
    AUTH_REQUIRED = "auth_required"  # signed in, still refused (age/members/bot check)
    UNAVAILABLE = "unavailable"  # private, removed, region-locked, not yet live
    RATE_LIMITED = "rate_limited"
    FORBIDDEN = "forbidden"  # HTTP 403 on media; often missing PO token
    NETWORK = "network"
    FORMAT_UNAVAILABLE = "format_unavailable"
    YTDLP_MISSING = "ytdlp_missing"
    CONFLICT = "conflict"  # already archived / exists on disk
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


RETRYABLE = frozenset(
    {ErrorKind.RATE_LIMITED, ErrorKind.FORBIDDEN, ErrorKind.NETWORK, ErrorKind.UNKNOWN}
)

MESSAGES: dict[ErrorKind, str] = {
    ErrorKind.COOKIES_MISSING: (
        "YouTube requires a signed-in session. Import a cookies.txt exported from a private "
        "browser window."
    ),
    ErrorKind.COOKIES_INVALID: (
        "Your YouTube cookies are no longer valid (rotated or expired). Export fresh cookies "
        "from a private browser window, then close that window without logging out."
    ),
    ErrorKind.AUTH_REQUIRED: (
        "YouTube refused this video even with cookies. The account may need age verification "
        "or channel membership."
    ),
    ErrorKind.UNAVAILABLE: "The video is unavailable (private, removed, or region-locked).",
    ErrorKind.RATE_LIMITED: "YouTube is rate-limiting requests. Will retry later.",
    ErrorKind.FORBIDDEN: (
        "YouTube returned HTTP 403 for the media. If this keeps happening, enable the PO-token "
        "provider."
    ),
    ErrorKind.NETWORK: "Network error while talking to YouTube. Will retry.",
    ErrorKind.FORMAT_UNAVAILABLE: "The requested quality is not available for this video.",
    ErrorKind.YTDLP_MISSING: "yt-dlp is not installed yet.",
    ErrorKind.CONFLICT: "Already archived.",
    ErrorKind.UNSUPPORTED: "Unsupported URL.",
    ErrorKind.UNKNOWN: "yt-dlp failed. See the job log for details.",
}

_COOKIES_INVALID = (
    "cookies are no longer valid",
    "cookies have likely been rotated",
)
_AUTH = (
    "sign in to confirm",
    "not a bot",
    "login required",
    "confirm your age",
    "age-restricted",
    "members-only",
    "join this channel",
    "use --cookies",
)
_UNAVAILABLE = (
    "private video",
    "video unavailable",
    "this video has been removed",
    "this video is no longer available",
    "account associated with this video has been terminated",
    "not available in your country",
    "who has blocked it on copyright",
    "this live event will begin",
    "premieres in",
)
_RATE = ("http error 429", "too many requests", "rate-limit", "rate limit")
_FORBIDDEN = ("http error 403",)
_NETWORK = (
    "timed out",
    "connection reset",
    "connection refused",
    "temporary failure in name resolution",
    "name or service not known",
    "network is unreachable",
    "remote end closed connection",
    "unable to download webpage",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
)
_FORMAT = ("requested format is not available",)


def error_lines(output: str, limit: int = 20) -> list[str]:
    lines = [ln.strip() for ln in output.splitlines()]
    return [ln for ln in lines if ln.startswith("ERROR:")][-limit:]


def classify(output: str, *, has_cookies: bool) -> ErrorKind:
    """Classify a failed yt-dlp run from its combined output."""
    text = output.lower()
    errors = "\n".join(error_lines(output)).lower() or text

    def has(needles: tuple[str, ...], haystack: str = errors) -> bool:
        return any(n in haystack for n in needles)

    # The rotation warning precedes the actual error; it explains the bot check that follows.
    if has_cookies and has(_COOKIES_INVALID, text):
        return ErrorKind.COOKIES_INVALID
    if has(_UNAVAILABLE) and not has(("sign in to confirm",)):
        return ErrorKind.UNAVAILABLE
    if has(_AUTH):
        return ErrorKind.AUTH_REQUIRED if has_cookies else ErrorKind.COOKIES_MISSING
    if has(_FORMAT):
        return ErrorKind.FORMAT_UNAVAILABLE
    if has(_RATE):
        return ErrorKind.RATE_LIMITED
    if has(_FORBIDDEN):
        return ErrorKind.FORBIDDEN
    if has(_NETWORK):
        return ErrorKind.NETWORK
    return ErrorKind.UNKNOWN


class YtdlpError(Exception):
    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {MESSAGES[kind]}")

    @property
    def message(self) -> str:
        return MESSAGES[self.kind]

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE
