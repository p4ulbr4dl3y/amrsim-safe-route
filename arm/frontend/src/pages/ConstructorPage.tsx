import React, { useState, useEffect, useRef, useMemo } from 'react';
import { RouteName, AmrScenario, MapData, ScenarioZone, ScenarioMapPatch, ScenarioPedestrian } from '../types';
import { apiClient } from '../api/client';
import {
  ConstructorCanvas,
  ConstructorTool,
  SelectedEntity,
  ConstructorLayers,
} from '../components/constructor/ConstructorCanvas';
import { scenarioTemplates } from '../utils/scenarioTemplates';
import { validateScenario } from '../utils/scenarioValidator';
import {
  saveUploadedScenario,
  setSelectedScenario as persistSelectedScenario,
  UploadedScenarioData,
} from '../utils/scenarioStorage';
import {
  Play,
  Upload,
  Download,
  Copy,
  Check,
  RotateCcw,
  Plus,
  Trash2,
  Sliders,
  Layers,
  List,
  MapPin,
  User,
  Package,
  Box,
  ShieldAlert,
  Navigation,
  FileCode,
  X,
  AlertTriangle,
  CheckCircle2,
  CloudSnow,
  CloudFog,
  Radio,
  Save,
  MousePointer,
  Hand,
  Building,
  Route,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

interface ConstructorPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

export const syncMissionsWithPoints = (
  missions: AmrScenario['missions'] | undefined,
  points: Record<string, any> | undefined
): NonNullable<AmrScenario['missions']> => {
  if (!missions || !points) return missions || [];
  return missions.map((m) => {
    const fromPt = m.from ? points[m.from] : null;
    const toPt = m.to ? points[m.to] : null;
    if (!fromPt && !toPt) return m;

    const oldPath: [number, number][] = m.reference_path || [];
    const fromX = fromPt ? fromPt.x : (oldPath[0]?.[0] ?? 0);
    const fromY = fromPt ? fromPt.y : (oldPath[0]?.[1] ?? 0);
    const toX = toPt ? toPt.x : (oldPath[oldPath.length - 1]?.[0] ?? fromX);
    const toY = toPt ? toPt.y : (oldPath[oldPath.length - 1]?.[1] ?? fromY);

    let newRefPath: [number, number][];
    if (oldPath.length <= 2) {
      newRefPath = [[fromX, fromY], [toX, toY]];
    } else {
      newRefPath = [[fromX, fromY], ...oldPath.slice(1, -1), [toX, toY]];
    }

    let len = 0;
    for (let k = 1; k < newRefPath.length; k++) {
      len += Math.hypot(newRefPath[k][0] - newRefPath[k - 1][0], newRefPath[k][1] - newRefPath[k - 1][1]);
    }

    return {
      ...m,
      reference_path: newRefPath,
      reference_length_m: Math.round(len * 10) / 10,
    };
  });
};

export const healDrivableMicrogaps = (
  drivablePolys: [number, number][][] | undefined,
  maxGap = 0.35
): [number, number][][] => {
  if (!drivablePolys || drivablePolys.length < 2) return drivablePolys || [];
  const res: [number, number][][] = drivablePolys.map((poly) =>
    poly.map(([x, y]) => [x, y] as [number, number])
  );
  const n = res.length;
  for (let i = 0; i < n; i++) {
    const p1 = res[i];
    if (p1.length !== 4) continue;
    const xs1 = p1.map((p) => p[0]);
    const ys1 = p1.map((p) => p[1]);
    const minx1 = Math.min(...xs1);
    const maxx1 = Math.max(...xs1);
    const miny1 = Math.min(...ys1);
    const maxy1 = Math.max(...ys1);

    for (let j = i + 1; j < n; j++) {
      const p2 = res[j];
      if (p2.length !== 4) continue;
      const xs2 = p2.map((p) => p[0]);
      const ys2 = p2.map((p) => p[1]);
      const minx2 = Math.min(...xs2);
      const maxx2 = Math.max(...xs2);
      const miny2 = Math.min(...ys2);
      const maxy2 = Math.max(...ys2);

      const xOverlap = Math.min(maxx1, maxx2) - Math.max(minx1, minx2);
      if (xOverlap > 0.5) {
        if (miny2 - maxy1 > 0 && miny2 - maxy1 <= maxGap) {
          const mid = Math.round(((maxy1 + miny2) / 2) * 100) / 100;
          for (let k = 0; k < 4; k++) {
            if (Math.abs(p1[k][1] - maxy1) < 1e-4) p1[k][1] = mid;
            if (Math.abs(p2[k][1] - miny2) < 1e-4) p2[k][1] = mid;
          }
        } else if (miny1 - maxy2 > 0 && miny1 - maxy2 <= maxGap) {
          const mid = Math.round(((maxy2 + miny1) / 2) * 100) / 100;
          for (let k = 0; k < 4; k++) {
            if (Math.abs(p2[k][1] - maxy2) < 1e-4) p2[k][1] = mid;
            if (Math.abs(p1[k][1] - miny1) < 1e-4) p1[k][1] = mid;
          }
        }
      }

      const yOverlap = Math.min(maxy1, maxy2) - Math.max(miny1, miny2);
      if (yOverlap > 0.5) {
        if (minx2 - maxx1 > 0 && minx2 - maxx1 <= maxGap) {
          const mid = Math.round(((maxx1 + minx2) / 2) * 100) / 100;
          for (let k = 0; k < 4; k++) {
            if (Math.abs(p1[k][0] - maxx1) < 1e-4) p1[k][0] = mid;
            if (Math.abs(p2[k][0] - minx2) < 1e-4) p2[k][0] = mid;
          }
        } else if (minx1 - maxx2 > 0 && minx1 - maxx2 <= maxGap) {
          const mid = Math.round(((maxx2 + minx1) / 2) * 100) / 100;
          for (let k = 0; k < 4; k++) {
            if (Math.abs(p2[k][0] - maxx2) < 1e-4) p2[k][0] = mid;
            if (Math.abs(p1[k][0] - minx1) < 1e-4) p1[k][0] = mid;
          }
        }
      }
    }
  }
  return res;
};

export const sanitizeScenario = (scenario: AmrScenario): AmrScenario => {
  const healedDrivable = healDrivableMicrogaps(scenario.map?.drivable);
  const syncedMissions = syncMissionsWithPoints(scenario.missions, scenario.map?.points);
  return {
    ...scenario,
    map: {
      ...scenario.map,
      drivable: healedDrivable,
    },
    missions: syncedMissions,
  };
};

export const ConstructorPage: React.FC<ConstructorPageProps> = ({
  onNavigate,
  onScenarioChange,
}) => {
  // Current active scenario state
  const [scenario, setScenario] = useState<AmrScenario>(() =>
    scenarioTemplates[0].createScenario()
  );

  // Selected template id in top selector
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('01_clear');

  // Active toolbar tool and selected entity
  const [activeTool, setActiveTool] = useState<ConstructorTool>('select');
  const [activeZoneType, setActiveZoneType] = useState<
    'speed_limit' | 'forbidden' | 'gnss_shadow' | 'people_area'
  >('speed_limit');
  const [selectedEntity, setSelectedEntity] = useState<SelectedEntity | null>(null);

  // Inspector sidebar tab and visibility
  const [sidebarTab, setSidebarTab] = useState<'params' | 'objects' | 'properties' | 'layers' | 'map'>('params');
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Clean map creation parameters
  const [cleanMapWidth, setCleanMapWidth] = useState(120);
  const [cleanMapHeight, setCleanMapHeight] = useState(100);
  const [cleanMapClearWalls, setCleanMapClearWalls] = useState(true);
  const [cleanMapAddBaseLane, setCleanMapAddBaseLane] = useState(true);

  // Map layer visibility
  const [layers, setLayers] = useState<ConstructorLayers>({
    robot: true,
    corridors: true,
    buildings: true,
    obstacles: true,
    pedestrians: true,
    zones: true,
    docks: true,
    grid: true,
  });

  // Weather & environment status
  const isSnowActive = Boolean(scenario.weather?.snow);
  const isFogActive = (scenario.events || []).some((ev) => ev.type === 'fog_bank');
  const isGnssActive = (scenario.events || []).some(
    (ev) => ev.type === 'gnss_outage' || ev.type === 'gnss_fault'
  );

  const toggleSnow = () => {
    setScenario((prev) => ({
      ...prev,
      weather: { ...prev.weather, snow: !prev.weather?.snow },
    }));
  };

  const toggleFog = () => {
    setScenario((prev) => {
      const current = prev.events || [];
      const hasFog = current.some((ev) => ev.type === 'fog_bank');
      const newEvents = hasFog
        ? current.filter((ev) => ev.type !== 'fog_bank')
        : [...current, { type: 'fog_bank', t1: 30.0, t2: 120.0 }];
      return { ...prev, events: newEvents };
    });
  };

  const toggleGnss = () => {
    setScenario((prev) => {
      const current = prev.events || [];
      const hasGnss = current.some(
        (ev) => ev.type === 'gnss_outage' || ev.type === 'gnss_fault'
      );
      const newEvents = hasGnss
        ? current.filter(
            (ev) => ev.type !== 'gnss_outage' && ev.type !== 'gnss_fault'
          )
        : [...current, { type: 'gnss_outage', t1: 40.0, t2: 100.0 }];
      return { ...prev, events: newEvents };
    });
  };

  // Rotation math & helpers
  const normalizeDeg = (deg: number) => {
    let d = Math.round(deg) % 360;
    if (d < 0) d += 360;
    return d;
  };

  const selectedObstacle = useMemo(() => {
    if (selectedEntity?.type === 'obstacle' && selectedEntity.index !== undefined) {
      return scenario.map_patches?.[selectedEntity.index] || null;
    }
    return null;
  }, [selectedEntity, scenario.map_patches]);

  const obstacleCurrentAngle = useMemo(() => {
    if (!selectedObstacle) return 0;
    if (selectedObstacle.heading !== undefined) return normalizeDeg(selectedObstacle.heading);
    const poly = selectedObstacle.polygon || [];
    if (poly.length >= 2) {
      return normalizeDeg(
        (Math.atan2(poly[1][1] - poly[0][1], poly[1][0] - poly[0][0]) * 180) / Math.PI
      );
    }
    return 0;
  }, [selectedObstacle]);

  const rotateSelectedObstacle = (deltaDeg: number) => {
    if (!selectedEntity || selectedEntity.type !== 'obstacle' || selectedEntity.index === undefined) return;
    const deltaRad = (deltaDeg * Math.PI) / 180;
    const cos = Math.cos(deltaRad);
    const sin = Math.sin(deltaRad);

    setScenario((prev) => {
      const patches = [...(prev.map_patches || [])];
      const target = patches[selectedEntity.index!];
      if (!target) return prev;
      const poly = target.polygon || [];
      const cx = poly.reduce((s, p) => s + p[0], 0) / (poly.length || 1);
      const cy = poly.reduce((s, p) => s + p[1], 0) / (poly.length || 1);
      const newPoly = poly.map(([px, py]) => {
        const rx = px - cx;
        const ry = py - cy;
        return [
          Math.round((cx + rx * cos - ry * sin) * 100) / 100,
          Math.round((cy + rx * sin + ry * cos) * 100) / 100,
        ] as [number, number];
      });
      const curHeading = target.heading !== undefined
        ? target.heading
        : poly.length >= 2
        ? Math.round((Math.atan2(poly[1][1] - poly[0][1], poly[1][0] - poly[0][0]) * 180) / Math.PI)
        : 0;
      const newHeading = normalizeDeg(curHeading + deltaDeg);
      patches[selectedEntity.index!] = {
        ...target,
        polygon: newPoly,
        heading: newHeading,
      };
      return { ...prev, map_patches: patches };
    });
  };

  const setObstacleAbsoluteAngle = (targetDeg: number) => {
    const delta = normalizeDeg(targetDeg) - normalizeDeg(obstacleCurrentAngle);
    rotateSelectedObstacle(delta);
  };

  const selectedPed = useMemo(() => {
    if (selectedEntity?.type === 'pedestrian' && selectedEntity.index !== undefined) {
      return scenario.pedestrians?.[selectedEntity.index] || null;
    }
    return null;
  }, [selectedEntity, scenario.pedestrians]);

  const pedestrianCurrentAngle = useMemo(() => {
    if (!selectedPed) return 0;
    if (selectedPed.heading !== undefined) return normalizeDeg(selectedPed.heading);
    const wps = selectedPed.waypoints || [];
    if (wps.length >= 2) {
      return normalizeDeg(
        (Math.atan2(wps[1][1] - wps[0][1], wps[1][0] - wps[0][0]) * 180) / Math.PI
      );
    }
    return 0;
  }, [selectedPed]);

  const rotateSelectedPedestrian = (deltaDeg: number) => {
    if (!selectedEntity || selectedEntity.type !== 'pedestrian' || selectedEntity.index === undefined) return;
    setScenario((prev) => {
      const peds = [...(prev.pedestrians || [])];
      const target = peds[selectedEntity.index!];
      if (!target) return prev;
      const wps = target.waypoints || [[0, 0], [0, 10]];
      const [x0, y0] = wps[0] || [0, 0];
      const [x1, y1] = wps[1] || [x0, y0 + 10];
      const dx = x1 - x0;
      const dy = y1 - y0;
      const dist = Math.max(2, Math.sqrt(dx * dx + dy * dy));
      const curHeading = target.heading !== undefined
        ? target.heading
        : Math.round((Math.atan2(dy, dx) * 180) / Math.PI);
      const newHeading = normalizeDeg(curHeading + deltaDeg);
      const rad = (newHeading * Math.PI) / 180;
      const newX1 = Math.round((x0 + dist * Math.cos(rad)) * 10) / 10;
      const newY1 = Math.round((y0 + dist * Math.sin(rad)) * 10) / 10;
      const newWps = [[x0, y0], [newX1, newY1], ...wps.slice(2)] as [number, number][];
      peds[selectedEntity.index!] = {
        ...target,
        waypoints: newWps,
        heading: newHeading,
      };
      return { ...prev, pedestrians: peds };
    });
  };

  const setPedestrianAbsoluteAngle = (targetDeg: number) => {
    const delta = normalizeDeg(targetDeg) - normalizeDeg(pedestrianCurrentAngle);
    rotateSelectedPedestrian(delta);
  };

  // Clean map creation handler
  const handleCreateCleanMap = (
    w = cleanMapWidth,
    h = cleanMapHeight,
    clearWalls = cleanMapClearWalls,
    addLane = cleanMapAddBaseLane
  ) => {
    const width = Math.max(20, Math.min(500, w));
    const height = Math.max(20, Math.min(500, h));
    const centerY = Math.round(height / 2);
    const laneWidth = 10;

    const baseDrivable = addLane
      ? [
          [
            [10, centerY - laneWidth / 2],
            [width - 10, centerY - laneWidth / 2],
            [width - 10, centerY + laneWidth / 2],
            [10, centerY + laneWidth / 2],
          ],
        ]
      : [];

    const newMap: any = {
      frame: 'x east, y north, meters; heading radians from +x counterclockwise',
      bounds: [0, 0, width, height],
      drivable: baseDrivable,
      buildings: clearWalls ? [] : scenario.map?.buildings || [],
      points: {
        dock_start: {
          x: 15,
          y: centerY,
          heading: 0,
          tol: 0.5,
          label: 'Стартовый док',
        },
        dock_end: {
          x: width - 15,
          y: centerY,
          heading: 0,
          tol: 0.5,
          label: 'Целевой док',
        },
      },
      zones: [],
      gates: [],
      crossing: [],
    };

    const newScenario: AmrScenario = {
      schema: 'amr-1.0',
      name: `custom_map_${width}x${height}`,
      description: `Пользовательская карта ${width}×${height}м с базовым проездом.`,
      dt: 0.1,
      duration_s: 300.0,
      hidden: false,
      provide_detections: false,
      weather: {
        snow: false,
      },
      events: [],
      start: {
        x: 15,
        y: centerY,
        theta: 0.0,
      },
      missions: [
        {
          id: 'm1',
          from: 'dock_start',
          to: 'dock_end',
          deadline_s: 180.0,
          reference_length_m: width - 30,
          reference_path: [
            [15, centerY],
            [width - 15, centerY],
          ],
        },
      ],
      map: newMap,
      map_patches: [],
      pedestrians: [],
    };

    setScenario(newScenario);
    setSelectedEntity(null);
    showToast(`Чистая карта ${width}×${height}м создана`);

    const scName = newScenario.name;
    const mapData: MapData = {
      bounds: newMap.bounds,
      drivable: newMap.drivable,
      buildings: newMap.buildings,
      zones: newMap.zones,
      gates: newMap.gates,
      crossing: newMap.crossing,
      points: newMap.points,
    };
    const uploadedData: UploadedScenarioData = {
      id: scName,
      name: scName,
      fileName: `${scName}.json`,
      fileType: 'scenario',
      mapData,
      scenarioJson: newScenario,
      missionsViewModel: {
        scenario: scName,
        summary: {
          completed: 1,
          total: 1,
          deliveryScore: 40.0,
          maxDeliveryScore: 40.0,
          efficiencyScore: 15.0,
          maxEfficiencyScore: 15.0,
        },
        missions: [
          {
            id: 'm1',
            from: 'dock_start',
            to: 'dock_end',
            fromLabel: 'Стартовый док',
            toLabel: 'Целевой док',
            status: 'DELIVERED',
            t_start: 0,
            t_end: 180.0,
            t_arrival: 120.0,
            hold_duration_s: 3.0,
            hold_ticks: 30,
            max_hold_dist: 0.1,
            tol: 0.5,
            deadline_s: 180.0,
            safety_margin_s: 54.0,
            reference_length_m: width - 30,
            actual_time_s: 120.0,
          },
        ],
      },
      uploadedAt: Date.now(),
    };
    saveUploadedScenario(uploadedData);
    persistSelectedScenario(scName);
    onScenarioChange?.(scName);
    apiClient.saveScenario(newScenario.name, newScenario).catch(() => {});
  };

  // Modals state
  const [showImportModal, setShowImportModal] = useState(false);
  const [showJsonModal, setShowJsonModal] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');
  const [importValidationResult, setImportValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);

  // Toast notification feedback
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [copiedFeedback, setCopiedFeedback] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((cur) => (cur === msg ? null : cur));
    }, 3200);
  };

  // Switch template
  const handleSelectTemplate = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const tmpl = scenarioTemplates.find((t) => t.id === templateId);
    if (tmpl) {
      const newSc = tmpl.createScenario();
      setScenario(newSc);
      setSelectedEntity(null);
      showToast(`Загружен шаблон: ${tmpl.name}`);
    }
  };

  // Reset to current template
  const handleReset = () => {
    handleSelectTemplate(selectedTemplateId);
  };

  // Save to scenarioStorage
  const handleSaveToStorage = async () => {
    const cleanScenario = sanitizeScenario(scenario);
    setScenario(cleanScenario);
    const scName = cleanScenario.name.trim() || 'custom_scenario';
    const mapData: MapData = {
      bounds: cleanScenario.map.bounds || [0, 0, 250, 200],
      drivable: cleanScenario.map.drivable || [],
      buildings: cleanScenario.map.buildings || [],
      zones: cleanScenario.map.zones || [],
      gates: cleanScenario.map.gates || [],
      crossing: cleanScenario.map.crossing || [],
      points: cleanScenario.map.points || {},
    };

    const missionsTotal = Array.isArray(cleanScenario.missions) ? cleanScenario.missions.length : 0;
    const missionsList = Array.isArray(cleanScenario.missions)
      ? cleanScenario.missions.map((m, idx) => ({
          id: m.id || `m${idx + 1}`,
          from: m.from || 'dock_start',
          to: m.to || 'dock_end',
          fromLabel: m.from || 'Стартовая точка',
          toLabel: m.to || 'Целевая точка',
          status: 'DELIVERED' as const,
          t_start: 0,
          t_end: m.deadline_s || 120,
          t_arrival: (m.deadline_s || 120) * 0.7,
          hold_duration_s: 3.0,
          hold_ticks: 30,
          max_hold_dist: 0.1,
          tol: 0.2,
          deadline_s: m.deadline_s || 120,
          safety_margin_s: (m.deadline_s || 120) * 0.3,
          reference_length_m: m.reference_length_m || 50,
          actual_time_s: (m.deadline_s || 120) * 0.7,
        }))
      : [];

    const uploadedData: UploadedScenarioData = {
      id: scName,
      name: scName,
      fileName: `${scName}.json`,
      fileType: 'scenario',
      mapData,
      scenarioJson: cleanScenario,
      missionsViewModel: {
        scenario: scName,
        summary: {
          completed: missionsTotal,
          total: missionsTotal,
          deliveryScore: 40.0,
          maxDeliveryScore: 40.0,
          efficiencyScore: 15.0,
          maxEfficiencyScore: 15.0,
        },
        missions: missionsList,
      },
      uploadedAt: Date.now(),
    };

    saveUploadedScenario(uploadedData);
    persistSelectedScenario(scName);
    onScenarioChange?.(scName);
    try {
      await apiClient.saveScenario(scName, cleanScenario);
    } catch (err) {
      console.warn('[ConstructorPage] Auto-save before simulation failed:', err);
    }
    showToast(`Сценарий "${scName}" сохранен`);
  };

  // Run in simulator
  const handleLaunchInSimulator = () => {
    const cleanScenario = sanitizeScenario(scenario);
    setScenario(cleanScenario);
    const scName = cleanScenario.name.trim() || 'custom_scenario';
    handleSaveToStorage();
    onNavigate('runner', { scenario: scName });
  };

  // Copy scenario JSON to clipboard
  const handleCopyJson = async () => {
    try {
      const cleanScenario = sanitizeScenario(scenario);
      setScenario(cleanScenario);
      const formatted = JSON.stringify(cleanScenario, null, 2);
      await navigator.clipboard.writeText(formatted);
      setCopiedFeedback(true);
      showToast('Сценарий скопирован в буфер обмена');
      setTimeout(() => setCopiedFeedback(false), 2000);
    } catch {
      showToast('Не удалось скопировать JSON в буфер');
    }
  };

  // Download scenario JSON file
  const handleDownloadJson = () => {
    const cleanScenario = sanitizeScenario(scenario);
    setScenario(cleanScenario);
    const fileName = `${cleanScenario.name || 'scenario'}.json`;
    const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(
      JSON.stringify(cleanScenario, null, 2)
    )}`;
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', jsonString);
    downloadAnchor.setAttribute('download', fileName);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    showToast(`Файл "${fileName}" загружен`);
  };

  // Handle Import validation & loading
  const handleValidateAndLoadImport = (rawText: string) => {
    try {
      const parsed = JSON.parse(rawText);
      const res = validateScenario(parsed);
      setImportValidationResult(res);

      if (res.valid && res.scenario) {
        setScenario(res.scenario);
        setSelectedEntity(null);
        setShowImportModal(false);
        setImportJsonText('');
        setImportValidationResult(null);
        showToast(`Сценарий "${res.scenario.name}" успешно импортирован!`);
      }
    } catch (err: any) {
      setImportValidationResult({
        valid: false,
        errors: [`Ошибка синтаксиса JSON: ${err?.message || 'Некорректный синтаксис'}`],
        warnings: [],
      });
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setImportJsonText(text);
      handleValidateAndLoadImport(text);
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleDropFile = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setImportJsonText(text);
      handleValidateAndLoadImport(text);
    };
    reader.readAsText(file);
  };

  // Delete selected entity
  const handleDeleteSelected = () => {
    if (!selectedEntity) return;

    if (selectedEntity.type === 'obstacle' && selectedEntity.index !== undefined) {
      setScenario((prev) => {
        const patches = [...(prev.map_patches || [])];
        patches.splice(selectedEntity.index!, 1);
        return { ...prev, map_patches: patches };
      });
      setSelectedEntity(null);
      showToast('Препятствие удалено');
    } else if (selectedEntity.type === 'pedestrian' && selectedEntity.index !== undefined) {
      setScenario((prev) => {
        const peds = [...(prev.pedestrians || [])];
        peds.splice(selectedEntity.index!, 1);
        return { ...prev, pedestrians: peds };
      });
      setSelectedEntity(null);
      showToast('Пешеход удален');
    } else if (selectedEntity.type === 'zone' && selectedEntity.index !== undefined) {
      setScenario((prev) => {
        const zones = [...(prev.map?.zones || [])];
        zones.splice(selectedEntity.index!, 1);
        return { ...prev, map: { ...prev.map, zones } };
      });
      setSelectedEntity(null);
      showToast('Зона удалена');
    } else if (selectedEntity.type === 'dock' && selectedEntity.id) {
      setScenario((prev) => {
        const pts = { ...(prev.map?.points || {}) };
        delete pts[selectedEntity.id!];
        return { ...prev, map: { ...prev.map, points: pts } };
      });
      setSelectedEntity(null);
      showToast('Док удален');
    }
  };

  // Auto-switch to properties tab when entity is selected
  useEffect(() => {
    if (selectedEntity) {
      setSidebarTab('properties');
    }
  }, [selectedEntity]);

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full min-w-[1240px] gap-4">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-16 right-6 z-50 bg-slate-900 text-white text-xs font-medium px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Application Toolbar */}
      <div className="bg-white rounded-xl border border-slate-200 p-3.5 px-5 flex flex-wrap items-center justify-between gap-4 z-20 shadow-sm">
        {/* Left: Title & Preset Selector */}
        <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold text-slate-900 tracking-tight">
                Конструктор сценариев
              </h1>
            </div>

          <div className="h-6 w-px bg-slate-200 mx-1 hidden md:block" />

          {/* Template Preset Selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium hidden lg:inline">Шаблон:</span>
            <select
              value={selectedTemplateId}
              onChange={(e) => handleSelectTemplate(e.target.value)}
              className="bg-slate-50 border border-slate-200 text-slate-800 text-xs font-semibold rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
            >
              {scenarioTemplates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <button
              onClick={handleReset}
              className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
              title="Сбросить к исходному шаблону"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setSidebarTab('map')}
              className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-2.5 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200 ml-1"
              title="Создать чистую карту с нуля"
            >
              <Plus className="w-3.5 h-3.5 text-blue-600" />
              <span>Чистая карта</span>
            </button>
          </div>

          <div className="h-6 w-px bg-slate-200 mx-1 hidden md:block" />

          {/* Compact Weather & Environment Toggles */}
          <div className="flex items-center gap-1.5 bg-slate-100/80 p-1 rounded-lg border border-slate-200">
            {/* Snow Toggle */}
            <button
              type="button"
              role="checkbox"
              aria-checked={isSnowActive}
              onClick={toggleSnow}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-md transition-colors ${
                isSnowActive
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'bg-white text-slate-600 hover:text-slate-900 border border-slate-200'
              }`}
              title={isSnowActive ? 'Снег включен (клик для отключения)' : 'Включить снег'}
            >
              <input
                type="checkbox"
                readOnly
                checked={isSnowActive}
                className="sr-only"
                tabIndex={-1}
              />
              <CloudSnow className="w-3.5 h-3.5" />
              <span>Снег</span>
            </button>

            {/* Fog Toggle */}
            <button
              type="button"
              onClick={toggleFog}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-md transition-colors ${
                isFogActive
                  ? 'bg-amber-500 text-white shadow-xs'
                  : 'bg-white text-slate-600 hover:text-slate-900 border border-slate-200'
              }`}
              title={isFogActive ? 'Туман активен (клик для отключения)' : 'Включить туман'}
            >
              <CloudFog className="w-3.5 h-3.5" />
              <span>Туман</span>
            </button>

            {/* GNSS Outage Toggle */}
            <button
              type="button"
              onClick={toggleGnss}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-md transition-colors ${
                isGnssActive
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'bg-white text-slate-600 hover:text-slate-900 border border-slate-200'
              }`}
              title={isGnssActive ? 'Сбой ГНСС активен (клик для отключения)' : 'Включить сбой ГНСС'}
            >
              <Radio className="w-3.5 h-3.5" />
              <span>ГНСС</span>
            </button>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          {/* Import JSON */}
          <button
            onClick={() => setShowImportModal(true)}
            className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200"
            title="Импортировать готовый JSON файл"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Импорт</span>
          </button>

          {/* View/Edit Raw JSON */}
          <button
            onClick={() => setShowJsonModal(true)}
            className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200"
            title="Просмотр и редактирование кода JSON"
          >
            <FileCode className="w-3.5 h-3.5" />
            <span>JSON</span>
          </button>

          {/* Copy to Clipboard */}
          <button
            onClick={handleCopyJson}
            className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200"
            title="Скопировать сценарий в буфер обмена"
          >
            {copiedFeedback ? (
              <Check className="w-3.5 h-3.5 text-emerald-600" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            <span>{copiedFeedback ? 'Скопировано!' : 'Копировать'}</span>
          </button>

          {/* Download File */}
          <button
            onClick={handleDownloadJson}
            className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200"
            title="Скачать сценарий в формате .json"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Экспорт</span>
          </button>

          {/* Save to Storage */}
          <button
            onClick={handleSaveToStorage}
            className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors border border-slate-200"
            title="Сохранить в сценарии для использования на других вкладках"
          >
            <Save className="w-3.5 h-3.5 text-slate-600" />
            <span>Сохранить</span>
          </button>

          {/* Launch in Simulator */}
          <button
            onClick={handleLaunchInSimulator}
            className="bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3.5 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors shadow-sm"
            title="Передать сценарий в симулятор и запустить"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Запустить в симуляторе</span>
          </button>
        </div>
      </div>

      {/* Main Workspace: Left Vertical Tabs + Inspector & Center Canvas & Right Element Sidebar */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm flex-1 flex overflow-hidden min-h-[640px] relative">
        {/* Left Vertical Tab Strip (compact icons) */}
        <div className="w-12 bg-slate-50 border-r border-slate-200 flex flex-col py-3 px-1.5 space-y-1.5 z-20 flex-shrink-0 select-none shadow-xs">
          {[
            { id: 'params', label: 'Параметры', icon: Sliders },
            { id: 'objects', label: 'Объекты', icon: List },
            { id: 'properties', label: 'Свойства', icon: Box },
            { id: 'layers', label: 'Слои', icon: Layers },
            { id: 'map', label: 'Карта', icon: MapPin },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = isSidebarOpen && sidebarTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => {
                  if (isSidebarOpen && sidebarTab === tab.id) {
                    setIsSidebarOpen(false);
                  } else {
                    setSidebarTab(tab.id as any);
                    setIsSidebarOpen(true);
                  }
                }}
                className={`w-9 h-9 mx-auto flex items-center justify-center rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
                title={tab.label}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
              </button>
            );
          })}

          {/* Toggle sidebar button at bottom of tab strip */}
          <button
            onClick={() => setIsSidebarOpen((prev) => !prev)}
            className="w-9 h-9 mx-auto flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-800 hover:bg-slate-100 transition-colors mt-auto"
            title={isSidebarOpen ? 'Свернуть панель' : 'Развернуть панель'}
          >
            {isSidebarOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        </div>

        {/* Left Inspector Sidebar (collapsible) */}
        {isSidebarOpen && (
          <aside className="w-80 lg:w-96 bg-white border-r border-slate-200 flex flex-col z-10 shadow-sm overflow-hidden flex-shrink-0">
            {/* Header showing current tab name and collapse button */}
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 bg-slate-50/70">
              <span className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                {sidebarTab === 'params' && 'Параметры сценария'}
                {sidebarTab === 'objects' && 'Объекты на карте'}
                {sidebarTab === 'properties' && 'Свойства элемента'}
                {sidebarTab === 'layers' && 'Слои отображения'}
                {sidebarTab === 'map' && 'Конструктор карты'}
              </span>
              <button
                onClick={() => setIsSidebarOpen(false)}
                className="p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 rounded-md transition-colors"
                title="Свернуть панель"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>

          {/* Sidebar Tab Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* 1. TAB: PARAMS */}
            {sidebarTab === 'params' && (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-700">Имя сценария:</label>
                  <input
                    type="text"
                    value={scenario.name}
                    onChange={(e) =>
                      setScenario((prev) => ({ ...prev, name: e.target.value }))
                    }
                    className="w-full bg-slate-50 border border-slate-200 text-slate-900 text-xs font-mono rounded-lg px-3 py-2 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    placeholder="my_scenario"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-700">Описание сценария:</label>
                  <textarea
                    rows={3}
                    value={scenario.description}
                    onChange={(e) =>
                      setScenario((prev) => ({ ...prev, description: e.target.value }))
                    }
                    className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 focus:ring-1 focus:ring-blue-500 focus:outline-none resize-none"
                    placeholder="Описание условий теста, погоды и маршрута..."
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-700">Шаг dt (с):</label>
                    <input
                      type="number"
                      step="0.05"
                      min="0.01"
                      value={scenario.dt}
                      onChange={(e) =>
                        setScenario((prev) => ({
                          ...prev,
                          dt: parseFloat(e.target.value) || 0.1,
                        }))
                      }
                      className="w-full bg-slate-50 border border-slate-200 text-slate-900 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-700">Длительность (с):</label>
                    <input
                      type="number"
                      step="10"
                      min="10"
                      value={scenario.duration_s}
                      onChange={(e) =>
                        setScenario((prev) => ({
                          ...prev,
                          duration_s: parseFloat(e.target.value) || 400.0,
                        }))
                      }
                      className="w-full bg-slate-50 border border-slate-200 text-slate-900 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                </div>

                {/* Weather & Environment Info */}
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5">
                  <span className="text-xs font-bold text-slate-800">Погода и помехи</span>
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    Управление снегом, туманом и сбоями ГНСС вынесено в компактные кнопки в верхней панели ([Снег], [Туман], [ГНСС]).
                  </p>
                </div>
              </div>
            )}

            {/* 2. TAB: OBJECTS */}
            {sidebarTab === 'objects' && (
              <div className="space-y-4">
                {/* Robot item */}
                <div
                  onClick={() => setSelectedEntity({ type: 'robot' })}
                  className={`p-3 rounded-xl border cursor-pointer transition-all ${
                    selectedEntity?.type === 'robot'
                      ? 'bg-blue-50 border-blue-400 shadow-xs'
                      : 'bg-white border-slate-200 hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold">
                        R
                      </div>
                      <div>
                        <div className="text-xs font-bold text-slate-900">Робот (АТЛАНТ-250)</div>
                        <div className="text-[11px] text-slate-500 font-mono">
                          X: {scenario.start.x.toFixed(1)} м, Y: {scenario.start.y.toFixed(1)} м, θ:{' '}
                          {scenario.start.theta.toFixed(2)} рад
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Docks section */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                    <div className="flex items-center gap-1.5">
                      <MapPin className="w-3.5 h-3.5 text-blue-600" />
                      <span>Док-станции и ворота ({Object.keys(scenario.map?.points || {}).length})</span>
                    </div>
                    <button
                      onClick={() => setActiveTool('add_dock')}
                      className="text-blue-600 text-[11px] hover:underline flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Добавить
                    </button>
                  </div>
                  <div className="space-y-1.5">
                    {Object.entries(scenario.map?.points || {}).map(([id, pt]) => (
                      <div
                        key={id}
                        onClick={() => setSelectedEntity({ type: 'dock', id })}
                        className={`p-2.5 rounded-lg border cursor-pointer flex items-center justify-between transition-colors ${
                          selectedEntity?.type === 'dock' && selectedEntity.id === id
                            ? 'bg-blue-50 border-blue-400'
                            : 'bg-white border-slate-200 hover:border-slate-300'
                        }`}
                      >
                        <div>
                          <div className="text-xs font-semibold text-slate-800">{pt.label || id}</div>
                          <div className="text-[10px] text-slate-400 font-mono">
                            X: {pt.x.toFixed(1)}, Y: {pt.y.toFixed(1)}, допуск: {pt.tol ?? 0.2} м
                          </div>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedEntity({ type: 'dock', id });
                            handleDeleteSelected();
                          }}
                          className="p-1 text-slate-400 hover:text-red-600 rounded"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Obstacles section */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                    <div className="flex items-center gap-1.5">
                      <Package className="w-3.5 h-3.5 text-amber-600" />
                      <span>Препятствия ({scenario.map_patches?.length || 0})</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setActiveTool('add_pallet')}
                        className="text-amber-700 bg-amber-50 hover:bg-amber-100 text-[10px] font-semibold px-2 py-0.5 rounded border border-amber-200"
                      >
                        + Поддон
                      </button>
                      <button
                        onClick={() => setActiveTool('add_container')}
                        className="text-blue-700 bg-blue-50 hover:bg-blue-100 text-[10px] font-semibold px-2 py-0.5 rounded border border-blue-200"
                      >
                        + Контейнер
                      </button>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    {(!scenario.map_patches || scenario.map_patches.length === 0) ? (
                      <div className="text-[11px] text-slate-400 italic p-2">Нет препятствий</div>
                    ) : (
                      scenario.map_patches.map((patch, idx) => (
                        <div
                          key={patch.id || idx}
                          onClick={() => setSelectedEntity({ type: 'obstacle', index: idx, id: patch.id })}
                          className={`p-2.5 rounded-lg border cursor-pointer flex items-center justify-between transition-colors ${
                            selectedEntity?.type === 'obstacle' && selectedEntity.index === idx
                              ? 'bg-blue-50 border-blue-400'
                              : 'bg-white border-slate-200 hover:border-slate-300'
                          }`}
                        >
                          <div>
                            <div className="text-xs font-semibold text-slate-800">{patch.id}</div>
                            <div className="text-[10px] text-slate-400 font-mono">
                              {patch.polygon.length} вершин, op: {patch.op}
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEntity({ type: 'obstacle', index: idx, id: patch.id });
                              handleDeleteSelected();
                            }}
                            className="p-1 text-slate-400 hover:text-red-600 rounded"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Pedestrians section */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                    <div className="flex items-center gap-1.5">
                      <User className="w-3.5 h-3.5 text-orange-600" />
                      <span>Пешеходы ({scenario.pedestrians?.length || 0})</span>
                    </div>
                    <button
                      onClick={() => setActiveTool('add_pedestrian')}
                      className="text-blue-600 text-[11px] hover:underline flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Добавить
                    </button>
                  </div>
                  <div className="space-y-1.5">
                    {(!scenario.pedestrians || scenario.pedestrians.length === 0) ? (
                      <div className="text-[11px] text-slate-400 italic p-2">Нет пешеходов</div>
                    ) : (
                      scenario.pedestrians.map((ped, idx) => (
                        <div
                          key={ped.id || idx}
                          onClick={() => setSelectedEntity({ type: 'pedestrian', index: idx, id: ped.id })}
                          className={`p-2.5 rounded-lg border cursor-pointer flex items-center justify-between transition-colors ${
                            selectedEntity?.type === 'pedestrian' && selectedEntity.index === idx
                              ? 'bg-blue-50 border-blue-400'
                              : 'bg-white border-slate-200 hover:border-slate-300'
                          }`}
                        >
                          <div>
                            <div className="text-xs font-semibold text-slate-800">
                              {ped.id} ({ped.speed} м/с)
                            </div>
                            <div className="text-[10px] text-slate-400 font-mono">
                              Точек: {ped.waypoints.length}, t_start: {ped.t_start} с
                              {ped.inattentive ? ', невнимателен' : ''}
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEntity({ type: 'pedestrian', index: idx, id: ped.id });
                              handleDeleteSelected();
                            }}
                            className="p-1 text-slate-400 hover:text-red-600 rounded"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Zones section */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                    <div className="flex items-center gap-1.5">
                      <ShieldAlert className="w-3.5 h-3.5 text-purple-600" />
                      <span>Зоны и ограничения ({scenario.map?.zones?.length || 0})</span>
                    </div>
                    <button
                      onClick={() => setActiveTool('add_zone')}
                      className="text-blue-600 text-[11px] hover:underline flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Добавить
                    </button>
                  </div>
                  <div className="space-y-1.5">
                    {(!scenario.map?.zones || scenario.map.zones.length === 0) ? (
                      <div className="text-[11px] text-slate-400 italic p-2">Нет зон</div>
                    ) : (
                      scenario.map.zones.map((zone, idx) => (
                        <div
                          key={zone.id || idx}
                          onClick={() => setSelectedEntity({ type: 'zone', index: idx, id: zone.id })}
                          className={`p-2.5 rounded-lg border cursor-pointer flex items-center justify-between transition-colors ${
                            selectedEntity?.type === 'zone' && selectedEntity.index === idx
                              ? 'bg-blue-50 border-blue-400'
                              : 'bg-white border-slate-200 hover:border-slate-300'
                          }`}
                        >
                          <div>
                            <div className="text-xs font-semibold text-slate-800">
                              {zone.id} ({zone.type})
                            </div>
                            <div className="text-[10px] text-slate-400 font-mono">
                              {zone.type === 'speed_limit' && `V_max: ${zone.v_max} м/с, `}
                              {zone.polygon.length} вершин
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedEntity({ type: 'zone', index: idx, id: zone.id });
                              handleDeleteSelected();
                            }}
                            className="p-1 text-slate-400 hover:text-red-600 rounded"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* 3. TAB: PROPERTIES */}
            {sidebarTab === 'properties' && (
              <div>
                {!selectedEntity ? (
                  <div className="text-center py-12 px-4 space-y-2">
                    <Box className="w-8 h-8 text-slate-300 mx-auto" />
                    <p className="text-xs font-semibold text-slate-600">Элемент не выбран</p>
                    <p className="text-[11px] text-slate-400">
                      Кликните на объект на карте или выберите его во вкладке «Объекты» для настройки параметров.
                    </p>
                  </div>
                ) : selectedEntity.type === 'robot' ? (
                  /* ROBOT PROPERTIES */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold text-slate-800">Робот: Позиция старта</span>
                      <span className="text-[10px] bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded font-mono font-semibold">
                        АТЛАНТ-250
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">X (м):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={scenario.start.x}
                          onChange={(e) =>
                            setScenario((prev) => ({
                              ...prev,
                              start: { ...prev.start, x: parseFloat(e.target.value) || 0 },
                            }))
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Y (м):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={scenario.start.y}
                          onChange={(e) =>
                            setScenario((prev) => ({
                              ...prev,
                              start: { ...prev.start, y: parseFloat(e.target.value) || 0 },
                            }))
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between items-center text-[11px] font-semibold text-slate-600 mb-1">
                        <span>Угол ориентации θ (рад):</span>
                        <span className="font-mono text-slate-900">{scenario.start.theta.toFixed(2)} рад ({(scenario.start.theta * 180 / Math.PI).toFixed(0)}°)</span>
                      </div>
                      <input
                        type="range"
                        min="-3.14"
                        max="3.14"
                        step="0.05"
                        value={scenario.start.theta}
                        onChange={(e) =>
                          setScenario((prev) => ({
                            ...prev,
                            start: { ...prev.start, theta: parseFloat(e.target.value) || 0 },
                          }))
                        }
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                    </div>
                  </div>
                ) : selectedEntity.type === 'obstacle' && selectedEntity.index !== undefined ? (
                  /* OBSTACLE PROPERTIES */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold text-slate-800">Препятствие</span>
                      <button
                        onClick={handleDeleteSelected}
                        className="text-red-600 hover:text-red-700 text-xs flex items-center gap-1 font-semibold"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Удалить
                      </button>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-slate-600">Идентификатор (ID):</label>
                      <input
                        type="text"
                        value={scenario.map_patches?.[selectedEntity.index]?.id || ''}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const patches = [...(prev.map_patches || [])];
                            if (patches[selectedEntity.index!]) {
                              patches[selectedEntity.index!] = {
                                ...patches[selectedEntity.index!],
                                id: e.target.value,
                              };
                            }
                            return { ...prev, map_patches: patches };
                          })
                        }
                        className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                      />
                    </div>

                    {/* Obstacle Rotation Controls */}
                    <div className="space-y-2 p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-slate-700">Угол поворота:</span>
                        <span className="font-mono font-bold text-slate-900 text-xs">
                          {obstacleCurrentAngle}°
                        </span>
                      </div>

                      <input
                        type="range"
                        min="0"
                        max="360"
                        step="5"
                        value={obstacleCurrentAngle}
                        onChange={(e) => setObstacleAbsoluteAngle(parseInt(e.target.value) || 0)}
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />

                      <div className="flex items-center gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => rotateSelectedObstacle(45)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          +45°
                        </button>
                        <button
                          type="button"
                          onClick={() => rotateSelectedObstacle(90)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          +90°
                        </button>
                        <button
                          type="button"
                          onClick={() => rotateSelectedObstacle(-90)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          -90°
                        </button>
                      </div>
                    </div>

                    <div className="space-y-1">
                      <span className="text-[11px] font-semibold text-slate-600">Координаты вершин полигона:</span>
                      <div className="space-y-1 max-h-48 overflow-y-auto pr-1">
                        {scenario.map_patches?.[selectedEntity.index]?.polygon.map(([px, py], pIdx) => (
                          <div key={pIdx} className="flex items-center gap-2 text-xs font-mono">
                            <span className="text-slate-400 w-4">{pIdx + 1}.</span>
                            <input
                              type="number"
                              step="0.1"
                              value={px}
                              onChange={(e) =>
                                setScenario((prev) => {
                                  const patches = [...(prev.map_patches || [])];
                                  const poly = [...patches[selectedEntity.index!].polygon];
                                  poly[pIdx] = [parseFloat(e.target.value) || 0, poly[pIdx][1]];
                                  patches[selectedEntity.index!] = { ...patches[selectedEntity.index!], polygon: poly };
                                  return { ...prev, map_patches: patches };
                                })
                              }
                              className="w-20 bg-slate-50 border border-slate-200 rounded px-1.5 py-1 text-center"
                            />
                            <input
                              type="number"
                              step="0.1"
                              value={py}
                              onChange={(e) =>
                                setScenario((prev) => {
                                  const patches = [...(prev.map_patches || [])];
                                  const poly = [...patches[selectedEntity.index!].polygon];
                                  poly[pIdx] = [poly[pIdx][0], parseFloat(e.target.value) || 0];
                                  patches[selectedEntity.index!] = { ...patches[selectedEntity.index!], polygon: poly };
                                  return { ...prev, map_patches: patches };
                                })
                              }
                              className="w-20 bg-slate-50 border border-slate-200 rounded px-1.5 py-1 text-center"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : selectedEntity.type === 'pedestrian' && selectedEntity.index !== undefined ? (
                  /* PEDESTRIAN PROPERTIES */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold text-slate-800">Пешеход</span>
                      <button
                        onClick={handleDeleteSelected}
                        className="text-red-600 hover:text-red-700 text-xs flex items-center gap-1 font-semibold"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Удалить
                      </button>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-slate-600">ID пешехода:</label>
                      <input
                        type="text"
                        value={scenario.pedestrians?.[selectedEntity.index]?.id || ''}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const peds = [...(prev.pedestrians || [])];
                            if (peds[selectedEntity.index!]) {
                              peds[selectedEntity.index!] = {
                                ...peds[selectedEntity.index!],
                                id: e.target.value,
                              };
                            }
                            return { ...prev, pedestrians: peds };
                          })
                        }
                        className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                      />
                    </div>

                    {/* Pedestrian Rotation Controls */}
                    <div className="space-y-2 p-3 bg-slate-50 rounded-xl border border-slate-200">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-slate-700">Угол направления:</span>
                        <span className="font-mono font-bold text-slate-900 text-xs">
                          {pedestrianCurrentAngle}°
                        </span>
                      </div>

                      <input
                        type="range"
                        min="0"
                        max="360"
                        step="5"
                        value={pedestrianCurrentAngle}
                        onChange={(e) => setPedestrianAbsoluteAngle(parseInt(e.target.value) || 0)}
                        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />

                      <div className="flex items-center gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => rotateSelectedPedestrian(45)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          +45°
                        </button>
                        <button
                          type="button"
                          onClick={() => rotateSelectedPedestrian(90)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          +90°
                        </button>
                        <button
                          type="button"
                          onClick={() => rotateSelectedPedestrian(-90)}
                          className="flex-1 bg-white hover:bg-slate-100 text-slate-700 border border-slate-200 text-xs font-semibold py-1 rounded-md transition-colors"
                        >
                          -90°
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Скорость (м/с):</label>
                        <input
                          type="number"
                          step="0.1"
                          min="0.1"
                          max="3.0"
                          value={scenario.pedestrians?.[selectedEntity.index]?.speed || 1.0}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const peds = [...(prev.pedestrians || [])];
                              if (peds[selectedEntity.index!]) {
                                peds[selectedEntity.index!] = {
                                  ...peds[selectedEntity.index!],
                                  speed: parseFloat(e.target.value) || 1.0,
                                };
                              }
                              return { ...prev, pedestrians: peds };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Старт t (с):</label>
                        <input
                          type="number"
                          step="5"
                          min="0"
                          value={scenario.pedestrians?.[selectedEntity.index]?.t_start || 0}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const peds = [...(prev.pedestrians || [])];
                              if (peds[selectedEntity.index!]) {
                                peds[selectedEntity.index!] = {
                                  ...peds[selectedEntity.index!],
                                  t_start: parseFloat(e.target.value) || 0,
                                };
                              }
                              return { ...prev, pedestrians: peds };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg border border-slate-200">
                      <span className="text-xs text-slate-700 font-semibold">Невнимательный пешеход</span>
                      <input
                        type="checkbox"
                        checked={Boolean(scenario.pedestrians?.[selectedEntity.index]?.inattentive)}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const peds = [...(prev.pedestrians || [])];
                            if (peds[selectedEntity.index!]) {
                              peds[selectedEntity.index!] = {
                                ...peds[selectedEntity.index!],
                                inattentive: e.target.checked,
                              };
                            }
                            return { ...prev, pedestrians: peds };
                          })
                        }
                        className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                      />
                    </div>

                    <div className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg border border-slate-200">
                      <span className="text-xs text-slate-700 font-semibold">Зацикленный маршрут (loop)</span>
                      <input
                        type="checkbox"
                        checked={Boolean(scenario.pedestrians?.[selectedEntity.index]?.loop)}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const peds = [...(prev.pedestrians || [])];
                            if (peds[selectedEntity.index!]) {
                              peds[selectedEntity.index!] = {
                                ...peds[selectedEntity.index!],
                                loop: e.target.checked,
                              };
                            }
                            return { ...prev, pedestrians: peds };
                          })
                        }
                        className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                      />
                    </div>
                  </div>
                ) : selectedEntity.type === 'zone' && selectedEntity.index !== undefined ? (
                  /* ZONE PROPERTIES */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold text-slate-800">Зона ограничений</span>
                      <button
                        onClick={handleDeleteSelected}
                        className="text-red-600 hover:text-red-700 text-xs flex items-center gap-1 font-semibold"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Удалить
                      </button>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-slate-600">ID зоны:</label>
                      <input
                        type="text"
                        value={scenario.map?.zones?.[selectedEntity.index]?.id || ''}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const zones = [...(prev.map?.zones || [])];
                            if (zones[selectedEntity.index!]) {
                              zones[selectedEntity.index!] = {
                                ...zones[selectedEntity.index!],
                                id: e.target.value,
                              };
                            }
                            return { ...prev, map: { ...prev.map, zones } };
                          })
                        }
                        className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-slate-600">Тип зоны:</label>
                      <select
                        value={scenario.map?.zones?.[selectedEntity.index]?.type || 'speed_limit'}
                        onChange={(e) =>
                          setScenario((prev) => {
                            const zones = [...(prev.map?.zones || [])];
                            if (zones[selectedEntity.index!]) {
                              zones[selectedEntity.index!] = {
                                ...zones[selectedEntity.index!],
                                type: e.target.value,
                              };
                            }
                            return { ...prev, map: { ...prev.map, zones } };
                          })
                        }
                        className="w-full bg-slate-50 border border-slate-200 text-xs font-semibold rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                      >
                        <option value="speed_limit">Ограничение скорости (speed_limit)</option>
                        <option value="forbidden">Запретная зона (forbidden)</option>
                        <option value="gnss_shadow">Тень ГНСС (gnss_shadow)</option>
                        <option value="people_area">Пешеходная зона (people_area)</option>
                      </select>
                    </div>

                    {scenario.map?.zones?.[selectedEntity.index]?.type === 'speed_limit' && (
                      <div className="space-y-1">
                        <label className="text-[11px] font-semibold text-slate-600">
                          Максимальная скорость V_max (м/с):
                        </label>
                        <input
                          type="number"
                          step="0.1"
                          min="0.1"
                          max="2.5"
                          value={scenario.map?.zones?.[selectedEntity.index]?.v_max || 0.8}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const zones = [...(prev.map?.zones || [])];
                              if (zones[selectedEntity.index!]) {
                                zones[selectedEntity.index!] = {
                                  ...zones[selectedEntity.index!],
                                  v_max: parseFloat(e.target.value) || 0.8,
                                };
                              }
                              return { ...prev, map: { ...prev.map, zones } };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                    )}
                  </div>
                ) : selectedEntity.type === 'dock' && selectedEntity.id ? (
                  /* DOCK PROPERTIES */
                  <div className="space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold text-slate-800">Док-станция</span>
                      <button
                        onClick={handleDeleteSelected}
                        className="text-red-600 hover:text-red-700 text-xs flex items-center gap-1 font-semibold"
                      >
                        <Trash2 className="w-3.5 h-3.5" /> Удалить
                      </button>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] font-semibold text-slate-600">Название / Метка:</label>
                      <input
                        type="text"
                        value={
                          scenario.map?.points?.[selectedEntity.id]?.label || selectedEntity.id
                        }
                        onChange={(e) =>
                          setScenario((prev) => {
                            const pts = { ...(prev.map?.points || {}) };
                            if (pts[selectedEntity.id!]) {
                              pts[selectedEntity.id!] = {
                                ...pts[selectedEntity.id!],
                                label: e.target.value,
                              };
                            }
                            return { ...prev, map: { ...prev.map, points: pts } };
                          })
                        }
                        className="w-full bg-slate-50 border border-slate-200 text-xs font-semibold rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">X (м):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={scenario.map?.points?.[selectedEntity.id]?.x || 0}
                          onChange={(e) => {
                            const newX = parseFloat(e.target.value) || 0;
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (!pts[selectedEntity.id!]) return prev;
                              pts[selectedEntity.id!] = {
                                ...pts[selectedEntity.id!],
                                x: newX,
                              };
                              const missions = syncMissionsWithPoints(prev.missions, pts);
                              return { ...prev, map: { ...prev.map, points: pts }, missions };
                            });
                          }}
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Y (м):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={scenario.map?.points?.[selectedEntity.id]?.y || 0}
                          onChange={(e) => {
                            const newY = parseFloat(e.target.value) || 0;
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (!pts[selectedEntity.id!]) return prev;
                              pts[selectedEntity.id!] = {
                                ...pts[selectedEntity.id!],
                                y: newY,
                              };
                              const missions = syncMissionsWithPoints(prev.missions, pts);
                              return { ...prev, map: { ...prev.map, points: pts }, missions };
                            });
                          }}
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Угол θ (рад):</label>
                        <input
                          type="number"
                          step="0.1"
                          value={scenario.map?.points?.[selectedEntity.id]?.heading || 0}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (pts[selectedEntity.id!]) {
                                pts[selectedEntity.id!] = {
                                  ...pts[selectedEntity.id!],
                                  heading: parseFloat(e.target.value) || 0,
                                };
                              }
                              return { ...prev, map: { ...prev.map, points: pts } };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Допуск (м):</label>
                        <input
                          type="number"
                          step="0.05"
                          min="0.05"
                          max="1.0"
                          value={scenario.map?.points?.[selectedEntity.id]?.tol || 0.2}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (pts[selectedEntity.id!]) {
                                pts[selectedEntity.id!] = {
                                  ...pts[selectedEntity.id!],
                                  tol: parseFloat(e.target.value) || 0.2,
                                };
                              }
                              return { ...prev, map: { ...prev.map, points: pts } };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {/* 4. TAB: LAYERS */}
            {sidebarTab === 'layers' && (
              <div className="space-y-3">
                <p className="text-xs font-bold text-slate-700">Отображение слоев карты:</p>

                {[
                  { key: 'robot', label: 'Робот (АТЛАНТ-250 старт)', icon: Navigation },
                  { key: 'corridors', label: 'Проезды и коридоры', icon: Box },
                  { key: 'buildings', label: 'Стены и здания', icon: Package },
                  { key: 'obstacles', label: 'Препятствия (паллеты, контейнеры)', icon: Package },
                  { key: 'pedestrians', label: 'Пешеходы и траектории', icon: User },
                  { key: 'zones', label: 'Зоны (скорость, запретные, ГНСС)', icon: ShieldAlert },
                  { key: 'docks', label: 'Доки и складские ворота', icon: MapPin },
                  { key: 'grid', label: 'Координатная сетка и рамка', icon: Layers },
                ].map(({ key, label, icon: Icon }) => (
                  <label
                    key={key}
                    className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg border border-slate-200 hover:bg-slate-100 cursor-pointer transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-slate-500" />
                      <span className="text-xs font-semibold text-slate-800">{label}</span>
                    </div>
                    <input
                      type="checkbox"
                      checked={Boolean((layers as any)[key])}
                      onChange={(e) =>
                        setLayers((prev) => ({ ...prev, [key]: e.target.checked }))
                      }
                      className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                    />
                  </label>
                ))}
              </div>
            )}

            {/* 5. TAB: MAP (Чистая карта) */}
            {sidebarTab === 'map' && (
              <div className="space-y-4">
                <div className="space-y-1">
                  <h3 className="text-xs font-bold text-slate-800">Чистая карта полигона</h3>
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    Создание собственной карты с настройкой габаритов в метрах, очисткой стен и прокладкой базового проезда.
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-700">Ширина карты (м):</label>
                    <input
                      type="number"
                      step="10"
                      min="20"
                      max="500"
                      value={cleanMapWidth}
                      onChange={(e) => setCleanMapWidth(Math.max(20, parseInt(e.target.value) || 20))}
                      className="w-full bg-slate-50 border border-slate-200 text-slate-900 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-700">Длина карты (м):</label>
                    <input
                      type="number"
                      step="10"
                      min="20"
                      max="500"
                      value={cleanMapHeight}
                      onChange={(e) => setCleanMapHeight(Math.max(20, parseInt(e.target.value) || 20))}
                      className="w-full bg-slate-50 border border-slate-200 text-slate-900 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                    />
                  </div>
                </div>

                <div className="space-y-2 pt-2 border-t border-slate-100">
                  <label className="flex items-center justify-between p-2.5 bg-slate-50 hover:bg-slate-100/80 rounded-lg border border-slate-200 cursor-pointer transition-colors">
                    <span className="text-xs font-medium text-slate-700">Очистить стены (без препятствий зданий)</span>
                    <input
                      type="checkbox"
                      checked={cleanMapClearWalls}
                      onChange={(e) => setCleanMapClearWalls(e.target.checked)}
                      className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                    />
                  </label>

                  <label className="flex items-center justify-between p-2.5 bg-slate-50 hover:bg-slate-100/80 rounded-lg border border-slate-200 cursor-pointer transition-colors">
                    <span className="text-xs font-medium text-slate-700">Добавить базовый проезд</span>
                    <input
                      type="checkbox"
                      checked={cleanMapAddBaseLane}
                      onChange={(e) => setCleanMapAddBaseLane(e.target.checked)}
                      className="rounded border-slate-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                    />
                  </label>
                </div>

                <button
                  type="button"
                  onClick={() => handleCreateCleanMap()}
                  className="w-full bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 transition-colors shadow-xs"
                >
                  <Plus className="w-4 h-4" />
                  <span>Создать чистую карту</span>
                </button>
              </div>
            )}
          </div>
        </aside>
      )}

      {/* Center Canvas Area */}
      <main className="flex-1 flex flex-col relative overflow-hidden">
        {/* Interactive Canvas */}
        <div className="flex-1 w-full h-full">
          <ConstructorCanvas
            scenario={scenario}
            activeTool={activeTool}
            activeZoneType={activeZoneType}
            selectedEntity={selectedEntity}
            layers={layers}
            onSelect={setSelectedEntity}
            onUpdateScenario={setScenario}
          />
        </div>

        {/* Bottom Status & Hint Bar */}
        <div className="bg-white border-t border-slate-200 px-6 py-2 flex items-center justify-between text-xs text-slate-500 z-10 shadow-xs">
          <div className="flex items-center gap-4">
            <span>
              Режим:{' '}
              <strong className="text-slate-800">
                {activeTool === 'select' && 'Выбор и перемещение'}
                {activeTool === 'pan' && 'Панорамирование'}
                {activeTool === 'set_robot' && 'Установка платформы АТЛАНТ-250 (кликните на карте, потяните для угла)'}
                {activeTool === 'add_pallet' && 'Добавление поддона (кликните в месте установки)'}
                {activeTool === 'add_container' && 'Добавление контейнера (кликните в месте установки)'}
                {activeTool === 'add_pedestrian' && 'Добавление пешехода (кликните для размещения)'}
                {activeTool === 'add_zone' && 'Создание зоны (растяните прямоугольник мышью)'}
                {activeTool === 'add_dock' && 'Добавление дока (кликните для размещения)'}
                {activeTool === 'add_wall' && 'Добавление стены / здания (растяните прямоугольник мышью)'}
                {activeTool === 'add_drivable' && 'Добавление проезжей зоны (растяните прямоугольник мышью)'}
                {activeTool === 'delete' && 'Удаление объекта (кликните на объект)'}
              </strong>
            </span>

            {selectedEntity && (
              <div className="flex items-center gap-2 pl-3 border-l border-slate-200">
                <span className="text-blue-600 font-semibold">
                  Выбрано: {selectedEntity.type} {selectedEntity.id ? `(${selectedEntity.id})` : ''}
                </span>
                <button
                  onClick={handleDeleteSelected}
                  className="text-red-600 hover:underline text-[11px] font-semibold"
                >
                  Удалить выбранное
                </button>
              </div>
            )}
          </div>

          <div className="text-[11px] text-slate-400">
            Колесико мыши: приблизить / отдалить • Клик: выбор / добавление
          </div>
        </div>
      </main>

      {/* Right Element Selection Sidebar */}
      <aside className="w-14 bg-white border-l border-slate-200 flex flex-col items-center py-3 px-1.5 space-y-1.5 z-20 flex-shrink-0 select-none shadow-xs">
        <button
          onClick={() => setActiveTool('select')}
          aria-label="Выбор"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'select'
              ? 'bg-blue-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Выбрать / переместить объект"
        >
          <MousePointer className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('pan')}
          aria-label="Рука"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'pan'
              ? 'bg-blue-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Панорамирование карты (или удерживайте Shift / среднюю кнопку мыши)"
        >
          <Hand className="w-4 h-4" />
        </button>

        <div className="w-6 h-px bg-slate-200 my-1" />

        <button
          onClick={() => setActiveTool('set_robot')}
          aria-label="Робот"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'set_robot'
              ? 'bg-emerald-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Установить начальную позицию и курс платформы АТЛАНТ-250"
        >
          <Navigation className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('add_pallet')}
          aria-label="Поддон"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_pallet'
              ? 'bg-amber-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить деревянный поддон 1.2 x 0.8 м"
        >
          <Package className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('add_container')}
          aria-label="Контейнер"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_container'
              ? 'bg-blue-800 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить контейнер 6.0 x 2.4 м"
        >
          <Box className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('add_pedestrian')}
          aria-label="Пешеход"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_pedestrian'
              ? 'bg-orange-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить пешехода с маршрутом"
        >
          <User className="w-4 h-4" />
        </button>

        <div className="relative">
          <button
            onClick={() => setActiveTool('add_zone')}
            aria-label="Зона"
            className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
              activeTool === 'add_zone'
                ? 'bg-purple-600 text-white shadow-xs'
                : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
            }`}
            title="Добавить зону (растяните прямоугольник мышью)"
          >
            <ShieldAlert className="w-4 h-4" />
          </button>
          {activeTool === 'add_zone' && (
            <div className="absolute right-full top-0 mr-2 z-30 bg-white border border-slate-200 rounded-lg shadow-lg p-1 whitespace-nowrap">
              <select
                value={activeZoneType}
                onChange={(e) => setActiveZoneType(e.target.value as any)}
                className="bg-purple-50 text-purple-900 text-[11px] font-semibold rounded-lg px-2 py-1 border border-purple-200 outline-none"
              >
                <option value="speed_limit">⚡ Скорость</option>
                <option value="forbidden">⛔ Запретная</option>
                <option value="gnss_shadow">📡 Тень ГНСС</option>
                <option value="people_area">🚶 Пешеходная</option>
              </select>
            </div>
          )}
        </div>

        <button
          onClick={() => setActiveTool('add_dock')}
          aria-label="Док"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_dock'
              ? 'bg-blue-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить док-станцию или складские ворота"
        >
          <MapPin className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('add_wall')}
          aria-label="Стена"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_wall'
              ? 'bg-slate-700 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить стену или здание (растяните прямоугольник мышью)"
        >
          <Building className="w-4 h-4" />
        </button>

        <button
          onClick={() => setActiveTool('add_drivable')}
          aria-label="Проезд"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'add_drivable'
              ? 'bg-indigo-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
          }`}
          title="Добавить проезжую зону (растяните прямоугольник мышью)"
        >
          <Route className="w-4 h-4" />
        </button>

        <div className="w-6 h-px bg-slate-200 my-1" />

        <button
          onClick={() => setActiveTool('delete')}
          aria-label="Удалить"
          className={`w-10 h-10 flex items-center justify-center rounded-xl text-xs font-semibold transition-all ${
            activeTool === 'delete'
              ? 'bg-red-600 text-white shadow-xs'
              : 'text-slate-600 hover:text-red-600 hover:bg-red-50'
          }`}
          title="Удалить кликнутый объект"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </aside>
      </div>

      {/* IMPORT SCENARIO MODAL */}
      {showImportModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-in fade-in">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Upload className="w-5 h-5 text-blue-600" />
                <h2 className="text-base font-bold text-slate-900">Импорт сценария</h2>
              </div>
              <button
                onClick={() => {
                  setShowImportModal(false);
                  setImportValidationResult(null);
                }}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Drag & drop upload area */}
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDropFile}
              className="border-2 border-dashed border-slate-300 hover:border-blue-500 rounded-xl p-6 text-center space-y-2 cursor-pointer transition-colors bg-slate-50/50"
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                onChange={handleFileUpload}
                className="hidden"
              />
              <Upload className="w-8 h-8 text-blue-500 mx-auto" />
              <div className="text-sm font-semibold text-slate-800">
                Перетащите файл .json сюда или нажмите для выбора
              </div>
              <div className="text-xs text-slate-400">
                Поддерживаются файлы сценариев формата JSON (amrsim)
              </div>
            </div>

            {/* Direct JSON paste textarea */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-700">Или вставьте JSON код сценария:</label>
              <textarea
                rows={6}
                value={importJsonText}
                onChange={(e) => setImportJsonText(e.target.value)}
                placeholder='{ "schema": "amr-1.0", "name": "my_scenario", ... }'
                className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg p-3 focus:ring-1 focus:ring-blue-500 focus:outline-none"
              />
            </div>

            {/* Validation errors/warnings block */}
            {importValidationResult && (
              <div
                className={`p-3 rounded-xl border text-xs space-y-1 ${
                  importValidationResult.valid
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                    : 'bg-red-50 border-red-200 text-red-800'
                }`}
              >
                <div className="font-bold flex items-center gap-1.5">
                  {importValidationResult.valid ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                  ) : (
                    <AlertTriangle className="w-4 h-4 text-red-600" />
                  )}
                  <span>
                    {importValidationResult.valid
                      ? 'Сценарий прошел валидацию'
                      : 'Ошибка валидации структуры сценария:'}
                  </span>
                </div>
                {importValidationResult.errors.map((err, i) => (
                  <div key={i} className="pl-5 text-red-700">
                    • {err}
                  </div>
                ))}
                {importValidationResult.warnings.map((warn, i) => (
                  <div key={i} className="pl-5 text-amber-700">
                    • Предупреждение: {warn}
                  </div>
                ))}
              </div>
            )}

            {/* Modal actions */}
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                onClick={() => {
                  setShowImportModal(false);
                  setImportValidationResult(null);
                }}
                className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                Отмена
              </button>
              <button
                onClick={() => handleValidateAndLoadImport(importJsonText)}
                disabled={!importJsonText.trim()}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
              >
                Применить сценарий
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RAW JSON VIEWER / EDITOR MODAL */}
      {showJsonModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-in fade-in">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-4xl w-full h-[85vh] p-6 flex flex-col space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <FileCode className="w-5 h-5 text-blue-600" />
                <h2 className="text-base font-bold text-slate-900">
                  Редактор кода сценария (JSON)
                </h2>
              </div>
              <button
                onClick={() => setShowJsonModal(false)}
                className="text-slate-400 hover:text-slate-700 p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 min-h-0">
              <textarea
                value={JSON.stringify(scenario, null, 2)}
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value);
                    setScenario(parsed);
                  } catch {
                    // syntax in progress
                  }
                }}
                className="w-full h-full bg-slate-900 text-emerald-400 font-mono text-xs rounded-xl p-4 focus:outline-none resize-none leading-relaxed"
                spellCheck={false}
              />
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-100">
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyJson}
                  className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>Копировать</span>
                </button>
                <button
                  onClick={handleDownloadJson}
                  className="bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Скачать .json</span>
                </button>
              </div>

              <button
                onClick={() => setShowJsonModal(false)}
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 transition-colors shadow-sm"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
