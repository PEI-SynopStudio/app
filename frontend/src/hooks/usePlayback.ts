import { useEffect, useRef, useState } from "react";
import { gsap } from "../lib/gsap";

/**
 * Simulated playback between `from` and `to` (seconds) until there is a real <video>.
 * This is state, not decoration: it runs with reduced motion too.
 */
export function usePlayback(from: number, to: number) {
  const [time, setTime] = useState(from);
  const [isPlaying, setIsPlaying] = useState(false);
  const timeRef = useRef(from);

  useEffect(() => {
    if (!isPlaying) return;
    let last = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const next = Math.min(to, Math.max(from, timeRef.current) + (now - last) / 1000);
      last = now;
      timeRef.current = next;
      setTime(next);
      if (next >= to) setIsPlaying(false);
      else frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [isPlaying, from, to]);

  function seek(next: number) {
    timeRef.current = next;
    setTime(next);
  }

  function toggle() {
    if (!isPlaying && timeRef.current >= to) seek(from); // finished: start over
    setIsPlaying((playing) => !playing);
  }

  function pause() {
    setIsPlaying(false);
  }

  // The range can change while editing; the time shown always stays inside it.
  return { time: gsap.utils.clamp(from, to, time), isPlaying, toggle, seek, pause };
}