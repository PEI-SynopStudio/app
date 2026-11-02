import type { WaveRange } from "../lib/utils";

interface WaveformProps {
  bars: number;
  ranges?: WaveRange[];
  seed?: number;
}

/** Altura (0.2–1) pseudo-aleatória mas estável para cada barra. */
function barHeight(index: number, seed: number) {
  const v = Math.abs(Math.sin(index * 0.82 + seed) * Math.cos(index * 0.31 + seed * 1.7));
  return 0.2 + v * 0.8;
}

export function Waveform({ bars, ranges = [], seed = 1 }: WaveformProps) {
  return (
    <div className="wave" aria-hidden="true">
      {Array.from({ length: bars }, (_, index) => {
        const range = ranges.find((r) => index >= r.from && index <= r.to);
        return (
          <span
            key={index}
            className={range ? "wave__bar is-pick" : "wave__bar"}
            data-range={range?.id}
            style={{ height: `${Math.round(barHeight(index, seed) * 100)}%` }}
          />
        );
      })}
    </div>
  );
}