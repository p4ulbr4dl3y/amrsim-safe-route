import React, { useState, useEffect } from 'react';
import { RouteName, MissionData, ScenarioItem, MissionsViewModel } from '../types';
import { apiClient } from '../api/client';
import { ArrowRight, CheckCircle2, ChevronDown, RefreshCw } from 'lucide-react';
import { Latex } from '../components/Latex';
import {
  getSelectedScenario,
  setSelectedScenario,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';

interface MissionsPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    scenario?: string;
    id?: string;
  };
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

export const MissionsPage: React.FC<MissionsPageProps> = ({
  onNavigate,
  queryParams,
  activeScenario,
  onScenarioChange,
}) => {
  const [scenario, setScenario] = useState(
    activeScenario || queryParams?.scenario || getSelectedScenario()
  );
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [data, setData] = useState<MissionsViewModel | null>(null);
  const [loading, setLoading] = useState(true);

  // Sync with activeScenario prop
  useEffect(() => {
    if (activeScenario && activeScenario !== scenario) {
      setScenario(activeScenario);
    }
  }, [activeScenario]);

  // Sync with global scenario change event
  useEffect(() => {
    const handleStorageChange = (e: any) => {
      const sc = e.detail;
      if (sc && sc !== scenario) {
        setScenario(sc);
      }
    };
    window.addEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleStorageChange);
    return () => {
      window.removeEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleStorageChange);
    };
  }, [scenario]);

  // Fetch scenarios list
  useEffect(() => {
    let mounted = true;
    apiClient.fetchScenarios().then((list) => {
      if (mounted) setScenarios(list);
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Update scenario from queryParams if changed
  useEffect(() => {
    if (queryParams?.scenario && queryParams.scenario !== scenario) {
      setScenario(queryParams.scenario);
    }
  }, [queryParams?.scenario]);

  const handleScenarioChange = (newSc: string) => {
    setScenario(newSc);
    setSelectedScenario(newSc);
    onScenarioChange?.(newSc);
    if (typeof window !== 'undefined') {
      const rawHash = window.location.hash.replace(/^#\/?/, '');
      const [route, queryStr] = rawHash.split('?');
      const sp = new URLSearchParams(queryStr || '');
      sp.set('scenario', newSc);
      window.location.hash = `#/${route || 'missions'}?${sp.toString()}`;
    }
  };

  // Fetch missions for scenario
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

  // If id is provided in queryParams, scroll to that card
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
    completed: 0,
    total: 0,
    deliveryScore: 0.0,
    maxDeliveryScore: 0.0,
    efficiencyScore: 0.0,
    maxEfficiencyScore: 0.0,
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full min-w-[1240px] gap-5">
      {/* Top Scenario Selector & Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-500 font-medium">Сценарий:</label>
          <div className="relative min-w-[200px]">
            <select
              value={scenario}
              onChange={(e) => handleScenarioChange(e.target.value)}
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
                <div className={`text-xs font-semibold px-3 py-1 rounded-full border flex items-center gap-1.5 font-mono ${
                  m.status === 'DELIVERED'
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : m.status === 'TIMEOUT'
                    ? 'bg-red-50 text-red-700 border-red-200'
                    : 'bg-amber-50 text-amber-700 border-amber-200'
                }`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    m.status === 'DELIVERED' ? 'bg-emerald-600' : m.status === 'TIMEOUT' ? 'bg-red-600' : 'bg-amber-600'
                  }`}></span>
                  {m.status === 'DELIVERED'
                    ? 'ДОСТАВЛЕНО'
                    : m.status === 'TIMEOUT'
                    ? 'ТАЙМАУТ'
                    : m.status || 'В ПУТИ'}
                </div>
              </div>

              {/* Metrics Grid matching mockup */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-3 text-xs font-mono">
                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Старт миссии</span>
                  <span className="text-slate-900 font-semibold">{(m.t_start ?? 0).toFixed(1)} с</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Макс. дистанция холда</span>
                  <span className="text-slate-900 font-semibold">
                    {(m.max_hold_dist ?? 0).toFixed(4)} м / допуск {(m.tol ?? 0).toFixed(2)} м
                  </span>
                </div>

                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Прибытие в док</span>
                  <span className="text-slate-900 font-semibold">{(m.actual_time_s ?? 0).toFixed(1)} с</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-50">
                  <span className="text-slate-500">Дедлайн доставки</span>
                  <span className="text-slate-900 font-semibold">
                    {(m.deadline_s ?? 0).toFixed(1)} с (запас +{(m.safety_margin_s ?? 0).toFixed(1)} с)
                  </span>
                </div>

                <div className="flex justify-between py-1">
                  <span className="text-slate-500">Удержание (холд)</span>
                  <span className="text-slate-900 font-semibold">
                    {(m.hold_duration_s ?? 0).toFixed(1)} с ({m.hold_ticks ?? 0} тиков)
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-slate-500">Опорная длина пути</span>
                  <span className="text-slate-900 font-semibold">
                    {(m.reference_length_m ?? 0).toFixed(1)} м
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
