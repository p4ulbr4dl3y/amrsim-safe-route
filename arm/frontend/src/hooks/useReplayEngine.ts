import { useState, useEffect, useRef, useCallback } from 'react';
import { TickData } from '../types';

export interface UseReplayEngineOptions {
  ticks: TickData[];
}

export function useReplayEngine({ ticks }: UseReplayEngineOptions) {
  const [currentTickIndex, setCurrentTickIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState<number>(1.0);

  const fractionalTickRef = useRef<number>(0);
  const animFrameRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number | null>(null);
  const ticksRef = useRef<TickData[]>(ticks);
  ticksRef.current = ticks;

  const seekTo = useCallback((idx: number, maxBound?: number) => {
    const listLen = maxBound !== undefined ? maxBound + 1 : ticksRef.current.length;
    const maxIdx = Math.max(0, listLen - 1);
    const clamped = Math.max(0, Math.min(maxIdx, idx));
    fractionalTickRef.current = clamped;
    setCurrentTickIndex(clamped);
  }, []);

  const step = useCallback(
    (delta: number) => {
      seekTo(fractionalTickRef.current + delta);
    },
    [seekTo]
  );

  const togglePlay = useCallback(() => {
    if (!isPlaying && fractionalTickRef.current >= ticksRef.current.length - 1) {
      seekTo(0);
    }
    setIsPlaying((prev) => !prev);
  }, [isPlaying, seekTo]);

  const reset = useCallback((startIdx: number, maxIdx?: number) => {
    const clamped = Math.max(0, maxIdx !== undefined ? Math.min(maxIdx, startIdx) : startIdx);
    fractionalTickRef.current = clamped;
    setCurrentTickIndex(clamped);
    setIsPlaying(false);
  }, []);

  // High precision animation loop
  useEffect(() => {
    if (!isPlaying || ticks.length === 0) {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = null;
      }
      lastTimeRef.current = null;
      return;
    }

    if (fractionalTickRef.current >= ticks.length - 1) {
      fractionalTickRef.current = 0;
      setCurrentTickIndex(0);
    }

    lastTimeRef.current = performance.now();

    const tickRate =
      ticks.length > 1 && ticks[ticks.length - 1].t > ticks[0].t
        ? (ticks.length - 1) / (ticks[ticks.length - 1].t - ticks[0].t)
        : 10;

    const loop = (now: number) => {
      if (lastTimeRef.current === null) {
        lastTimeRef.current = now;
      }
      const elapsedSeconds = (now - lastTimeRef.current) / 1000;
      lastTimeRef.current = now;

      const clampedDt = Math.min(elapsedSeconds, 0.1);
      const deltaTicks = clampedDt * playSpeed * tickRate;
      const nextTick = fractionalTickRef.current + deltaTicks;

      if (nextTick >= ticks.length - 1) {
        fractionalTickRef.current = ticks.length - 1;
        setCurrentTickIndex(ticks.length - 1);
        setIsPlaying(false);
        return;
      }

      fractionalTickRef.current = nextTick;
      const nextInt = Math.floor(nextTick);
      setCurrentTickIndex((prev) => (prev !== nextInt ? nextInt : prev));

      animFrameRef.current = requestAnimationFrame(loop);
    };

    animFrameRef.current = requestAnimationFrame(loop);

    return () => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = null;
      }
      lastTimeRef.current = null;
    };
  }, [isPlaying, playSpeed, ticks]);

  return {
    currentTickIndex,
    isPlaying,
    setIsPlaying,
    playSpeed,
    setPlaySpeed,
    seekTo,
    step,
    togglePlay,
    reset,
  };
}
