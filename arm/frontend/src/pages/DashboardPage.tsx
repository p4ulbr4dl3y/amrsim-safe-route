import React, { useState, useEffect, useRef } from 'react';
import {
  RouteName,
  DashboardViewModel,
  ScenarioItem,
  TickData,
  MapData,
  RecentEvent,
  ReplayViewModel,
  MissionsViewModel,
  MissionData,
} from '../types';
import { apiClient } from '../api/client';
import { MapCanvas } from '../components/MapCanvas';
import { Upload, Play, ArrowRight, ChevronDown, RefreshCw, RotateCcw } from 'lucide-react';
import { Latex } from '../components/Latex';
import {
  saveUploadedScenario,
  getUploadedScenario,
  clearUploadedScenario,
  hasUploadedScenario,
  UploadedScenarioData,
  AMR_STORAGE_EVENT,
  getSelectedScenario,
  setSelectedScenario as persistSelectedScenario,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';

const formatTime = (seconds: number): string => {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

interface DashboardPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  onNavigate,
  activeScenario,
  onScenarioChange,
}) => {
  const [selectedScenario, setSelectedScenario] = useState<string>(
    activeScenario || getSelectedScenario()
  );
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [data, setData] = useState<DashboardViewModel | null>(null);
  const [loading, setLoading] = useState(true);
  const uploadedRef = useRef(false);

  // Sync with activeScenario prop
  useEffect(() => {
    if (activeScenario && activeScenario !== selectedScenario) {
      setSelectedScenario(activeScenario);
    }
  }, [activeScenario]);

  // Sync with global scenario change event
  useEffect(() => {
    const handleStorageChange = (e: any) => {
      const sc = e.detail;
      if (sc && sc !== selectedScenario) {
        setSelectedScenario(sc);
      }
    };
    window.addEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleStorageChange);
    return () => {
      window.removeEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleStorageChange);
    };
  }, [selectedScenario]);

  // Check storage on mount and fetch scenarios
  useEffect(() => {
    let mounted = true;
    const uploaded = getUploadedScenario();
    if (uploaded) {
      setSelectedScenario(uploaded.id);
      if (uploaded.dashboardViewModel) {
        setData(uploaded.dashboardViewModel);
        setLoading(false);
      }
    }

    apiClient.fetchScenarios().then((list) => {
      if (mounted) {
        setScenarios(list);
      }
    });

    const handleStorageChange = (e: any) => {
      const up = e.detail as UploadedScenarioData | null;
      if (up) {
        setSelectedScenario(up.id);
        if (up.dashboardViewModel) {
          setData(up.dashboardViewModel);
          setLoading(false);
        }
      } else {
        setSelectedScenario(getSelectedScenario());
      }
      apiClient.fetchScenarios().then((list) => {
        if (mounted) setScenarios(list);
      });
    };

    window.addEventListener(AMR_STORAGE_EVENT as any, handleStorageChange);
    return () => {
      mounted = false;
      window.removeEventListener(AMR_STORAGE_EVENT as any, handleStorageChange);
    };
  }, []);

  // Fetch dashboard data when scenario changes
  useEffect(() => {
    let mounted = true;
    if (uploadedRef.current) {
      uploadedRef.current = false;
      return;
    }
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

  // Client-side FileReader parser for:
  // A) Scenario JSON (schema: amr-1.0 with map, name, missions, start)
  // B) Simulator report JSON (score, summary, ticks, end_reason)
  // C) Telemetry log JSONL (type: 'tick')
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      if (!text) return;

      try {
        const isJsonl =
          file.name.endsWith('.jsonl') ||
          text.includes('\n{"type":"tick"') ||
          text.includes('\n{"type": "tick"');

        if (isJsonl) {
          // --- Case C: .jsonl (frame-by-frame telemetry log) ---
          const lines = text.split('\n');
          let headerObj: any = null;
          const parsedTicks: TickData[] = [];

          for (const rawLine of lines) {
            const trimmed = rawLine.trim();
            if (!trimmed) continue;
            try {
              const item = JSON.parse(trimmed);
              if (item.type === 'header') {
                headerObj = item;
              } else if (item.type === 'tick') {
                if (item.pe && item.pe.length >= 2 && item.pe_error === undefined) {
                  item.pe_error = Math.hypot(item.pe[0] - item.x, item.pe[1] - item.y);
                }
                parsedTicks.push(item as TickData);
              }
            } catch {
              // skip unparseable line
            }
          }

          if (parsedTicks.length > 0) {
            const previewTick = parsedTicks[parsedTicks.length - 1];
            const historyTicks = parsedTicks;

            // Sample speeds |v| (40 samples across duration)
            const NUM_SPEED_SAMPLES = 40;
            const speedHistory: number[] = [];
            const speedTimestamps: string[] = [];
            const totalTicks = parsedTicks.length;

            if (totalTicks <= NUM_SPEED_SAMPLES) {
              for (const tk of parsedTicks) {
                speedHistory.push(Math.round(Math.abs(tk.v || 0) * 100) / 100);
                speedTimestamps.push(formatTime(tk.t || 0));
              }
            } else {
              const step = (totalTicks - 1) / (NUM_SPEED_SAMPLES - 1);
              for (let i = 0; i < NUM_SPEED_SAMPLES; i++) {
                const idx = Math.min(totalTicks - 1, Math.round(i * step));
                const tk = parsedTicks[idx];
                speedHistory.push(Math.round(Math.abs(tk.v || 0) * 100) / 100);
                speedTimestamps.push(formatTime(tk.t || 0));
              }
            }

            // Map data from header if present
            let parsedMapData: MapData | undefined = undefined;
            if (headerObj?.map && Array.isArray(headerObj.map.bounds)) {
              parsedMapData = {
                bounds: headerObj.map.bounds,
                drivable: headerObj.map.drivable || [],
                buildings: headerObj.map.buildings || [],
                zones: headerObj.map.zones || [],
                gates: headerObj.map.gates || [],
                crossing: headerObj.map.crossing || [],
                points: headerObj.map.points || headerObj.points || {},
              };
            }

            const activeMapData = parsedMapData || data?.mapData;

            // Localization error from ticks
            const peErrors = parsedTicks
              .filter((t) => typeof t.pe_error === 'number' && !isNaN(t.pe_error))
              .map((t) => t.pe_error!);
            const meanLocError =
              peErrors.length > 0
                ? Math.round((peErrors.reduce((sum, v) => sum + v, 0) / peErrors.length) * 100) / 100
                : null;

            const fatalCollisions = parsedTicks.some((t) => t.coll === 1) ? 1 : 0;
            const scenarioName = headerObj?.scenario || file.name.replace(/\.jsonl$/i, '');
            const scenarioId = scenarioName;

            const newEvent: RecentEvent = {
              id: `log-${Date.now()}`,
              title: `Загружен лог · ${file.name}`,
              detail: `Кадров телеметрии: ${parsedTicks.length}, время: ${formatTime(previewTick.t || 0)}`,
              time: formatTime(previewTick.t || 0),
              status: fatalCollisions > 0 ? 'critical' : 'success',
            };

            const updatedDashboard: DashboardViewModel = {
              scenario: scenarioId,
              totalScore: fatalCollisions > 0 ? 0.0 : (data?.totalScore ?? 0),
              totalMax: 100,
              deliveriesCount: data?.deliveriesCount ?? 0,
              deliveriesTotal: data?.deliveriesTotal ?? 0,
              safetyFatal: fatalCollisions,
              safetyWarnings: 0,
              localizationError: meanLocError,
              recentEvents: [newEvent, ...(data?.recentEvents || [])].slice(0, 6),
              controllerState: {
                online: true,
                meanDelayMs: 0,
                maxDelayMs: 0,
                nSteps: parsedTicks.length,
              },
              speedHistory,
              speedTimestamps,
              previewTick,
              historyTicks,
              mapData: activeMapData,
            };

            const updatedReplay: ReplayViewModel = {
              scenario: scenarioId,
              seed: 7,
              header: headerObj || { scenario: scenarioId, dt: 0.1 },
              mapData: activeMapData,
              ticks: parsedTicks,
              totalTicks: parsedTicks.length,
              duration: parsedTicks[parsedTicks.length - 1]?.t || 300,
              episodes: [],
            };

            uploadedRef.current = true;
            saveUploadedScenario({
              id: scenarioId,
              name: scenarioName,
              fileName: file.name,
              fileType: 'log',
              mapData: activeMapData,
              dashboardViewModel: updatedDashboard,
              replayViewModel: updatedReplay,
              uploadedAt: Date.now(),
            });

            setSelectedScenario(scenarioId);
            setData(updatedDashboard);
            apiClient.fetchScenarios().then((list) => setScenarios(list));
          }
        } else {
          // Parse .json
          const raw = JSON.parse(text);

          const isReport =
            raw.score !== undefined ||
            raw.end_reason !== undefined ||
            raw.summary?.fatalCount !== undefined ||
            raw.summary?.ruleViolationsCount !== undefined;

          if (!isReport && (raw.map !== undefined || raw.start !== undefined || raw.missions !== undefined || (raw.schema === 'amr-1.0' && raw.name !== undefined))) {
            // --- Case A: Scenario JSON (schema: amr-1.0 with map, name, missions, start) ---
            const scenarioName = raw.name || file.name.replace(/\.json$/i, '');
            const scenarioId = scenarioName;

            const parsedMapData: MapData = {
              bounds: raw.map?.bounds || [0, 0, 200, 150],
              drivable: raw.map?.drivable || [],
              buildings: raw.map?.buildings || [],
              zones: raw.map?.zones || [],
              gates: raw.map?.gates || [],
              crossing: raw.map?.crossing || [],
              points: raw.map?.points || raw.points || {},
            };

            const startX = typeof raw.start?.x === 'number' ? raw.start.x : (parsedMapData.bounds[0] + 10);
            const startY = typeof raw.start?.y === 'number' ? raw.start.y : (parsedMapData.bounds[1] + 10);
            const startTheta = typeof raw.start?.theta === 'number' ? raw.start.theta : 0;

            const previewTick: TickData = {
              t: 0,
              x: startX,
              y: startY,
              th: startTheta,
              v: 0,
              w: 0,
              cv: 0,
              cw: 0,
              st: 'idle',
              pe: [startX, startY, startTheta],
              nt: 'Начальная позиция сценария',
              m: Array.isArray(raw.missions) && raw.missions[0] ? raw.missions[0].id : null,
              drv: 1,
              fbd: 0,
              vmax: null,
              hum: null,
              obj: null,
              coll: 0,
              cont: 0,
              pe_error: 0,
            };

            const missionsTotal = Array.isArray(raw.missions) ? raw.missions.length : 0;

            const missionsList: MissionData[] = Array.isArray(raw.missions)
              ? raw.missions.map((m: any, idx: number) => {
                  const fromPt = parsedMapData.points[m.from];
                  const toPt = parsedMapData.points[m.to];
                  return {
                    id: m.id || `m${idx + 1}`,
                    from: m.from || 'dock_start',
                    to: m.to || 'dock_end',
                    fromLabel: fromPt?.label || m.from || 'Стартовая точка',
                    toLabel: toPt?.label || m.to || 'Целевая точка',
                    status: 'DELIVERED',
                    t_start: 0,
                    t_end: m.deadline_s || 120,
                    t_arrival: m.deadline_s ? m.deadline_s * 0.7 : 80,
                    hold_duration_s: 3.0,
                    hold_ticks: 30,
                    max_hold_dist: 0.1,
                    tol: toPt?.tol || 0.5,
                    deadline_s: m.deadline_s || 120,
                    safety_margin_s: m.deadline_s ? m.deadline_s * 0.3 : 36,
                    reference_length_m: m.reference_length_m || 50,
                    actual_time_s: m.deadline_s ? m.deadline_s * 0.7 : 80,
                  };
                })
              : [];

            const missionsViewModel: MissionsViewModel = {
              scenario: scenarioId,
              summary: {
                completed: 0,
                total: missionsTotal,
                deliveryScore: 40.0,
                maxDeliveryScore: 40.0,
                efficiencyScore: 15.0,
                maxEfficiencyScore: 15.0,
              },
              missions: missionsList,
            };

            const replayViewModel: ReplayViewModel = {
              scenario: scenarioId,
              seed: 7,
              header: { scenario: scenarioId, dt: raw.dt || 0.1, duration_s: raw.duration_s || 300 },
              mapData: parsedMapData,
              ticks: [previewTick],
              totalTicks: 1,
              duration: raw.duration_s || 300,
              episodes: [],
            };

            const newEvent: RecentEvent = {
              id: `scen-${Date.now()}`,
              title: `Загружен сценарий · ${file.name}`,
              detail: `Заданий: ${missionsTotal}, размер: ${parsedMapData.bounds[2] - parsedMapData.bounds[0]}x${parsedMapData.bounds[3] - parsedMapData.bounds[1]}м`,
              time: '00:00',
              status: 'success',
            };

            const updatedDashboard: DashboardViewModel = {
              scenario: scenarioId,
              totalScore: 100.0,
              totalMax: 100,
              deliveriesCount: 0,
              deliveriesTotal: missionsTotal,
              safetyFatal: 0,
              safetyWarnings: 0,
              localizationError: 0.0,
              recentEvents: [newEvent, ...(data?.recentEvents || [])].slice(0, 6),
              controllerState: {
                online: true,
                meanDelayMs: 2.1,
                maxDelayMs: 15.0,
                nSteps: 0,
              },
              speedHistory: [0, 0, 0, 0],
              speedTimestamps: ['00:00', '01:00', '02:00', '03:00'],
              previewTick,
              historyTicks: [previewTick],
              mapData: parsedMapData,
            };

            uploadedRef.current = true;
            saveUploadedScenario({
              id: scenarioId,
              name: scenarioName,
              fileName: file.name,
              fileType: 'scenario',
              mapData: parsedMapData,
              scenarioJson: raw,
              dashboardViewModel: updatedDashboard,
              replayViewModel,
              missionsViewModel,
              uploadedAt: Date.now(),
            });

            setSelectedScenario(scenarioId);
            setData(updatedDashboard);
            apiClient.fetchScenarios().then((list) => setScenarios(list));
          } else {
            // --- Case B: Report JSON (simulator run report) ---
            const report = raw;
            const scenarioName =
              report.scenario || report.id || report.scenario_id || file.name.replace(/\.json$/i, '');
            const scenarioId = scenarioName;

            const totalScore =
              typeof report.score?.total === 'number'
                ? report.score.total
                : typeof report.totalScore === 'number'
                ? report.totalScore
                : 0.0;

            // Deliveries
            let deliveriesCount: number | undefined = undefined;
            let deliveriesTotal: number | undefined = undefined;
            if (Array.isArray(report.missions)) {
              deliveriesTotal = report.missions.length;
              deliveriesCount =
                typeof report.score?.deliveries === 'number'
                  ? report.score.deliveries
                  : report.missions.filter((m: any) => m.delivered === true || m.status === 'DELIVERED').length;
            } else if (typeof report.score?.deliveries === 'number') {
              deliveriesCount = report.score.deliveries;
            }

            // Safety Fatal & Warnings
            let safetyFatal: number | undefined = undefined;
            let safetyWarnings: number | undefined = undefined;

            if (report.summary?.fatalCount !== undefined) {
              safetyFatal = Number(report.summary.fatalCount);
            } else if (report.summary?.fatal !== undefined) {
              safetyFatal = report.summary.fatal ? 1 : 0;
            } else if (report.score?.fatal !== undefined) {
              safetyFatal = report.score.fatal ? 1 : 0;
            } else if (Array.isArray(report.episodes_raw)) {
              safetyFatal = report.episodes_raw.filter(
                (e: any) => e.severity === 'critical' || e.cost <= -20
              ).length;
            }

            if (report.summary?.warningsCount !== undefined) {
              safetyWarnings = Number(report.summary.warningsCount);
            } else if (report.summary?.warnings !== undefined) {
              safetyWarnings = Number(report.summary.warnings);
            } else if (Array.isArray(report.episodes_raw)) {
              safetyWarnings = report.episodes_raw.filter(
                (e: any) =>
                  e.severity === 'warning' ||
                  (e.cost !== undefined && e.cost < 0 && e.cost > -20)
              ).length;
            } else if (Array.isArray(report.score?.episodes)) {
              safetyWarnings = report.score.episodes.length;
            }

            // Localization Error
            const localizationError =
              report.pose_error?.mean_m ??
              report.localizationError ??
              report.score?.pose_error?.mean_m ??
              (typeof report.pose_error === 'number' ? report.pose_error : null);

            // Step time
            const meanDelay = report.step_time_ms?.mean ?? 0;
            const maxDelay = report.step_time_ms?.max ?? 0;
            const nSteps = report.step_time_ms?.n ?? report.ticks ?? 0;

            let parsedMapData: MapData | undefined = undefined;
            if (report.map && Array.isArray(report.map.bounds)) {
              parsedMapData = {
                bounds: report.map.bounds,
                drivable: report.map.drivable || [],
                buildings: report.map.buildings || [],
                zones: report.map.zones || [],
                gates: report.map.gates || [],
                crossing: report.map.crossing || [],
                points: report.map.points || report.points || {},
              };
            }

            const activeMapData = parsedMapData || data?.mapData;

            const newEvent: RecentEvent = {
              id: `rep-${Date.now()}`,
              title: `Загружен отчет · ${file.name}`,
              detail: `Балл: ${(totalScore ?? 0).toFixed(2)}, Доставок: ${deliveriesCount ?? 0}/${
                deliveriesTotal ?? 0
              }`,
              time: '00:00',
              status: safetyFatal && safetyFatal > 0 ? 'critical' : 'success',
            };

            const updatedDashboard: DashboardViewModel = {
              scenario: scenarioId,
              totalScore: totalScore ?? 0,
              totalMax: 100,
              deliveriesCount: deliveriesCount !== undefined ? deliveriesCount : (data?.deliveriesCount ?? 0),
              deliveriesTotal: deliveriesTotal !== undefined ? deliveriesTotal : (data?.deliveriesTotal ?? 0),
              safetyFatal: safetyFatal !== undefined ? safetyFatal : (data?.safetyFatal ?? 0),
              safetyWarnings: safetyWarnings !== undefined ? safetyWarnings : (data?.safetyWarnings ?? 0),
              localizationError:
                localizationError !== undefined ? localizationError : (data?.localizationError ?? null),
              recentEvents: [newEvent, ...(data?.recentEvents || [])].slice(0, 6),
              controllerState: {
                online: true,
                meanDelayMs: meanDelay,
                maxDelayMs: maxDelay,
                nSteps,
              },
              speedHistory: data?.speedHistory || [],
              speedTimestamps: data?.speedTimestamps || [],
              previewTick: data?.previewTick || null,
              historyTicks: data?.historyTicks || [],
              mapData: activeMapData,
            };

            uploadedRef.current = true;
            saveUploadedScenario({
              id: scenarioId,
              name: scenarioName,
              fileName: file.name,
              fileType: 'report',
              mapData: activeMapData,
              reportJson: report,
              dashboardViewModel: updatedDashboard,
              uploadedAt: Date.now(),
            });

            handleScenarioChange(scenarioId);
            setData(updatedDashboard);
            apiClient.fetchScenarios().then((list) => setScenarios(list));
          }
        }
      } catch (err) {
        console.error('[DashboardPage] Failed to parse uploaded file:', err);
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleScenarioChange = (newSc: string) => {
    setSelectedScenario(newSc);
    persistSelectedScenario(newSc);
    onScenarioChange?.(newSc);
    if (typeof window !== 'undefined') {
      const rawHash = window.location.hash.replace(/^#\/?/, '');
      const [route, queryStr] = rawHash.split('?');
      const sp = new URLSearchParams(queryStr || '');
      sp.set('scenario', newSc);
      window.location.hash = `#/${route || 'dashboard'}?${sp.toString()}`;
    }
  };

  const handleClearUploaded = () => {
    clearUploadedScenario();
    handleScenarioChange('04_busy_yard');
    setLoading(true);
    apiClient.fetchDashboard('04_busy_yard').then((vm) => {
      setData(vm);
      setLoading(false);
    });
    apiClient.fetchScenarios().then((list) => {
      setScenarios(list);
    });
  };

  const totalScore = data?.totalScore ?? null;
  const scorePct = totalScore !== null ? Math.max(0, Math.min(100, totalScore)) : 0;

  // Compute speed curve points dynamically for SVG
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
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full min-w-[1240px] gap-5">
      {/* Subheader Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-white p-3.5 px-5 rounded-xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-500 font-medium">Сценарий:</label>
          <div className="relative min-w-[200px]">
            <select
              value={selectedScenario}
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

          {/* Clear Uploaded Scenario button */}
          {hasUploadedScenario() && (
            <button
              data-testid="clear-uploaded-btn"
              onClick={handleClearUploaded}
              className="flex items-center gap-1.5 text-xs text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 px-3 py-1.5 rounded-lg transition-colors font-medium"
              title="Сбросить загруженный сценарий"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Сбросить сценарий</span>
            </button>
          )}

          {/* Upload Log Button */}
          <label className="cursor-pointer flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors font-medium">
            <Upload className="w-3.5 h-3.5" />
            <span>Загрузить лог</span>
            <input
              type="file"
              data-testid="upload-log-input"
              className="hidden"
              accept=".json,.jsonl"
              onChange={handleFileUpload}
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
              {totalScore !== null ? totalScore.toFixed(1) : '—'}
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
              {totalScore !== null ? totalScore.toFixed(2) : '—'}{' '}
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
              {data?.deliveriesCount ?? 0}{' '}
              <span className="text-sm font-normal text-slate-400">/ {data?.deliveriesTotal ?? 0}</span>
            </div>
          </div>
        </div>

        {/* KPI 3: Safety */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex items-center gap-4">
          <div
            className={`w-3.5 h-3.5 rounded-full ring-4 ${
              (data?.safetyFatal ?? 0) > 0
                ? 'bg-rose-500 ring-rose-100'
                : (data?.safetyWarnings ?? 0) > 0
                ? 'bg-amber-500 ring-amber-100'
                : 'bg-emerald-500 ring-emerald-100'
            }`}
          ></div>
          <div>
            <div className="text-xs text-slate-500 font-medium">Безопасность</div>
            <div className="text-xl font-bold font-mono mt-0.5 flex items-baseline gap-1.5">
              {(data?.safetyFatal ?? 0) > 0 && (
                <>
                  <span className="text-rose-600 font-bold">{data?.safetyFatal}</span>
                  <span className="text-xs font-normal text-slate-500 font-sans">Фатальных ·{' '}</span>
                </>
              )}
              <span className={(data?.safetyWarnings ?? 0) > 0 ? 'text-amber-600' : 'text-slate-900'}>
                {data?.safetyWarnings ?? 0}
              </span>{' '}
              <span className="text-xs font-normal text-slate-500 font-sans">Предупреждений</span>
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
              {typeof data?.localizationError === 'number' ? (
                <>
                  {data.localizationError.toFixed(2)}{' '}
                  <span className="text-sm font-normal text-slate-500">м</span>
                </>
              ) : (
                '—'
              )}
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
            <h2 className="text-sm font-semibold text-slate-800">Быстрый запуск</h2>

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
              {(data?.recentEvents || []).length === 0 ? (
                <div className="text-xs text-slate-400 py-4 text-center">
                  Нет зарегистрированных событий
                </div>
              ) : (
                data!.recentEvents.map((evt) => (
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
                ))
              )}
            </div>
          </div>

          {/* Card: Состояние контроллера */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-800">Контроллер платформы (backend/)</h2>
              {data?.controllerState?.online ? (
                <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                  Онлайн
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[11px] text-slate-400 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-300"></span>
                  Ожидание
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4 mt-1 pt-2 border-t border-slate-100">
              <div>
                <div className="text-[11px] text-slate-500">Средняя задержка шага</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {typeof data?.controllerState?.meanDelayMs === 'number' && data.controllerState.online ? (
                    <>
                      {data.controllerState.meanDelayMs.toFixed(2)}{' '}
                      <span className="text-xs font-normal text-slate-500">мс</span>
                    </>
                  ) : (
                    '—'
                  )}
                </div>
                <div className="text-[10px] text-slate-400 font-mono">среднее время шага</div>
              </div>

              <div>
                <div className="text-[11px] text-slate-500">Максимальная задержка</div>
                <div className="text-base font-bold text-slate-900 font-mono mt-0.5">
                  {typeof data?.controllerState?.maxDelayMs === 'number' && data.controllerState.online ? (
                    <>
                      {data.controllerState.maxDelayMs.toFixed(1)}{' '}
                      <span className="text-xs font-normal text-slate-500">мс</span>
                    </>
                  ) : (
                    '—'
                  )}
                </div>
                <div className="text-[10px] text-slate-400 font-mono">макс. задержка</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
