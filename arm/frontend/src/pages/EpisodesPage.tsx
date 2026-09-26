import React, { useState, useEffect } from 'react';
import { RouteName, EpisodeData, ScenarioItem, EpisodesViewModel } from '../types';
import { apiClient } from '../api/client';
import { Search, ChevronDown, RefreshCw, AlertTriangle, ShieldCheck, MapPin, Gauge, Download } from 'lucide-react';
import { Latex } from '../components/Latex';
import {
  getSelectedScenario,
  setSelectedScenario,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';

const EPISODE_FORMULAS: Record<string, { formula: string; condition: string }> = {
  person_near_fast: {
    formula: 'S_{\\text{pen}} = -2.0 \\times \\Delta t_{\\text{sec}}',
    condition: 'd_{\\text{hum}} < 3.0\\,\\text{м} \\land |v| > 0.28\\,\\text{м/с}',
  },
  person_near_slow: {
    formula: 'S_{\\text{pen}} = 0.0',
    condition: 'd_{\\text{hum}} \\ge 0.5\\,\\text{м} \\land |v| \\le 0.28\\,\\text{м/с}',
  },
  close_pass: {
    formula: 'S_{\\text{pen}} = -10.0',
    condition: 'd_{\\text{hum}} < 0.5\\,\\text{м} \\land |v| > 0.0\\,\\text{м/с}',
  },
  person_close_pass: {
    formula: 'S_{\\text{pen}} = -10.0',
    condition: 'd_{\\text{hum}} < 0.5\\,\\text{м} \\land |v| > 0.0\\,\\text{м/с}',
  },
  person_contact_standing: {
    formula: 'S_{\\text{pen}} = -10.0',
    condition: '\\text{contact} \\land |v|_{1\\text{s}} \\le 0.1\\,\\text{м/с}',
  },
  person_contact_moving: {
    formula: 'S_{\\text{total}} = 0 \\quad (\\text{FATAL})',
    condition: '\\text{contact} \\land |v|_{1\\text{s}} > 0.1\\,\\text{м/с}',
  },
  out_of_drivable: {
    formula: 'S_{\\text{pen}} = -3.0',
    condition: 'd_{\\text{drv}} < 0.5\\,\\text{м}',
  },
  forbidden_zone: {
    formula: 'S_{\\text{pen}} = -5.0',
    condition: '\\mathbf{p} \\in \\text{forbidden}',
  },
  speed_limit: {
    formula: 'S_{\\text{pen}} = -2.0',
    condition: '|v| > v_{\\max} + 0.05\\,\\text{м/с}',
  },
  overspeed: {
    formula: 'S_{\\text{pen}} = -2.0',
    condition: '|v| > v_{\\max} + 0.05\\,\\text{м/с}',
  },
  pose_drift: {
    formula: 'S_{\\text{pen}} = -3.0',
    condition: '\\|\\hat{\\mathbf{p}} - \\mathbf{p}\\| > 1.0\\,\\text{м} \\land |v| > 0.05\\,\\text{м/с} \\land \\Delta t > 5.0\\,\\text{с}',
  },
  pose_error: {
    formula: 'S_{\\text{pen}} = -3.0',
    condition: '\\|\\hat{\\mathbf{p}} - \\mathbf{p}\\| > 1.0\\,\\text{м} \\land |v| > 0.05\\,\\text{м/с} \\land \\Delta t > 5.0\\,\\text{с}',
  },
  status_mismatch: {
    formula: 'S_{\\text{pen}} = -2.0',
    condition: '\\text{status} \\neq \\text{moving} \\land |v| > 0.05\\,\\text{м/с} \\land \\Delta t > 1.0\\,\\text{с}',
  },
  estop_no_object: {
    formula: 'S_{\\text{pen}} = -1.0',
    condition: '\\text{status} = \\text{estop} \\land d_{\\text{obj}} \\ge 1.5\\,\\text{м}',
  },
  collision: {
    formula: 'S_{\\text{pen}} = -30.0',
    condition: '\\text{контакт со стеной / объектом}',
  },
  obstacle_close: {
    formula: 'd_{\\text{obj}} < 0.8\\,\\text{м}',
    condition: '\\text{сближение со статическим объектом}',
  },
};

interface EpisodesPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    scenario?: string;
    type?: string;
  };
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

export const EpisodesPage: React.FC<EpisodesPageProps> = ({
  onNavigate,
  queryParams,
  activeScenario,
  onScenarioChange,
}) => {
  const [scenario, setScenario] = useState(
    activeScenario || queryParams?.scenario || getSelectedScenario()
  );
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [episodesData, setEpisodesData] = useState<EpisodesViewModel | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<EpisodeData | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>(queryParams?.type || 'all');
  const [costFilter, setCostFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
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

  // Fetch episodes when scenario changes
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient.fetchEpisodes(scenario).then((vm) => {
      if (!mounted) return;
      setEpisodesData(vm);
      if (vm.episodes.length > 0) {
        setSelectedEpisode(vm.episodes[0]);
      } else {
        setSelectedEpisode(null);
      }
      setLoading(false);
    });
    return () => {
      mounted = false;
    };
  }, [scenario]);

  // CSV Export handler
  const handleExportCSV = () => {
    if (episodesData && episodesData.episodes && episodesData.episodes.length > 0) {
      const headers = "Episode ID,Type,Category,Severity,Start (s),End (s),X,Y,Speed (m/s),Hum Dist (m),Obj Dist (m),PE Error (m),Cost (pts),Explanation";
      const rows = episodesData.episodes.map((ep) => {
        const snap = (ep.telemetrySnapshot || {}) as Record<string, any>;
        const v = typeof snap.v === 'number' ? snap.v.toFixed(2) : '';
        const hum = typeof snap.hum === 'number' ? snap.hum.toFixed(2) : '';
        const obj = typeof snap.obj === 'number' ? snap.obj.toFixed(2) : '';
        const pe = typeof snap.pe_error === 'number' ? snap.pe_error.toFixed(4) : '';
        const cost = (ep.cost || 0).toFixed(2);
        const expl = (ep.ruleExplanation || '').replace(/"/g, '""');
        return `${ep.id},${ep.type},${ep.category},${ep.severity || 'info'},${ep.t_start},${ep.t_end},${ep.x},${ep.y},${v},${hum},${obj},${pe},${cost},"${expl}"`;
      });
      const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + encodeURIComponent([headers, ...rows].join('\n'));
      const link = document.createElement('a');
      link.setAttribute('href', csvContent);
      link.setAttribute('download', `amrsim_episodes_${scenario}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      return;
    }
    const url = apiClient.getExportCsvUrl(scenario);
    const link = document.createElement('a');
    link.href = url;
    link.download = `amrsim_episodes_${scenario}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // JSON Export handler
  const handleExportJSON = () => {
    if (!episodesData) return;
    const jsonStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(episodesData, null, 2));
    const link = document.createElement('a');
    link.setAttribute('href', jsonStr);
    link.setAttribute('download', `amrsim_episodes_${scenario}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const episodes = episodesData?.episodes || [];
  const summary = episodesData?.summary || {
    totalCost: 0,
    fatalCount: 0,
    warningsCount: 0,
    ruleViolationsCount: 0,
  };

  // Dynamic episode types for filter dropdown
  const uniqueTypes = Array.from(new Set(episodes.map((e) => e.type)));

  // Filtering
  const filteredEpisodes = episodes.filter((ep) => {
    if (typeFilter !== 'all' && ep.type !== typeFilter) return false;
    if (costFilter === 'high' && ep.cost > -0.5) return false;
    if (costFilter === 'low' && ep.cost <= -0.5) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        ep.type.toLowerCase().includes(q) ||
        ep.category.toLowerCase().includes(q) ||
        ep.x.toString().includes(q) ||
        ep.y.toString().includes(q) ||
        (ep.ruleExplanation && ep.ruleExplanation.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const handleScenarioChange = (newSc: string) => {
    setScenario(newSc);
    setSelectedScenario(newSc);
    onScenarioChange?.(newSc);
    if (typeof window !== 'undefined') {
      const rawHash = window.location.hash.replace(/^#\/?/, '');
      const [route, queryStr] = rawHash.split('?');
      const sp = new URLSearchParams(queryStr || '');
      sp.set('scenario', newSc);
      window.location.hash = `#/${route || 'episodes'}?${sp.toString()}`;
    }
  };

  const handleInspect = (ep: EpisodeData) => {
    setSelectedEpisode(ep);
    onNavigate('replay', {
      scenario,
      t: ep.t_start,
      x: ep.x,
      y: ep.y,
    });
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

          {/* Export Buttons */}
          <div className="flex items-center gap-2 ml-2">
            <button
              onClick={handleExportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
              title="Выгрузить реальные инциденты и события в CSV"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Экспорт CSV</span>
            </button>
            <button
              onClick={handleExportJSON}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
              title="Выгрузить события в JSON"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Экспорт JSON</span>
            </button>
          </div>
        </div>
      </div>

      {/* 4 Metric Cards matching episodes.png */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Штрафные баллы */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-red-500 ring-4 ring-red-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Штрафные баллы</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.totalCost.toFixed(2)}{' '}
              <span className="text-xs font-normal text-slate-400">баллов</span>
            </div>
          </div>
        </div>

        {/* Card 2: Фатальные */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-slate-400 ring-4 ring-slate-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Фатальные ошибки</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.fatalCount}
            </div>
          </div>
        </div>

        {/* Card 3: Предупреждения по безопасности */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-amber-500 ring-4 ring-amber-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Предупреждения безопасности</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.warningsCount}
            </div>
          </div>
        </div>

        {/* Card 4: События регламента */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div className="w-3.5 h-3.5 rounded-full bg-blue-500 ring-4 ring-blue-100"></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">События регламента</div>
            <div className="text-xl font-bold text-slate-900 font-mono mt-0.5">
              {summary.ruleViolationsCount}
            </div>
          </div>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center gap-4">
        {/* Type filter */}
        <div className="flex flex-col gap-1 min-w-[180px]">
          <span className="text-[11px] text-slate-500 font-medium">Тип события</span>
          <div className="relative">
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              <option value="all">Все типы ({episodes.length})</option>
              {uniqueTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
          </div>
        </div>

        {/* Cost filter */}
        <div className="flex flex-col gap-1 min-w-[180px]">
          <span className="text-[11px] text-slate-500 font-medium">Штраф</span>
          <div className="relative">
            <select
              value={costFilter}
              onChange={(e) => setCostFilter(e.target.value)}
              className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              <option value="all">Все значения</option>
              <option value="high">Высокий штраф (&gt; 0.5 балла)</option>
              <option value="low">Низкий / штатный (≤ 0.5 балла)</option>
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
              placeholder="Поиск по событиям, типам, координатам..."
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
                  <th className="py-3 px-4 w-12 text-center">Статус</th>
                  <th className="py-3 px-4">Тип эпизода</th>
                  <th className="py-3 px-4">Категория</th>
                  <th className="py-3 px-4">Время (с)</th>
                  <th className="py-3 px-4 font-mono">Координаты</th>
                  <th className="py-3 px-4 font-mono text-right">Штраф</th>
                  <th className="py-3 px-4 text-center">Действие</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredEpisodes.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-slate-400">
                      В данном сценарии нет зафиксированных инцидентов по заданным фильтрам
                    </td>
                  </tr>
                ) : (
                  filteredEpisodes.map((ep) => {
                    const isSelected = selectedEpisode?.id === ep.id;
                    const dotColor =
                      ep.severity === 'critical'
                        ? 'bg-red-500'
                        : ep.severity === 'warning'
                        ? 'bg-amber-500'
                        : ep.severity === 'info'
                        ? 'bg-blue-500'
                        : 'bg-emerald-500';

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
                        <td className="py-3 px-4 font-mono font-medium text-slate-900">
                          {ep.type}
                        </td>
                        <td className="py-3 px-4 text-slate-600">{ep.category}</td>
                        <td className="py-3 px-4 font-mono text-slate-600">
                          {ep.t_start.toFixed(1)} с - {ep.t_end.toFixed(1)} с
                        </td>
                        <td className="py-3 px-4 font-mono text-slate-500">
                          ({ep.x.toFixed(1)}, {ep.y.toFixed(1)})
                        </td>
                        <td
                          className={`py-3 px-4 font-mono text-right font-semibold ${
                            ep.cost < 0 ? 'text-red-600' : 'text-slate-500'
                          }`}
                        >
                          {ep.cost.toFixed(2)}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleInspect(ep);
                            }}
                            className="text-blue-600 hover:text-blue-800 font-medium text-xs hover:underline"
                          >
                            Просмотр
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Details Panel matching episodes.png (4 cols) */}
        <div className="lg:col-span-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-800">Детали эпизода</h2>
          </div>

          {selectedEpisode ? (
            <div className="flex flex-col gap-4">
              {/* Header: Type and Cost */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2.5 h-2.5 rounded-full ${
                        selectedEpisode.severity === 'critical'
                          ? 'bg-red-500'
                          : selectedEpisode.severity === 'warning'
                          ? 'bg-amber-500'
                          : selectedEpisode.severity === 'info'
                          ? 'bg-blue-500'
                          : 'bg-emerald-500'
                      }`}
                    ></span>
                    <span className="font-mono font-bold text-sm text-slate-900">
                      {selectedEpisode.type}
                    </span>
                  </div>
                  <span
                    className={`font-mono font-bold text-sm ${
                      selectedEpisode.cost < 0 ? 'text-red-600' : 'text-emerald-600'
                    }`}
                  >
                    {selectedEpisode.cost.toFixed(2)} баллов
                  </span>
                </div>
                <div className="text-xs text-slate-500 mt-1">{selectedEpisode.category}</div>
              </div>

              {/* Timing and Coordinates */}
              <div className="grid grid-cols-2 gap-3 text-xs bg-slate-50 p-3 rounded-lg border border-slate-100 font-mono">
                <div>
                  <div className="text-[11px] text-slate-400 font-sans">Временной интервал</div>
                  <div className="font-semibold text-slate-800 mt-0.5">
                    {selectedEpisode.t_start.toFixed(1)} с - {selectedEpisode.t_end.toFixed(1)} с
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-slate-400 font-sans">Координаты (x, y)</div>
                  <div className="font-semibold text-slate-800 mt-0.5">
                    {selectedEpisode.x.toFixed(2)}, {selectedEpisode.y.toFixed(2)}
                  </div>
                </div>
              </div>

              {/* Rule Explanation */}
              <div>
                <div className="text-xs font-semibold text-slate-700 mb-1">
                  Объяснение регламента
                </div>
                <div className="text-xs text-slate-600 leading-relaxed bg-blue-50/50 p-3 rounded-lg border border-blue-100">
                  <Latex>
                    {selectedEpisode.ruleExplanation ||
                      'Контроллер зарегистрировал взаимодействие с окружающей средой платформы АТЛАНТ-250.'}
                  </Latex>
                </div>
              </div>

              {/* Penalty Formula if defined */}
              {EPISODE_FORMULAS[selectedEpisode.type] && (
                <div className="bg-slate-50 p-3 rounded-lg border border-slate-200 flex flex-col gap-1.5 text-xs">
                  <div className="text-[11px] font-semibold text-slate-700 flex items-center justify-between">
                    <span>Формула штрафа:</span>
                    <span className="font-mono text-slate-400 text-[10px]">правило</span>
                  </div>
                  <div className="bg-white p-2 rounded border border-slate-200 text-center font-serif text-xs">
                    <Latex math={EPISODE_FORMULAS[selectedEpisode.type].formula} displayMode />
                  </div>
                  <div className="text-[11px] text-slate-500 flex items-center justify-between pt-0.5">
                    <span>Условие:</span>
                    <span className="font-serif text-slate-700">
                      <Latex math={EPISODE_FORMULAS[selectedEpisode.type].condition} />
                    </span>
                  </div>
                </div>
              )}

              {/* Telemetry Snapshot */}
              {selectedEpisode.telemetrySnapshot && (
                <div>
                  <div className="text-xs font-semibold text-slate-700 mb-1.5">
                    Снимок телеметрии (t = {selectedEpisode.t_start.toFixed(1)} с)
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs font-mono bg-slate-50 p-3 rounded-lg border border-slate-100">
                    <div>
                      <span className="text-slate-400 font-sans">
                        Скорость (<Latex math="v" />):{' '}
                      </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.v.toFixed(2)} м/с
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 font-sans">
                        Команда (<Latex math="v_{\text{cmd}}" />):{' '}
                      </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.cv.toFixed(2)} м/с
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 font-sans">
                        Человек (<Latex math="d_{\text{hum}}" />):{' '}
                      </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.hum !== null
                          ? `${selectedEpisode.telemetrySnapshot.hum.toFixed(2)} м`
                          : '-'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 font-sans">
                        Объект (<Latex math="d_{\text{obj}}" />):{' '}
                      </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.obj !== null
                          ? `${selectedEpisode.telemetrySnapshot.obj.toFixed(2)} м`
                          : '-'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 font-sans">
                        Ошибка позы (<Latex math="\|\mathbf{e}_{\text{pose}}\|" />):{' '}
                      </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.pe_error.toFixed(3)} м
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 font-sans">Статус: </span>
                      <span className="font-semibold text-slate-800">
                        {selectedEpisode.telemetrySnapshot.status}
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Inspect in Replay Button */}
              <button
                onClick={() => handleInspect(selectedEpisode)}
                className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors mt-2"
              >
                <span>Смотреть момент в Replay</span>
              </button>
            </div>
          ) : (
            <div className="py-12 text-center text-xs text-slate-400">
              Выберите эпизод в таблице для просмотра деталей
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
