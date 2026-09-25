import React, { useState } from 'react';
import { RouteName, EpisodeData } from '../types';
import { mockEpisodes } from '../mock/mockData';
import { Search, ChevronDown, Play, X, User } from 'lucide-react';

interface EpisodesPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    type?: string;
  };
}

export const EpisodesPage: React.FC<EpisodesPageProps> = ({ onNavigate, queryParams }) => {
  const [selectedEpisode, setSelectedEpisode] = useState<EpisodeData>(mockEpisodes[0]);
  const [typeFilter, setTypeFilter] = useState<string>(queryParams?.type || 'all');
  const [costFilter, setCostFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Filtering
  const filteredEpisodes = mockEpisodes.filter(ep => {
    if (typeFilter !== 'all' && ep.type !== typeFilter) return false;
    if (costFilter === 'high' && ep.cost > -1.0) return false;
    if (costFilter === 'low' && ep.cost <= -1.0) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        ep.type.toLowerCase().includes(q) ||
        ep.category.toLowerCase().includes(q) ||
        ep.x.toString().includes(q) ||
        ep.y.toString().includes(q)
      );
    }
    return true;
  });

  const handleInspect = (ep: EpisodeData) => {
    setSelectedEpisode(ep);
    // Navigation to replay with parameters as per frontend.md:
    onNavigate('replay', { t: ep.t_start, x: ep.x, y: ep.y });
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* 4 Metric Cards matching episodes.png */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Штрафные баллы */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-red-500 ring-4 ring-red-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Штрафные баллы</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              -2.69 <span className="text-xs font-normal text-slate-400">pts</span>
            </div>
          </div>
        </div>

        {/* Card 2: Фатальные */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-slate-400 ring-4 ring-slate-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Фатальные</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              0
            </div>
          </div>
        </div>

        {/* Card 3: Предупреждения по безопасности */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-amber-500 ring-4 ring-amber-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Предупреждения по безопасности</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              1
            </div>
          </div>
        </div>

        {/* Card 4: Дрейф позы */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-blue-500 ring-4 ring-blue-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Дрейф позы</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              2
            </div>
          </div>
        </div>
      </div>

      {/* Filters Bar matching episodes.png */}
      <div className="bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center gap-4">
        {/* Type filter */}
        <div className="flex flex-col gap-1 min-w-[170px]">
          <span className="text-[11px] text-slate-500 font-medium">Тип эпизода</span>
          <div className="relative">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              <option value="all">Все типы</option>
              <option value="person_near_fast">person_near_fast</option>
              <option value="pose_drift">pose_drift</option>
              <option value="obstacle_close">obstacle_close</option>
              <option value="speed_limit">speed_limit</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
          </div>
        </div>

        {/* Cost filter */}
        <div className="flex flex-col gap-1 min-w-[170px]">
          <span className="text-[11px] text-slate-500 font-medium">Стоимость</span>
          <div className="relative">
            <select
              value={costFilter}
              onChange={(e) => setCostFilter(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              <option value="all">Все значения</option>
              <option value="high">Высокий штраф ( &gt; 1 pt )</option>
              <option value="low">Низкий штраф ( &le; 1 pt )</option>
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
          </div>
        </div>

        {/* Search Input */}
        <div className="flex flex-col gap-1 flex-1 min-w-[240px]">
          <span className="text-[11px] text-transparent select-none">Поиск</span>
          <div className="relative">
            <input
              type="text"
              placeholder="Поиск по эпизодам, правилам, координатам..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg pl-9 pr-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
          </div>
        </div>
      </div>

      {/* Main Grid: Episodes Table (8 cols) & Detail Drawer (4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Table (8 cols) */}
        <div className="lg:col-span-8 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
                <tr>
                  <th className="py-3 px-4 w-12 text-center">Серьёзность</th>
                  <th className="py-3 px-4">Тип эпизода</th>
                  <th className="py-3 px-4">Категория правила</th>
                  <th className="py-3 px-4">Временной интервал</th>
                  <th className="py-3 px-4 font-mono">Координаты</th>
                  <th className="py-3 px-4 font-mono text-right">Стоимость</th>
                  <th className="py-3 px-4 text-center">Действие</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredEpisodes.map((ep) => {
                  const isSelected = selectedEpisode?.id === ep.id;
                  const dotColor = ep.severity === 'warning' ? 'bg-amber-500' : ep.severity === 'info' ? 'bg-blue-500' : 'bg-emerald-500';

                  return (
                    <tr 
                      key={ep.id}
                      onClick={() => setSelectedEpisode(ep)}
                      className={`hover:bg-blue-50/50 transition-colors cursor-pointer ${
                        isSelected ? 'bg-blue-50/80 font-medium' : ''
                      }`}
                    >
                      <td className="py-3 px-4 text-center">
                        <span className={`w-2.5 h-2.5 rounded-full inline-block ${dotColor}`}></span>
                      </td>
                      <td className="py-3 px-4 font-mono font-medium text-slate-900">{ep.type}</td>
                      <td className="py-3 px-4 text-slate-600">{ep.category}</td>
                      <td className="py-3 px-4 font-mono text-slate-600">{ep.t_start.toFixed(1)} s – {ep.t_end.toFixed(1)} s</td>
                      <td className="py-3 px-4 font-mono text-slate-500">({ep.x.toFixed(1)}, {ep.y.toFixed(1)})</td>
                      <td className="py-3 px-4 font-mono text-right text-red-600 font-semibold">{ep.cost.toFixed(2)}</td>
                      <td className="py-3 px-4 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleInspect(ep);
                          }}
                          className="text-blue-600 hover:text-blue-800 font-medium text-xs hover:underline"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Details Panel matching episodes.png (4 cols) */}
        <div className="lg:col-span-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-800">Детали эпизода</h2>
          </div>

          {selectedEpisode && (
            <div className="flex flex-col gap-4">
              {/* Header: Type and Cost */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${
                      selectedEpisode.severity === 'warning' ? 'bg-amber-500' : selectedEpisode.severity === 'info' ? 'bg-blue-500' : 'bg-emerald-500'
                    }`}></span>
                    <span className="font-mono font-bold text-sm text-slate-900">{selectedEpisode.type}</span>
                  </div>
                  <span className="font-mono font-bold text-red-600 text-sm">{selectedEpisode.cost.toFixed(2)} pts</span>
                </div>
                <div className="text-xs text-slate-500 mt-1 flex justify-between font-mono">
                  <span>{selectedEpisode.category}</span>
                  <span>{selectedEpisode.t_start} s – {selectedEpisode.t_end} s</span>
                </div>
              </div>

              {/* Radar Mini-map Snapshot */}
              <div className="w-full h-36 bg-slate-50 rounded-lg border border-slate-200 relative overflow-hidden flex items-center justify-center">
                {/* SVG Mockup Radar */}
                <svg className="w-full h-full" viewBox="0 0 200 100">
                  {/* Road */}
                  <rect x="0" y="35" width="200" height="30" fill="#E8EEF5" />
                  {/* Buildings */}
                  <rect x="20" y="5" width="60" height="25" fill="#CBD5E1" rx="2" />
                  <rect x="100" y="5" width="80" height="25" fill="#CBD5E1" rx="2" />
                  <rect x="20" y="70" width="70" height="25" fill="#CBD5E1" rx="2" />
                  <rect x="110" y="70" width="70" height="25" fill="#CBD5E1" rx="2" />

                  {/* Robot */}
                  <circle cx="70" cy="50" r="6" fill="#10B981" stroke="#065F46" strokeWidth="1.5" />
                  <line x1="70" y1="50" x2="80" y2="50" stroke="#FFFFFF" strokeWidth="2" />

                  {/* Pedestrian */}
                  <circle cx="130" cy="46" r="4" fill="#F97316" stroke="#FFFFFF" strokeWidth="1" />
                  <circle cx="130" cy="46" r="14" fill="rgba(249, 115, 22, 0.15)" stroke="rgba(249, 115, 22, 0.4)" strokeWidth="1" />

                  {/* Distance line */}
                  <line x1="76" y1="50" x2="126" y2="46" stroke="#EF4444" strokeWidth="1.5" strokeDasharray="3 2" />

                  {/* Lidar rays */}
                  <line x1="70" y1="50" x2="50" y2="30" stroke="rgba(147, 197, 253, 0.5)" strokeWidth="1" />
                  <line x1="70" y1="50" x2="60" y2="20" stroke="rgba(147, 197, 253, 0.5)" strokeWidth="1" />
                  <line x1="70" y1="50" x2="80" y2="25" stroke="rgba(147, 197, 253, 0.5)" strokeWidth="1" />
                </svg>

                {/* Legend badges */}
                <div className="absolute bottom-1 left-2 flex items-center gap-3 text-[9px] text-slate-500">
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Робот</span>
                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-orange-500"></span> Пешеход</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-0.5 bg-red-400"></span> Расстояние</span>
                </div>
              </div>

              {/* Telemetry Snapshot Grid matching mockup */}
              <div>
                <span className="text-xs font-semibold text-slate-700 block mb-1.5">Телеметрия</span>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs font-mono bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <div className="flex justify-between">
                    <span className="text-slate-400">v</span>
                    <span className="text-slate-800 font-semibold">{selectedEpisode.telemetrySnapshot?.v} m/s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">pe</span>
                    <span className="text-slate-800">{selectedEpisode.telemetrySnapshot?.pe_error}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">cv</span>
                    <span className="text-slate-700">{selectedEpisode.telemetrySnapshot?.cv} m/s</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">status</span>
                    <span className="text-emerald-700 font-semibold">{selectedEpisode.telemetrySnapshot?.status}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">hum</span>
                    <span className="text-amber-700 font-semibold">{selectedEpisode.telemetrySnapshot?.hum} m</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">note</span>
                    <span className="text-slate-700 truncate max-w-[80px]">{selectedEpisode.telemetrySnapshot?.note}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">obj</span>
                    <span className="text-slate-800">{selectedEpisode.telemetrySnapshot?.obj} m</span>
                  </div>
                </div>
              </div>

              {/* Пояснение правила */}
              <div>
                <span className="text-xs font-semibold text-slate-700 block mb-1">Пояснение правила</span>
                <p className="text-xs text-slate-600 leading-relaxed bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                  {selectedEpisode.ruleExplanation}
                </p>
              </div>

              {/* Sole action button to Replay as per frontend.md */}
              <button
                onClick={() => handleInspect(selectedEpisode)}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors mt-1"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Open in Replay at {selectedEpisode.t_start} s · 0.5x</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
