import { useId, type ReactNode } from "react";
import {
  AUDIO_TRANSITIONS,
  TEXT_COLORS,
  TRANSITIONS,
  TRANSITION_LENGTH,
  type ItemContent,
  type MediaAsset,
  type TextBackground,
  type TextColor,
  type TextLayer,
  type TextPosition,
  type TextWeight,
  type TimelineItem,
  type Track,
  type Transition,
} from "../../lib/editor";
import { formatTimecode } from "../../lib/utils";
import { IconCopy, IconFilm, IconImage, IconMusic, IconScissors, IconText, IconTrash } from "../Icons";
import { RangeField, Segmented } from "./controls";

interface InspectorProps {
  item: TimelineItem | null;
  asset?: MediaAsset;
  track?: Track;
  duration: number;
  itemCount: number;
  canSplit: boolean;
  onPreview: (patch: Partial<TimelineItem>) => void; // live, while dragging a slider or typing
  onCommit: (patch: Partial<TimelineItem>) => void;
  onSettle: () => void;
  onSplit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

const KIND_ICONS: Record<ItemContent, ReactNode> = {
  video: <IconFilm />,
  image: <IconImage />,
  audio: <IconMusic />,
  text: <IconText />,
};

const KIND_LABELS: Record<ItemContent, string> = { video: "Video", image: "Image", audio: "Audio", text: "Text" };

const WEIGHTS: { value: TextWeight; label: string }[] = [
  { value: 500, label: "Regular" },
  { value: 600, label: "Semibold" },
  { value: 700, label: "Bold" },
];

const POSITIONS: { value: TextPosition; label: string }[] = [
  { value: "top", label: "Top" },
  { value: "center", label: "Middle" },
  { value: "bottom", label: "Bottom" },
];

const BACKGROUNDS: { value: TextBackground; label: string }[] = [
  { value: "none", label: "None" },
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "accent", label: "Orange" },
];

const FITS: { value: "cover" | "contain"; label: string }[] = [
  { value: "cover", label: "Fill frame" },
  { value: "contain", label: "Fit inside" },
];

const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ["Space"], label: "Play / pause" },
  { keys: ["S"], label: "Split at playhead" },
  { keys: ["Del"], label: "Delete clip" },
  { keys: ["Ctrl", "D"], label: "Duplicate" },
  { keys: ["Ctrl", "Z"], label: "Undo" },
  { keys: ["Ctrl", "Shift", "Z"], label: "Redo" },
  { keys: ["←", "→"], label: "Step 0.1 s (Shift: 1 s)" },
  { keys: ["Ctrl", "S"], label: "Save" },
];

const percent = (value: number) => `${Math.round(value * 100)}%`;
const seconds = (value: number) => `${value.toFixed(1)} s`;

export function Inspector(props: InspectorProps) {
  const { item, duration, itemCount, ...rest } = props;
  return (
    <aside className="inspector" aria-label="Inspector" data-enter>
      {item ? (
        <ItemInspector key={item.id} {...rest} item={item} />
      ) : (
        <TimelineSummary duration={duration} itemCount={itemCount} />
      )}
    </aside>
  );
}

function TimelineSummary({ duration, itemCount }: { duration: number; itemCount: number }) {
  return (
    <>
      <section className="inspector__section">
        <h2 className="inspector__label">Timeline</h2>
        <dl className="stat-grid">
          <div>
            <dt>Length</dt>
            <dd>{formatTimecode(duration)}</dd>
          </div>
          <div>
            <dt>Clips</dt>
            <dd>{itemCount}</dd>
          </div>
        </dl>
        <p className="inspector__hint">
          Select something on the timeline or in the preview to edit it. Drag media, text and transitions from the
          library onto the tracks.
        </p>
      </section>
      <section className="inspector__section">
        <h2 className="inspector__label">Shortcuts</h2>
        <dl className="shortcuts">
          {SHORTCUTS.map((shortcut) => (
            <div key={shortcut.label}>
              <dt>{shortcut.label}</dt>
              <dd>
                {shortcut.keys.map((key) => (
                  <kbd key={key}>{key}</kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}

type ItemInspectorProps = Omit<InspectorProps, "item" | "duration" | "itemCount"> & { item: TimelineItem };

function ItemInspector({
  item,
  asset,
  track,
  canSplit,
  onPreview,
  onCommit,
  onSettle,
  onSplit,
  onDuplicate,
  onDelete,
}: ItemInspectorProps) {
  const id = useId();
  const content: ItemContent = item.kind === "text" ? "text" : (asset?.kind ?? "video");
  const text = item.text;
  const name = text ? text.content.trim() || "Text" : (asset?.name ?? "Missing media");
  const hasSource = content === "video" || content === "audio";
  const transitions = content === "audio" ? AUDIO_TRANSITIONS : TRANSITIONS;

  function editText(patch: Partial<TextLayer>, live = false) {
    if (!text) return;
    const update = { text: { ...text, ...patch } };
    if (live) onPreview(update);
    else onCommit(update);
  }

  return (
    <>
      <header className="inspector__head">
        <span className="inspector__icon" aria-hidden="true">
          {KIND_ICONS[content]}
        </span>
        <div className="inspector__heading">
          <h2 className="inspector__title">{name}</h2>
          <p className="inspector__meta">
            {KIND_LABELS[content]}
            {track ? ` · ${track.label} track` : ""}
          </p>
        </div>
      </header>

      <section className="inspector__section">
        <dl className="stat-grid">
          <div>
            <dt>Start</dt>
            <dd>{formatTimecode(item.start)}</dd>
          </div>
          <div>
            <dt>Length</dt>
            <dd>{formatTimecode(item.duration)}</dd>
          </div>
          {hasSource && (
            <div>
              <dt>Source</dt>
              <dd>{formatTimecode((asset?.offset ?? 0) + (item.inPoint ?? 0))}</dd>
            </div>
          )}
        </dl>
      </section>

      {text && (
        <section className="inspector__section">
          <h3 className="inspector__label">Text</h3>
          <div className="field">
            <label className="field__label" htmlFor={`${id}-content`}>
              Content
            </label>
            <textarea
              id={`${id}-content`}
              className="input input--textarea"
              rows={3}
              value={text.content}
              onChange={(event) => editText({ content: event.target.value }, true)}
              onBlur={onSettle}
            />
          </div>
          <RangeField
            label="Size"
            value={text.size}
            min={3}
            max={16}
            step={0.5}
            format={(value) => value.toFixed(1)}
            onChange={(size) => editText({ size }, true)}
            onSettle={onSettle}
          />
          <Segmented label="Weight" value={text.weight} options={WEIGHTS} onChange={(weight) => editText({ weight })} />
          <ColorField value={text.color} onChange={(color) => editText({ color })} />
          <Segmented
            label="Position"
            value={text.position}
            options={POSITIONS}
            onChange={(position) => editText({ position })}
          />
          <Segmented
            label="Background"
            value={text.background}
            options={BACKGROUNDS}
            onChange={(background) => editText({ background })}
          />
          <RangeField
            label="Opacity"
            value={item.opacity ?? 1}
            min={0}
            max={1}
            step={0.01}
            format={percent}
            onChange={(opacity) => onPreview({ opacity })}
            onSettle={onSettle}
          />
        </section>
      )}

      {(content === "video" || content === "image") && (
        <section className="inspector__section">
          <h3 className="inspector__label">Picture</h3>
          <Segmented label="Framing" value={item.fit ?? "cover"} options={FITS} onChange={(fit) => onCommit({ fit })} />
          <RangeField
            label="Opacity"
            value={item.opacity ?? 1}
            min={0}
            max={1}
            step={0.01}
            format={percent}
            onChange={(opacity) => onPreview({ opacity })}
            onSettle={onSettle}
          />
        </section>
      )}

      {hasSource && (
        <section className="inspector__section">
          <h3 className="inspector__label">Sound</h3>
          <RangeField
            label="Volume"
            value={item.volume ?? 1}
            min={0}
            max={1}
            step={0.01}
            format={(value) => (value === 0 ? "Muted" : percent(value))}
            onChange={(volume) => onPreview({ volume })}
            onSettle={onSettle}
          />
        </section>
      )}

      <section className="inspector__section">
        <h3 className="inspector__label">Transitions</h3>
        <TransitionField
          label="In"
          value={item.transitionIn}
          options={transitions}
          maxDuration={item.duration}
          onCommit={(transitionIn) => onCommit({ transitionIn })}
          onPreview={(transitionIn) => onPreview({ transitionIn })}
          onSettle={onSettle}
        />
        <TransitionField
          label="Out"
          value={item.transitionOut}
          options={transitions}
          maxDuration={item.duration}
          onCommit={(transitionOut) => onCommit({ transitionOut })}
          onPreview={(transitionOut) => onPreview({ transitionOut })}
          onSettle={onSettle}
        />
      </section>

      <div className="inspector__actions">
        <button type="button" className="btn btn--ghost btn--sm" onClick={onSplit} disabled={!canSplit}>
          <IconScissors /> Split
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onDuplicate}>
          <IconCopy /> Duplicate
        </button>
        <button type="button" className="btn btn--danger-ghost btn--sm" onClick={onDelete}>
          <IconTrash /> Delete
        </button>
      </div>
    </>
  );
}

function ColorField({ value, onChange }: { value: TextColor; onChange: (color: TextColor) => void }) {
  const id = useId();
  return (
    <div className="field">
      <p className="field__label" id={id}>
        Color
      </p>
      <div className="swatches" role="radiogroup" aria-labelledby={id}>
        {TEXT_COLORS.map((color) => (
          <label key={color.value} className={`swatch swatch--${color.value}`} title={color.label}>
            <input
              className="sr-only"
              type="radio"
              name={id}
              checked={value === color.value}
              onChange={() => onChange(color.value)}
            />
            <span className="sr-only">{color.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

interface TransitionFieldProps {
  label: string;
  value?: Transition;
  options: typeof TRANSITIONS;
  maxDuration: number;
  onCommit: (transition: Transition | undefined) => void;
  onPreview: (transition: Transition) => void;
  onSettle: () => void;
}

function TransitionField({ label, value, options, maxDuration, onCommit, onPreview, onSettle }: TransitionFieldProps) {
  const id = useId();
  const longest = Math.max(0.2, Math.min(2, maxDuration));

  return (
    <div className="transition-field">
      <div className="field">
        <label className="field__label" htmlFor={id}>
          {label}
        </label>
        <select
          id={id}
          className="input"
          value={value?.type ?? ""}
          onChange={(event) => {
            const type = options.find((option) => option.value === event.target.value)?.value;
            onCommit(type ? { type, duration: value?.duration ?? Math.min(TRANSITION_LENGTH, longest) } : undefined);
          }}
        >
          <option value="">None</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {value && (
        <RangeField
          label="Duration"
          value={Math.min(value.duration, longest)}
          min={0.1}
          max={longest}
          step={0.1}
          format={seconds}
          onChange={(duration) => onPreview({ ...value, duration })}
          onSettle={onSettle}
        />
      )}
    </div>
  );
}