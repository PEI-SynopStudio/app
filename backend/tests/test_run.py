import sys
from pathlib import Path

# Adiciona a raiz do backend (/app) ao path do Python para encontrar o módulo 'app'
backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.services.video.ingestion import (
    download_youtube_video,
    inspect_media,
    extract_normalized_audio,
    generate_proxy_video,
)

# 1. Pasta de teste no volume persistente
test_dir = Path("/data/media/test_001")
test_dir.mkdir(parents=True, exist_ok=True)

video_path = test_dir / "sample.mp4"
audio_path = test_dir / "normalized_audio.wav"
proxy_path = test_dir / "proxy_720p.mp4"

print("--- 1. A testar download de 10 segundos do YouTube ---")
download_youtube_video(
    url="https://www.youtube.com/watch?v=9bZkp7q19f0",
    output_path=video_path,
    start_time="00:01:07",
    end_time="00:01:27",
)
print(f"[OK] Vídeo descarregado: {video_path.exists()} ({video_path.stat().st_size} bytes)")

print("\n--- 2. A testar inspeção com ffprobe ---")
info = inspect_media(video_path)
duration = info.get("format", {}).get("duration", "N/A")
print(f"[OK] Duração detetada: {duration}s")
print(f"[OK] Faixas: {[s.get('codec_type') for s in info.get('streams', [])]}")

print("\n--- 3. A testar extração de áudio (16kHz mono PCM) ---")
extract_normalized_audio(video_path, audio_path)
print(f"[OK] Áudio WAV criado: {audio_path.exists()} ({audio_path.stat().st_size} bytes)")

print("\n--- 4. A testar geração do proxy (720p H.264) ---")
generate_proxy_video(video_path, proxy_path)
print(f"[OK] Proxy MP4 criado: {proxy_path.exists()} ({proxy_path.stat().st_size} bytes)")

print("\n--- TESTE CONCLUÍDO COM SUCESSO! ---")