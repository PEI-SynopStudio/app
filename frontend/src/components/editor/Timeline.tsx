import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import {
  DRAG_TRANSITION,
  DRAG_TYPES,
  MIN_LENGTH,
  SNAP_PX,
  ZOOM_LEVELS,
  canPlace,
  collides,
  draggedContent,
  isTransitionType,
  itemAt,
  itemContent,
  itemEnd,
  maxLength,
  snapPoints,
  snapStart,
  snapTime,
  trimBounds,
  type EditorDoc,
  type MediaAsset,
  type TimelineItem,
  type Track,
  type TrackKind,
  type TransitionType,
} from "../../lib/editor";
import { formatTime, formatTimecode } from "../../lib/utils";
import {
  IconCopy,
  IconEye,
  IconEyeOff,
  IconFilm,
  IconImage,
  IconMagnet,
  IconMinus,
  IconMusic,
  IconPlus,
  IconScissors,
  IconText,
  IconTrash,
  IconVolume,
  IconVolumeOff,
} from "../Icons";
import { ToolButton, rangeFill } from "./controls";

type DocUpdate = (doc: EditorDoc) => EditorDoc;

interface TimelineProps {
  doc: EditorDoc;
  assets: Record<string, MediaAsset>;
  time: number;
  duration: number;
  isPlaying: boolean;
  selectedId: string | null;
  zoom: number; // index into ZOOM_LEVELS
  snapping: boolean;
  canSplit: boolean;
  onSelect: (id: string | null) => void;
  onSeek: (time: number) => void;
  onPreview: (update: DocUpdate) => void;
  onCommit: (update: DocUpdate) => void;
  onGestureEnd: () => void;
  onDropAsset: (assetId: string, trackId: string, at: number) => void;
  onDropText: (presetId: string, trackId: string, at: number) => void;
  onDropTransition: (itemId: string, type: TransitionType, edge: "in" | "out") => void;
  onToggleTrack: (trackId: string, flag: "muted" | "hidden") => void;
  onZoom: (delta: number) => void;
  onSnappingChange: (snapping: boolean) => void;
  onSplit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

interface Gesture {
  mode: "move" | "trim-start" | "trim-end";
  item: TimelineItem; // as it was when the pointer went down
  x: number;
  y: number;
  moved: boolean;
}

const RULER_H = 28;
const ROW_H: Record<TrackKind, number> = { text: 40, overlay: 48, video: 64, audio: 48 };
const ITEM_INSET = 5;
const TAIL = 30; // seconds of empty timeline after the last clip, room to drop more
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

const TRACK_ICONS: Record<TrackKind, ReactNode> = {
  video: <IconFilm />,
  overlay: <IconImage />,
  text: <IconText />,
  audio: <IconMusic />,
};

const TRACK_HINTS: Record<TrackKind, string> = {
  video: "Drop video or images here",
  overlay: "Drop media to layer it over the video",
  text: "Drop text styles here",
  audio: "Drop music or a voice-over here",
};

function replaceItem(next: TimelineItem): DocUpdate {
  return (doc) => ({ ...doc, items: doc.items.map((item) => (item.id === next.id ? next : item)) });
}

export function Timeline({
  doc,
  assets,
  time,
  duration,
  isPlaying,
  selectedId,
  zoom,
  snapping,
  canSplit,
  onSelect,
  onSeek,
  onPreview,
  onCommit,
  onGestureEnd,
  onDropAsset,
  onDropText,
  onDropTransition,
  onToggleTrack,
  onZoom,
  onSnappingChange,
  onSplit,
  onDuplicate,
  onDelete,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const timeRef = useRef(time);
  const [dropTrackId, setDropTrackId] = useState<string | null>(null);
  const [dropItemId, setDropItemId] = useState<string | null>(null);

  const pps = ZOOM_LEVELS[zoom];
  const width = (Math.max(duration, 10) + TAIL) * pps;
  const step = RULER_STEPS.find((value) => value * pps >= 72) ?? RULER_STEPS[RULER_STEPS.length - 1];
  const ticks = Array.from({ length: Math.floor(width / pps / step) + 1 }, (_, index) => index * step);

  // Rows are only backgrounds; items sit in one layer above them, so a clip keeps its
  // element (and its pointer capture) when it is dragged to another track.
  const rowTop: Record<string, number> = {};
  let nextTop = RULER_H;
  for (const track of doc.tracks) {
    rowTop[track.id] = nextTop;
    nextTop += ROW_H[track.kind];
  }
  const tracksById = Object.fromEntries(doc.tracks.map((track) => [track.id, track]));

  useEffect(() => {
    timeRef.current = time;
  }, [time]);

  // Keep the playhead in view while playing.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || !isPlaying) return;
    const x = time * pps;
    if (x < scroller.scrollLeft || x > scroller.scrollLeft + scroller.clientWidth - 40) scroller.scrollLeft = x - 40;
  }, [time, pps, isPlaying]);

  // After a zoom, bring the playhead back to the middle.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (scroller) scroller.scrollLeft = timeRef.current * pps - scroller.clientWidth / 2;
  }, [pps]);

  // Ctrl/⌘ + wheel zooms; a plain wheel scrolls sideways (the timeline has nothing above or below).
  // Needs a non-passive listener to stop the page from zooming or scrolling.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        onZoom(event.deltaY < 0 ? 1 : -1);
      } else if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
        event.preventDefault();
        scroller.scrollLeft += event.deltaY;
      }
    };
    scroller.addEventListener("wheel", handleWheel, { passive: false });
    return () => scroller.removeEventListener("wheel", handleWheel);
  }, [onZoom]);

  function timeAt(clientX: number): number {
    const content = contentRef.current;
    return content ? Math.max(0, (clientX - content.getBoundingClientRect().left) / pps) : 0;
  }

  function trackAtY(clientY: number): Track | undefined {
    const content = contentRef.current;
    if (!content) return undefined;
    const y = clientY - content.getBoundingClientRect().top;
    return doc.tracks.find((track) => y >= rowTop[track.id] && y < rowTop[track.id] + ROW_H[track.kind]);
  }

  function itemAtPoint(clientX: number, clientY: number): TimelineItem | undefined {
    const track = trackAtY(clientY);
    return track ? itemAt(doc.items, track.id, timeAt(clientX)) : undefined;
  }

  // ---------- Playhead ----------

  function handleRulerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    onSeek(timeAt(event.clientX));
  }

  function handleRulerMove(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) onSeek(timeAt(event.clientX));
  }

  function handleRowDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    onSelect(null);
    onSeek(timeAt(event.clientX));
  }

  // ---------- Move and trim ----------

  function startGesture(event: PointerEvent<HTMLElement>, item: TimelineItem, mode: Gesture["mode"]) {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    onSelect(item.id);
    gesture.current = { mode, item, x: event.clientX, y: event.clientY, moved: false };
  }

  function moveGesture(event: PointerEvent<HTMLElement>) {
    const current = gesture.current;
    if (!current) return;
    if (!current.moved && Math.hypot(event.clientX - current.x, event.clientY - current.y) < 3) return;
    current.moved = true;

    const { item, mode } = current;
    const asset: MediaAsset | undefined = item.assetId ? assets[item.assetId] : undefined;
    const delta = (event.clientX - current.x) / pps;
    const others = doc.items.filter((other) => other.id !== item.id);
    const points = snapping ? snapPoints(others, time) : [];
    const threshold = SNAP_PX / pps;

    if (mode === "move") {
      const live = doc.items.find((other) => other.id === item.id) ?? item;
      const target = trackAtY(event.clientY);
      const trackId = target && canPlace(target, itemContent(item, assets)) ? target.id : live.trackId;
      const start = Math.max(0, snapStart(item.start + delta, item.duration, points, threshold));
      if (collides(doc.items, trackId, start, item.duration, item.id)) return; // stays at the last free spot
      onPreview(replaceItem({ ...live, start, trackId }));
      return;
    }

    const bounds = trimBounds(doc.items, item);
    const end = itemEnd(item);
    const limited = maxLength(item, asset) !== Infinity;

    if (mode === "trim-start") {
      // Video and audio cannot start before their first frame; images and text stretch freely.
      const earliest = Math.max(bounds.min, limited ? item.start - (item.inPoint ?? 0) : 0);
      const start = Math.min(Math.max(snapTime(item.start + delta, points, threshold), earliest), end - MIN_LENGTH);
      const inPoint = item.kind === "media" ? (item.inPoint ?? 0) + start - item.start : item.inPoint;
      onPreview(replaceItem({ ...item, start, duration: end - start, inPoint }));
    } else {
      const latest = Math.min(bounds.max, item.start + maxLength(item, asset));
      const nextEnd = Math.min(Math.max(snapTime(end + delta, points, threshold), item.start + MIN_LENGTH), latest);
      onPreview(replaceItem({ ...item, duration: nextEnd - item.start }));
    }
  }

  function endGesture() {
    if (!gesture.current) return;
    gesture.current = null;
    onGestureEnd();
  }

  // Arrow keys nudge the focused clip by 0.1 s (Shift: 1 s).
  function handleItemKey(event: KeyboardEvent<HTMLDivElement>, item: TimelineItem) {
    if (event.key === "Enter") {
      onSelect(item.id);
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    event.stopPropagation();
    const step = (event.shiftKey ? 1 : 0.1) * (event.key === "ArrowLeft" ? -1 : 1);
    const start = Math.max(0, item.start + step);
    onSelect(item.id);
    if (!collides(doc.items, item.trackId, start, item.duration, item.id)) onCommit(replaceItem({ ...item, start }));
  }

  // ---------- Drops from the library ----------

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    const types = event.dataTransfer.types;
    if (types.includes(DRAG_TRANSITION)) {
      const item = itemAtPoint(event.clientX, event.clientY);
      setDropItemId(item?.id ?? null);
      if (!item) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
      return;
    }
    const content = draggedContent(types);
    const track = trackAtY(event.clientY);
    const fits = track !== undefined && canPlace(track, content);
    setDropTrackId(fits ? track.id : null);
    if (!fits) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDropTrackId(null);
    setDropItemId(null);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    setDropTrackId(null);
    setDropItemId(null);
    const types = event.dataTransfer.types;

    if (types.includes(DRAG_TRANSITION)) {
      const item = itemAtPoint(event.clientX, event.clientY);
      const type = event.dataTransfer.getData(DRAG_TRANSITION);
      if (!item || !isTransitionType(type)) return;
      event.preventDefault();
      // The half of the clip it lands on decides between entrance and exit.
      onDropTransition(item.id, type, timeAt(event.clientX) < item.start + item.duration / 2 ? "in" : "out");
      return;
    }

    const content = draggedContent(types);
    const track = trackAtY(event.clientY);
    if (!content || !track || !canPlace(track, content)) return;
    event.preventDefault();
    const id = event.dataTransfer.getData(DRAG_TYPES[content]);
    const at = timeAt(event.clientX);
    const start = snapping ? snapTime(at, snapPoints(doc.items, time), SNAP_PX / pps) : at;
    if (content === "text") onDropText(id, track.id, start);
    else onDropAsset(id, track.id, start);
  }

  // ---------- Render ----------

  function renderItem(item: TimelineItem) {
    const track = tracksById[item.trackId];
    if (!track) return null;
    const asset: MediaAsset | undefined = item.assetId ? assets[item.assetId] : undefined;
    const content = itemContent(item, assets);
    const label = item.kind === "text" ? item.text?.content.trim() || "Text" : (asset?.name ?? "Missing media");
    const isSelected = item.id === selectedId;
    const className = [
      "tl-item",
      `tl-item--${content ?? "missing"}`,
      isSelected && "is-selected",
      dropItemId === item.id && "is-drop",
      (track.hidden || track.muted) && "is-dim",
    ]
      .filter(Boolean)
      .join(" ");
    const style: CSSProperties = {
      top: rowTop[item.trackId] + ITEM_INSET,
      height: ROW_H[track.kind] - ITEM_INSET * 2,
      left: item.start * pps,
      width: Math.max(item.duration * pps, 4),
    };
    if (asset?.kind === "image" && asset.url) style.backgroundImage = `url("${asset.url}")`;

    return (
      <div
        key={item.id}
        className={className}
        style={style}
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        aria-label={`${label}, ${formatTimecode(item.start)} to ${formatTimecode(itemEnd(item))}`}
        onPointerDown={(event) => startGesture(event, item, "move")}
        onPointerMove={moveGesture}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        onKeyDown={(event) => handleItemKey(event, item)}
      >
        {item.transitionIn && (
          <span
            className="tl-item__fx tl-item__fx--in"
            style={{ width: Math.min(item.transitionIn.duration, item.duration) * pps }}
          />
        )}
        {item.transitionOut && (
          <span
            className="tl-item__fx tl-item__fx--out"
            style={{ width: Math.min(item.transitionOut.duration, item.duration) * pps }}
          />
        )}
        <span className="tl-item__label">{label}</span>
        <span className="tl-item__length">{formatTimecode(item.duration)}</span>
        <span
          className="tl-item__handle tl-item__handle--start"
          onPointerDown={(event) => startGesture(event, item, "trim-start")}
        />
        <span
          className="tl-item__handle tl-item__handle--end"
          onPointerDown={(event) => startGesture(event, item, "trim-end")}
        />
      </div>
    );
  }

  return (
    <section className="tl" aria-label="Timeline" data-enter>
      <div className="tl-bar">
        <div className="tl-bar__group">
          <ToolButton label="Split at playhead (S)" onClick={onSplit} disabled={!canSplit}>
            <IconScissors />
          </ToolButton>
          <ToolButton label="Duplicate (Ctrl+D)" onClick={onDuplicate} disabled={!selectedId}>
            <IconCopy />
          </ToolButton>
          <ToolButton label="Delete (Del)" onClick={onDelete} disabled={!selectedId}>
            <IconTrash />
          </ToolButton>
        </div>
        <p className="tl-bar__hint">Drag clips to move them and their edges to trim · Ctrl + scroll to zoom</p>
        <div className="tl-bar__group">
          <ToolButton label="Snap to clips and playhead" pressed={snapping} onClick={() => onSnappingChange(!snapping)}>
            <IconMagnet />
          </ToolButton>
          <span className="tl-bar__divider" aria-hidden="true" />
          <ToolButton label="Zoom out" onClick={() => onZoom(-1)} disabled={zoom === 0}>
            <IconMinus />
          </ToolButton>
          <input
            className="range tl-bar__zoom"
            type="range"
            min={0}
            max={ZOOM_LEVELS.length - 1}
            step={1}
            value={zoom}
            aria-label="Timeline zoom"
            style={rangeFill(zoom, 0, ZOOM_LEVELS.length - 1)}
            onChange={(event) => onZoom(Number(event.target.value) - zoom)}
          />
          <ToolButton label="Zoom in" onClick={() => onZoom(1)} disabled={zoom === ZOOM_LEVELS.length - 1}>
            <IconPlus />
          </ToolButton>
        </div>
      </div>

      <div className="tl-body">
        <div className="tl-heads">
          <div className="tl-heads__corner" style={{ height: RULER_H }}>
            {formatTimecode(time)}
          </div>
          {doc.tracks.map((track) => (
            <div key={track.id} className="tl-head" style={{ height: ROW_H[track.kind] }}>
              <span className="tl-head__icon" aria-hidden="true">
                {TRACK_ICONS[track.kind]}
              </span>
              <span className="tl-head__label">{track.label}</span>
              <span className="tl-head__actions">
                {track.kind !== "audio" && (
                  <ToolButton
                    small
                    label={track.hidden ? `Show ${track.label} track` : `Hide ${track.label} track`}
                    pressed={Boolean(track.hidden)}
                    onClick={() => onToggleTrack(track.id, "hidden")}
                  >
                    {track.hidden ? <IconEyeOff /> : <IconEye />}
                  </ToolButton>
                )}
                {track.kind !== "text" && (
                  <ToolButton
                    small
                    label={track.muted ? `Unmute ${track.label} track` : `Mute ${track.label} track`}
                    pressed={Boolean(track.muted)}
                    onClick={() => onToggleTrack(track.id, "muted")}
                  >
                    {track.muted ? <IconVolumeOff /> : <IconVolume />}
                  </ToolButton>
                )}
              </span>
            </div>
          ))}
        </div>

        <div className="tl-scroll" ref={scrollRef}>
          <div
            className="tl-content"
            ref={contentRef}
            style={{ width }}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div
              className="tl-ruler"
              style={{ height: RULER_H, "--minor": `${(step * pps) / 4}px` } as CSSProperties}
              onPointerDown={handleRulerDown}
              onPointerMove={handleRulerMove}
              aria-hidden="true"
            >
              {ticks.map((tick) => (
                <span key={tick} className="tl-ruler__tick" style={{ left: tick * pps }}>
                  {step < 1 ? formatTimecode(tick) : formatTime(tick)}
                </span>
              ))}
            </div>

            {doc.tracks.map((track) => (
              <div
                key={track.id}
                className={dropTrackId === track.id ? "tl-track is-drop" : "tl-track"}
                data-kind={track.kind}
                style={{ height: ROW_H[track.kind] }}
                onPointerDown={handleRowDown}
              >
                {!doc.items.some((item) => item.trackId === track.id) && (
                  <span className="tl-track__hint">{TRACK_HINTS[track.kind]}</span>
                )}
              </div>
            ))}

            {doc.items.map(renderItem)}

            <div className="tl-playhead" style={{ transform: `translateX(${time * pps}px)` }} aria-hidden="true" />
          </div>
        </div>
      </div>
    </section>
  );
}