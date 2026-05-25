import logging
import re
import urllib.request

import yt_dlp

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 30  # segments per playlist window (~5 min at 10s each)
_OVERLAP = 3  # segments of overlap between windows


def resolve_track(url: str) -> dict:
    """Resolve a SoundCloud URL to track metadata and HLS playlist info."""
    ydl_opts = {
        "format": "bestaudio[acodec=mp3][protocol=m3u8_native]/hls_aac_96k/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    m3u8_url = info["url"]
    raw_m3u8 = urllib.request.urlopen(m3u8_url, timeout=10).read().decode()

    segments = []
    init_url = None
    target_duration = 10
    current_extinf = None

    for line in raw_m3u8.splitlines():
        if line.startswith("#EXT-X-TARGETDURATION:"):
            target_duration = int(line.split(":")[1])
        elif line.startswith("#EXTINF:"):
            current_extinf = line
        elif line.startswith("https://"):
            segments.append((current_extinf or "#EXTINF:10.0,", line))
            current_extinf = None
        elif line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                init_url = m.group(1)

    return {
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail", ""),
        "m3u8_url": m3u8_url,
        "segments": segments,
        "init_url": init_url,
        "target_duration": target_duration,
        "cursor": 0,
    }


def build_m3u8_window(
    track_id: str,
    base_url: str,
    info: dict,
) -> str:
    """Build a live-style HLS playlist window from the current cursor position."""
    segments = info["segments"]
    total = len(segments)
    cursor = info.get("cursor", 0)
    target_duration = info.get("target_duration", 10)
    init_url = info.get("init_url")

    start = max(0, cursor - _OVERLAP)
    end = min(start + _WINDOW_SIZE, total)
    is_last = end >= total

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        f"#EXT-X-MEDIA-SEQUENCE:{start}",
    ]

    if is_last:
        lines.append("#EXT-X-PLAYLIST-TYPE:VOD")

    if init_url:
        lines.append(f'#EXT-X-MAP:URI="{base_url}/soundcloud/init/{track_id}"')

    for i in range(start, end):
        extinf, _ = segments[i]
        lines.append(extinf)
        lines.append(f"{base_url}/soundcloud/seg/{track_id}/{i}")

    if is_last:
        lines.append("#EXT-X-ENDLIST")

    return "\n".join(lines) + "\n"


def fetch_segment(url: str) -> bytes:
    """Fetch a single audio segment from the CDN."""
    return urllib.request.urlopen(url, timeout=30).read()
