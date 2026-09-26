import React, { useState, useEffect } from 'react';
import { RouteName, AnalyticsViewModel, ScenarioItem } from '../types';
import { apiClient } from '../api/client';
import { Download, CheckCircle2, AlertOctagon, ChevronDown, RefreshCw } from 'lucide-react';
import { Latex } from '../components/Latex';
import {
  getSelectedScenario,
  setSelectedScenario,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';

const BLOCK_FORMULAS: Record<string, string> = {
  delivery: 'S_{\\text{del}}',
  efficiency: 'S_{\\text{eff}}',
  safety: 'S_{\\text{safe}}',
  rules: 'S_{\\text{rules}}',
  pose: 'S_{\\text{pose}}',
  collisions: 'S_{\\text{col}}',
};

interface AnalyticsPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    scenario?: string;
  };
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

export const AnalyticsPage: React.FC<AnalyticsPageProps> = ({
  onNavigate,
  queryParams,
  activeScenario,
  onScenarioChange,
}) => {
  const [scenario, setScenario] = useState(
    activeScenario || queryParams?.scenario || getSelectedScenario()
  );
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [data, setData] = useState<AnalyticsViewModel | null>(null);
  const [stderrOpen, setStderrOpen] = useState(true);
  const [showFormulas, setShowFormulas] = useState(false);
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

  // Load scenarios on mount
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
      window.location.hash = `#/${route || 'analytics'}?${sp.toString()}`;
    }
  };

  // Load analytics when scenario changes
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiClient.fetchAnalytics(scenario).then((vm) => {
      if (mounted) {
        setData(vm);
        setLoading(false);
      }
    });
    return () => {
      mounted = false;
    };
  }, [scenario]);

  // CSV Export handler
  const handleExportCSV = () => {
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
    if (!data) return;
    const jsonStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(data, null, 2));
    const link = document.createElement('a');
    link.setAttribute('href', jsonStr);
    link.setAttribute('download', `amrsim_report_${scenario}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const totalScore = data?.totalScore ?? 0;
  const blocks = data?.blocks || [];
  const radarValues = data?.radar?.values || (blocks.length > 0 ? blocks.map((b) => b.percentage / 100) : [0, 0, 0, 0, 0, 0]);
  const compute = data?.computeBudget || {
    limit_s: 600,
    fact_s: 0,
    mean_step_ms: 0,
    max_step_ms: 0,
    step_distribution: [],
  };
  const sandbox = data?.sandbox || {
    violations: [],
    stderr_tail: [],
  };

  // Radar points computation (6-axis hexagon)
  const radarPoints = radarValues.map((val, i) => {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    const r = 85 * Math.max(0.1, Math.min(1.0, val));
    return `${(120 + r * Math.cos(angle)).toFixed(1)},${(120 + r * Math.sin(angle)).toFixed(1)}`;
  }).join(' ');

  // Compute max count in histogram for scaling
  const maxBinCount = Math.max(1, ...(compute.step_distribution || []).map((d) => d.count));

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full min-w-[1240px] gap-5">
      {/* Top Banner matching analytics.png */}
      <div className="bg-white p-5 px-8 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-4">
        {/* Score & Scenario Selector */}
        <div className="flex items-center gap-4">
          <div className="text-3xl font-extrabold text-slate-900 font-mono">
            {totalScore.toFixed(2)} <span className="text-xl font-normal text-slate-400">/ 100</span>
          </div>

          {/* Scenario Selector */}
          <div className="relative min-w-[200px] ml-2">
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

          {loading && <RefreshCw className="w-4 h-4 animate-spin text-blue-600 ml-1" />}
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
            title="Выгрузить реальные инциденты в CSV"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Экспорт CSV</span>
          </button>
          <button
            onClick={handleExportJSON}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
            title="Выгрузить полный отчет симуляции в JSON"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Экспорт JSON</span>
          </button>
        </div>
      </div>

      {/* Main Row: Radar Chart (5 cols) & Score Blocks Table (7 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Radar Chart (5 cols) */}
        <div className="lg:col-span-5 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col items-center">
          <h2 className="w-full text-sm font-semibold text-slate-800 mb-2">
            Показатели по 6 блокам скоринга
          </h2>

          {/* SVG 6-Axis Spider / Radar chart */}
          <div className="w-72 h-72 relative flex items-center justify-center my-2">
            <svg className="w-full h-full overflow-visible" viewBox="0 0 240 240">
              {/* Concentric hexagonal webs (20%, 40%, 60%, 80%, 100%) */}
              {[0.2, 0.4, 0.6, 0.8, 1.0].map((level, idx) => {
                const r = 85 * level;
                const points = [0, 1, 2, 3, 4, 5]
                  .map((i) => {
                    const angle = (Math.PI / 3) * i - Math.PI / 2;
                    return `${(120 + r * Math.cos(angle)).toFixed(1)},${(120 + r * Math.sin(angle)).toFixed(1)}`;
                  })
                  .join(' ');

                return (
                  <polygon
                    key={idx}
                    points={points}
                    fill="none"
                    stroke="#E2E8F0"
                    strokeWidth="1"
                  />
                );
              })}

              {/* 6 Radial spokes */}
              {[0, 1, 2, 3, 4, 5].map((i) => {
                const angle = (Math.PI / 3) * i - Math.PI / 2;
                return (
                  <line
                    key={i}
                    x1="120"
                    y1="120"
                    x2={120 + 85 * Math.cos(angle)}
                    y2={120 + 85 * Math.sin(angle)}
                    stroke="#E2E8F0"
                    strokeWidth="1"
                  />
                );
              })}

              {/* Dynamic Real Data Polygon */}
              <polygon
                points={radarPoints}
                fill="rgba(37, 99, 235, 0.12)"
                stroke="#2563EB"
                strokeWidth="2"
              />

              {/* Vertices */}
              {radarValues.map((val, i) => {
                const angle = (Math.PI / 3) * i - Math.PI / 2;
                const r = 85 * Math.max(0.1, Math.min(1.0, val));
                return (
                  <circle
                    key={i}
                    cx={120 + r * Math.cos(angle)}
                    cy={120 + r * Math.sin(angle)}
                    r="3.5"
                    fill="#2563EB"
                  />
                );
              })}

              {/* Axis Labels */}
              {[
                { label: 'Доставка', x: 120, y: 15 },
                { label: 'Эффективность', x: 215, y: 70 },
                { label: 'Безопасность', x: 215, y: 175 },
                { label: 'Правила', x: 120, y: 230 },
                { label: 'Поза', x: 25, y: 175 },
                { label: 'Коллизии', x: 25, y: 70 },
              ].map((item, idx) => (
                <text
                  key={idx}
                  x={item.x}
                  y={item.y}
                  textAnchor="middle"
                  className="text-[10px] fill-slate-500 font-medium select-none"
                >
                  {item.label}
                </text>
              ))}
            </svg>
          </div>
        </div>

        {/* Score Blocks Table (7 cols) */}
        <div className="lg:col-span-7 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-slate-800">Детализация баллов</h2>
              <div className="text-xs text-slate-600 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200">
                <Latex math="S_{\text{total}} = \min\left(100, \max\left(0, \sum S_i\right)\right)" />
              </div>
            </div>
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-slate-400 font-medium border-b border-slate-100">
                <tr>
                  <th className="pb-2">Блок скоринга</th>
                  <th className="pb-2 text-right">Max</th>
                  <th className="pb-2 text-right">Факт</th>
                  <th className="pb-2 pl-8">Процент выполнения</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {blocks.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="py-8 text-center text-slate-400 font-sans text-xs">
                      Отчет скоринга не найден. Запустите симуляцию сценария в разделе «Запуск».
                    </td>
                  </tr>
                ) : (
                  blocks.map((block) => (
                    <tr key={block.key}>
                      <td className="py-2.5 font-medium text-slate-800 font-sans">
                        <div className="flex items-center gap-2">
                          <span>{block.name}</span>
                          {BLOCK_FORMULAS[block.key] && (
                            <span className="text-[11px] text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-100 font-serif">
                              <Latex math={BLOCK_FORMULAS[block.key]} />
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 text-right text-slate-500">{(block.max ?? 0).toFixed(2)}</td>
                      <td className="py-2.5 text-right text-slate-800 font-semibold">
                        {(block.achieved ?? 0).toFixed(2)}
                      </td>
                      <td className="py-2.5 pl-8">
                        <div className="flex items-center gap-3">
                          <div className="flex-1 bg-slate-100 h-2 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-500 ${
                                (block.percentage ?? 0) >= 95
                                  ? 'bg-blue-600'
                                  : (block.percentage ?? 0) >= 80
                                  ? 'bg-emerald-500'
                                  : 'bg-amber-500'
                              }`}
                              style={{ width: `${block.percentage ?? 0}%` }}
                            ></div>
                          </div>
                          <span className="w-12 text-right text-[11px] text-slate-600">
                            {(block.percentage ?? 0).toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Mathematical Model of AMR-1.0 Scoring Regulation */}
      <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-700 font-bold font-serif text-sm">
              ∑
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">
                Математическая модель регламента скоринга (AMR-1.0)
              </h2>
              <p className="text-xs text-slate-500">
                Формулы расчета баллов, весовых коэффициентов и штрафных санкций по 6 ключевым блокам
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowFormulas(!showFormulas)}
            className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1 bg-blue-50 hover:bg-blue-100 px-3 py-1.5 rounded-lg border border-blue-200 transition-colors"
          >
            <span>{showFormulas ? 'Свернуть формулы' : 'Развернуть формулы'}</span>
            <ChevronDown
              className={`w-3.5 h-3.5 transform transition-transform ${
                showFormulas ? 'rotate-180' : ''
              }`}
            />
          </button>
        </div>

        {showFormulas && (
          <div className="flex flex-col gap-5 pt-1">
            {/* Global Total Formula Banner */}
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col lg:flex-row items-center justify-between gap-4">
              <div className="flex flex-col gap-1">
                <span className="text-xs font-semibold text-slate-700">Итоговая целевая функция сценария:</span>
                <span className="text-xs text-slate-500">
                  Условие зачета: отсутствие фатальных нарушений, укладка в таймаут 600 с и хотя бы 1 доставленная миссия.
                </span>
              </div>
              <div className="bg-white px-5 py-2.5 rounded-lg border border-slate-200 shadow-xs text-sm">
                <Latex
                  math="S_{\text{total}} = \begin{cases} 0, & \text{если } \text{fatal} \lor \neg\text{counted} \lor N_{\text{del}} = 0 \\ \min\left(100, \max\left(0, \sum_{i=1}^{6} S_i\right)\right), & \text{иначе} \end{cases}"
                  displayMode
                />
              </div>
            </div>

            {/* 6 Block Formula Cards (3 cols) */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-xs">
              {/* Block 1: Delivery */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-blue-600"></span>
                      1. Доставка
                    </span>
                    <span className="font-mono text-blue-700 bg-blue-100/60 px-2 py-0.5 rounded text-[11px]">
                      Max 40.0 pts
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{del}} = 40 \times \frac{\sum_{m \in M} \mathbb{I}(\text{delivered}_m)}{|M|}" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Пикап: <Latex math="\min_t \|\mathbf{p}(t) - \mathbf{p}_{\text{from}}\| < 2.0\,\text{м}" /></li>
                    <li>Створ дока: <Latex math="\|\mathbf{p}(t) - \mathbf{p}_{\text{to}}\| \le \text{tol} = 0.20\,\text{м}" /></li>
                    <li>Удержание: 10 тиков подряд со статусом <code className="font-mono text-slate-800 font-semibold">arrived</code></li>
                    <li>Дедлайн: <Latex math="t_{\text{arrival}} - t_{\text{start}} \le t_{\text{deadline}}" /></li>
                  </ul>
                </div>
              </div>

              {/* Block 2: Efficiency */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-600"></span>
                      2. Эффективность
                    </span>
                    <span className="font-mono text-emerald-700 bg-emerald-100/60 px-2 py-0.5 rounded text-[11px]">
                      Max 15.0 pts
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{eff}} = \frac{15}{|M|} \sum_{m \in M} \eta_m" displayMode />
                  </div>
                  <div className="my-1.5 bg-white p-2 rounded-lg border border-slate-200 text-center text-[11px]">
                    <Latex math="\eta_m = \min\left(1.0, \max\left(0.0, 2.0 - \frac{t_{\text{mis}}}{t_{\text{ref}}}\right)\right)" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Норматив: <Latex math="t_{\text{ref}} = \frac{L}{v_{\text{ref}}} \times 1.25, \quad v_{\text{ref}} = 1.39\,\text{м/с}" /></li>
                    <li>Недоставленная миссия: <Latex math="\eta_m = 0.0" /></li>
                  </ul>
                </div>
              </div>

              {/* Block 3: Safety */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                      3. Безопасность
                    </span>
                    <span className="font-mono text-amber-700 bg-amber-100/60 px-2 py-0.5 rounded text-[11px]">
                      Max 25.0 pts
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{safe}} = 25.0 - \sum \text{penalties}" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Сближение на скорости: <Latex math="d_{\text{hum}} < 3.0\,\text{м} \land |v| > 0.28\,\text{м/с} \implies -2.0/\text{с}" /></li>
                    <li>Опасный проезд: <Latex math="d_{\text{hum}} < 0.5\,\text{м} \land |v| > 0 \implies -10.0" /></li>
                    <li>Контакт стоя: <Latex math="|v|_{\text{1s}} \le 0.1\,\text{м/с} \implies -10.0" /></li>
                    <li>Фатал: <Latex math="\text{контакт при } |v|_{\text{1s}} > 0.1 \implies \text{FATAL}" /></li>
                  </ul>
                </div>
              </div>

              {/* Block 4: Rules */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-purple-600"></span>
                      4. Соблюдение ПДД
                    </span>
                    <span className="font-mono text-purple-700 bg-purple-100/60 px-2 py-0.5 rounded text-[11px]">
                      Max 10.0 pts
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{rules}} = 10.0 - \sum \text{penalties}" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Вне проезда: <Latex math="d_{\text{drv}} < 0.5 \implies -3.0/\text{эпизод}" /></li>
                    <li>Запретная зона (FB_HAZ): <Latex math="fbd > 0.5 \implies -5.0/\text{эпизод}" /></li>
                    <li>Превышение скорости: <Latex math="|v| > v_{\max} + 0.05\,\text{м/с} \implies -2.0" /></li>
                  </ul>
                </div>
              </div>

              {/* Block 5: Pose Honesty */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-cyan-600"></span>
                      5. Оценка позы
                    </span>
                    <span className="font-mono text-cyan-700 bg-cyan-100/60 px-2 py-0.5 rounded text-[11px]">
                      Max 10.0 pts
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{pose}} = 10.0 - \sum \text{penalties}" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Дрейф позы: <Latex math="\|\hat{\mathbf{p}} - \mathbf{p}\| > 1.0\,\text{м} \land |v| > 0.05 \land \Delta t > 5.0\,\text{с} \implies -3.0" /></li>
                    <li>Несоответствие статуса: <Latex math="\text{st} \neq \text{moving} \land |v| > 0.05 \land \Delta t > 1.0\,\text{с} \implies -2.0" /></li>
                    <li>Ложный E-Stop: <Latex math="\text{st} = \text{estop} \land d_{\text{obj}} \ge 1.5\,\text{м} \implies -1.0" /></li>
                  </ul>
                </div>
              </div>

              {/* Block 6: Collisions */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex flex-col justify-between gap-2.5">
                <div>
                  <div className="flex items-center justify-between font-semibold text-slate-800 mb-1">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-red-600"></span>
                      6. Столкновения
                    </span>
                    <span className="font-mono text-red-700 bg-red-100/60 px-2 py-0.5 rounded text-[11px]">
                      Штрафной блок
                    </span>
                  </div>
                  <div className="my-2 bg-white p-2.5 rounded-lg border border-slate-200 text-center">
                    <Latex math="S_{\text{col}} = -30.0 \times N_{\text{collisions}}" displayMode />
                  </div>
                  <ul className="text-slate-600 space-y-1 text-[11px] list-disc pl-3.5">
                    <li>Контакт с объектом/стеной: <Latex math="\text{coll} > 0 \implies -30.0/\text{эпизод}" /></li>
                    <li>Склейка тиков: разрыв <Latex math="\Delta t_{\text{gap}} < 2.0\,\text{с}" /> (20 тиков) объединяется в 1 эпизод</li>
                    <li>Защитные зазоры платформы: <Latex math="R_{\text{amr}} = 0.9\,\text{м}, \; R_{\text{hum}} = 0.3\,\text{м}" /></li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom Grid: Compute Budget (7 cols) & Sandbox Audit (5 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Compute Budget (7 cols) */}
        <div className="lg:col-span-7 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-800">Вычислительный бюджет (Compute Budget)</h2>

          {/* 4 Metrics Row */}
          <div className="grid grid-cols-4 gap-4 text-xs font-mono pb-3 border-b border-slate-100">
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Лимит времени</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{compute.limit_s} с</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Факт (wall-time)</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{compute.fact_s.toFixed(2)} с</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Средний шаг</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{compute.mean_step_ms.toFixed(2)} мс</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Макс. шаг</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{compute.max_step_ms.toFixed(1)} мс</div>
            </div>
          </div>

          {/* Histogram: Step latency distribution */}
          <div>
            <div className="text-xs text-slate-500 mb-2">Распределение времени шага (мс)</div>
            <div className="w-full h-28 relative">
              <svg
                className="w-full h-full overflow-visible"
                viewBox="0 0 500 100"
                preserveAspectRatio="none"
              >
                {/* Horizontal grid */}
                <line x1="0" y1="20" x2="500" y2="20" stroke="#F8FAFC" strokeWidth="1" />
                <line x1="0" y1="50" x2="500" y2="50" stroke="#F8FAFC" strokeWidth="1" />
                <line x1="0" y1="80" x2="500" y2="80" stroke="#F8FAFC" strokeWidth="1" />

                {/* Bars */}
                {(compute.step_distribution || []).map((item, idx) => {
                  const x = (item.bin / 25) * 480 + 10;
                  const barH = (item.count / maxBinCount) * 75;
                  return (
                    <rect
                      key={idx}
                      x={x}
                      y={95 - barH}
                      width="10"
                      height={Math.max(2, barH)}
                      fill="#94A3B8"
                      rx="1"
                    />
                  );
                })}

                {/* 5ms Threshold vertical line */}
                <line x1="106" y1="5" x2="106" y2="95" stroke="#3B82F6" strokeWidth="1.5" />
                <text x="112" y="15" className="text-[9px] fill-blue-600 font-mono">
                  Порог 5 мс (О1 норма)
                </text>
              </svg>

              {/* X-axis labels */}
              <div className="flex justify-between text-[10px] text-slate-400 font-mono mt-1 px-2">
                <span>0</span>
                <span>5</span>
                <span>10</span>
                <span>15</span>
                <span>20</span>
                <span>25</span>
              </div>
              <div className="text-right text-[10px] text-slate-400 font-mono mt-0.5">
                Время шага, мс
              </div>
            </div>
          </div>
        </div>

        {/* Sandbox Audit (5 cols) matching analytics.png */}
        <div className="lg:col-span-5 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-800">Аудит изоляции песочницы</h2>

          {/* Violations Check Badge */}
          {sandbox.violations.length === 0 ? (
            <div className="flex items-center gap-2 text-xs font-mono text-slate-700 bg-emerald-50/50 p-2.5 rounded-lg border border-emerald-200">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
              <span className="font-semibold text-slate-900">
                sandbox_violations: [] — 0 нарушений (Чисто)
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs font-mono text-red-700 bg-red-50 p-2.5 rounded-lg border border-red-200">
              <AlertOctagon className="w-4 h-4 text-red-600 flex-shrink-0" />
              <span className="font-semibold text-red-900">
                sandbox_violations: {sandbox.violations.length} нарушений!
              </span>
            </div>
          )}

          {/* Terminal Box for stderr tail */}
          <div className="border border-slate-200 rounded-lg overflow-hidden flex flex-col text-xs font-mono">
            <div
              onClick={() => setStderrOpen(!stderrOpen)}
              className="bg-slate-50 px-3 py-2 border-b border-slate-200 flex items-center justify-between cursor-pointer hover:bg-slate-100 transition-colors"
            >
              <div className="flex items-center gap-1.5 text-slate-600">
                <span className="w-2 h-2 rounded-full border border-slate-400"></span>
                <span>Лог аудита контроллера (stderr tail)</span>
              </div>
              <ChevronDown
                className={`w-3.5 h-3.5 text-slate-400 transform transition-transform ${
                  stderrOpen ? 'rotate-180' : ''
                }`}
              />
            </div>

            {stderrOpen && (
              <div className="p-3 bg-white space-y-1 text-slate-700 text-[11px] leading-relaxed max-h-48 overflow-y-auto">
                {(sandbox.stderr_tail || []).map((line, idx) => (
                  <div key={idx} className="flex gap-3">
                    <span className="text-slate-400 select-none w-3 text-right">{idx + 1}</span>
                    <span className="text-slate-600 font-mono">{line}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
