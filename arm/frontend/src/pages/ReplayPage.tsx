import React, { useState, useEffect } from 'react';
import { apiClient } from '../api/client';
import { MapCanvas, MapLayersConfig } from '../components/MapCanvas';
import { MapLegend } from '../components/map/MapLegend';
import { ReplayToolbar } from '../components/replay/ReplayToolbar';
import { ReplayTelemetry } from '../components/replay/ReplayTelemetry';
import { ReplayControls } from '../components/replay/ReplayControls';
import { useReplayEngine } from '../hooks/useReplayEngine';
import { TickData, MapData, ScenarioItem, ReplayMissionData } from '../types';

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
  const [missions, setMissions] = useState<ReplayMissionData[]>([]);
  const [totalTicks, setTotalTicks] = useState(3410);
  const [followRobot, setFollowRobot] = useState(false);
  const [loading, setLoading] = useState(true);

  // Конфигурация слоев
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

  const {
    currentTickIndex,
    isPlaying,
    playSpeed,
    setPlaySpeed,
    seekTo,
    step,
    togglePlay,
    reset,
  } = useReplayEngine({ ticks });

  // Загрузка сценариев при монтировании
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

  // Загрузка данных воспроизведения для выбранного сценария
  useEffect(() => {
    let mounted = true;
    setLoading(true);

    apiClient.fetchReplay(scenario).then((vm) => {
      if (!mounted) return;
      setTicks(vm.ticks);
      setMapData(vm.mapData);
      setEpisodes(vm.episodes);
      setMissions(vm.missions || []);
      setTotalTicks(vm.totalTicks);

      // Поиск такта при передаче t в параметрах URL
      if (queryParams?.t !== undefined) {
        const targetT = Number(queryParams.t);
        const idx = vm.ticks.findIndex((tk) => tk.t >= targetT);
        const initialIdx = idx !== -1 ? idx : 0;
        reset(initialIdx, vm.ticks.length - 1);
      } else {
        // Переход к началу или первому событию по умолчанию
        const defaultIdx = Math.min(100, Math.floor(vm.ticks.length * 0.1));
        reset(defaultIdx, vm.ticks.length - 1);
      }
      setLoading(false);
    });

    return () => {
      mounted = false;
    };
  }, [scenario]);

  // Обработка обновления параметров URL при загруженных данных
  useEffect(() => {
    if (queryParams?.t !== undefined && ticks.length > 0) {
      const targetTime = Number(queryParams.t);
      const closestIndex = ticks.findIndex((tick) => tick.t >= targetTime);
      if (closestIndex !== -1) {
        seekTo(closestIndex);
      }
    }
  }, [queryParams?.t, ticks]);

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
  const activeMission = missions.find((m) => m.id === currentTick.m) || missions[0];
  const totalTime = ticks[ticks.length - 1]?.t || 341.0;
  const currentActualTick = Math.min(totalTicks, Math.round(currentTick.t * 10));

  // Определение примечания и статуса
  const isPersonNear = (currentTick.hum !== null && currentTick.hum < 3.0) || !!currentTick.nt;
  const noteText =
    currentTick.nt === 'person_near'
      ? 'рядом человек · ограничение скорости'
      : currentTick.nt || (isPersonNear ? 'рядом человек · ограничение скорости' : null);

  const toggleLayer = (key: keyof MapLayersConfig) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-4">
      {/* Top Replay Toolbar matching reply.png */}
      <ReplayToolbar
        scenario={scenario}
        onScenarioChange={setScenario}
        scenarios={scenarios}
        currentTickTime={currentTick.t}
        totalTime={totalTime}
        currentActualTick={currentActualTick}
        totalTicks={totalTicks}
        loading={loading}
        followRobot={followRobot}
        onToggleFollowRobot={() => setFollowRobot(!followRobot)}
        layers={layers}
        onToggleLayer={toggleLayer}
      />

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
          <MapLegend />
        </div>

        {/* Right Telemetry HUD (3 cols) matching reply.png */}
        <ReplayTelemetry
          currentTick={currentTick}
          activeMission={activeMission}
          noteText={noteText}
        />
      </div>

      {/* Bottom Playback Dock & Timeline matching reply.png */}
      <ReplayControls
        currentTickIndex={currentTickIndex}
        maxTickIndex={Math.max(0, ticks.length - 1)}
        isPlaying={isPlaying}
        playSpeed={playSpeed}
        episodes={episodes}
        totalTime={totalTime}
        onSeekTo={seekTo}
        onStep={step}
        onTogglePlay={togglePlay}
        onSpeedChange={setPlaySpeed}
      />
    </div>
  );
};

export default ReplayPage;
