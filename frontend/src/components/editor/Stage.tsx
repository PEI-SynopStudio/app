import { useEffect, useRef, type CSSProperties } from "react";
import { CAPTION_SAMPLE, FORMAT_RATIO } from "../../data/options";
import {
  itemAt,
  itemGain,
  layerLook,
  type EditorDoc,
  type MediaAsset,
  type TextLayer,
  type TimelineItem,
  type Track,
} from "../../lib/editor";
import { formatTimecode } from "../../lib/utils";
import { Caption } from "../Caption";
import { IconFilm, IconPause, IconPlay, IconSkipBack } from "../Icons";
import { ToolButton } from "./controls";

interface StageProps {
  doc: EditorDoc;
  assets: Record<string, MediaAsset>;
  time: number;
  duration: number;
  isPlaying: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onToggle: () => void;
  onSeek: (time: number) => void;
}

export function Stage({ doc, assets, time, duration, isPlaying, selectedId, onSelect, onToggle, onSeek }: StageProps) {
  // Exactly at the end nothing sits under the playhead, so read the frame just before it.
  const at = duration > 0 ? Math.min(time, duration - 0.001) : 0;
  const layers: { track: Track; item: TimelineItem }[] = [];
  const sounds: TimelineItem[] = [];

  for (const track of doc.tracks) {
    const item = itemAt(doc.items, track.id, at);
    if (!item) continue;
    if (track.kind === "audio") {
      if (!track.muted) sounds.push(item);
    } else if (!track.hidden) {
      layers.unshift({ track, item }); // the first track in the list is drawn on top
    }
  }

  return (
    <section className="stage" aria-label="Preview" data-enter>
      <div className="stage__viewport" onPointerDown={() => onSelect(null)}>
        <div className="stage__frame" style={{ "--ratio": FORMAT_RATIO[doc.format] } as CSSProperties}>
          {layers.map(({ track, item }, index) => (
            <StageLayer
              key={item.id}
              track={track}
              item={item}
              asset={item.assetId ? assets[item.assetId] : undefined}
              time={at}
              isPlaying={isPlaying}
              isSelected={item.id === selectedId}
              zIndex={index + 1}
              onSelect={onSelect}
            />
          ))}
          {layers.length === 0 && (
            <p className="stage__empty">
              {doc.items.length === 0 ? "Import media and drag it onto the timeline" : "Nothing on screen here"}
            </p>
          )}
          {doc.captions && layers.length > 0 && (
            <Caption text={CAPTION_SAMPLE[doc.captions.language]} variant={doc.captions.style} />
          )}
        </div>

        {sounds.map((item) => {
          const asset: MediaAsset | undefined = item.assetId ? assets[item.assetId] : undefined;
          if (!asset?.url) return null;
          return (
            <SyncedMedia
              key={item.id}
              kind="audio"
              src={asset.url}
              time={(item.inPoint ?? 0) + at - item.start}
              playing={isPlaying}
              volume={itemGain(item, at)}
            />
          );
        })}
      </div>

      <div className="stage__transport">
        <ToolButton label="Back to start" onClick={() => onSeek(0)}>
          <IconSkipBack />
        </ToolButton>
        <button
          type="button"
          className="stage__play"
          aria-label={isPlaying ? "Pause" : "Play"}
          disabled={duration <= 0}
          onClick={onToggle}
        >
          {isPlaying ? <IconPause /> : <IconPlay />}
        </button>
        <p className="stage__time">
          <span>{formatTimecode(time)}</span> / {formatTimecode(duration)}
        </p>
      </div>
    </section>
  );
}

interface StageLayerProps {
  track: Track;
  item: TimelineItem;
  asset?: MediaAsset;
  time: number;
  isPlaying: boolean;
  isSelected: boolean;
  zIndex: number;
  onSelect: (id: string) => void;
}

function StageLayer({ track, item, asset, time, isPlaying, isSelected, zIndex, onSelect }: StageLayerProps) {
  const look = layerLook(item, time);
  const className = ["stage__layer", item.kind === "text" && "stage__layer--text", isSelected && "is-selected"]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      style={{ zIndex, ...look }}
      onPointerDown={(event) => {
        event.stopPropagation();
        onSelect(item.id);
      }}
    >
      {item.kind === "text" && item.text ? (
        <StageText layer={item.text} />
      ) : (
        <StageMedia item={item} asset={asset} time={time} isPlaying={isPlaying} muted={Boolean(track.muted)} />
      )}
    </div>
  );
}

function StageText({ layer }: { layer: TextLayer }) {
  return (
    <p
      className={`stage-text stage-text--${layer.position} stage-text--${layer.color} stage-text--bg-${layer.background}`}
      style={{ fontSize: `${layer.size}cqi`, fontWeight: layer.weight }}
    >
      <span className="stage-text__box">{layer.content || " "}</span>
    </p>
  );
}

interface StageMediaProps {
  item: TimelineItem;
  asset?: MediaAsset;
  time: number;
  isPlaying: boolean;
  muted: boolean;
}

function StageMedia({ item, asset, time, isPlaying, muted }: StageMediaProps) {
  if (!asset) return <SourcePlaceholder name="Missing media" />;
  const sourceTime = (item.inPoint ?? 0) + time - item.start;
  const fit = item.fit ?? "cover";

  if (!asset.url) return <SourcePlaceholder name={asset.name} time={(asset.offset ?? 0) + sourceTime} />;
  if (asset.kind === "image") {
    return <img className="stage-media" style={{ objectFit: fit }} src={asset.url} alt="" draggable={false} />;
  }
  return (
    <SyncedMedia
      kind="video"
      src={asset.url}
      time={sourceTime}
      playing={isPlaying}
      volume={muted ? 0 : itemGain(item, time)}
      fit={fit}
    />
  );
}

/** Project media lives on the server; until the API streams it, this stands in for the picture. */
function SourcePlaceholder({ name, time }: { name: string; time?: number }) {
  return (
    <div className="stage-source">
      {time !== undefined && (
        <span className="stage-source__strip" style={{ backgroundPositionX: `${time * -32}px` }} aria-hidden="true" />
      )}
      <IconFilm />
      <span className="stage-source__name">{name}</span>
      {time !== undefined && <span className="stage-source__time">{formatTimecode(time)}</span>}
    </div>
  );
}

interface SyncedMediaProps {
  kind: "video" | "audio";
  src: string;
  time: number; // seconds into the file
  playing: boolean;
  volume: number;
  fit?: "cover" | "contain";
}

/** A real <video>/<audio> that follows the editor clock; it is only corrected when it drifts. */
function SyncedMedia({ kind, src, time, playing, volume, fit }: SyncedMediaProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const media = videoRef.current ?? audioRef.current;
    if (media && Math.abs(media.currentTime - time) > (playing ? 0.3 : 0.04)) media.currentTime = time;
  }, [time, playing]);

  useEffect(() => {
    const media = videoRef.current ?? audioRef.current;
    if (media) media.volume = Math.min(Math.max(volume, 0), 1);
  }, [volume]);

  useEffect(() => {
    const media = videoRef.current ?? audioRef.current;
    if (!media) return;
    if (playing) media.play().catch(() => undefined);
    else media.pause();
  }, [playing]);

  if (kind === "audio") return <audio ref={audioRef} src={src} preload="auto" />;
  return <video ref={videoRef} className="stage-media" style={{ objectFit: fit }} src={src} preload="auto" playsInline />;
}