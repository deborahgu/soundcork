import logging
import urllib.request

import yt_dlp

logger = logging.getLogger(__name__)


def resolve_track(url: str) -> dict:
    """Resolve a SoundCloud URL to track metadata and HLS playlist info."""
    ydl_opts = {
        "format": "hls_mp3_1_0/hls_aac_96k/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    m3u8_url = info["url"]

    raw = urllib.request.urlopen(m3u8_url, timeout=10).read().decode()
    durations = []
    segment_urls = []
    for line in raw.splitlines():
        if line.startswith("#EXTINF:"):
            durations.append(float(line.split(":")[1].rstrip(",")))
        elif line.startswith("https://"):
            segment_urls.append(line)

    return {
        "title": info.get("title", ""),
        "uploader": info.get("uploader", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail", ""),
        "m3u8_url": m3u8_url,
        "segments": segment_urls,
        "durations": durations,
    }


def rewrite_m3u8(track_id: str, base_url: str, durations: list[float], segment_count: int) -> str:
    """Generate a rewritten HLS playlist with short proxy segment URLs."""
    max_dur = max(durations) if durations else 10
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{int(max_dur) + 1}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    for i in range(segment_count):
        dur = durations[i] if i < len(durations) else 10.0
        lines.append(f"#EXTINF:{dur:.6f},")
        lines.append(f"{base_url}/soundcloud/seg/{track_id}/{i}")
    return "\n".join(lines) + "\n"


def fetch_segment(url: str) -> bytes:
    """Fetch a single audio segment from the CDN."""
    return urllib.request.urlopen(url, timeout=30).read()
