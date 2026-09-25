import React, { useState } from 'react';
import { RouteName } from '../types';
import { mockReport, mockEpisodes, mockMissions } from '../mock/mockData';
import { Download, CheckCircle2, ChevronDown } from 'lucide-react';

interface AnalyticsPageProps {
  onNavigate: (route: RouteName) => void;
}

export const AnalyticsPage: React.FC<AnalyticsPageProps> = () => {
  const [stderrOpen, setStderrOpen] = useState(true);

  // CSV Export handler
  const handleExportCSV = () => {
    const csvRows = [
      ['Episode ID', 'Type', 'Category', 'Start (s)', 'End (s)', 'X', 'Y', 'Cost (pts)'],
      ...mockEpisodes.map(ep => [ep.id, ep.type, ep.category, ep.t_start, ep.t_end, ep.x, ep.y, ep.cost])
    ];
    const csvContent = 'data:text/csv;charset=utf-8,' + csvRows.map(e => e.join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `amrsim_episodes_${mockReport.scenario}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // JSON Export handler
  const handleExportJSON = () => {
    const exportData = {
      scenario: mockReport.scenario,
      seed: mockReport.seed,
      score: {
        total: mockReport.totalScore,
        counted: mockReport.counted,
        blocks: mockReport.blocks
      },
      missions: mockMissions,
      episodes: mockEpisodes,
      computeBudget: mockReport.computeBudget,
      sandbox: mockReport.sandbox
    };
    const jsonStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(exportData, null, 2));
    const link = document.createElement('a');
    link.setAttribute('href', jsonStr);
    link.setAttribute('download', `amrsim_report_${mockReport.scenario}.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Top Banner matching analytics.png */}
      <div className="bg-white p-5 px-8 rounded-xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-4">
        {/* Score & Counted badge */}
        <div className="flex items-center gap-4">
          <div className="text-3xl font-extrabold text-slate-900 font-mono">
            {mockReport.totalScore.toFixed(2)} <span className="text-xl font-normal text-slate-400">/ 100</span>
          </div>

          <div className="bg-emerald-50 text-emerald-700 text-xs font-semibold px-3 py-1 rounded-full border border-emerald-200 flex items-center gap-1.5 font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>
            COUNTED
          </div>
        </div>

        {/* Export Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleExportCSV}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export CSV</span>
          </button>
          <button
            onClick={handleExportJSON}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export JSON</span>
          </button>
        </div>
      </div>

      {/* Main Row: Radar Chart (5 cols) & Score Blocks Table (7 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Radar Chart (5 cols) */}
        <div className="lg:col-span-5 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col items-center">
          <h2 className="w-full text-sm font-semibold text-slate-800 mb-2">Показатели по блокам</h2>

          {/* SVG 6-Axis Spider / Radar chart */}
          <div className="w-72 h-72 relative flex items-center justify-center my-2">
            <svg className="w-full h-full overflow-visible" viewBox="0 0 240 240">
              {/* Concentric hexagonal webs (20%, 40%, 60%, 80%, 100%) */}
              {[0.2, 0.4, 0.6, 0.8, 1.0].map((level, idx) => {
                const r = 85 * level;
                const points = [0, 1, 2, 3, 4, 5].map(i => {
                  const angle = (Math.PI / 3) * i - Math.PI / 2;
                  return `${120 + r * Math.cos(angle)},${120 + r * Math.sin(angle)}`;
                }).join(' ');

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
              {[0, 1, 2, 3, 4, 5].map(i => {
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

              {/* Data Polygon matching values in mockup:
                  Delivery 100%, Efficiency 93.6%, Safety 98.2%, Rules 96.4%, Pose 94.7%, Collisions 98.9%
              */}
              {(() => {
                const values = [1.0, 0.936, 0.982, 0.964, 0.947, 0.989];
                const points = values.map((val, i) => {
                  const angle = (Math.PI / 3) * i - Math.PI / 2;
                  const r = 85 * val;
                  return `${120 + r * Math.cos(angle)},${120 + r * Math.sin(angle)}`;
                }).join(' ');

                return (
                  <>
                    <polygon
                      points={points}
                      fill="rgba(37, 99, 235, 0.08)"
                      stroke="#2563EB"
                      strokeWidth="2"
                    />
                    {values.map((val, i) => {
                      const angle = (Math.PI / 3) * i - Math.PI / 2;
                      const r = 85 * val;
                      return (
                        <circle
                          key={i}
                          cx={120 + r * Math.cos(angle)}
                          cy={120 + r * Math.sin(angle)}
                          r="3"
                          fill="#2563EB"
                        />
                      );
                    })}
                  </>
                );
              })()}

              {/* Axis Labels */}
              <text x="120" y="20" textAnchor="middle" className="text-[10px] font-sans font-medium fill-slate-700">Delivery 100.0</text>
              <text x="215" y="70" textAnchor="start" className="text-[10px] font-sans font-medium fill-slate-700">Efficiency 93.6</text>
              <text x="215" y="175" textAnchor="start" className="text-[10px] font-sans font-medium fill-slate-700">Safety 98.2</text>
              <text x="120" y="225" textAnchor="middle" className="text-[10px] font-sans font-medium fill-slate-700">Rules 96.4</text>
              <text x="25" y="175" textAnchor="end" className="text-[10px] font-sans font-medium fill-slate-700">Pose 94.7</text>
              <text x="25" y="70" textAnchor="end" className="text-[10px] font-sans font-medium fill-slate-700">Collisions 98.9</text>
            </svg>
          </div>
        </div>

        {/* Score Blocks Table (7 cols) */}
        <div className="lg:col-span-7 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <h2 className="text-sm font-semibold text-slate-800 mb-3">Блоки оценки</h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="text-slate-400 font-normal border-b border-slate-100 pb-2">
                <tr>
                  <th className="py-2 font-normal">Блок</th>
                  <th className="py-2 font-normal text-right">Макс.</th>
                  <th className="py-2 font-normal text-right">Достигнуто</th>
                  <th className="py-2 font-normal pl-8">Прогресс</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {mockReport.blocks.map((block) => (
                  <tr key={block.key} className="py-2">
                    <td className="py-2.5 font-medium text-slate-800 flex items-center gap-2">
                      <span className="w-2 h-2 rounded-full bg-blue-600 inline-block"></span>
                      <span>{block.name}</span>
                    </td>
                    <td className="py-2.5 text-right text-slate-500">{block.max.toFixed(2)}</td>
                    <td className="py-2.5 text-right text-slate-800 font-semibold">{block.achieved.toFixed(2)}</td>
                    <td className="py-2.5 pl-8">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 bg-slate-100 h-2 rounded-full overflow-hidden">
                          <div
                            className="bg-blue-600 h-full rounded-full transition-all duration-500"
                            style={{ width: `${block.percentage}%` }}
                          ></div>
                        </div>
                        <span className="w-12 text-right text-[11px] text-slate-600">{block.percentage.toFixed(1)}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Bottom Grid: Compute Budget (7 cols) & Sandbox Audit (5 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Compute Budget (7 cols) */}
        <div className="lg:col-span-7 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-800">Compute Budget</h2>

          {/* 4 Metrics Row */}
          <div className="grid grid-cols-4 gap-4 text-xs font-mono pb-3 border-b border-slate-100">
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Лимит</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{mockReport.computeBudget.limit_s} s</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Факт</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{mockReport.computeBudget.fact_s} s</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Средний шаг</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{mockReport.computeBudget.mean_step_ms} ms</div>
            </div>
            <div>
              <div className="text-[11px] text-slate-500 font-sans">Макс. шаг</div>
              <div className="text-base font-bold text-slate-900 mt-0.5">{mockReport.computeBudget.max_step_ms} ms</div>
            </div>
          </div>

          {/* Histogram: Step latency distribution */}
          <div>
            <div className="text-xs text-slate-500 mb-2">Распределение времени шага (ms)</div>
            <div className="w-full h-28 relative">
              <svg className="w-full h-full overflow-visible" viewBox="0 0 500 100" preserveAspectRatio="none">
                {/* Horizontal grid */}
                <line x1="0" y1="20" x2="500" y2="20" stroke="#F8FAFC" strokeWidth="1" />
                <line x1="0" y1="50" x2="500" y2="50" stroke="#F8FAFC" strokeWidth="1" />
                <line x1="0" y1="80" x2="500" y2="80" stroke="#F8FAFC" strokeWidth="1" />

                {/* Bars */}
                {mockReport.computeBudget.step_distribution.map((item, idx) => {
                  const x = (item.bin / 25) * 480 + 10;
                  const barH = (item.count / 150) * 85;
                  return (
                    <rect
                      key={idx}
                      x={x}
                      y={95 - barH}
                      width="8"
                      height={barH}
                      fill="#CBD5E1"
                      rx="1"
                    />
                  );
                })}

                {/* 5ms Threshold vertical line matching mockup */}
                <line x1="106" y1="5" x2="106" y2="95" stroke="#3B82F6" strokeWidth="1.5" />
                <text x="110" y="15" className="text-[9px] fill-blue-600 font-mono">Порог 5 ms</text>
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
                Время шага, ms
              </div>
            </div>
          </div>
        </div>

        {/* Sandbox Audit (5 cols) matching analytics.png */}
        <div className="lg:col-span-5 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-800">Sandbox Audit</h2>

          {/* Green Check Badge */}
          <div className="flex items-center gap-2 text-xs font-mono text-slate-700 bg-slate-50 p-2.5 rounded-lg border border-slate-200">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span className="font-semibold text-slate-900">sandbox_violations: [] — 0 violations</span>
          </div>

          {/* Terminal Box for stderr tail */}
          <div className="border border-slate-200 rounded-lg overflow-hidden flex flex-col text-xs font-mono">
            <div
              onClick={() => setStderrOpen(!stderrOpen)}
              className="bg-slate-50 px-3 py-2 border-b border-slate-200 flex items-center justify-between cursor-pointer hover:bg-slate-100 transition-colors"
            >
              <div className="flex items-center gap-1.5 text-slate-600">
                <span className="w-2 h-2 rounded-full border border-slate-400"></span>
                <span>stderr (tail)</span>
              </div>
              <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transform transition-transform ${stderrOpen ? 'rotate-180' : ''}`} />
            </div>

            {stderrOpen && (
              <div className="p-3 bg-white space-y-1 text-slate-700 text-[11px] leading-relaxed">
                {mockReport.sandbox.stderr_tail.map((line, idx) => (
                  <div key={idx} className="flex gap-3">
                    <span className="text-slate-400 select-none w-3 text-right">{idx + 1}</span>
                    <span className="text-slate-600">{line}</span>
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
