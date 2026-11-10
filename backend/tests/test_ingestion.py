import json
import math
import wave
from array import array

import av
import pytest

from app.core.config import AUDIO_CODEC, AUDIO_SAMPLE_RATE, PROXY_MAX_HEIGHT, JobErrorCodeEnum
from app.core.exceptions import MediaRejectedError
from app.services.video.ingestion import (
    PacketScan,
    _download_progress_hook,
    check_audio_not_silent,
    check_packet_integrity,
    check_supported_formats,
    cut_media,
    extract_normalized_audio,
    generate_keyframe_index,
    generate_proxy_video,
    generate_waveform,
    inspect_media,
    scan_packets,
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


def assert_rising_progress(reported):
    assert reported == sorted(reported)
    assert reported[0] >= 0 and reported[-1] <= 100
    assert reported[-1] > 80


def test_extract_normalized_audio_reports_progress(make_sample, tmp_path):
    reported = []

    extract_normalized_audio(make_sample(), tmp_path / "audio.wav", reported.append)

    assert_rising_progress(reported)


def test_generate_proxy_video_reports_progress(make_sample, tmp_path):
    reported = []

    generate_proxy_video(make_sample(), tmp_path / "proxy.mp4", reported.append)

    assert_rising_progress(sorted(reported))


def download_report(downloaded, total, formats=None):
    info = {"requested_formats": formats} if formats else {}
    return {"status": "downloading", "downloaded_bytes": downloaded, "total_bytes": total, "info_dict": info}


def test_download_progress_gives_each_file_an_equal_share():
    reported = []
    hook = _download_progress_hook(reported.append)
    formats = [{"format_id": "video"}, {"format_id": "audio"}]

    hook(download_report(50, 100, formats))
    hook({"status": "finished", "info_dict": {}})
    hook(download_report(50, 100, formats))

    assert reported == [25, 75]


def test_download_progress_of_a_single_file():
    reported = []

    _download_progress_hook(reported.append)(download_report(50, 100))

    assert reported == [50]


def test_download_progress_needs_a_known_size():
    reported = []

    _download_progress_hook(reported.append)(download_report(50, None))

    assert reported == []


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


def truncate(path, share=0.5):
    """Keep only the first part of a file, as an interrupted copy would."""
    path.write_bytes(path.read_bytes()[: int(path.stat().st_size * share)])
    return path


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_scan_packets_accepts_a_healthy_file(make_sample, extension, video_codec, audio_codec):
    scan = scan_packets(make_sample(extension, video_codec, audio_codec))

    assert (scan.is_vfr, scan.corrupted_packets) == (False, 0)
    check_packet_integrity(scan)


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_scan_packets_detects_a_variable_frame_rate(make_sample, vfr_frame_times, extension, video_codec, audio_codec):
    scan = scan_packets(make_sample(extension, video_codec, audio_codec, frame_times_ms=vfr_frame_times))

    assert scan.is_vfr is True
    check_packet_integrity(scan)


def test_scan_packets_tolerates_a_dropped_frame(make_sample):
    times = [index * 40 for index in range(200) if index != 100]

    assert scan_packets(make_sample(seconds=8, frame_times_ms=times)).is_vfr is False


def test_scan_packets_tolerates_timestamp_rounding(make_sample):
    """29.97 fps in a millisecond time base alternates between 33 and 34 ms."""
    times = [round(index * 1001 / 30) for index in range(60)]

    assert scan_packets(make_sample("mkv", frame_times_ms=times)).is_vfr is False


def test_scan_packets_tolerates_rounding_carried_over_by_a_remux(make_sample, tmp_path):
    """60 fps rounded to milliseconds keeps its 16 and 17 ms intervals in the finer time base of an MP4."""
    times = [round(index * 1000 / 60) for index in range(120)]

    proxy_path = generate_proxy_video(make_sample("mkv", frame_times_ms=times), tmp_path / "proxy.mp4")

    assert scan_packets(proxy_path).is_vfr is False


def test_scan_packets_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_packets(tmp_path / "missing.mp4")


@pytest.mark.parametrize("extension,video_codec,audio_codec", [("mkv", "h264", "aac"), ("webm", "libvpx-vp9", "libopus")])
def test_truncated_file_is_rejected(make_sample, extension, video_codec, audio_codec):
    scan = scan_packets(truncate(make_sample(extension, video_codec, audio_codec, seconds=8)))

    # Depending on where the cut falls, FFmpeg also flags the last packet as corrupted; both reasons reject the file.
    with pytest.raises(MediaRejectedError) as error:
        check_packet_integrity(scan)
    assert error.value.code == JobErrorCodeEnum.CORRUPTED_MEDIA


def test_truncated_faststart_mp4_is_rejected(make_sample, tmp_path):
    """+faststart keeps the index at the start of the file, so a truncated copy still opens."""
    proxy = generate_proxy_video(make_sample(seconds=8), tmp_path / "proxy.mp4")

    with pytest.raises(MediaRejectedError):
        check_packet_integrity(scan_packets(truncate(proxy)))


def test_corrupted_packets_are_rejected():
    with pytest.raises(MediaRejectedError, match="2 corrupted packet") as error:
        check_packet_integrity(PacketScan(is_vfr=False, corrupted_packets=2))
    assert error.value.code == JobErrorCodeEnum.CORRUPTED_MEDIA


def test_unknown_duration_is_not_treated_as_truncated():
    check_packet_integrity(PacketScan(is_vfr=False, corrupted_packets=0, missing_seconds=None))


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_generate_proxy_video_keeps_constant_timing(make_sample, tmp_path, extension, video_codec, audio_codec):
    source = make_sample(extension, video_codec, audio_codec)

    proxy_path = generate_proxy_video(source, tmp_path / "proxy.mp4")

    assert scan_packets(proxy_path).is_vfr is False
    assert inspect_media(proxy_path).duration_seconds == pytest.approx(inspect_media(source).duration_seconds, abs=0.2)


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_generate_proxy_video_keeps_variable_timing(
    make_sample, vfr_frame_times, tmp_path, extension, video_codec, audio_codec
):
    source = make_sample(extension, video_codec, audio_codec, frame_times_ms=vfr_frame_times)

    proxy_path = generate_proxy_video(source, tmp_path / "proxy.mp4")

    assert scan_packets(proxy_path).is_vfr is True
    assert inspect_media(proxy_path).duration_seconds == pytest.approx(inspect_media(source).duration_seconds, abs=0.2)


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


def keyframe_times(proxy_path, tmp_path):
    index_path = generate_keyframe_index(proxy_path, tmp_path / "analysis" / "keyframes.json")
    return json.loads(index_path.read_text())["times_seconds"]


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_proxy_has_a_keyframe_every_two_seconds(make_sample, tmp_path, extension, video_codec, audio_codec):
    source = make_sample(extension, video_codec, audio_codec, seconds=8)

    times = keyframe_times(generate_proxy_video(source, tmp_path / "proxy.mp4"), tmp_path)

    assert times == pytest.approx([0, 2, 4, 6], abs=0.05)


def test_proxy_keyframes_stay_regular_at_a_variable_frame_rate(make_sample, tmp_path):
    frame_times = [index * 40 + index % 3 * 15 for index in range(200)]

    source = make_sample(seconds=8, frame_times_ms=frame_times)

    times = keyframe_times(generate_proxy_video(source, tmp_path / "proxy.mp4"), tmp_path)

    assert len(times) >= 4
    assert all(2 <= later - earlier <= 2.1 for earlier, later in zip(times, times[1:]))


def test_proxy_keyframes_are_regular_when_the_video_is_scaled(make_sample, tmp_path):
    source = make_sample(width=1280, height=960, seconds=4)

    assert keyframe_times(generate_proxy_video(source, tmp_path / "proxy.mp4"), tmp_path) == pytest.approx([0, 2], abs=0.05)


def test_generate_keyframe_index_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_keyframe_index(tmp_path / "missing.mp4", tmp_path / "keyframes.json")


def last_keyframe_before(path, seconds):
    """The encoder of the synthetic samples does not always place keyframes on exact seconds."""
    with av.open(str(path)) as container:
        packets = container.demux(container.streams.video[0])
        return max(float(p.pts * p.time_base) for p in packets if p.size and p.is_keyframe and p.pts * p.time_base <= seconds)


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_cut_media_starts_on_the_previous_keyframe(make_sample, tmp_path, extension, video_codec, audio_codec):
    source = make_sample(extension, video_codec, audio_codec, seconds=10, gop_size=50)
    output = tmp_path / f"cut.{extension}"

    cut = cut_media(source, output, 3.0, 7.0)

    media = inspect_media(output)
    assert cut.path == output
    assert cut.start_seconds == pytest.approx(last_keyframe_before(source, 3.0), abs=0.1)
    assert media.duration_seconds == pytest.approx(7 - cut.start_seconds, abs=0.5)
    assert media.streams_of("video")[0].codec_name == inspect_media(source).streams_of("video")[0].codec_name
    assert media.streams_of("audio")[0].codec_name == inspect_media(source).streams_of("audio")[0].codec_name


@pytest.mark.parametrize("extension,video_codec,audio_codec", CONTAINERS)
def test_cut_media_output_can_be_processed(make_sample, tmp_path, extension, video_codec, audio_codec):
    source = make_sample(extension, video_codec, audio_codec, seconds=10, gop_size=50)
    cut = cut_media(source, tmp_path / f"cut.{extension}", 3.0, 7.0)

    proxy_path = generate_proxy_video(cut.path, tmp_path / "proxy.mp4")

    assert inspect_media(proxy_path).duration_seconds == pytest.approx(inspect_media(cut.path).duration_seconds, abs=0.5)
    check_packet_integrity(scan_packets(cut.path))


def test_cut_media_can_keep_until_the_end(make_sample, tmp_path):
    cut = cut_media(make_sample(seconds=10, gop_size=50), tmp_path / "cut.mp4", 4.0, math.inf)

    assert 0 < cut.start_seconds <= 4
    assert inspect_media(cut.path).duration_seconds == pytest.approx(10 - cut.start_seconds, abs=0.5)


def test_cut_media_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        cut_media(tmp_path / "missing.mp4", tmp_path / "cut.mp4", 0.0, 1.0)


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


def read_waveform(path):
    return json.loads(path.read_text())


def test_generate_waveform_measures_each_window(tmp_path):
    wav_path = write_tone(tmp_path / "tone.wav", 0.5, seconds=2, silent_seconds=1)

    waveform = read_waveform(generate_waveform(wav_path, tmp_path / "analysis" / "waveform.json"))

    assert waveform["window_seconds"] == 0.1
    assert len(waveform["peaks"]) == len(waveform["rms"]) == 30
    assert set(waveform["peaks"][:10]) == set(waveform["rms"][:10]) == {0}
    assert waveform["peaks"][20] == pytest.approx(0.5, abs=0.01)
    assert waveform["rms"][20] == pytest.approx(0.5 / math.sqrt(2), abs=0.01)


def test_generate_waveform_keeps_a_shorter_last_window(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.video.ingestion.WAVEFORM_WINDOW_SECONDS", 0.3)
    wav_path = write_tone(tmp_path / "tone.wav", 0.5, seconds=1)

    waveform = read_waveform(generate_waveform(wav_path, tmp_path / "waveform.json"))

    assert len(waveform["rms"]) == 4
    assert waveform["rms"][-1] == pytest.approx(0.5 / math.sqrt(2), abs=0.01)


def test_generate_waveform_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_waveform(tmp_path / "missing.wav", tmp_path / "waveform.json")


def test_check_audio_not_silent_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        check_audio_not_silent(tmp_path / "missing.wav")


def test_check_audio_not_silent_rejects_very_quiet_tone(tmp_path):
    with pytest.raises(ValueError, match="silent"):
        check_audio_not_silent(write_tone(tmp_path / "tone.wav", 0.001))  # about -63 dBFS RMS
