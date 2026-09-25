import React, { useState, useEffect } from 'react';
import { RouteName, MissionData, ScenarioItem, MissionsViewModel } from '../types';
import { apiClient } from '../api/client';
import { ArrowRight, CheckCircle2, ChevronDown, RefreshCw } from 'lucide-react';
import { Latex } from '../components/Latex';

interface MissionsPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    scenario?: string;
    id?: string;
  };
}

export const MissionsPage: React.FC<MissionsPageProps> = ({ onNavigate, queryParams }) => {
  const [scenario, setScenario] = useState(queryParams?.scenario || '04_busy_yard');
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [data, setData] = useState<MissionsViewModel | null>(null);
  const [loading, setLoading] = useState(true);

  // Загрузка списка сценариев
  useEffect(() => {
    let mounted = true;
    apiClient.fetchScenarios().then((list) => {
      if (mounted) setScenarios(list);
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Обновление сценария из параметров URL при изменении
  useEffect(() => {
    if (queryParams?.scenario && queryParams.scenario !== scenario) {
      setScenario(queryParams.scenario);
    }
  }, [queryParams?.scenario]);

  // Загрузка миссий для сценария
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient.fetchMissions(scenario).then((vm) => {
      if (mounted) {
        setData(vm);
        setLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, [scenario]);

  // Прокрутка к карточке при передаче id в параметрах URL
  useEffect(() => {
    if (queryParams?.id) {
      const el = document.getElementById(`mission-${queryParams.id}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }, [queryParams?.id, data]);

  const missions = data?.missions || [];
  const summary = data?.summary || {
    completed: 2,
    total: 2,
    deliveryScore: 40.0,
    maxDeliveryScore: 40.0,
    efficiencyScore: 13.78,
    maxEfficiencyScore: 15.0,
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Top Scenario Selector & Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="font-bold text-slate-800 text-sm tracking-tight">Задания и Доставка</span>
          <span className="text-slate-400 text-xs">//</span>
          <span className="text-slate-600 text-xs font-medium">Маршрутные миссии платформы</span>
        </div>

        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-500 font-medium">Сценарий:</label>
          <div className="relative min-w-[200px]">
            <select
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs font-semibold rounded-lg px-3 py-1.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              {scenarios.map((sc) => (
                <option key={sc.id} value={sc.id}>
                  {sc.name}
                </option>
              ))}
            </select>
            <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 top-2 pointer-events-none" />
          </div>
          {loading && <RefreshCw className="w-3.5 h-3.5 animate-spin text-blue-600" />}
        </div>
      </div>

      {/* Top 3 KPI Bar matching missions.png */}
      <div className="bg-white p-5 px-8 rounded-xl border border-slate-200 shadow-sm grid grid-cols-1 md:grid-cols-3 gap-6 divide-y md:divide-y-0 md:divide-x divide-slate-100">
        {/* KPI 1: Миссии */}
        <div className="flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-emerald-500 ring-4 ring-emerald-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Миссии</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.completed} <span className="text-slate-400 font-normal">/ {summary.total}</span>{' '}
              <span className="text-xs text-slate-500 font-sans font-normal ml-1">выполнено</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Результат доставки */}
        <div className="flex items-center gap-4 md:pl-6">
          <div>
            <div className="text-xs text-slate-500 font-medium flex items-center gap-1.5">
              <span>Результат доставки</span>
              <span className="text-[11px] text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-100 font-serif">
                <Latex math="S_{\text{del}}" />
              </span>
            </div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.deliveryScore.toFixed(1)}{' '}
              <span className="text-slate-400 font-normal">/ {summary.maxDeliveryScore.toFixed(1)}</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Эффективность */}
        <div className="flex items-center gap-4 md:pl-6">
          <div>
            <div className="text-xs text-slate-500 font-medium flex items-center gap-1.5">
              <span>Эффективность</span>
              <span className="text-[11px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-100 font-serif">
                <Latex math="S_{\text{eff}}" />
              </span>
            </div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.efficiencyScore.toFixed(2)}{' '}
              <span className="text-slate-400 font-normal">/ {summary.maxEfficiencyScore.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Mission Cards matching missions.png */}
      <div className="flex flex-col gap-4">
        {missions.length === 0 ? (
          <div className="bg-white p-8 rounded-xl border border-slate-200 text-center text-slate-400 text-xs">
            Нет доступных миссий для выбранного сценария
          </div>
        ) : (
          missions.map((m) => (
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
                  <span className="text-xs font-mono text-slate-700">
                    {m.fromLabel} → {m.toLabel}
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
                  <span className="text-slate-500">Старт миссии</span>
                  <span className="text-slate-900 font-semibold">{m.t_start.toFixed(1)} s</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Макс. дистанция холда</span>
                  <span className="text-slate-900 font-semibold">
                    {m.max_hold_dist.toFixed(4)} m / tol {m.tol.toFixed(2)} m
                  </span>
                </div>

                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Прибытие в док</span>
                  <span className="text-slate-900 font-semibold">{m.actual_time_s.toFixed(1)} s</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Дедлайн доставки</span>
                  <span className="text-slate-900 font-semibold">
                    {m.deadline_s.toFixed(1)} s (запас +{m.safety_margin_s.toFixed(1)} s)
                  </span>
                </div>

                <div className="flex justify-between py-1">
                  <span className="text-slate-500">Удержание (холд)</span>
                  <span className="text-slate-900 font-semibold">
                    {m.hold_duration_s.toFixed(1)} s ({m.hold_ticks} ticks)
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-500">Опорная длина пути</span>
                  <span className="text-slate-900 font-semibold">
                    {m.reference_length_m.toFixed(1)} m
                  </span>
                </div>
              </div>

              {/* Action link: opens /replay?mission=... */}
              <div className="pt-2 border-t border-slate-100 flex justify-end">
                <button
                  onClick={() =>
                    onNavigate('replay', {
                      scenario,
                      mission: m.id,
                      t: m.t_start,
                    })
                  }
                  className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1 group"
                >
                  <span>Смотреть миссию в Replay</span>
                  <ArrowRight className="w-3.5 h-3.5 transform group-hover:translate-x-0.5 transition-transform" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
