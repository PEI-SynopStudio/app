import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

# Root directory mounted via Docker volume (/data/media)
MEDIA_ROOT = Path("/data/media")


# ==============================================================================
# Function: inspect_media
# ------------------------------------------------------------------------------
# Description:
#   Inspects the multimedia container using ffprobe to validate stream
#   integrity and verify the presence of at least one decodable audio track.
#   Unreadable, corrupted, or silent files are rejected immediately.
#
# Arguments:
#   - input_path (Path): Path to the video/audio file to inspect.
#
# Returns:
#   - Dict[str, Any]: Parsed JSON metadata containing stream and format details.
#
# Sources & Provenance:
#   - Command structure (-v error, -show_entries, -of json):
#       Adapted from `fujiwarachoki/supoclip` (`backend/src/media/ffmpeg.py`).
#   - Business rule (reject unreadable or silent files without decodable audio):
#       Derived directly from Milestone 2 specification (`MS2-Elaboration.pdf`,
#       FR02 - Step 3: Container and Stream Integrity Inspection).
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
# Function: extract_normalized_audio
# ------------------------------------------------------------------------------
# Description:
#   Isolates the audio stream from the source video, removes the video track
#   (-vn), and normalizes it to uncompressed 16 kHz, 16-bit mono PCM WAV format.
#   This standardized format is required by Whisper speech recognition models.
#
# Arguments:
#   - video_path (Path): Path to the source video file.
#   - output_wav_path (Path): Destination path for the normalized .wav file.
#
# Returns:
#   - Path: Path to the generated normalized .wav file.
#
# Sources & Provenance:
#   - Base ffmpeg invocation and video discarding (-vn):
#       Adapted from `fujiwarachoki/supoclip` (`backend/src/media/ffmpeg.py` - extract_audio).
#   - Audio normalization parameters (-acodec pcm_s16le, -ar 16000, -ac 1):
#       Configured strictly according to Milestone 2 requirements (`MS2-Elaboration.pdf`,
#       FR02 - Step 4: Audio Extraction and Normalization).
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
# Function: generate_proxy_video
# ------------------------------------------------------------------------------
# Description:
#   Generates a lightweight 720p H.264 proxy video with progressive download
#   flags (+faststart) to ensure smooth playback and scrubbing in the web editor
#   without consuming high network bandwidth.
#
# Arguments:
#   - video_path (Path): Path to the high-resolution source video file.
#   - output_proxy_path (Path): Destination path for the generated proxy video.
#
# Returns:
#   - Path: Path to the generated proxy video file.
#
# Sources & Provenance:
#   - Proxy resolution (720p H.264):
#       Mandated by Milestone 2 specification (`MS2-Elaboration.pdf`,
#       FR02 - Step 5: Visual Proxy and Keyframe Generation).
#   - Streaming optimization (-movflags +faststart):
#       Derived from the professor's script `find_me.py` (`export_clips` function).
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
# Function: download_youtube_video
# ------------------------------------------------------------------------------
# Description:
#   Downloads a video from a YouTube URL via yt-dlp. Supports selective interval
#   downloading via time boundaries, forcing keyframe cuts to ensure clean edits
#   without downloading unneeded footage.
#
# Arguments:
#   - url (str): Valid YouTube video HTTP/HTTPS URL.
#   - output_path (Path): Target MP4 file destination path.
#   - start_time (Optional[str]): Start timestamp (e.g., '00:01:00').
#   - end_time (Optional[str]): End timestamp (e.g., '00:03:30').
#
# Returns:
#   - Path: Path to the downloaded MP4 file.
#
# Sources & Provenance:
#   - CLI command execution and interval slicing (--download-sections, --force-keyframes-at-cuts):
#       Directly extracted from the professor's script `youtube_interval.py` (lines 53-65).
#   - Remote URL ingestion requirements and partial range handling:
#       Aligned with Milestone 2 specification (`MS2-Elaboration.pdf`,
#       FR02 / US05: "specify the time range to import").
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