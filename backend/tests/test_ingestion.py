import pytest

from app.core.config import AUDIO_CODEC, AUDIO_SAMPLE_RATE, PROXY_MAX_HEIGHT
from app.services.video.ingestion import (
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
