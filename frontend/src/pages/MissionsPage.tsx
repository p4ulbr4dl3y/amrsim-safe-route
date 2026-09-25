import React, { useEffect } from 'react';
import { RouteName } from '../types';
import { mockMissions } from '../mock/mockData';
import { ArrowRight, CheckCircle2 } from 'lucide-react';

interface MissionsPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    id?: string;
  };
}

export const MissionsPage: React.FC<MissionsPageProps> = ({ onNavigate, queryParams }) => {
  // If id is provided in queryParams, scroll to that card
  useEffect(() => {
    if (queryParams?.id) {
      const el = document.getElementById(`mission-${queryParams.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }, [queryParams]);

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Top 3 KPI Bar matching missions.png */}
      <div className="bg-white p-5 px-8 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 md:grid-cols-3 gap-6 divide-y md:divide-y-0 md:divide-x divide-slate-100">
        {/* KPI 1: Миссии */}
        <div className="flex items-center gap-4">
          <div className="w-3 h-3 rounded-full bg-emerald-500 ring-4 ring-emerald-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Миссии</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              2 <span className="text-slate-400 font-normal">/ 2</span> <span className="text-xs text-slate-500 font-sans font-normal ml-1">выполнено</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Результат доставки */}
        <div className="flex items-center gap-4 md:pl-6">
          <div>
            <div className="text-xs text-slate-500 font-medium">Результат доставки</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              40.0 <span className="text-slate-400 font-normal">/ 40.0</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Эффективность */}
        <div className="flex items-center gap-4 md:pl-6">
          <div>
            <div className="text-xs text-slate-500 font-medium">Эффективность</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              12.31 <span className="text-slate-400 font-normal">/ 15.00</span>
            </div>
          </div>
        </div>
      </div>

      {/* Mission Cards matching missions.png */}
      <div className="flex flex-col gap-4">
        {mockMissions.map((m) => (
          <div
            key={m.id}
            id={`mission-${m.id}`}
            className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4"
          >
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <div className="flex items-center gap-4">
                <span className="text-base font-bold font-mono text-slate-900">{m.id}</span>
                <span className="text-slate-300">|</span>
                <span className="text-xs font-mono text-slate-600">
                  {m.from} → {m.to}
                </span>
              </div>

              {/* Status Badge */}
              <div className="bg-emerald-50 text-emerald-700 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-200 flex items-center gap-1.5 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>
                {m.status}
              </div>
            </div>

            {/* Metrics Grid matching mockup */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-3 text-xs font-mono">
              <div className="flex justify-between py-1 border-b border-slate-50">
                <span className="text-slate-500">Старт</span>
                <span className="text-slate-900 font-semibold">{m.t_start.toFixed(1)} s</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-50">
                <span className="text-slate-500">Макс. дистанция холда</span>
                <span className="text-slate-900 font-semibold">{m.max_hold_dist.toFixed(4)} m / tol {m.tol.toFixed(2)} m</span>
              </div>

              <div className="flex justify-between py-1 border-b border-slate-50">
                <span className="text-slate-500">Прибытие</span>
                <span className="text-slate-900 font-semibold">{m.actual_time_s.toFixed(1)} s</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-50">
                <span className="text-slate-500">Дедлайн</span>
                <span className="text-slate-900 font-semibold">{m.deadline_s.toFixed(1)} s (запас +{m.safety_margin_s.toFixed(1)} s)</span>
              </div>

              <div className="flex justify-between py-1">
                <span className="text-slate-500">Холд</span>
                <span className="text-slate-900 font-semibold">{m.hold_duration_s.toFixed(1)} s ({m.hold_ticks} ticks)</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-slate-500">Опорная длина</span>
                <span className="text-slate-900 font-semibold">{m.reference_length_m.toFixed(1)} m</span>
              </div>
            </div>

            {/* Action link as per frontend.md: opens /replay?mission=... */}
            <div className="pt-2 border-t border-slate-100">
              <button
                onClick={() => onNavigate('replay', { mission: m.id, t: m.t_start })}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1 group"
              >
                <span>Показать траекторию на карте</span>
                <ArrowRight className="w-3.5 h-3.5 transform group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Comparison Chart matching missions.png */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
        <h2 className="text-sm font-semibold text-slate-800">Сравнение времени выполнения миссий</h2>

        <div className="flex flex-col gap-4 mt-2">
          {/* Mission 1 Bar */}
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="w-8 font-bold text-slate-800">m1</span>
            <div className="flex-1 flex flex-col gap-1.5">
              {/* Actual time bar */}
              <div className="relative h-3 bg-slate-100 rounded-sm">
                <div className="h-full bg-blue-500 rounded-sm" style={{ width: `${(159.2 / 250) * 100}%` }}></div>
                <span className="absolute left-[65%] -top-0.5 text-[10px] text-slate-600">159.2 s</span>
              </div>
              {/* Reference time bar */}
              <div className="relative h-2 bg-slate-100 rounded-sm">
                <div className="h-full bg-slate-400 rounded-sm" style={{ width: `${(174.3 / 250) * 100}%` }}></div>
                <span className="absolute left-[71%] -top-1 text-[10px] text-slate-400">174.3 s</span>
              </div>
              {/* Deadline bar */}
              <div className="relative h-2 bg-slate-100 rounded-sm">
                <div className="h-full bg-slate-200 rounded-sm" style={{ width: `${(200.7 / 250) * 100}%` }}></div>
                <span className="absolute left-[82%] -top-1 text-[10px] text-slate-400">200.7 s</span>
              </div>
            </div>
          </div>

          {/* Mission 2 Bar */}
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="w-8 font-bold text-slate-800">m2</span>
            <div className="flex-1 flex flex-col gap-1.5">
              <div className="relative h-3 bg-slate-100 rounded-sm">
                <div className="h-full bg-blue-500 rounded-sm" style={{ width: `${(159.2 / 250) * 100}%` }}></div>
                <span className="absolute left-[65%] -top-0.5 text-[10px] text-slate-600">159.2 s</span>
              </div>
              <div className="relative h-2 bg-slate-100 rounded-sm">
                <div className="h-full bg-slate-400 rounded-sm" style={{ width: `${(174.3 / 250) * 100}%` }}></div>
                <span className="absolute left-[71%] -top-1 text-[10px] text-slate-400">174.3 s</span>
              </div>
              <div className="relative h-2 bg-slate-100 rounded-sm">
                <div className="h-full bg-slate-200 rounded-sm" style={{ width: `${(200.7 / 250) * 100}%` }}></div>
                <span className="absolute left-[82%] -top-1 text-[10px] text-slate-400">200.7 s</span>
              </div>
            </div>
          </div>

          {/* X-axis ticks & Legend */}
          <div className="flex items-center justify-between pt-3 border-t border-slate-100 text-[10px] text-slate-400 font-mono">
            <div className="flex gap-16 pl-12">
              <span>0</span>
              <span>50</span>
              <span>100</span>
              <span>150</span>
              <span>200</span>
              <span>250 Время, с</span>
            </div>

            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-blue-500 rounded-sm"></span> Фактическое время</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-slate-400 rounded-sm"></span> Опорное время</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 bg-slate-200 rounded-sm"></span> Дедлайн</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
