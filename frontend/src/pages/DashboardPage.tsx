import React, { useState } from 'react';
import { RouteName } from '../types';
import { mockDashboardData, mockTicks } from '../mock/mockData';
import { MapCanvas } from '../components/MapCanvas';
import { Upload, Play, ArrowRight, ChevronDown } from 'lucide-react';

interface DashboardPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({ onNavigate }) => {
  const [selectedScenario, setSelectedScenario] = useState('04_busy_yard');

  // Preview tick for map
  const previewTick = mockTicks[200] || mockTicks[0];
  const historyTicks = mockTicks.slice(0, 200);

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Subheader Toolbar matching dashboard.png */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="font-bold text-slate-800 text-sm tracking-tight">AMR-SIM</span>
          <span className="text-slate-400 text-xs">//</span>
          <span className="text-slate-600 text-xs font-medium">Станция управления безопасными маршрутами</span>
        </div>

        <div className="flex items-center gap-3">
          {/* Upload Log Button */}
          <label className="cursor-pointer flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors font-medium">
            <Upload className="w-3.5 h-3.5" />
            <span>Загрузить лог</span>
            <input type="file" className="hidden" accept=".json,.jsonl" onChange={() => alert('Лог успешно импортирован (Mock)')} />
          </label>
        </div>
      </div>

      {/* Top KPI Cards (4 items) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Total Score (clickable -> /analytics as per frontend.md) */}
        <div 
          onClick={() => onNavigate('analytics')}
          className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4 cursor-pointer hover:border-blue-400 hover:shadow-md transition-all group"
          title="Нажмите для перехода в детальную Аналитику"
        >
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
                strokeDasharray="97.31, 100"
                strokeWidth="3.5"
                strokeLinecap="round"
                stroke="currentColor"
                fill="none"
                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
              />
            </svg>
            <span className="absolute text-[11px] font-bold text-slate-800 font-mono">97.31</span>
          </div>

          <div>
            <div className="text-xs text-slate-500 font-medium group-hover:text-blue-600 transition-colors flex items-center gap-1">
              <span>Общий балл</span>
              <ArrowRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              97.31 <span className="text-sm font-normal text-slate-400">/ 100</span>
            </div>
          </div>
        </div>

        {/* KPI 2: Deliveries */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-emerald-500 ring-4 ring-emerald-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Доставки</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              2 <span className="text-sm font-normal text-slate-400">/ 2</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Safety */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-amber-500 ring-4 ring-amber-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Безопасность</div>
            <div className="text-sm font-bold text-slate-900 mt-1">
              <span className="text-slate-900">0</span> Фатальных · <span className="text-amber-600 font-mono font-semibold">3</span> Предупреждения
            </div>
          </div>
        </div>

        {/* KPI 4: Localization Error */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-slate-400 ring-4 ring-slate-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Ошибка локализации</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              0.18 <span className="text-sm font-normal text-slate-500">м</span>
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
              <h2 className="text-sm font-semibold text-slate-800">План склада</h2>
              <div className="flex items-center gap-4 text-xs text-slate-500">
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-emerald-600 inline-block"></span>
                  Траектория AMR
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-2 bg-slate-200 inline-block rounded-sm"></span>
                  Движение (проезжая часть)
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full border border-blue-600 inline-block"></span>
                  Док
                </span>
              </div>
            </div>

            {/* Canvas mini-map */}
            <div className="w-full h-80 bg-slate-50 rounded-lg overflow-hidden border border-slate-200 relative">
              <MapCanvas
                currentTick={previewTick}
                historyTicks={historyTicks}
                isMiniMap={true}
                followRobot={false}
              />
            </div>

            {/* Sole navigation link to Replay as per frontend.md */}
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => onNavigate('replay')}
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
              <h2 className="text-sm font-semibold text-slate-800">Скорость AMR</h2>
            </div>
            
            {/* SVG Speed Curve matching mockup */}
            <div className="w-full h-36 relative mt-2">
              <svg className="w-full h-full overflow-visible" viewBox="0 0 600 100" preserveAspectRatio="none">
                {/* Horizontal grid lines */}
                <line x1="0" y1="20" x2="600" y2="20" stroke="#F1F5F9" strokeWidth="1" />
                <line x1="0" y1="50" x2="600" y2="50" stroke="#F1F5F9" strokeWidth="1" />
                <line x1="0" y1="80" x2="600" y2="80" stroke="#F1F5F9" strokeWidth="1" />

                {/* Y-axis labels */}
                <text x="5" y="24" className="text-[9px] fill-slate-400 font-mono">1.5</text>
                <text x="5" y="54" className="text-[9px] fill-slate-400 font-mono">1.0</text>
                <text x="5" y="84" className="text-[9px] fill-slate-400 font-mono">0.5</text>
                <text x="5" y="98" className="text-[9px] fill-slate-400 font-mono">0.0</text>

                {/* Smooth velocity line */}
                <path
                  d="M 30,95 Q 60,65 100,50 T 150,70 T 200,90 T 250,55 T 300,60 T 350,70 T 400,95 T 450,45 T 500,45 T 550,90 T 580,60"
                  fill="none"
                  stroke="#2563EB"
                  strokeWidth="2"
                />
              </svg>

              {/* X-axis time labels */}
              <div className="flex justify-between text-[10px] text-slate-400 font-mono mt-1 px-4">
                <span>00:00</span>
                <span>02:00</span>
                <span>04:00</span>
                <span>06:00</span>
                <span>08:00</span>
                <span>10:00</span>
              </div>
              <div className="text-right text-[10px] text-slate-400 font-mono mt-0.5">
                Время, мин
              </div>
            </div>
          </div>
        </div>

        {/* Right Column (4 cols): Quick Launch, Recent Events, Controller State */}
        <div className="lg:col-span-4 flex flex-col gap-5">
          {/* Card: Быстрый запуск */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
            <h2 className="text-sm font-semibold text-slate-800">Быстрый запуск</h2>
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1.5">Сценарий</label>
              <div className="relative">
                <select
                  value={selectedScenario}
                  onChange={(e) => setSelectedScenario(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                >
                  <option value="01_clear">01_clear.json (Ясная погода)</option>
                  <option value="02_gnss_shadow">02_gnss_shadow.json (Тень ГНСС)</option>
                  <option value="03_fog_snow">03_fog_snow.json (Туман и снег)</option>
                  <option value="04_busy_yard">04_busy_yard.json (Оживленный двор)</option>
                </select>
                <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
              </div>
            </div>

            {/* Sole button leading to /runner as per frontend.md */}
            <button
              onClick={() => onNavigate('runner')}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Запустить симуляцию</span>
            </button>
          </div>

          {/* Card: Последние события (Header links to /episodes as per frontend.md) */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800">Последние события</h2>
              <button
                onClick={() => onNavigate('episodes')}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-0.5"
              >
                <span>Все события</span>
                <ArrowRight className="w-3 h-3" />
              </button>
            </div>

            <div className="flex flex-col gap-3 mt-1">
              {mockDashboardData.recentEvents.map((evt) => (
                <div key={evt.id} className="flex items-start justify-between text-xs py-1 border-b border-slate-100 last:border-0">
                  <div className="flex items-start gap-2.5">
                    <span className={`w-2 h-2 rounded-full mt-1 flex-shrink-0 ${
                      evt.status === 'success' ? 'bg-emerald-500' : evt.status === 'warning' ? 'bg-amber-500' : 'bg-blue-500'
                    }`} />
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
              <h2 className="text-sm font-semibold text-slate-800">Состояние контроллера</h2>
              <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                Онлайн
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 mt-1 pt-2 border-t border-slate-100">
              <div>
                <div className="text-[11px] text-slate-500">Средняя задержка (цикл)</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {mockDashboardData.controllerState.meanDelayMs} <span className="text-xs font-normal text-slate-500">мс</span>
                </div>
                <div className="text-[10px] text-slate-400 font-mono">mean</div>
              </div>

              <div>
                <div className="text-[11px] text-slate-500">Максимальная задержка (цикл)</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {mockDashboardData.controllerState.maxDelayMs} <span className="text-xs font-normal text-slate-500">мс</span>
                </div>
                <div className="text-[10px] text-slate-400 font-mono">max</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
