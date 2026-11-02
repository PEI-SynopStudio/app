import { useCallback, useEffect, useRef, useState } from "react";

/** Playback clock for the editor: runs from 0 to `duration` and stops at the end. */
export function useTransport(duration: number) {
  const [time, setTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const timeRef = useRef(0);
  const durationRef = useRef(duration);

  useEffect(() => {
    durationRef.current = duration;
  }, [duration]);

  useEffect(() => {
    if (!isPlaying) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const next = Math.min(timeRef.current + (now - last) / 1000, durationRef.current);
      last = now;
      timeRef.current = next;
      setTime(next);
      if (next >= durationRef.current) {
        setIsPlaying(false);
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [isPlaying]);

  const seek = useCallback((value: number) => {
    const next = Math.min(Math.max(value, 0), durationRef.current);
    timeRef.current = next;
    setTime(next);
  }, []);

  const pause = useCallback(() => setIsPlaying(false), []);

  const toggle = useCallback(() => {
    if (isPlaying) {
      setIsPlaying(false);
      return;
    }
    if (durationRef.current <= 0) return;
    // Pressing play at the end starts over.
    if (timeRef.current >= durationRef.current - 0.05) seek(0);
    setIsPlaying(true);
  }, [isPlaying, seek]);

  return { time: Math.min(time, duration), isPlaying, toggle, seek, pause };
}