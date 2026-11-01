import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# Root directory mounted via Docker volume (/data/media)
MEDIA_ROOT = Path("/data/media")


# ==============================================================================
# Inspect the container with ffprobe; reject unreadable files and files without audio.
# Source: MS2 FR02 - Step 3 (Container and Stream Integrity Inspection)
# ==============================================================================
def inspect_media(input_path: Path) -> Dict[str, Any]:
    """Inspect media container integrity and verify the existence of a decodable audio stream."""
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,channels,sample_rate",
        "-show_entries", "format=duration,size,format_name",
        "-of", "json",
        str(input_path),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Corrupted or unreadable media file: {result.stderr.strip()}")

    probe_data = json.loads(result.stdout)
    streams = probe_data.get("streams", [])

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_audio:
        raise ValueError("Video rejected: does not contain any decodable audio stream.")

    return probe_data


# ==============================================================================
# Extract audio and normalize to 16 kHz, 16-bit mono PCM WAV (Whisper input).
# Source: MS2 FR02 – Step 4 (Audio Extraction and Normalization).
# ==============================================================================
def extract_normalized_audio(video_path: Path, output_wav_path: Path) -> Path:
    """Extract and normalize audio stream to uncompressed 16 kHz, 16-bit mono PCM WAV."""
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav_path),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to extract normalized audio: {result.stderr.strip()}")

    return output_wav_path


# ==============================================================================
# Generate a 720p H.264 proxy with +faststart for web playback and scrubbing.
# Source: MS2 FR02 – Step 5 (Visual Proxy); +faststart from the professor's `find_me.py`.
# ==============================================================================
def generate_proxy_video(video_path: Path, output_proxy_path: Path) -> Path:
    """Generate a lightweight 720p H.264 proxy video for timeline scrubbing and web preview."""
    output_proxy_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "26",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_proxy_path),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate proxy video: {result.stderr.strip()}")

    return output_proxy_path


# ==============================================================================
# Download a YouTube video, or only a time interval of it, to MP4 with yt-dlp.
# Source: professor's `youtube_interval.py`; MS2 FR02 / US05 (time range to import).
# ==============================================================================
def download_youtube_video(
    url: str,
    output_path: Path,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Path:
    """Download a video or specific section from YouTube to an MP4 container using yt-dlp."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-overwrites",
        "-t", "mp4",
        "-o", str(output_path),
    ]

    if start_time and end_time:
        cmd.extend([
            "--download-sections", f"*{start_time}-{end_time}",
            "--force-keyframes-at-cuts",
        ])

    cmd.extend(["--", url])

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to download YouTube video with yt-dlp: {result.stderr.strip()}")

    return output_path