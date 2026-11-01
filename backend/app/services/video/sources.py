from typing import Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, parse_duration

from app.core.config import (
    ALLOWED_AVAILABILITY,
    ALLOWED_URL_SCHEMES,
    DOMAIN_SEPARATOR,
    ERROR_DOMAIN_NOT_ALLOWED,
    ERROR_DURATION_EXCEEDED,
    ERROR_DURATION_UNKNOWN,
    ERROR_INVALID_TIME_RANGE,
    ERROR_INVALID_TIMECODE,
    ERROR_INVALID_URL,
    ERROR_TIME_RANGE_INCOMPLETE,
    ERROR_VIDEO_IS_LIVE,
    ERROR_VIDEO_NOT_PUBLIC,
    ERROR_VIDEO_UNAVAILABLE,
    REJECTED_LIVE_STATUSES,
    get_settings,
)


class RemoteVideoInfo(BaseModel):
    url: str
    title: Optional[str] = None
    duration_seconds: float
    availability: Optional[str] = None
    extractor: Optional[str] = None


# Accept only http(s) links whose host is an allowed domain or one of its subdomains.
# Source: MS2 FR02 – Step 1 (URL syntax and authorised platform).
def validate_source_url(url: str) -> str:
    """Validate the URL syntax and check its host against the configured domain whitelist."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not host:
        raise ValueError(ERROR_INVALID_URL)

    allowed = get_settings().allowed_source_domains
    if not any(host == domain or host.endswith(DOMAIN_SEPARATOR + domain) for domain in allowed):
        raise ValueError(ERROR_DOMAIN_NOT_ALLOWED.format(domain=host))

    return parsed.geturl()


# Read the remote metadata with yt-dlp (no download); reject private, live and too long videos.
# Source: MS2 FR02 – Step 1 (accessibility, public/unlisted, duration limit).
def probe_remote_video(url: str) -> RemoteVideoInfo:
    """Fetch metadata of a remote video without downloading it and check it can be imported."""
    url = validate_source_url(url)
    options = {"noplaylist": True, "skip_download": True, "quiet": True, "no_warnings": True}

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise ValueError(ERROR_VIDEO_UNAVAILABLE.format(details=exc)) from exc

    # yt-dlp leaves availability empty when the platform does not report it.
    availability = info.get("availability")
    if availability is not None and availability not in ALLOWED_AVAILABILITY:
        raise ValueError(ERROR_VIDEO_NOT_PUBLIC.format(availability=availability))
    if info.get("is_live") or info.get("live_status") in REJECTED_LIVE_STATUSES:
        raise ValueError(ERROR_VIDEO_IS_LIVE)

    duration = info.get("duration")
    if not duration:
        raise ValueError(ERROR_DURATION_UNKNOWN)
    limit = get_settings().max_duration_seconds
    if duration > limit:
        raise ValueError(ERROR_DURATION_EXCEEDED.format(duration=duration, limit=limit))

    return RemoteVideoInfo(
        url=info.get("webpage_url") or url,
        title=info.get("title"),
        duration_seconds=duration,
        availability=availability,
        extractor=info.get("extractor_key"),
    )


# Parse optional start/end timecodes (HH:MM:SS or seconds) and check 0 <= start < end <= duration.
# Source: MS2 FR02 – Step 1 / US05 (time range to import).
def validate_time_range(
    start_time: Optional[str], end_time: Optional[str], duration_seconds: float
) -> Optional[Tuple[float, float]]:
    """Return the range in seconds, or None when no range was requested."""
    if start_time is None and end_time is None:
        return None
    if start_time is None or end_time is None:
        raise ValueError(ERROR_TIME_RANGE_INCOMPLETE)

    start, end = _parse_timecode(start_time), _parse_timecode(end_time)
    if not start < end <= duration_seconds:
        raise ValueError(ERROR_INVALID_TIME_RANGE.format(start=start, end=end, duration=duration_seconds))
    return start, end


def _parse_timecode(value: str) -> float:
    seconds = parse_duration(value)
    if seconds is None or seconds < 0:
        raise ValueError(ERROR_INVALID_TIMECODE.format(value=value))
    return seconds
