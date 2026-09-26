import React, { useState } from 'react';
import { ChevronDown, Layers, RefreshCw } from 'lucide-react';
import { ScenarioItem } from '../../types';
import { MapLayersConfig } from '../MapCanvas';

export interface ReplayToolbarProps {
  scenario: string;
  onScenarioChange: (scenario: string) => void;
  scenarios: ScenarioItem[];
  currentTickTime: number;
  totalTime: number;
  currentActualTick: number;
  totalTicks: number;
  loading: boolean;
  followRobot: boolean;
  onToggleFollowRobot: () => void;
  layers: MapLayersConfig;
  onToggleLayer: (key: keyof MapLayersConfig) => void;
}

const LAYER_ITEMS: { key: keyof MapLayersConfig; label: string }[] = [
  { key: 'robot', label: 'Робот' },
  { key: 'poseEst', label: 'Оценка позы' },
  { key: 'poseDiff', label: 'Разница поз' },
  { key: 'lidar', label: 'Лидар' },
  { key: 'referencePath', label: 'Опорный маршрут' },
  { key: 'drivable', label: 'Проезжая часть' },
  { key: 'buildings', label: 'Здания' },
  { key: 'docks', label: 'Доки' },
  { key: 'pedestrians', label: 'Пешеходы' },
];

export const ReplayToolbar: React.FC<ReplayToolbarProps> = ({
  scenario,
  onScenarioChange,
  scenarios,
  currentTickTime,
  totalTime,
  currentActualTick,
  totalTicks,
  loading,
  followRobot,
  onToggleFollowRobot,
  layers,
  onToggleLayer,
}) => {
  const [layersMenuOpen, setLayersMenuOpen] = useState(false);

  const formatTime = (secs: number) => {
    const mins = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    const ms = Math.floor((secs % 1) * 10);
    return `${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3 px-5 rounded-xl border border-slate-200 shadow-sm">
      {/* Scenario selector */}
      <div className="relative min-w-[200px]">
        <select
          value={scenario}
          onChange={(e) => onScenarioChange(e.target.value)}
          className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs font-semibold rounded-lg px-3 py-2 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
        >
          {scenarios.length > 0 ? (
            scenarios.map((sc) => (
              <option key={sc.id} value={sc.id}>
                {sc.name}
              </option>
            ))
          ) : (
            <>
              <option value="01_clear">01_clear.json</option>
              <option value="01e_clear_easy">01e_clear_easy.json</option>
              <option value="02_gnss_shadow">02_gnss_shadow.json</option>
              <option value="02e_gnss_shadow_easy">02e_gnss_shadow_easy.json</option>
              <option value="03_fog_snow">03_fog_snow.json</option>
              <option value="04_busy_yard">04_busy_yard.json</option>
              <option value="s1_pallet_2m">backend/s1_pallet_2m.json</option>
              <option value="s2_container_block">backend/s2_container_block.json</option>
              <option value="s3_wall_removed">backend/s3_wall_removed.json</option>
              <option value="s4_shadow_start_charger">backend/s4_shadow_start_charger.json</option>
              <option value="s5_fog_inattentive">backend/s5_fog_inattentive.json</option>
            </>
          )}
        </select>
        <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
      </div>

      {/* Center Clock / Tick Readout */}
      <div className="bg-slate-50 border border-slate-200 px-6 py-1.5 rounded-lg text-xs font-mono font-medium text-slate-700 flex items-center gap-2">
        <span>{formatTime(currentTickTime)}</span>
        <span className="text-slate-400">/</span>
        <span className="text-slate-500">{formatTime(totalTime)}</span>
        <span className="text-slate-300">·</span>
        <span>Tick {currentActualTick}</span>
        <span className="text-slate-400">/</span>
        <span className="text-slate-500">{totalTicks}</span>
        {loading && <RefreshCw className="w-3 h-3 animate-spin text-blue-600 ml-1" />}
      </div>

      {/* Right Controls: Follow Robot & Layers */}
      <div className="flex items-center gap-4">
        {/* Follow Robot toggle */}
        <label className="flex items-center gap-2 text-xs font-medium text-slate-700 cursor-pointer select-none">
          <div
            onClick={onToggleFollowRobot}
            className={`w-9 h-5 flex items-center rounded-full p-0.5 transition-colors ${
              followRobot ? 'bg-blue-600 justify-end' : 'bg-slate-200 justify-start'
            }`}
          >
            <div className="bg-white w-4 h-4 rounded-full shadow-sm"></div>
          </div>
          <span>Следовать за роботом</span>
        </label>

        {/* Layers dropdown */}
        <div className="relative">
          <button
            onClick={() => setLayersMenuOpen(!layersMenuOpen)}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 px-3 py-1.5 rounded-lg transition-colors select-none"
          >
            <Layers className="w-3.5 h-3.5 text-slate-500" />
            <span>Слои</span>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          </button>

          {layersMenuOpen && (
            <div className="absolute right-0 mt-2 w-52 bg-white border border-slate-200 rounded-lg shadow-lg p-2 z-50 text-xs flex flex-col gap-1">
              {LAYER_ITEMS.map(({ key, label }) => (
                <label
                  key={key}
                  className="flex items-center gap-2 p-1 hover:bg-slate-50 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={layers[key]}
                    onChange={() => onToggleLayer(key)}
                    className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-slate-700">{label}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
