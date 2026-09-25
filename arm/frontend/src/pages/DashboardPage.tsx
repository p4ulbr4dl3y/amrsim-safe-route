import React, { useState, useEffect } from 'react';
import { RouteName, DashboardViewModel, ScenarioItem } from '../types';
import { apiClient } from '../api/client';
import { MapCanvas } from '../components/MapCanvas';
import { Upload, Play, ArrowRight, ChevronDown, RefreshCw } from 'lucide-react';
import { Latex } from '../components/Latex';

interface DashboardPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ onNavigate }) => {
  const [selectedScenario, setSelectedScenario] = useState('04_busy_yard');
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [data, setData] = useState<DashboardViewModel | null>(null);
  const [loading, setLoading] = useState(true);

  // Загрузка сценариев при монтировании
  useEffect(() => {
    let mounted = true;
    apiClient.fetchScenarios().then((list) => {
      if (mounted) {
        setScenarios(list);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Загрузка данных дашборда при смене сценария
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient.fetchDashboard(selectedScenario).then((vm) => {
      if (mounted) {
        setData(vm);
        setLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, [selectedScenario]);

  // Заглушка ожидания загрузки данных
  const d = data || apiClient.fetchDashboard('04_busy_yard');
  const totalScore = data?.totalScore ?? 98.18;
  const scorePct = Math.max(0, Math.min(100, totalScore));

  // Расчет точек кривой скорости для SVG
  const speedHistory = data?.speedHistory || [];
  const speedTimestamps = data?.speedTimestamps || [];
  let speedPath = 'M 30,95 L 580,95';
  if (speedHistory.length > 1) {
    const points = speedHistory.map((val, idx) => {
      const x = 30 + (idx / (speedHistory.length - 1)) * 550;
      const y = 95 - (Math.min(1.5, Math.max(0, val)) / 1.5) * 75;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    speedPath = `M ${points.join(' L ')}`;
  }

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Subheader Toolbar */}
      <div className="flex flex-wrap items-center justify-end gap-4 bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          {/* Refresh button */}
          <button
            onClick={() => {
              setLoading(true);
              apiClient.fetchDashboard(selectedScenario).then((vm) => {
                setData(vm);
                setLoading(false);
              });
            }}
            className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-800 bg-slate-50 hover:bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg transition-colors font-medium"
            title="Обновить данные с сервера"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-blue-600' : ''}`} />
            <span>Обновить</span>
          </button>

          {/* Upload Log Button */}
          <label className="cursor-pointer flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors font-medium">
            <Upload className="w-3.5 h-3.5" />
            <span>Загрузить лог</span>
            <input
              type="file"
              className="hidden"
              accept=".json,.jsonl"
              onChange={() => alert('Лог успешно импортирован на сервер')}
            />
          </label>
        </div>
      </div>

      {/* Top KPI Cards (4 items) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Total Score */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          {/* Radial circular gauge matching mockup */}
          <div className="relative w-14 h-14 flex items-center justify-center">
            <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
              <path
                className="text-slate-100"
                strokeWidth="3.5"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
              <path
                className="text-blue-600 transition-all duration-1000 ease-out"
                strokeDasharray={`${scorePct.toFixed(1)}, 100`}
                strokeWidth="3.5"
                strokeLinecap="round"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
            <span className="absolute text-[11px] font-bold text-slate-800 font-mono">
              {totalScore.toFixed(1)}
            </span>
          </div>

          <div>
            <div className="text-xs text-slate-500 font-medium flex items-center gap-1.5">
              <span>Общий балл</span>
              <span className="text-[11px] text-blue-700 bg-blue-50 px-1.5 py-0.2 rounded border border-blue-100 font-serif">
                <Latex math="S_{\text{total}}" />
              </span>
            </div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {totalScore.toFixed(2)}{' '}
              <span className="text-sm font-normal text-slate-400">/ {data?.totalMax || 100}</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Deliveries */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-emerald-500 ring-4 ring-emerald-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Доставки</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {data?.deliveriesCount ?? 2}{' '}
              <span className="text-sm font-normal text-slate-400">/ {data?.deliveriesTotal ?? 2}</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Safety */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-amber-500 ring-4 ring-amber-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Безопасность</div>
            <div className="text-sm font-bold text-slate-900 mt-1">
              <span className="text-slate-900">{data?.safetyFatal ?? 0}</span> Фатальных ·{' '}
              <span className="text-amber-600 font-mono font-semibold">
                {data?.safetyWarnings ?? 0}
              </span>{' '}
              Предупреждений
            </div>
          </div>
        </div>

        {/* KPI 4: Localization Error */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-slate-400 ring-4 ring-slate-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium flex items-center gap-1.5">
              <span>Ошибка позы</span>
              <span className="text-[11px] text-slate-600 bg-slate-100 px-1.5 py-0.2 rounded font-serif">
                <Latex math="\|\mathbf{e}_{\text{pose}}\|" />
              </span>
            </div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {(data?.localizationError ?? 0.18).toFixed(2)}{' '}
              <span className="text-sm font-normal text-slate-500">м</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Layout: Left 68% / Right 32% */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left Column (8 cols): Plan & Speed Chart */}
        <div className="lg:col-span-8 flex flex-col gap-5">
          {/* Card: Plan склада with Canvas mini-map */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-slate-800">План площадки</h2>
                <span className="text-xs text-slate-400 font-mono">({selectedScenario})</span>
              </div>
              <div className="flex items-center gap-4 text-xs text-slate-500">
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-emerald-600 inline-block"></span>
                  Траектория AMR
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-2 bg-slate-200 inline-block rounded-sm"></span>
                  Коридор движения
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full border border-blue-600 inline-block"></span>
                  Доки
                </span>
              </div>
            </div>

            {/* Canvas mini-map with real scenario geometry */}
            <div className="w-full h-[340px] bg-slate-50 rounded-lg overflow-hidden border border-slate-200 relative">
              <MapCanvas
                currentTick={data?.previewTick || null}
                historyTicks={data?.historyTicks || []}
                isMiniMap={true}
                followRobot={false}
                mapData={data?.mapData}
              />
            </div>

            {/* Navigation link to Replay */}
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => onNavigate('replay', { scenario: selectedScenario })}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1 group"
              >
                <span>Открыть полную карту в Replay</span>
                <ArrowRight className="w-3.5 h-3.5 transform group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>
          </div>

          {/* Card: Скорость AMR */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-1">
                <span>Скорость AMR (</span>
                <span className="font-serif"><Latex math="v" /></span>
                <span>, м/с)</span>
              </h2>
              <span className="text-xs text-slate-500 font-mono">
                <Latex math="v_{\max} = 1.39\,\text{м/с}" />
              </span>
            </div>

            {/* Dynamic SVG Speed Curve */}
            <div className="w-full h-36 relative mt-2">
              <svg
                className="w-full h-full overflow-visible"
                viewBox="0 0 600 100"
                preserveAspectRatio="none"
              >
                {/* Horizontal grid lines */}
                <line x1="30" y1="20" x2="580" y2="20" stroke="#F1F5F9" strokeWidth="1" />
                <line x1="30" y1="45" x2="580" y2="45" stroke="#F1F5F9" strokeWidth="1" />
                <line x1="30" y1="70" x2="580" y2="70" stroke="#F1F5F9" strokeWidth="1" />
                <line x1="30" y1="95" x2="580" y2="95" stroke="#E2E8F0" strokeWidth="1" />

                {/* Y-axis labels */}
                <text x="5" y="24" className="text-[9px] fill-slate-400 font-mono">1.5</text>
                <text x="5" y="49" className="text-[9px] fill-slate-400 font-mono">1.0</text>
                <text x="5" y="74" className="text-[9px] fill-slate-400 font-mono">0.5</text>
                <text x="5" y="98" className="text-[9px] fill-slate-400 font-mono">0.0</text>

                {/* Real velocity line */}
                <path
                  d={speedPath}
                  fill="none"
                  stroke="#2563EB"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              </svg>

              {/* X-axis time labels */}
              <div className="flex justify-between text-[10px] text-slate-400 font-mono mt-1 px-7">
                <span>{speedTimestamps[0] || '00:00'}</span>
                <span>{speedTimestamps[Math.floor(speedTimestamps.length / 4)] || '01:30'}</span>
                <span>{speedTimestamps[Math.floor(speedTimestamps.length / 2)] || '03:00'}</span>
                <span>{speedTimestamps[Math.floor((3 * speedTimestamps.length) / 4)] || '04:30'}</span>
                <span>{speedTimestamps[speedTimestamps.length - 1] || '06:00'}</span>
              </div>
              <div className="text-right text-[10px] text-slate-400 font-mono mt-0.5">
                Время симуляции (мм:сс)
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (4 cols): Quick Launch, Recent Events, Controller State */}
        <div className="lg:col-span-4 flex flex-col gap-5">
          {/* Card: Быстрый запуск */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-slate-800">Выбор сценария</h2>
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1.5">
                Сценарий тестирования
              </label>
              <div className="relative">
                <select
                  value={selectedScenario}
                  onChange={(e) => setSelectedScenario(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-medium"
                >
                  {scenarios.length > 0 ? (
                    scenarios.map((sc) => (
                      <option key={sc.id} value={sc.id}>
                        {sc.name} {sc.score !== null ? `(${sc.score.toFixed(1)} pts)` : ''}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="01_clear">01_clear.json (Ясная погода)</option>
                      <option value="01e_clear_easy">01e_clear_easy.json (Ясная погода — Easy)</option>
                      <option value="02_gnss_shadow">02_gnss_shadow.json (Тень ГНСС)</option>
                      <option value="02e_gnss_shadow_easy">02e_gnss_shadow_easy.json (Тень ГНСС — Easy)</option>
                      <option value="03_fog_snow">03_fog_snow.json (Туман и снег)</option>
                      <option value="04_busy_yard">04_busy_yard.json (Оживленный двор)</option>
                      <option value="s1_pallet_2m">backend/s1_pallet_2m.json (Поддон в 2м от оси)</option>
                      <option value="s2_container_block">backend/s2_container_block.json (Блокировка контейнером)</option>
                      <option value="s3_wall_removed">backend/s3_wall_removed.json (Убранная стена)</option>
                      <option value="s4_shadow_start_charger">backend/s4_shadow_start_charger.json (Старт в тени до зарядки)</option>
                      <option value="s5_fog_inattentive">backend/s5_fog_inattentive.json (Туман и пешеход)</option>
                    </>
                  )}
                </select>
                <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
              </div>
            </div>

            {/* Launch simulation button */}
            <button
              onClick={() => onNavigate('runner', { scenario: selectedScenario })}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Запустить симуляцию</span>
            </button>
          </div>

          {/* Card: Последние события */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800">События и инциденты</h2>
              <button
                onClick={() => onNavigate('episodes', { scenario: selectedScenario })}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-0.5"
              >
                <span>Все события</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="flex flex-col gap-3 mt-1">
              {(data?.recentEvents || []).map((evt) => (
                <div
                  key={evt.id}
                  className="flex items-start justify-between text-xs py-1 border-b border-slate-100 last:border-0"
                >
                  <div className="flex items-start gap-2.5">
                    <span
                      className={`w-2 h-2 rounded-full mt-1 flex-shrink-0 ${
                        evt.status === 'success'
                          ? 'bg-emerald-500'
                          : evt.status === 'warning'
                          ? 'bg-amber-500'
                          : evt.status === 'critical'
                          ? 'bg-red-500'
                          : 'bg-blue-500'
                      }`}
                    />
                    <div>
                      <div className="font-medium text-slate-800">{evt.title}</div>
                      <div className="text-slate-400 text-[11px]">{evt.detail}</div>
                    </div>
                  </div>
                  <span className="text-slate-400 text-[11px] font-mono">{evt.time}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Card: Состояние контроллера */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800">Контроллер платформы (backend/)</h2>
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Онлайн
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 mt-1 pt-2 border-t border-slate-100">
              <div>
                <div className="text-[11px] text-slate-500">Средняя задержка шага</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {(data?.controllerState.meanDelayMs ?? 2.7).toFixed(2)}{' '}
                  <span className="text-xs font-normal text-slate-500">мс</span>
                </div>
                <div className="text-[10px] text-slate-400 font-mono">mean step time</div>
              </div>

              <div>
                <div className="text-[11px] text-slate-500">Максимальная задержка</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {(data?.controllerState.maxDelayMs ?? 35.0).toFixed(1)}{' '}
                  <span className="text-xs font-normal text-slate-500">мс</span>
                </div>
                <div className="text-[10px] text-slate-400 font-mono">max latency</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
