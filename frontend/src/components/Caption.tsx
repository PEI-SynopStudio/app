import type { CaptionStyle } from "../data/options";
import "../styles/player.css";

export function Caption({ text, variant }: { text: string; variant: CaptionStyle }) {
  return (
    <p className={`caption caption--${variant}`}>
      <span>{text}</span>
    </p>
  );
}