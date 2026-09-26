import React from 'react';
import { Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight } from 'lucide-react';

export interface ReplayControlsProps {
  currentTickIndex: number;
  maxTickIndex: number;
  isPlaying: boolean;
  playSpeed: number;
  episodes: any[];
  totalTime: number;
  onSeekTo: (idx: number) => void;
  onStep: (delta: number) => void;
  onTogglePlay: () => void;
  onSpeedChange: (speed: number) => void;
}

const SPEED_PRESETS = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0];

export const ReplayControls: React.FC<ReplayControlsProps> = ({
  currentTickIndex,
  maxTickIndex,
  isPlaying,
  playSpeed,
  episodes,
  totalTime,
  onSeekTo,
  onStep,
  onTogglePlay,
  onSpeedChange,
}) => {
  return (
    <div className="bg-white p-3.5 px-6 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
      {/* Playback Controls */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => onSeekTo(0)}
          className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
          title="В начало"
        >
          <SkipBack className="w-3.5 h-3.5 fill-current" />
        </button>
        <button
          onClick={() => onStep(-10)}
          className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
          title="Шаг назад"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <button
          onClick={onTogglePlay}
          className="w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center shadow-md transition-colors"
          title={isPlaying ? 'Пауза' : 'Воспроизведение'}
        >
          {isPlaying ? (
            <Pause className="w-4 h-4 fill-current" />
          ) : (
            <Play className="w-4 h-4 fill-current ml-0.5" />
          )}
        </button>
        <button
          onClick={() => onStep(10)}
          className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
          title="Шаг вперед"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={() => onSeekTo(maxTickIndex)}
          className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
          title="В конец"
        >
          <SkipForward className="w-3.5 h-3.5 fill-current" />
        </button>
      </div>

      {/* Timeline Scrubber */}
      <div className="flex-1 w-full mx-4 relative py-2">
        <input
          type="range"
          min={0}
          max={maxTickIndex}
          value={currentTickIndex}
          onChange={(e) => onSeekTo(Number(e.target.value))}
          className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
        />

        {/* Incident tick markers on timeline */}
        <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 pointer-events-none px-1 flex justify-between">
          {episodes.slice(0, 10).map((ep, i) => {
            const leftPercent = Math.min(100, Math.max(0, (ep.t_start / totalTime) * 100));
            const color =
              ep.cost < -0.5
                ? 'bg-amber-500'
                : ep.cost < 0
                ? 'bg-blue-500'
                : 'bg-emerald-500';
            return (
              <div
                key={ep.id || i}
                className={`absolute w-1.5 h-3 rounded-full ${color}`}
                style={{ left: `${leftPercent}%` }}
                title={`${ep.type}: ${ep.cost} pts (t=${ep.t_start}s)`}
              />
            );
          })}
        </div>
      </div>

      {/* Speed Multipliers */}
      <div className="flex items-center gap-1 text-xs">
        {SPEED_PRESETS.map((s) => (
          <button
            key={s}
            onClick={() => onSpeedChange(s)}
            className={`px-2 py-1 rounded-md font-mono transition-colors ${
              playSpeed === s
                ? 'bg-blue-600 text-white font-bold'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
            }`}
          >
            {s}x
          </button>
        ))}
      </div>
    </div>
  );
};
