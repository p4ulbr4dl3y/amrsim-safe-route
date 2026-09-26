import React from 'react';
import { User } from 'lucide-react';
import { TickData, ReplayMissionData } from '../../types';

export interface ReplayTelemetryProps {
  currentTick: TickData;
  activeMission?: ReplayMissionData;
  noteText?: string | null;
}

export const ReplayTelemetry: React.FC<ReplayTelemetryProps> = ({
  currentTick,
  activeMission,
  noteText,
}) => {
  const missionId = currentTick.m || activeMission?.id || '—';
  const missionTimeLeft = activeMission
    ? Math.max(0, activeMission.t_start + activeMission.deadline_s - currentTick.t)
    : null;

  return (
    <div className="lg:col-span-3 flex flex-col gap-4">
      {/* Status Badge */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
        <div className="flex items-center justify-center py-2 px-4 rounded-full bg-emerald-50 border border-emerald-200">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            <span className="text-xs font-bold tracking-wider text-emerald-800 uppercase font-mono">
              {currentTick.st || 'MOVING'}
            </span>
          </div>
        </div>

        {/* Note badge */}
        {noteText && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 flex items-center gap-2 text-xs text-amber-800">
            <User className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span className="font-medium text-[11px] leading-tight">{noteText}</span>
          </div>
        )}

        {/* Speeds */}
        <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
          <span className="text-slate-500">v</span>
          <span className="font-bold text-slate-800">{currentTick.v.toFixed(2)} м/с</span>
          <span className="text-slate-300">·</span>
          <span className="text-slate-500">cv</span>
          <span className="font-semibold text-slate-700">{currentTick.cv.toFixed(2)} м/с</span>
        </div>

        {/* Distance to human with proximity gauge */}
        <div className="pt-2 border-t border-slate-100 flex flex-col gap-1.5 text-xs font-mono">
          <div className="flex justify-between items-center">
            <span className="text-slate-500">hum</span>
            <span className="font-bold text-slate-800">
              {currentTick.hum !== null ? `${currentTick.hum.toFixed(2)} м` : '—'}
            </span>
          </div>
          <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                currentTick.hum && currentTick.hum < 1.0
                  ? 'bg-red-500'
                  : currentTick.hum && currentTick.hum < 3.0
                  ? 'bg-amber-500'
                  : 'bg-emerald-500'
              }`}
              style={{
                width: `${Math.min(100, Math.max(0, ((currentTick.hum || 5) / 5) * 100))}%`,
              }}
            ></div>
          </div>
        </div>

        {/* Distance to obstacle */}
        <div className="pt-1 flex items-center justify-between text-xs font-mono">
          <span className="text-slate-500">obj</span>
          <span className="font-bold text-slate-800">
            {currentTick.obj !== null ? `${currentTick.obj.toFixed(2)} м` : '—'}
          </span>
        </div>

        {/* Pose estimation and error */}
        <div className="pt-2 border-t border-slate-100 flex flex-col gap-1 text-xs font-mono">
          <div className="flex justify-between text-slate-500">
            <span>pose_est:</span>
            <span className="text-slate-800">
              {currentTick.pe
                ? `${currentTick.pe[0].toFixed(1)}, ${currentTick.pe[1].toFixed(1)}`
                : 'none'}
            </span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>pe_error:</span>
            <span
              className={`font-semibold ${
                (currentTick.pe_error || 0) > 0.5 ? 'text-amber-600' : 'text-slate-800'
              }`}
            >
              {(currentTick.pe_error || 0).toFixed(3)} м
            </span>
          </div>
        </div>

        {/* Collisions */}
        <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
          <div className="flex items-center gap-1 text-slate-600">
            <span>coll</span>
            <span
              className={`font-bold ${
                currentTick.coll ? 'text-red-600' : 'text-slate-800'
              }`}
            >
              {currentTick.coll}
            </span>
          </div>
          <span className="text-slate-300">·</span>
          <div className="flex items-center gap-1 text-slate-600">
            <span>cont</span>
            <span
              className={`font-bold ${
                currentTick.cont ? 'text-red-600' : 'text-slate-800'
              }`}
            >
              {currentTick.cont}
            </span>
          </div>
        </div>
      </div>

      {/* Current Mission Card */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-2">
        <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
          ТЕКУЩЕЕ ЗАДАНИЕ
        </span>
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 font-mono text-xs">
          <div className="font-bold text-slate-900 text-sm">{missionId}</div>
          <div className="text-slate-600 text-[11px] mt-1">
            {activeMission ? (
              <>
                <span>
                  {activeMission.fromLabel} → {activeMission.toLabel}
                </span>{' '}
                <span className="text-slate-400">·</span>{' '}
                <span>{missionTimeLeft !== null ? missionTimeLeft.toFixed(1) : '0.0'} s left</span>
              </>
            ) : (
              <span className="text-slate-400">данные миссии недоступны</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
