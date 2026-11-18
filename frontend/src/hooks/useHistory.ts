import { useCallback, useState } from "react";

const LIMIT = 100;

interface History<T> {
  past: T[];
  present: T;
  future: T[];
  /** Where an ongoing gesture (drag, slider, typing) started; null when idle. */
  anchor: T | null;
}

/** Closes an ongoing gesture: the state before it becomes a single undo step. */
function settle<T>(history: History<T>): History<T> {
  if (history.anchor === null) return history;
  if (history.anchor === history.present) return { ...history, anchor: null };
  return { past: [...history.past, history.anchor].slice(-LIMIT), present: history.present, future: [], anchor: null };
}

/**
 * Undo/redo for an immutable state.
 * - commit: one step per call (clicks, shortcuts, drops).
 * - preview: live updates during a gesture; `end` (or the next commit/undo) turns
 *   the whole gesture into one step.
 */
export function useHistory<T>(init: () => T) {
  const [history, setHistory] = useState<History<T>>(() => ({ past: [], present: init(), future: [], anchor: null }));

  const commit = useCallback((update: (state: T) => T) => {
    setHistory((current) => {
      const settled = settle(current);
      const next = update(settled.present);
      if (next === settled.present) return settled;
      return { past: [...settled.past, settled.present].slice(-LIMIT), present: next, future: [], anchor: null };
    });
  }, []);

  const preview = useCallback((update: (state: T) => T) => {
    setHistory((current) => {
      const next = update(current.present);
      if (next === current.present) return current;
      return { ...current, present: next, anchor: current.anchor ?? current.present };
    });
  }, []);

  const end = useCallback(() => setHistory((current) => settle(current)), []);

  const undo = useCallback(() => {
    setHistory((current) => {
      const settled = settle(current);
      if (settled.past.length === 0) return settled;
      const previous = settled.past[settled.past.length - 1];
      return {
        past: settled.past.slice(0, -1),
        present: previous,
        future: [settled.present, ...settled.future],
        anchor: null,
      };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((current) => {
      const settled = settle(current);
      if (settled.future.length === 0) return settled;
      const [next, ...rest] = settled.future;
      return { past: [...settled.past, settled.present], present: next, future: rest, anchor: null };
    });
  }, []);

  return {
    state: history.present,
    commit,
    preview,
    end,
    undo,
    redo,
    canUndo: history.past.length > 0 || (history.anchor !== null && history.anchor !== history.present),
    canRedo: history.future.length > 0,
  };
}