import React, { useState, useEffect, useRef } from 'react';
import { apiClient } from '../api/client';
import { MapCanvas, MapLayersConfig } from '../components/MapCanvas';
import { TickData, MapData, ScenarioItem } from '../types';
import { 
  Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight, 
  ChevronDown, User, Layers, RefreshCw
} from 'lucide-react';

interface ReplayPageProps {
  queryParams?: {
    scenario?: string;
    t?: number;
    x?: number;
    y?: number;
    mission?: string;
    run?: string;
  };
}

export const ReplayPage: React.FC<ReplayPageProps> = ({ queryParams }) => {
  const [scenario, setScenario] = useState(queryParams?.scenario || '04_busy_yard');
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [ticks, setTicks] = useState<TickData[]>([]);
  const [mapData, setMapData] = useState<MapData | undefined>(undefined);
  const [episodes, setEpisodes] = useState<any[]>([]);
  const [totalTicks, setTotalTicks] = useState(3410);
  const [currentTickIndex, setCurrentTickIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState<number>(1.0);
  const [followRobot, setFollowRobot] = useState(false);
  const [layersMenuOpen, setLayersMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  // Layers configuration
  const [layers, setLayers] = useState<MapLayersConfig>({
    robot: true,
    poseEst: true,
    poseDiff: true,
    lidar: true,
    referencePath: true,
    drivable: true,
    buildings: true,
    docks: true,
    pedestrians: true,
  });

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

  const fractionalTickRef = useRef<number>(0);
  const animFrameRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number | null>(null);

  const seekTo = (idx: number) => {
    const maxIdx = Math.max(0, ticks.length - 1);
    const clamped = Math.max(0, Math.min(maxIdx, idx));
    fractionalTickRef.current = clamped;
    setCurrentTickIndex(clamped);
  };

  // Load replay data for selected scenario
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setIsPlaying(false);

    apiClient.fetchReplay(scenario).then((vm) => {
      if (!mounted) return;
      setTicks(vm.ticks);
      setMapData(vm.mapData);
      setEpisodes(vm.episodes);
      setTotalTicks(vm.totalTicks);

      // If queryParams has t, find matching tick
      if (queryParams?.t !== undefined) {
        const targetT = Number(queryParams.t);
        const idx = vm.ticks.findIndex((tk) => tk.t >= targetT);
        const initialIdx = idx !== -1 ? idx : 0;
        setCurrentTickIndex(initialIdx);
        fractionalTickRef.current = initialIdx;
      } else {
        // Default to beginning or interesting moment
        const defaultIdx = Math.min(100, Math.floor(vm.ticks.length * 0.1));
        setCurrentTickIndex(defaultIdx);
        fractionalTickRef.current = defaultIdx;
      }
      setLoading(false);
    });

    return () => {
      mounted = false;
    };
  }, [scenario]);

  // Handle incoming query params updates when already loaded
  useEffect(() => {
    if (queryParams?.t !== undefined && ticks.length > 0) {
      const targetTime = Number(queryParams.t);
      const closestIndex = ticks.findIndex((tick) => tick.t >= targetTime);
      if (closestIndex !== -1) {
        seekTo(closestIndex);
      }
    }
  }, [queryParams?.t, ticks]);

  // High-precision animation playback loop
  useEffect(() => {
    if (!isPlaying || ticks.length === 0) {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = null;
      }
      lastTimeRef.current = null;
      return;
    }

    // If starting at the end, restart from beginning
    if (fractionalTickRef.current >= ticks.length - 1) {
      fractionalTickRef.current = 0;
      setCurrentTickIndex(0);
    }

    lastTimeRef.current = performance.now();

    // Determine simulation tick rate (Hz): ticks per simulation second
    const tickRate =
      ticks.length > 1 && ticks[ticks.length - 1].t > ticks[0].t
        ? (ticks.length - 1) / (ticks[ticks.length - 1].t - ticks[0].t)
        : 10;

    const loop = (now: number) => {
      if (lastTimeRef.current === null) {
        lastTimeRef.current = now;
      }
      const elapsedSeconds = (now - lastTimeRef.current) / 1000;
      lastTimeRef.current = now;

      // Cap delta time to 0.1s to prevent huge jumps on tab switch/lag spike
      const clampedDt = Math.min(elapsedSeconds, 0.1);
      const deltaTicks = clampedDt * playSpeed * tickRate;
      const nextTick = fractionalTickRef.current + deltaTicks;

      if (nextTick >= ticks.length - 1) {
        fractionalTickRef.current = ticks.length - 1;
        setCurrentTickIndex(ticks.length - 1);
        setIsPlaying(false);
        return;
      }

      fractionalTickRef.current = nextTick;
      const nextInt = Math.floor(nextTick);
      setCurrentTickIndex((prev) => (prev !== nextInt ? nextInt : prev));

      animFrameRef.current = requestAnimationFrame(loop);
    };

    animFrameRef.current = requestAnimationFrame(loop);

    return () => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = null;
      }
      lastTimeRef.current = null;
    };
  }, [isPlaying, playSpeed, ticks]);

  const currentTick: TickData = ticks[currentTickIndex] || {
    t: 0,
    x: 51.5,
    y: 150.0,
    th: 0,
    v: 0,
    w: 0,
    cv: 0,
    cw: 0,
    st: 'waiting',
    pe: [51.5, 150.0, 0],
    nt: null,
    m: 'm1',
    drv: 1,
    fbd: 0,
    vmax: null,
    hum: null,
    obj: null,
    coll: 0,
    cont: 0,
  };

  const historyTicks = ticks.slice(0, currentTickIndex + 1);

  // Format time mm:ss.d
  const formatTime = (secs: number) => {
    const mins = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    const ms = Math.floor((secs % 1) * 10);
    return `${String(mins).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
  };

  const totalTime = ticks[ticks.length - 1]?.t || 341.0;
  const currentActualTick = Math.min(totalTicks, Math.round(currentTick.t * 10));

  // Determine note & status
  const isPersonNear = (currentTick.hum !== null && currentTick.hum < 3.0) || !!currentTick.nt;
  const noteText = currentTick.nt === 'person_near'
    ? 'рядом человек · ограничение скорости'
    : currentTick.nt || (isPersonNear ? 'рядом человек · ограничение скорости' : null);

  const toggleLayer = (key: keyof MapLayersConfig) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-4">
      {/* Top Replay Toolbar matching reply.png */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3 px-5 rounded-xl border border-slate-200 shadow-sm">
        {/* Scenario selector */}
        <div className="relative min-w-[200px]">
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
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
          <span>{formatTime(currentTick.t)}</span>
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
              onClick={() => setFollowRobot(!followRobot)}
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
                {[
                  { key: 'robot', label: 'Робот' },
                  { key: 'poseEst', label: 'Оценка позы' },
                  { key: 'poseDiff', label: 'Разница поз' },
                  { key: 'lidar', label: 'Лидар' },
                  { key: 'referencePath', label: 'Опорный маршрут' },
                  { key: 'drivable', label: 'Проезжая часть' },
                  { key: 'buildings', label: 'Здания' },
                  { key: 'docks', label: 'Доки' },
                  { key: 'pedestrians', label: 'Пешеходы' },
                ].map(({ key, label }) => (
                  <label
                    key={key}
                    className="flex items-center gap-2 p-1 hover:bg-slate-50 rounded cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={layers[key as keyof MapLayersConfig]}
                      onChange={() => toggleLayer(key as keyof MapLayersConfig)}
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

      {/* Main View: Left Map Canvas / Right Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1 min-h-[500px]">
        {/* Map Container (9 cols) */}
        <div className="lg:col-span-9 bg-white rounded-xl border border-slate-200 shadow-sm flex flex-col overflow-hidden">
          <div className="flex-1 w-full h-[460px] bg-slate-50 relative">
            <MapCanvas
              currentTick={currentTick}
              historyTicks={historyTicks}
              highlightMission={queryParams?.mission || null}
              targetCoords={
                queryParams?.x && queryParams?.y
                  ? { x: Number(queryParams.x), y: Number(queryParams.y) }
                  : null
              }
              layers={layers}
              followRobot={followRobot}
              mapData={mapData}
            />
          </div>

          {/* Legend below map matching reply.png */}
          <div className="bg-white border-t border-slate-100 px-4 py-2.5 flex flex-wrap items-center justify-between gap-y-2 text-[11px] text-slate-600">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block"></span>
              <span>Робот</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full border-2 border-purple-500 inline-block"></span>
              <span>Оценка позы</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 border-b-2 border-dashed border-red-500 inline-block"></span>
              <span>Разница поз</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-0.5 bg-blue-300 inline-block"></span>
              <span>Лидар</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 border-b-2 border-dashed border-blue-400 inline-block"></span>
              <span>Опорный маршрут</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-2 bg-slate-200 rounded-sm inline-block"></span>
              <span>Проезжая часть</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-2 bg-slate-300 rounded-sm inline-block"></span>
              <span>Здание</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full border-2 border-blue-600 inline-block"></span>
              <span>Док</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-500 inline-block"></span>
              <span>Пешеход (3 м)</span>
            </div>
          </div>
        </div>

        {/* Right Telemetry HUD (3 cols) matching reply.png */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          {/* Status Badge */}
          <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
            <div className="flex items-center justify-center py-2 px-4 rounded-full bg-emerald-50 border border-emerald-200">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <span className="text-xs font-bold tracking-wider text-emerald-800 uppercase font-mono">
                  {currentTick.st || 'MOVING'}
                </span>
              </div>
            </div>

            {/* Note badge */}
            {noteText && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 flex items-center gap-2 text-xs text-amber-800">
                <User className="w-4 h-4 text-amber-600 flex-shrink-0" />
                <span className="font-medium text-[11px] leading-tight">{noteText}</span>
              </div>
            )}

            {/* Speeds */}
            <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
              <span className="text-slate-500">v</span>
              <span className="font-bold text-slate-800">{currentTick.v.toFixed(2)} м/с</span>
              <span className="text-slate-300">·</span>
              <span className="text-slate-500">cv</span>
              <span className="font-semibold text-slate-700">{currentTick.cv.toFixed(2)} м/с</span>
            </div>

            {/* Distance to human with proximity gauge */}
            <div className="pt-2 border-t border-slate-100 flex flex-col gap-1.5 text-xs font-mono">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">hum</span>
                <span className="font-bold text-slate-800">
                  {currentTick.hum !== null ? `${currentTick.hum.toFixed(2)} м` : '—'}
                </span>
              </div>
              <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    currentTick.hum && currentTick.hum < 1.0
                      ? 'bg-red-500'
                      : currentTick.hum && currentTick.hum < 3.0
                      ? 'bg-amber-500'
                      : 'bg-emerald-500'
                  }`}
                  style={{
                    width: `${Math.min(
                      100,
                      Math.max(0, ((currentTick.hum || 5) / 5) * 100)
                    )}%`,
                  }}
                ></div>
              </div>
            </div>

            {/* Distance to obstacle */}
            <div className="pt-1 flex items-center justify-between text-xs font-mono">
              <span className="text-slate-500">obj</span>
              <span className="font-bold text-slate-800">
                {currentTick.obj !== null ? `${currentTick.obj.toFixed(2)} м` : '—'}
              </span>
            </div>

            {/* Pose estimation and error */}
            <div className="pt-2 border-t border-slate-100 flex flex-col gap-1 text-xs font-mono">
              <div className="flex justify-between text-slate-500">
                <span>pose_est:</span>
                <span className="text-slate-800">
                  {currentTick.pe
                    ? `${currentTick.pe[0].toFixed(1)}, ${currentTick.pe[1].toFixed(1)}`
                    : 'none'}
                </span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>pe_error:</span>
                <span
                  className={`font-semibold ${
                    (currentTick.pe_error || 0) > 0.5 ? 'text-amber-600' : 'text-slate-800'
                  }`}
                >
                  {(currentTick.pe_error || 0).toFixed(3)} м
                </span>
              </div>
            </div>

            {/* Collisions */}
            <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs font-mono">
              <div className="flex items-center gap-1 text-slate-600">
                <span>coll</span>
                <span
                  className={`font-bold ${
                    currentTick.coll ? 'text-red-600' : 'text-slate-800'
                  }`}
                >
                  {currentTick.coll}
                </span>
              </div>
              <span className="text-slate-300">·</span>
              <div className="flex items-center gap-1 text-slate-600">
                <span>cont</span>
                <span
                  className={`font-bold ${
                    currentTick.cont ? 'text-red-600' : 'text-slate-800'
                  }`}
                >
                  {currentTick.cont}
                </span>
              </div>
            </div>
          </div>

          {/* Current Mission Card */}
          <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-2">
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
              ТЕКУЩЕЕ ЗАДАНИЕ
            </span>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 font-mono text-xs">
              <div className="font-bold text-slate-900 text-sm">{currentTick.m || 'm1'}</div>
              <div className="text-slate-600 text-[11px] mt-1">
                Склад → Цех А <span className="text-slate-400">·</span>{' '}
                {Math.max(0, 200.7 - currentTick.t).toFixed(1)} s left
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Playback Dock & Timeline matching reply.png */}
      <div className="bg-white p-3.5 px-6 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
        {/* Playback Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => seekTo(0)}
            className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
            title="В начало"
          >
            <SkipBack className="w-3.5 h-3.5 fill-current" />
          </button>
          <button
            onClick={() => seekTo(currentTickIndex - 10)}
            className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
            title="Шаг назад"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => {
              if (!isPlaying && currentTickIndex >= ticks.length - 1) {
                seekTo(0);
              }
              setIsPlaying(!isPlaying);
            }}
            className="w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center shadow-md transition-colors"
            title={isPlaying ? 'Пауза' : 'Воспроизведение'}
          >
            {isPlaying ? (
              <Pause className="w-4 h-4 fill-current" />
            ) : (
              <Play className="w-4 h-4 fill-current ml-0.5" />
            )}
          </button>
          <button
            onClick={() => seekTo(currentTickIndex + 10)}
            className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
            title="Шаг вперед"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => seekTo(ticks.length - 1)}
            className="w-8 h-8 rounded-lg border border-slate-200 hover:bg-slate-50 flex items-center justify-center text-slate-600 transition-colors"
            title="В конец"
          >
            <SkipForward className="w-3.5 h-3.5 fill-current" />
          </button>
        </div>

        {/* Timeline Scrubber */}
        <div className="flex-1 w-full mx-4 relative py-2">
          <input
            type="range"
            min={0}
            max={Math.max(0, ticks.length - 1)}
            value={currentTickIndex}
            onChange={(e) => seekTo(Number(e.target.value))}
            className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />

          {/* Incident tick markers on timeline */}
          <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 pointer-events-none px-1 flex justify-between">
            {episodes.slice(0, 10).map((ep, i) => {
              const leftPercent = Math.min(100, Math.max(0, (ep.t_start / totalTime) * 100));
              const color =
                ep.cost < -0.5
                  ? 'bg-amber-500'
                  : ep.cost < 0
                  ? 'bg-blue-500'
                  : 'bg-emerald-500';
              return (
                <div
                  key={ep.id || i}
                  className={`absolute w-1.5 h-3 rounded-full ${color}`}
                  style={{ left: `${leftPercent}%` }}
                  title={`${ep.type}: ${ep.cost} pts (t=${ep.t_start}s)`}
                />
              );
            })}
          </div>
        </div>

        {/* Speed Multipliers */}
        <div className="flex items-center gap-1 text-xs">
          {[0.1, 0.5, 1.0, 2.0, 5.0, 10.0].map((s) => (
            <button
              key={s}
              onClick={() => setPlaySpeed(s)}
              className={`px-2 py-1 rounded-md font-mono transition-colors ${
                playSpeed === s
                  ? 'bg-blue-600 text-white font-bold'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
