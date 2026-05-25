import logging
import re
import urllib.request

import yt_dlp

logger = logging.getLogger(__name__)


def resolve_track(url: str) -> dict:
    """Resolve a SoundCloud URL to track metadata and HLS playlist info."""
    ydl_opts = {
        "format": "hls_mp3_0_1/hls_mp3_1_0/hls_aac_96k/best",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    m3u8_url = info["url"]

    raw_m3u8 = urllib.request.urlopen(m3u8_url, timeout=10).read().decode()

    segment_urls = []
    init_url = None
    for line in raw_m3u8.splitlines():
        if line.startswith("https://"):
            segment_urls.append(line)
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
        "raw_m3u8": raw_m3u8,
        "segments": segment_urls,
        "init_url": init_url,
    }


_MAX_SEGMENTS = 60  # ~10 minutes at 10s per segment


def rewrite_m3u8(track_id: str, base_url: str, raw_m3u8: str, segments: list[str], init_url: str | None) -> str:
    """Replace long CDN URLs in the original m3u8 with short proxy URLs.

    Truncates playlists longer than _MAX_SEGMENTS to avoid overwhelming
    the speaker's HLS parser.
    """
    use_count = min(len(segments), _MAX_SEGMENTS)
    use_urls = set(segments[:use_count])

    lines = raw_m3u8.splitlines()
    out: list[str] = []
    skip_next_url = False
    seg_idx = 0

    for line in lines:
        if line.startswith("#EXT-X-MAP:") and init_url:
            out.append(line.replace(init_url, f"{base_url}/soundcloud/init/{track_id}"))
        elif line.startswith("https://"):
            if line in use_urls:
                out.append(f"{base_url}/soundcloud/seg/{track_id}/{seg_idx}")
                seg_idx += 1
            else:
                # Drop this URL and the preceding EXTINF
                if out and out[-1].startswith("#EXTINF:"):
                    out.pop()
                continue
        elif line == "#EXT-X-ENDLIST":
            out.append(line)
        else:
            out.append(line)

    if not any(l == "#EXT-X-ENDLIST" for l in out):
        out.append("#EXT-X-ENDLIST")

    return "\n".join(out) + "\n"


def fetch_segment(url: str) -> bytes:
    """Fetch a single audio segment from the CDN."""
    return urllib.request.urlopen(url, timeout=30).read()
