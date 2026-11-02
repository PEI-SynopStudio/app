import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router";
import { ConfirmDialog } from "../../components/Dialog";
import { ToolButton } from "../../components/editor/controls";
import { ExportDialog } from "../../components/editor/ExportDialog";
import { Inspector } from "../../components/editor/Inspector";
import { LibraryPanel } from "../../components/editor/LibraryPanel";
import { Stage } from "../../components/editor/Stage";
import { Timeline } from "../../components/editor/Timeline";
import { IconArrowLeft, IconCheck, IconDownload, IconRedo, IconShare, IconUndo } from "../../components/Icons";
import { ShareDialog } from "../../components/ShareDialog";
import { getClip, type Clip, type Project } from "../../data/mock";
import { FORMATS, type AspectRatio, type CaptionSettings } from "../../data/options";
import { useHistory } from "../../hooks/useHistory";
import { useMotion, usePageEnter } from "../../hooks/useMotion";
import { useTransport } from "../../hooks/useTransport";
import {
  DEFAULT_ZOOM,
  MIN_LENGTH,
  TEXT_LENGTH,
  TEXT_PRESETS,
  TRANSITION_LENGTH,
  ZOOM_LEVELS,
  canPlace,
  contentEnd,
  createDoc,
  createId,
  findFreeStart,
  insertLength,
  itemContent,
  itemEnd,
  projectAssets,
  splitItem,
  type EditorDoc,
  type MediaAsset,
  type TextLayer,
  type TimelineItem,
  type Transition,
  type TransitionType,
} from "../../lib/editor";
import { DURATION, EASE, gsap } from "../../lib/gsap";
import { readMediaFile } from "../../lib/media";
import { plural } from "../../lib/utils";
import "../../styles/app.css";
import "../../styles/studio.css";

type DocUpdate = (doc: EditorDoc) => EditorDoc;

function updateItem(id: string, patch: Partial<TimelineItem>): DocUpdate {
  return (doc) => ({ ...doc, items: doc.items.map((item) => (item.id === id ? { ...item, ...patch } : item)) });
}

export function ClipEditor() {
  const { projectId, clipId } = useParams();
  const found = getClip(projectId, clipId);
  if (!found) return <ClipMissing projectId={projectId} />;
  return <Studio key={found.clip.id} project={found.project} clip={found.clip} />;
}

function ClipMissing({ projectId }: { projectId?: string }) {
  return (
    <main className="studio-missing">
      <div className="empty">
        <p>This clip does not exist or has been removed.</p>
        <Link to={projectId ? `/app/projects/${projectId}` : "/app"} className="btn btn--ghost btn--sm">
          Back to project
        </Link>
      </div>
    </main>
  );
}

function Studio({ project, clip }: { project: Project; clip: Clip }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const { state: doc, commit, preview, end, undo, redo, canUndo, canRedo } = useHistory(() =>
    createDoc(project, clip),
  );
  const [savedDoc, setSavedDoc] = useState(doc);
  const [title, setTitle] = useState(clip.title);
  const [savedTitle, setSavedTitle] = useState(clip.title);
  const [savedAt, setSavedAt] = useState(0);
  const [assets, setAssets] = useState<MediaAsset[]>(() => projectAssets(project));
  const [importing, setImporting] = useState(0);
  const [importError, setImportError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [snapping, setSnapping] = useState(true);
  const [shareOpen, setShareOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const assetMap = useMemo(() => Object.fromEntries(assets.map((asset) => [asset.id, asset])), [assets]);
  const usedAssetIds = useMemo(
    () => new Set(doc.items.flatMap((item) => (item.assetId ? [item.assetId] : []))),
    [doc.items],
  );
  const duration = contentEnd(doc.items);
  const transport = useTransport(duration);
  const { time } = transport;
  const selected = doc.items.find((item) => item.id === selectedId) ?? null;
  const canSplit = selected !== null && time > selected.start + MIN_LENGTH && time < itemEnd(selected) - MIN_LENGTH;
  const isDirty = doc !== savedDoc || title !== savedTitle;
  const clipNumber = String(project.clips.indexOf(clip) + 1).padStart(2, "0");

  usePageEnter(rootRef);

  // "Saved" confirmation: a small scale pop, no overshoot.
  useMotion(
    rootRef,
    () => {
      if (!savedAt) return;
      gsap.from("[data-saved]", { scale: 0.85, autoAlpha: 0, duration: DURATION.base, ease: EASE.out });
    },
    [savedAt],
  );

  // Unsaved work: confirm before leaving inside the app, and let the browser warn on tab close.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => isDirty && currentLocation.pathname !== nextLocation.pathname,
  );

  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  // Object URLs of imported files are released when the editor closes.
  const assetsRef = useRef(assets);
  useEffect(() => {
    assetsRef.current = assets;
  }, [assets]);
  useEffect(
    () => () => {
      for (const asset of assetsRef.current) if (asset.url) URL.revokeObjectURL(asset.url);
    },
    [],
  );

  // ---------- Editing ----------

  function addAsset(asset: MediaAsset, trackId?: string, at = time) {
    const track =
      doc.tracks.find((candidate) => candidate.id === trackId) ??
      doc.tracks.find((candidate) => candidate.kind === (asset.kind === "audio" ? "audio" : "video"));
    if (!track || !canPlace(track, asset.kind)) return;
    const id = createId("item");
    const length = insertLength(asset);
    commit((current) => {
      const item: TimelineItem = {
        id,
        trackId: track.id,
        kind: "media",
        assetId: asset.id,
        start: findFreeStart(current.items, track.id, at, length),
        duration: length,
        inPoint: 0,
        volume: 1,
        opacity: 1,
        fit: "cover",
      };
      return { ...current, items: [...current.items, item] };
    });
    setSelectedId(id);
  }

  function addText(layer: TextLayer, trackId?: string, at = time) {
    const track =
      doc.tracks.find((candidate) => candidate.id === trackId) ??
      doc.tracks.find((candidate) => candidate.kind === "text");
    if (!track) return;
    const id = createId("item");
    commit((current) => {
      const item: TimelineItem = {
        id,
        trackId: track.id,
        kind: "text",
        text: layer,
        start: findFreeStart(current.items, track.id, at, TEXT_LENGTH),
        duration: TEXT_LENGTH,
        opacity: 1,
      };
      return { ...current, items: [...current.items, item] };
    });
    setSelectedId(id);
  }

  function applyTransition(type: TransitionType, itemId = selectedId, edge: "in" | "out" = "in") {
    const item = doc.items.find((candidate) => candidate.id === itemId);
    if (!item) return;
    const transition: Transition = {
      type: itemContent(item, assetMap) === "audio" ? "fade" : type,
      duration: Math.min(TRANSITION_LENGTH, item.duration / 2),
    };
    commit(updateItem(item.id, edge === "in" ? { transitionIn: transition } : { transitionOut: transition }));
    setSelectedId(item.id);
  }

  function editSelected(patch: Partial<TimelineItem>, live = false) {
    if (!selected) return;
    if (live) preview(updateItem(selected.id, patch));
    else commit(updateItem(selected.id, patch));
  }

  function splitSelected() {
    if (!selected) return;
    const rightId = createId("item");
    const parts = splitItem(selected, time, rightId);
    if (!parts) return;
    commit((current) => ({
      ...current,
      items: current.items.flatMap((item) => (item.id === selected.id ? parts : [item])),
    }));
    setSelectedId(rightId);
  }

  function duplicateSelected() {
    if (!selected) return;
    const id = createId("item");
    commit((current) => {
      const start = findFreeStart(current.items, selected.trackId, itemEnd(selected), selected.duration);
      return { ...current, items: [...current.items, { ...selected, id, start }] };
    });
    setSelectedId(id);
  }

  function removeSelected() {
    if (!selected) return;
    commit((current) => ({ ...current, items: current.items.filter((item) => item.id !== selected.id) }));
    setSelectedId(null);
  }

  function toggleTrack(trackId: string, flag: "muted" | "hidden") {
    commit((current) => ({
      ...current,
      tracks: current.tracks.map((track) => {
        if (track.id !== trackId) return track;
        return flag === "muted" ? { ...track, muted: !track.muted } : { ...track, hidden: !track.hidden };
      }),
    }));
  }

  function setFormat(format: AspectRatio) {
    commit((current) => ({ ...current, format }));
  }

  function setCaptions(captions: CaptionSettings | null) {
    commit((current) => ({ ...current, captions }));
  }

  async function importFiles(files: File[]) {
    setImportError(null);
    setImporting((count) => count + files.length);
    const results = await Promise.all(files.map(readMediaFile));
    setImporting((count) => count - files.length);
    const added = results.filter((asset): asset is MediaAsset => asset !== null);
    const failed = files.length - added.length;
    if (failed > 0) {
      setImportError(`${plural(failed, "file", "files")} could not be read. Use video, audio or image files.`);
    }
    // TODO(api): upload each file to /projects/:projectId/assets and swap the object URL for the stored one.
    setAssets((current) => [...current, ...added]);
  }

  function removeAsset(asset: MediaAsset) {
    if (usedAssetIds.has(asset.id)) return;
    if (asset.url) URL.revokeObjectURL(asset.url);
    setAssets((current) => current.filter((candidate) => candidate.id !== asset.id));
  }

  function save() {
    if (!isDirty) return;
    // TODO(api): PUT /projects/:projectId/clips/:clipId/edit with { title, ...doc } (uploads as asset ids, not object URLs).
    setSavedDoc(doc);
    setSavedTitle(title);
    setSavedAt(Date.now());
  }

  const changeZoom = useCallback(
    (delta: number) => setZoom((current) => Math.min(Math.max(current + delta, 0), ZOOM_LEVELS.length - 1)),
    [],
  );

  // ---------- Keyboard ----------

  const handleKey = useRef<(event: KeyboardEvent) => void>(() => undefined);

  useEffect(() => {
    handleKey.current = (event) => {
      if (event.defaultPrevented || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      if (document.querySelector("dialog[open]")) return;
      const key = event.key.toLowerCase();

      if (event.ctrlKey || event.metaKey) {
        if (key === "z") {
          event.preventDefault();
          if (event.shiftKey) redo();
          else undo();
        } else if (key === "y") {
          event.preventDefault();
          redo();
        } else if (key === "s") {
          event.preventDefault();
          save();
        } else if (key === "d") {
          event.preventDefault();
          duplicateSelected();
        }
        return;
      }

      switch (key) {
        case " ":
          event.preventDefault();
          transport.toggle();
          break;
        case "s":
          splitSelected();
          break;
        case "delete":
        case "backspace":
          event.preventDefault();
          removeSelected();
          break;
        case "arrowleft":
        case "arrowright": {
          event.preventDefault();
          const step = event.shiftKey ? 1 : 0.1;
          transport.seek(time + (key === "arrowleft" ? -step : step));
          break;
        }
        case "home":
          event.preventDefault();
          transport.seek(0);
          break;
        case "end":
          event.preventDefault();
          transport.seek(duration);
          break;
        case "escape":
          setSelectedId(null);
          break;
      }
    };
  });

  useEffect(() => {
    const listener = (event: KeyboardEvent) => handleKey.current(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  // ---------- Layout ----------

  return (
    <div className="studio surface-dark" ref={rootRef}>
      <header className="studio__bar" data-enter>
        <div className="studio__bar-start">
          <Link
            to={`/app/projects/${project.id}`}
            className="tool-btn"
            aria-label={`Back to ${project.title}`}
            title="Back to project"
          >
            <IconArrowLeft />
          </Link>
          <div className="studio__heading">
            <input
              className="studio__title"
              value={title}
              maxLength={120}
              placeholder="Untitled clip"
              aria-label="Clip title"
              onChange={(event) => setTitle(event.target.value)}
            />
            <p className="studio__crumb">
              {project.title} · Clip {clipNumber}
            </p>
          </div>
        </div>

        <div className="studio__bar-middle">
          <ToolButton label="Undo (Ctrl+Z)" onClick={undo} disabled={!canUndo}>
            <IconUndo />
          </ToolButton>
          <ToolButton label="Redo (Ctrl+Shift+Z)" onClick={redo} disabled={!canRedo}>
            <IconRedo />
          </ToolButton>
          <span className="studio__divider" aria-hidden="true" />
          <label className="studio__format">
            <span className="sr-only">Format</span>
            <select
              className="input"
              value={doc.format}
              onChange={(event) => {
                const format = FORMATS.find((option) => option.value === event.target.value)?.value;
                if (format) setFormat(format);
              }}
            >
              {FORMATS.map((format) => (
                <option key={format.value} value={format.value}>
                  {format.value} · {format.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="studio__bar-end">
          <p className="saved" role="status">
            {isDirty ? (
              <span className="studio__unsaved">Unsaved changes</span>
            ) : (
              savedAt > 0 && (
                <span className="saved__inner" data-saved>
                  <IconCheck /> Saved
                </span>
              )
            )}
          </p>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setShareOpen(true)}>
            <IconShare /> Share
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={save} disabled={!isDirty}>
            Save
          </button>
          <button
            type="button"
            className="btn btn--accent btn--sm"
            disabled={duration <= 0}
            onClick={() => {
              transport.pause();
              setExportOpen(true);
            }}
          >
            <IconDownload /> Export
          </button>
        </div>
      </header>

      <LibraryPanel
        assets={assets}
        usedAssetIds={usedAssetIds}
        importing={importing > 0}
        importError={importError}
        captions={doc.captions}
        hasSelection={selected !== null}
        onImport={(files) => void importFiles(files)}
        onAddAsset={(asset) => addAsset(asset)}
        onRemoveAsset={removeAsset}
        onAddText={(layer) => addText(layer)}
        onApplyTransition={(type) => applyTransition(type)}
        onCaptionsChange={setCaptions}
      />

      <Stage
        doc={doc}
        assets={assetMap}
        time={time}
        duration={duration}
        isPlaying={transport.isPlaying}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onToggle={transport.toggle}
        onSeek={transport.seek}
      />

      <Inspector
        item={selected}
        asset={selected?.assetId ? assetMap[selected.assetId] : undefined}
        track={doc.tracks.find((track) => track.id === selected?.trackId)}
        duration={duration}
        itemCount={doc.items.length}
        canSplit={canSplit}
        onPreview={(patch) => editSelected(patch, true)}
        onCommit={(patch) => editSelected(patch)}
        onSettle={end}
        onSplit={splitSelected}
        onDuplicate={duplicateSelected}
        onDelete={removeSelected}
      />

      <Timeline
        doc={doc}
        assets={assetMap}
        time={time}
        duration={duration}
        isPlaying={transport.isPlaying}
        selectedId={selectedId}
        zoom={zoom}
        snapping={snapping}
        canSplit={canSplit}
        onSelect={setSelectedId}
        onSeek={transport.seek}
        onPreview={preview}
        onCommit={commit}
        onGestureEnd={end}
        onDropAsset={(assetId, trackId, at) => {
          const asset: MediaAsset | undefined = assetMap[assetId];
          if (asset) addAsset(asset, trackId, at);
        }}
        onDropText={(presetId, trackId, at) => {
          const preset = TEXT_PRESETS.find((candidate) => candidate.id === presetId);
          if (preset) addText(preset.layer, trackId, at);
        }}
        onDropTransition={(itemId, type, edge) => applyTransition(type, itemId, edge)}
        onToggleTrack={toggleTrack}
        onZoom={changeZoom}
        onSnappingChange={setSnapping}
        onSplit={splitSelected}
        onDuplicate={duplicateSelected}
        onDelete={removeSelected}
      />

      <ShareDialog open={shareOpen} onClose={() => setShareOpen(false)} project={project} clip={clip} />
      <ExportDialog
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        title={title.trim() || "Untitled clip"}
        format={doc.format}
        duration={duration}
        hasCaptions={doc.captions !== null}
      />
      <ConfirmDialog
        open={blocker.state === "blocked"}
        onClose={() => blocker.reset?.()}
        onConfirm={() => blocker.proceed?.()}
        title="Leave without saving?"
        description="Your changes to this clip since the last save will be lost."
        confirmLabel="Discard changes"
      />
    </div>
  );
}