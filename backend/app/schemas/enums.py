from __future__ import annotations

from enum import Enum


class JobTypeEnum(str, Enum):
    """Identifica a ação atómica ou pipeline a executar."""
    INGESTION="ingestion" # descarregar vídeos de fontes externas.
    #CLIPPING="clipping" # operações de corte
    TRANSCRIPTION="transcription" #extrair faixa de áudio
    #FULL_PIPELINE="full_pipeline" #ciclo completo

class JobStatusEnum(str, Enum):
    """Máquina de estados global do trabalho assíncrono."""
    PENDING="pending" # persistente na bd
    QUEUED="queued" # no broker
    PROCESSING="processing" # a ser executada no Worker
    COMPLETED="completed"  # execução concluída com sucesso
    FAILED="failed" # execução falhada por erro
    CANCELLED="cancelled" #interrompida pelo utilizador


class JobStepProcessingEnum(str, Enum):
    """Fases granulares para reporte de progresso na interface."""
    INITIALIZING="initializing"         # Criação do workspace temporário isolado no disco do worker
    DOWNLOADING_MEDIA="downloading_media"       # Descarregamento da fonte de vídeo via rede ou storage
    EXTRACTING_AUDIO="extracting_audio"         # Extração e conversão do fluxo áudio para análise
    GENERATING_PROXY = "generating_proxy"       # proxy 720p + keyframes
    #SCANNING_FACES="scanning_faces" # Deteção e correspondência facial nos frames com visão computacional
    TRANSCRIBING="transcribing"             # Inferência de reconhecimento de fala com Whisper
    #EXPORTING_CLIPS="exporting_clips"          # Codificação e corte físico dos ficheiros MP4 finais
    DIARIZING = "diarizing"         #quem falou quando
    PERSISTING_RESULTS = "persisting_results"       # envio dos artefactos para storage/BD
    CLEANING_UP="cleaning_up"           # Envio dos artefactos para o storage e remoção de ficheiros temporários
    FINISHED="finished"         # Todas as etapas e limpezas locais foram fechadas com êxito
    

class JobErrorCodeEnum(str, Enum):
    """Códigos de erro estáveis; a UI mapeia-os para mensagens"""
    
    INVALID_SOURCE = "invalid_source"
    SOURCE_UNAVAILABLE = "source_unavailable"
    DURATION_LIMIT_EXCEEDED = "duration_limit_exceeded"
    CORRUPTED_MEDIA = "corrupted_media"
    NO_AUDIO_TRACK = "no_audio_track"
    INTERNAL_ERROR = "internal_error"
    
    
class AcousticProfileEnum(str, Enum):
    """Perfil de contexto acústico"""
    LECTURE = "lecture"
    DEBATE = "debate"
    CONFERENCE = "conference"
    INTERVIEW = "interview"