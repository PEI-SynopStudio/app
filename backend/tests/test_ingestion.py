import math
import wave
from array import array

import pytest

from app.core.config import AUDIO_CODEC, AUDIO_SAMPLE_RATE, PROXY_MAX_HEIGHT
from app.services.video.ingestion import (
    check_audio_not_silent,
    check_supported_formats,
    extract_normalized_audio,
    generate_proxy_video,
    inspect_media,
)

# Containers and codecs accepted by FR02 for direct upload.
CONTAINERS = [
    ("mp4", "h264", "aac"),
    ("mov", "h264", "aac"),
    ("mkv", "hevc", "opus"),
    ("webm", "libvpx-vp9", "libopus"),
    ("avi", "h264", "mp3"),
]


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_inspect_media_reads_supported_containers(make_sample, extension, video_codec, audio_codec):
    media = inspect_media(make_sample(extension, video_codec, audio_codec))

    video = media.streams_of("video")[0]
    assert media.duration_seconds == pytest.approx(2, abs=0.1)
    assert (video.width, video.height) == (320, 240)
    assert video.frame_rate == pytest.approx(25)
    assert len(media.streams_of("audio")) == 1


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_extract_normalized_audio(make_sample, tmp_path, extension, video_codec, audio_codec):
    wav_path = extract_normalized_audio(
        make_sample(extension, video_codec, audio_codec), tmp_path / "audio.wav"
    )

    audio = inspect_media(wav_path).streams_of("audio")[0]
    assert audio.codec_name == AUDIO_CODEC
    assert audio.sample_rate == AUDIO_SAMPLE_RATE
    assert audio.channels == 1


def test_inspect_media_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        inspect_media(tmp_path / "missing.mp4")


def test_inspect_media_rejects_video_without_audio(make_sample):
    with pytest.raises(ValueError, match="audio"):
        inspect_media(make_sample(audio_codec=None))


def test_extract_audio_rejects_video_without_audio(make_sample, tmp_path):
    with pytest.raises(ValueError, match="audio"):
        extract_normalized_audio(make_sample(audio_codec=None), tmp_path / "audio.wav")


def test_inspect_media_rejects_unreadable_file(tmp_path):
    corrupted = tmp_path / "corrupted.mp4"
    corrupted.write_bytes(b"not a video" * 100)

    with pytest.raises(RuntimeError, match="unreadable"):
        inspect_media(corrupted)


def test_generate_proxy_video_downscales_to_720p(make_sample, tmp_path):
    proxy_path = generate_proxy_video(make_sample(width=1280, height=960), tmp_path / "proxy.mp4")

    media = inspect_media(proxy_path)
    video = media.streams_of("video")[0]
    assert video.codec_name == "h264"
    assert (video.width, video.height) == (960, PROXY_MAX_HEIGHT)
    assert media.streams_of("audio")[0].codec_name == "aac"
    assert media.duration_seconds == pytest.approx(2, abs=0.1)


def test_generate_proxy_video_does_not_upscale(make_sample, tmp_path):
    proxy_path = generate_proxy_video(make_sample(width=320, height=240), tmp_path / "proxy.mp4")

    video = inspect_media(proxy_path).streams_of("video")[0]
    assert (video.width, video.height) == (320, 240)


def test_generate_proxy_video_is_faststart(make_sample, tmp_path):
    proxy_path = generate_proxy_video(make_sample(), tmp_path / "proxy.mp4")

    data = proxy_path.read_bytes()
    assert data.find(b"moov") < data.find(b"mdat"), "moov atom must come first for progressive playback"


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_check_supported_formats_accepts_whitelist(make_sample, extension, video_codec, audio_codec):
    check_supported_formats(inspect_media(make_sample(extension, video_codec, audio_codec)))


@pytest.mark.parametrize("extension,video_codec,audio_codec,message", [
    ("ts", "h264", "aac", "container format"),
    ("mkv", "mpeg4", "aac", "video codec 'mpeg4'"),
    ("mkv", "h264", "ac3", "audio codec 'ac3'"),
])
def test_check_supported_formats_rejects(make_sample, extension, video_codec, audio_codec, message):
    with pytest.raises(ValueError, match=message):
        check_supported_formats(inspect_media(make_sample(extension, video_codec, audio_codec)))


def test_check_supported_formats_rejects_audio_only_file(make_sample, tmp_path):
    wav_path = extract_normalized_audio(make_sample(), tmp_path / "audio.wav")

    with pytest.raises(ValueError, match="container format"):
        check_supported_formats(inspect_media(wav_path))


def test_inspect_media_reads_aspect_ratio(make_sample):
    video = inspect_media(make_sample(width=640, height=360)).streams_of("video")[0]
    assert video.aspect_ratio == "16:9"


def write_tone(path, amplitude, seconds=3, silent_seconds=0):
    """Write a 16 kHz mono 16-bit WAV: optional leading silence, then a 440 Hz tone (amplitude 0..1)."""
    samples = array("h", [0] * (AUDIO_SAMPLE_RATE * silent_seconds))
    samples.extend(
        int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / AUDIO_SAMPLE_RATE))
        for index in range(AUDIO_SAMPLE_RATE * seconds)
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(AUDIO_SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return path


def test_check_audio_not_silent_rejects_silent_recording(make_sample, tmp_path):
    # make_sample writes digital silence in its audio track.
    wav_path = extract_normalized_audio(make_sample(), tmp_path / "audio.wav")

    with pytest.raises(ValueError, match="silent"):
        check_audio_not_silent(wav_path)


@pytest.mark.parametrize("amplitude", [0.5, 0.01])  # about -9 dBFS and -43 dBFS RMS
def test_check_audio_not_silent_accepts_audible_tone(tmp_path, amplitude):
    check_audio_not_silent(write_tone(tmp_path / "tone.wav", amplitude, silent_seconds=5))


def test_check_audio_not_silent_rejects_very_quiet_tone(tmp_path):
    with pytest.raises(ValueError, match="silent"):
        check_audio_not_silent(write_tone(tmp_path / "tone.wav", 0.001))  # about -63 dBFS RMS
