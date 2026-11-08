import heapq
import math
import sys
import wave
from array import array
from collections import deque
from fractions import Fraction
from pathlib import Path
from typing import Deque, List, Optional, Tuple

import av
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, download_range_func

from app.core.config import (
    ALLOWED_CONTAINER_FORMATS,
    ASPECT_RATIO_FORMAT,
    AUDIO_CODEC,
    AUDIO_CONTAINER,
    AUDIO_LAYOUT,
    AUDIO_SAMPLE_FORMAT,
    AUDIO_SAMPLE_RATE,
    CONTAINERS_WITHOUT_PRESENTATION_TIMES,
    DECIBEL_BASE,
    DECIBEL_FACTOR,
    ERROR_AUDIO_EXTRACTION_FAILED,
    ERROR_CORRUPTED_PACKETS,
    ERROR_DOWNLOAD_FAILED,
    ERROR_FILE_NOT_FOUND,
    ERROR_NO_AUDIO_STREAM,
    ERROR_NO_VIDEO_STREAM,
    ERROR_PROXY_FAILED,
    ERROR_SILENT_AUDIO,
    ERROR_TRUNCATED_MEDIA,
    ERROR_UNREADABLE_MEDIA,
    ERROR_UNSUPPORTED_AUDIO_CODEC,
    ERROR_UNSUPPORTED_CONTAINER,
    ERROR_UNSUPPORTED_VIDEO_CODEC,
    EVEN_DIMENSION,
    LIST_SEPARATOR,
    MEDIA_WRITE_MODE,
    PCM_FULL_SCALE,
    PCM_SAMPLE_TYPECODE,
    PROXY_AUDIO_BITRATE,
    PROXY_AUDIO_CODEC,
    PROXY_AUDIO_FRAME_SIZE,
    PROXY_AUDIO_SAMPLE_FORMAT,
    PROXY_CONTAINER,
    PROXY_MAX_HEIGHT,
    PROXY_MUXER_OPTIONS,
    PROXY_PIXEL_FORMAT,
    PROXY_VIDEO_CODEC,
    PROXY_VIDEO_OPTIONS,
    SILENCE_THRESHOLD_DBFS,
    SILENCE_WINDOW_SECONDS,
    STREAM_TYPE_AUDIO,
    STREAM_TYPE_VIDEO,
    TRUNCATION_TOLERANCE_SECONDS,
    VFR_INTERVAL_TOLERANCE,
    VFR_MIN_IRREGULAR_SHARE,
    VFR_REORDER_WINDOW,
    VFR_TIMESTAMP_ROUNDING_SECONDS,
    VIDEO_START_SECONDS,
    WAV_BYTE_ORDER,
    WAV_READ_MODE,
    YTDLP_FORMAT_SORT,
    YTDLP_FORMAT_TEMPLATE,
    YTDLP_MAX_HEIGHT,
    YTDLP_OUTPUT_CONTAINER,
    YTDLP_OUTPUT_TEMPLATE,
    YTDLP_REMUXER,
    JobErrorCodeEnum,
    get_settings,
)
from app.core.exceptions import MediaProcessingError, MediaRejectedError
from app.schemas.timecode import parse_time


class StreamInfo(BaseModel):
    index: int
    codec_type: str
    codec_name: str
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None
    frame_rate: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


class MediaInfo(BaseModel):
    format_name: str
    duration_seconds: Optional[float] = None
    size_bytes: int
    streams: List[StreamInfo]

    def streams_of(self, codec_type: str) -> List[StreamInfo]:
        return [stream for stream in self.streams if stream.codec_type == codec_type]


# Inspect the container with PyAV; reject unreadable files and files without audio.
# Source: MS2 FR02 – Step 3 (Container and Stream Integrity Inspection).
def inspect_media(input_path: Path) -> MediaInfo:
    """Inspect media container integrity and verify the existence of a decodable audio stream."""
    if not input_path.exists():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=input_path))

    try:
        with av.open(str(input_path)) as container:
            streams = []
            for stream in container.streams:
                codec = stream.codec_context
                # canonical_name is the codec, not the decoder (e.g. "mp3", not "mp3float").
                info = StreamInfo(
                    index=stream.index, codec_type=stream.type, codec_name=codec.codec.canonical_name
                )
                if stream.type == STREAM_TYPE_VIDEO:
                    info.width, info.height = codec.width, codec.height
                    info.aspect_ratio = _display_aspect_ratio(codec.width, codec.height, stream.sample_aspect_ratio)
                    info.frame_rate = float(stream.average_rate) if stream.average_rate else None
                elif stream.type == STREAM_TYPE_AUDIO:
                    info.sample_rate = codec.sample_rate
                    info.channels = codec.channels
                streams.append(info)

            media = MediaInfo(
                format_name=container.format.name,
                duration_seconds=container.duration / av.time_base if container.duration else None,
                size_bytes=container.size,
                streams=streams,
            )
    except av.FFmpegError as exc:
        raise RuntimeError(ERROR_UNREADABLE_MEDIA.format(details=exc)) from exc

    if not media.streams_of(STREAM_TYPE_AUDIO):
        raise MediaRejectedError(JobErrorCodeEnum.NO_AUDIO_TRACK, ERROR_NO_AUDIO_STREAM)

    return media


def _display_aspect_ratio(width: int, height: int, sample_aspect_ratio: Optional[Fraction]) -> Optional[str]:
    """Width:height as shown on screen; a missing sample aspect ratio (0/1) means square pixels."""
    if not width or not height:
        return None
    ratio = Fraction(width, height) * (sample_aspect_ratio or 1)
    return ASPECT_RATIO_FORMAT.format(numerator=ratio.numerator, denominator=ratio.denominator)


class PacketScan(BaseModel):
    is_vfr: bool
    corrupted_packets: int
    missing_seconds: Optional[float] = None


class _FrameIntervals:
    """Counts changes between consecutive frame intervals, in presentation order and constant memory."""

    def __init__(self, rounding_ticks: float) -> None:
        self._rounding_ticks = rounding_ticks
        self._pending: List[int] = []
        self._last_pts: Optional[int] = None
        self._last_interval: Optional[int] = None
        self._compared = 0
        self._irregular = 0

    def add(self, pts: int) -> None:
        heapq.heappush(self._pending, pts)
        if len(self._pending) > VFR_REORDER_WINDOW:
            self._advance(heapq.heappop(self._pending))

    def is_variable(self) -> bool:
        while self._pending:
            self._advance(heapq.heappop(self._pending))
        return self._irregular > self._compared * VFR_MIN_IRREGULAR_SHARE

    def _advance(self, pts: int) -> None:
        if self._last_pts is not None:
            interval = pts - self._last_pts
            if self._last_interval is not None:
                self._compared += 1
                tolerance = max(self._rounding_ticks, min(interval, self._last_interval) * VFR_INTERVAL_TOLERANCE)
                if abs(interval - self._last_interval) > tolerance:
                    self._irregular += 1
            self._last_interval = interval
        self._last_pts = pts


# Read every packet without decoding: frame timing, packets flagged as damaged and where the data really ends.
# Source: MS2 FR02 – Step 3 (corrupted packets, variable frame rate).
def scan_packets(input_path: Path) -> PacketScan:
    """Measure the source in one streaming pass; `missing_seconds` is None when the file declares no duration."""
    if not input_path.exists():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=input_path))

    corrupted = 0
    data_end: Optional[Fraction] = None
    try:
        with av.open(str(input_path)) as container:
            video = container.streams.video[0]
            intervals = _FrameIntervals(VFR_TIMESTAMP_ROUNDING_SECONDS / float(video.time_base))
            for packet in container.demux():
                # Each stream ends with an empty packet that only flushes the decoder.
                if not packet.size:
                    continue
                if packet.is_corrupt:
                    corrupted += 1
                if packet.pts is None:
                    continue
                if packet.stream.index == video.index:
                    intervals.add(packet.pts)
                packet_end = (packet.pts + (packet.duration or 0)) * packet.time_base
                data_end = packet_end if data_end is None else max(data_end, packet_end)

            missing = None
            if container.duration and data_end is not None:
                declared_end = Fraction((container.start_time or 0) + container.duration, av.time_base)
                missing = float(declared_end - data_end)
    except av.FFmpegError as exc:
        raise RuntimeError(ERROR_UNREADABLE_MEDIA.format(details=exc)) from exc

    return PacketScan(is_vfr=intervals.is_variable(), corrupted_packets=corrupted, missing_seconds=missing)


# Reject sources with packets flagged as damaged or whose data ends before the declared duration.
# Source: MS2 FR02 – Step 3 (corrupted packets; unreadable files rejected with details).
def check_packet_integrity(scan: PacketScan) -> None:
    """A variable frame rate is only recorded, never rejected."""
    if scan.corrupted_packets:
        raise MediaRejectedError(
            JobErrorCodeEnum.CORRUPTED_MEDIA, ERROR_CORRUPTED_PACKETS.format(count=scan.corrupted_packets)
        )
    if scan.missing_seconds is not None and scan.missing_seconds > TRUNCATION_TOLERANCE_SECONDS:
        raise MediaRejectedError(
            JobErrorCodeEnum.CORRUPTED_MEDIA, ERROR_TRUNCATED_MEDIA.format(missing=scan.missing_seconds)
        )


# Reject containers and codecs outside the FR02 whitelist (checked on the server, not only in the client).
# Source: MS2 FR02 – Inputs (MP4, MOV, MKV, WebM, AVI; H.264, H.265, VP9, AV1; AAC, MP3, Opus, PCM).
def check_supported_formats(media: MediaInfo) -> None:
    """Raise ValueError when the container, the first video stream or the first audio stream is not allowed."""
    if not set(media.format_name.split(LIST_SEPARATOR)) & set(ALLOWED_CONTAINER_FORMATS):
        raise MediaRejectedError(
            JobErrorCodeEnum.UNSUPPORTED_FORMAT, ERROR_UNSUPPORTED_CONTAINER.format(format_name=media.format_name)
        )

    videos, audios = media.streams_of(STREAM_TYPE_VIDEO), media.streams_of(STREAM_TYPE_AUDIO)
    if not videos:
        raise MediaRejectedError(JobErrorCodeEnum.UNSUPPORTED_FORMAT, ERROR_NO_VIDEO_STREAM)
    if not audios:
        raise MediaRejectedError(JobErrorCodeEnum.NO_AUDIO_TRACK, ERROR_NO_AUDIO_STREAM)

    settings = get_settings()
    if videos[0].codec_name not in settings.allowed_video_codecs:
        raise MediaRejectedError(
            JobErrorCodeEnum.UNSUPPORTED_FORMAT, ERROR_UNSUPPORTED_VIDEO_CODEC.format(codec=videos[0].codec_name)
        )
    if audios[0].codec_name not in settings.allowed_audio_codecs:
        raise MediaRejectedError(
            JobErrorCodeEnum.UNSUPPORTED_FORMAT, ERROR_UNSUPPORTED_AUDIO_CODEC.format(codec=audios[0].codec_name)
        )


# Extract audio and normalize to 16 kHz, 16-bit mono PCM WAV (Whisper input) with PyAV.
# Source: MS2 FR02 – Step 4 (Audio Extraction and Normalization).
def extract_normalized_audio(video_path: Path, output_wav_path: Path) -> Path:
    """Extract and normalize audio stream to uncompressed 16 kHz, 16-bit mono PCM WAV."""
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with av.open(str(video_path)) as source:
            if not source.streams.audio:
                raise MediaRejectedError(JobErrorCodeEnum.NO_AUDIO_TRACK, ERROR_NO_AUDIO_STREAM)
            input_stream = source.streams.audio[0]
            resampler = av.AudioResampler(
                format=AUDIO_SAMPLE_FORMAT, layout=AUDIO_LAYOUT, rate=AUDIO_SAMPLE_RATE
            )

            with av.open(str(output_wav_path), MEDIA_WRITE_MODE, format=AUDIO_CONTAINER) as target:
                output_stream = target.add_stream(AUDIO_CODEC, rate=AUDIO_SAMPLE_RATE, layout=AUDIO_LAYOUT)
                for frame in source.decode(input_stream):
                    for resampled in resampler.resample(frame):
                        target.mux(output_stream.encode(resampled))
                # Flush the resampler and the encoder so no trailing samples are lost.
                for resampled in resampler.resample(None):
                    target.mux(output_stream.encode(resampled))
                target.mux(output_stream.encode(None))
    except av.FFmpegError as exc:
        raise RuntimeError(ERROR_AUDIO_EXTRACTION_FAILED.format(details=exc)) from exc

    return output_wav_path


# Reject recordings whose normalized audio never rises above the silence threshold.
# Source: MS2 FR02 – Step 3 ("silent or unreadable files rejected").
def check_audio_not_silent(wav_path: Path) -> None:
    """Scan the 16-bit PCM WAV in 1 s windows; raise ValueError if no window is louder than the threshold.

    Stops at the first loud window, so normal recordings are not read to the end.
    """
    if not wav_path.exists():
        raise FileNotFoundError(ERROR_FILE_NOT_FOUND.format(path=wav_path))

    # Compare sums of squares with the threshold converted to linear RMS (no sqrt/log per window).
    threshold_rms = PCM_FULL_SCALE * DECIBEL_BASE ** (SILENCE_THRESHOLD_DBFS / DECIBEL_FACTOR)
    with wave.open(str(wav_path), WAV_READ_MODE) as wav:
        window_frames = wav.getframerate() * SILENCE_WINDOW_SECONDS
        while True:
            samples = array(PCM_SAMPLE_TYPECODE, wav.readframes(window_frames))
            if not samples:
                break
            if sys.byteorder != WAV_BYTE_ORDER:
                samples.byteswap()
            if math.fsum(sample * sample for sample in samples) > threshold_rms**2 * len(samples):
                return

    raise MediaRejectedError(JobErrorCodeEnum.SILENT_AUDIO, ERROR_SILENT_AUDIO.format(threshold=SILENCE_THRESHOLD_DBFS))


# Generate a lightweight H.264/AAC proxy (max 720p, +faststart) with PyAV for web playback and scrubbing.
# Source: MS2 FR02 – Step 5 (Visual Proxy); +faststart from the professor's `find_me.py`.
def generate_proxy_video(video_path: Path, output_proxy_path: Path) -> Path:
    """Generate a lightweight proxy video (H.264, max 720p, AAC, +faststart) for timeline scrubbing and web preview."""
    output_proxy_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with av.open(str(video_path)) as source:
            if not source.streams.video:
                raise MediaRejectedError(JobErrorCodeEnum.UNSUPPORTED_FORMAT, ERROR_NO_VIDEO_STREAM)
            video_in = source.streams.video[0]
            audio_in = source.streams.audio[0] if source.streams.audio else None
            width, height = _proxy_size(video_in.codec_context.width, video_in.codec_context.height)

            with av.open(
                str(output_proxy_path), MEDIA_WRITE_MODE, format=PROXY_CONTAINER, options=PROXY_MUXER_OPTIONS
            ) as target:
                video_out = target.add_stream(PROXY_VIDEO_CODEC, rate=video_in.average_rate)
                video_out.width, video_out.height, video_out.pix_fmt = width, height, PROXY_PIXEL_FORMAT
                video_out.options = dict(PROXY_VIDEO_OPTIONS)
                # With the default 1/frame_rate, close frames of a variable-frame-rate source would share a timestamp.
                video_out.codec_context.time_base = video_in.time_base

                input_streams = [video_in]
                audio_out = resampler = None
                if audio_in is not None:
                    sample_rate = audio_in.codec_context.sample_rate
                    audio_out = target.add_stream(PROXY_AUDIO_CODEC, rate=sample_rate)
                    audio_out.bit_rate = PROXY_AUDIO_BITRATE
                    resampler = av.AudioResampler(
                        format=PROXY_AUDIO_SAMPLE_FORMAT,
                        layout=audio_in.codec_context.layout.name,
                        rate=sample_rate,
                        frame_size=PROXY_AUDIO_FRAME_SIZE,
                    )
                    input_streams.append(audio_in)

                # Without presentation times, frames come out in display order but with shuffled timestamps,
                # so each frame takes the next decode time instead.
                decode_times: Optional[Deque[int]] = None
                if source.format.name in CONTAINERS_WITHOUT_PRESENTATION_TIMES:
                    decode_times = deque()

                # Single pass over the source: packets are demuxed in order and routed by stream type.
                for packet in source.demux(*input_streams):
                    if decode_times is not None and packet.stream.type == STREAM_TYPE_VIDEO and packet.size:
                        decode_times.append(packet.dts)
                    for frame in packet.decode():
                        if packet.stream.type == STREAM_TYPE_VIDEO:
                            if decode_times is not None:
                                frame.pts = decode_times.popleft()
                            scaled = frame.reformat(width=width, height=height, format=PROXY_PIXEL_FORMAT)
                            target.mux(video_out.encode(scaled))
                        else:
                            # AVI can use one tick per packet, too coarse for the shorter chunks of the resampler.
                            if frame.pts is not None:
                                frame.pts = round(frame.pts * frame.time_base * sample_rate)
                                frame.time_base = Fraction(1, sample_rate)
                            for chunk in resampler.resample(frame):
                                target.mux(audio_out.encode(chunk))

                # Flush the encoders (and the resampler) so no trailing frames are lost.
                target.mux(video_out.encode(None))
                if audio_out is not None:
                    for chunk in resampler.resample(None):
                        target.mux(audio_out.encode(chunk))
                    target.mux(audio_out.encode(None))
    except av.FFmpegError as exc:
        raise RuntimeError(ERROR_PROXY_FAILED.format(details=exc)) from exc

    return output_proxy_path


def _proxy_size(width: int, height: int) -> Tuple[int, int]:
    """Scale to at most PROXY_MAX_HEIGHT keeping the aspect ratio; H.264 needs even dimensions."""
    target_height = min(height, PROXY_MAX_HEIGHT)
    target_height -= target_height % EVEN_DIMENSION
    target_width = round(width * target_height / height / EVEN_DIMENSION) * EVEN_DIMENSION
    return target_width, target_height


# Download a YouTube video, or only a time interval of it, to MP4 (max 1080p) with the yt-dlp API.
# Source: professor's `youtube_interval.py`; MS2 FR02 – Step 2 / US05 (time range to import).
def download_youtube_video(
    url: str,
    output_path: Path,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> Path:
    """Download a video or a time range of it to an MP4 container (max 1080p) using the yt-dlp Python API."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    options = {
        "noplaylist": True,
        "overwrites": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": YTDLP_FORMAT_TEMPLATE.format(max_height=YTDLP_MAX_HEIGHT),
        "format_sort": list(YTDLP_FORMAT_SORT),
        "merge_output_format": YTDLP_OUTPUT_CONTAINER,
        "postprocessors": [{"key": YTDLP_REMUXER, "preferedformat": YTDLP_OUTPUT_CONTAINER}],
        "outtmpl": str(output_path.with_name(YTDLP_OUTPUT_TEMPLATE.format(stem=output_path.stem))),
    }

    if start_time or end_time:
        start = float(parse_time(start_time)) if start_time else VIDEO_START_SECONDS
        end = float(parse_time(end_time)) if end_time else math.inf
        options["download_ranges"] = download_range_func(None, [(start, end)])
        options["force_keyframes_at_cuts"] = True

    try:
        with YoutubeDL(options) as ydl:
            ydl.download([url])
    except DownloadError as exc:
        raise MediaProcessingError(JobErrorCodeEnum.SOURCE_UNAVAILABLE, ERROR_DOWNLOAD_FAILED.format(details=exc)) from exc

    return output_path.with_suffix(f".{YTDLP_OUTPUT_CONTAINER}")