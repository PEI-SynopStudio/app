import { useId, useState, type ChangeEvent, type DragEvent, type ReactNode } from "react";
import type { CaptionSettings } from "../../data/options";
import {
  DRAG_TRANSITION,
  DRAG_TYPES,
  TEXT_PRESETS,
  TRANSITIONS,
  type AssetKind,
  type MediaAsset,
  type TextLayer,
  type TransitionType,
} from "../../lib/editor";
import { ACCEPTED_MEDIA } from "../../lib/media";
import { formatBytes, formatTime } from "../../lib/utils";
import { CaptionOptions } from "../CaptionOptions";
import {
  IconCaptions,
  IconFilm,
  IconImage,
  IconMusic,
  IconPlus,
  IconText,
  IconTransition,
  IconTrash,
  IconUpload,
} from "../Icons";
import { ToolButton } from "./controls";

type Tab = "media" | "text" | "transitions" | "subtitles";

const TABS: { value: Tab; label: string; icon: ReactNode }[] = [
  { value: "media", label: "Media", icon: <IconFilm /> },
  { value: "text", label: "Text", icon: <IconText /> },
  { value: "transitions", label: "Transitions", icon: <IconTransition /> },
  { value: "subtitles", label: "Subtitles", icon: <IconCaptions /> },
];

const ASSET_ICONS: Record<AssetKind, ReactNode> = {
  video: <IconFilm />,
  image: <IconImage />,
  audio: <IconMusic />,
};

interface LibraryPanelProps {
  assets: MediaAsset[];
  usedAssetIds: Set<string>;
  importing: boolean;
  importError: string | null;
  captions: CaptionSettings | null;
  hasSelection: boolean;
  onImport: (files: File[]) => void;
  onAddAsset: (asset: MediaAsset) => void;
  onRemoveAsset: (asset: MediaAsset) => void;
  onAddText: (layer: TextLayer) => void;
  onApplyTransition: (type: TransitionType) => void;
  onCaptionsChange: (captions: CaptionSettings | null) => void;
}

export function LibraryPanel(props: LibraryPanelProps) {
  const id = useId();
  const [tab, setTab] = useState<Tab>("media");

  return (
    <aside className="library" aria-label="Library" data-enter>
      <div className="library__tabs" role="tablist" aria-label="Library sections">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            id={`${id}-tab-${item.value}`}
            aria-selected={tab === item.value}
            aria-controls={`${id}-panel`}
            className="library__tab"
            onClick={() => setTab(item.value)}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      <div className="library__body" role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${tab}`}>
        {tab === "media" && <MediaTab {...props} />}
        {tab === "text" && <TextTab onAddText={props.onAddText} />}
        {tab === "transitions" && <TransitionsTab hasSelection={props.hasSelection} onApply={props.onApplyTransition} />}
        {tab === "subtitles" && (
          <section className="library__group">
            <h3 className="library__label">Subtitles</h3>
            <p className="library__help">Generated from the speech in the recording and burned into the export.</p>
            <CaptionOptions value={props.captions} onChange={props.onCaptionsChange} />
          </section>
        )}
      </div>
    </aside>
  );
}

function MediaTab({ assets, usedAssetIds, importing, importError, onImport, onAddAsset, onRemoveAsset }: LibraryPanelProps) {
  const [isDragging, setIsDragging] = useState(false);
  const fromProject = assets.filter((asset) => asset.source === "project");
  const uploads = assets.filter((asset) => asset.source === "upload");

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = ""; // lets the same file be picked again
    if (files.length > 0) onImport(files);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setIsDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onImport(files);
  }

  return (
    <>
      <label
        className={isDragging ? "dropzone dropzone--compact is-dragging" : "dropzone dropzone--compact"}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input className="sr-only" type="file" multiple accept={ACCEPTED_MEDIA} onChange={handleInput} />
        <span className="dropzone__icon">
          <IconUpload />
        </span>
        <span className="dropzone__text">
          <span className="dropzone__title">{importing ? "Importing…" : "Import media"}</span>
          <span className="dropzone__hint">
            Drop files or <u>browse</u> · video, audio, images
          </span>
        </span>
      </label>
      {importError && (
        <p className="form-error" role="alert">
          {importError}
        </p>
      )}

      <AssetGroup
        title="From this project"
        assets={fromProject}
        usedAssetIds={usedAssetIds}
        onAdd={onAddAsset}
        onRemove={onRemoveAsset}
      />
      <AssetGroup
        title="Uploads"
        assets={uploads}
        empty="Files you import show up here. Drag them onto a track or press + to add them at the playhead."
        usedAssetIds={usedAssetIds}
        onAdd={onAddAsset}
        onRemove={onRemoveAsset}
      />
    </>
  );
}

interface AssetGroupProps {
  title: string;
  assets: MediaAsset[];
  empty?: string;
  usedAssetIds: Set<string>;
  onAdd: (asset: MediaAsset) => void;
  onRemove: (asset: MediaAsset) => void;
}

function AssetGroup({ title, assets, empty, usedAssetIds, onAdd, onRemove }: AssetGroupProps) {
  return (
    <section className="library__group">
      <h3 className="library__label">{title}</h3>
      {assets.length === 0 ? (
        <p className="library__empty">{empty}</p>
      ) : (
        <ul className="asset-list">
          {assets.map((asset) => {
            const inUse = usedAssetIds.has(asset.id);
            return (
              <li
                key={asset.id}
                className="asset"
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData(DRAG_TYPES[asset.kind], asset.id);
                  event.dataTransfer.effectAllowed = "copy";
                }}
              >
                <AssetThumb asset={asset} />
                <div className="asset__info">
                  <p className="asset__name" title={asset.name}>
                    {asset.name}
                  </p>
                  <p className="asset__meta">{assetMeta(asset)}</p>
                </div>
                <div className="asset__actions">
                  <ToolButton small label={`Add ${asset.name} at the playhead`} onClick={() => onAdd(asset)}>
                    <IconPlus />
                  </ToolButton>
                  {asset.source === "upload" && (
                    <ToolButton
                      small
                      label={inUse ? "In use on the timeline" : `Remove ${asset.name}`}
                      disabled={inUse}
                      onClick={() => onRemove(asset)}
                    >
                      <IconTrash />
                    </ToolButton>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function AssetThumb({ asset }: { asset: MediaAsset }) {
  if (asset.url && asset.kind === "image") {
    return <img className="asset__thumb" src={asset.url} alt="" draggable={false} />;
  }
  if (asset.url && asset.kind === "video") {
    // #t=0.1 makes the browser paint a frame instead of a blank box.
    return <video className="asset__thumb" src={`${asset.url}#t=0.1`} muted preload="metadata" />;
  }
  return (
    <span className="asset__thumb asset__thumb--icon" aria-hidden="true">
      {ASSET_ICONS[asset.kind]}
    </span>
  );
}

function assetMeta(asset: MediaAsset): string {
  const parts = [asset.kind === "image" ? "Image" : formatTime(asset.duration)];
  if (asset.source === "project" && asset.offset) parts.push(`from ${formatTime(asset.offset)}`);
  if (asset.size) parts.push(formatBytes(asset.size));
  return parts.join(" · ");
}

function TextTab({ onAddText }: { onAddText: (layer: TextLayer) => void }) {
  return (
    <section className="library__group">
      <h3 className="library__label">Text styles</h3>
      <p className="library__help">Click to add at the playhead, or drag onto the Text track.</p>
      <ul className="preset-grid">
        {TEXT_PRESETS.map((preset) => (
          <li key={preset.id}>
            <button
              type="button"
              className="preset"
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(DRAG_TYPES.text, preset.id);
                event.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => onAddText(preset.layer)}
            >
              <span className="preset__preview" aria-hidden="true">
                <span
                  className={`stage-text stage-text--center stage-text--${preset.layer.color} stage-text--bg-${preset.layer.background}`}
                  style={{ fontSize: `${8 + preset.layer.size}px`, fontWeight: preset.layer.weight }}
                >
                  <span className="stage-text__box">{preset.layer.content}</span>
                </span>
              </span>
              <span className="preset__label">{preset.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TransitionsTab({ hasSelection, onApply }: { hasSelection: boolean; onApply: (type: TransitionType) => void }) {
  return (
    <section className="library__group">
      <h3 className="library__label">Transitions</h3>
      <p className="library__help">
        {hasSelection
          ? "Click to use one as the selected clip's entrance, or drag it onto the start or end of any clip."
          : "Drag one onto the start or end of a clip, or select a clip first and click."}
      </p>
      <ul className="preset-grid">
        {TRANSITIONS.map((transition) => (
          <li key={transition.value}>
            <button
              type="button"
              className="preset"
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(DRAG_TRANSITION, transition.value);
                event.dataTransfer.effectAllowed = "copy";
              }}
              onClick={() => onApply(transition.value)}
            >
              <span className={`preset__preview fx-demo fx-demo--${transition.value}`} aria-hidden="true">
                <span className="fx-demo__b" />
              </span>
              <span className="preset__label">{transition.label}</span>
              <span className="preset__hint">{transition.hint}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}