import React, { useState, useEffect, useRef } from 'react';
import { RouteName, AmrScenario, MapData, ScenarioZone, ScenarioMapPatch, ScenarioPedestrian } from '../types';
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
} from 'lucide-react';

interface ConstructorPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  activeScenario?: string;
  onScenarioChange?: (scenario: string) => void;
}

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

  // Inspector sidebar tab
  const [sidebarTab, setSidebarTab] = useState<'params' | 'objects' | 'properties' | 'layers'>('params');

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
  const handleSaveToStorage = () => {
    const scName = scenario.name.trim() || 'custom_scenario';
    const mapData: MapData = {
      bounds: scenario.map.bounds || [0, 0, 250, 200],
      drivable: scenario.map.drivable || [],
      buildings: scenario.map.buildings || [],
      zones: scenario.map.zones || [],
      gates: scenario.map.gates || [],
      crossing: scenario.map.crossing || [],
      points: scenario.map.points || {},
    };

    const missionsTotal = Array.isArray(scenario.missions) ? scenario.missions.length : 0;
    const missionsList = Array.isArray(scenario.missions)
      ? scenario.missions.map((m, idx) => ({
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
      scenarioJson: scenario,
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
    showToast(`Сценарий "${scName}" сохранен в локальное хранилище`);
  };

  // Run in simulator
  const handleLaunchInSimulator = () => {
    handleSaveToStorage();
    const scName = scenario.name.trim() || 'custom_scenario';
    onNavigate('runner', { scenario: scName });
  };

  // Copy scenario JSON to clipboard
  const handleCopyJson = async () => {
    try {
      const formatted = JSON.stringify(scenario, null, 2);
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
    const fileName = `${scenario.name || 'scenario'}.json`;
    const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(
      JSON.stringify(scenario, null, 2)
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
    <div className="flex-1 flex flex-col h-[calc(100vh-57px)] overflow-hidden bg-slate-100 min-w-[1240px]">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed top-16 right-6 z-50 bg-slate-900 text-white text-xs font-medium px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Top Application Toolbar */}
      <div className="bg-white border-b border-slate-200 px-6 py-2.5 flex flex-wrap items-center justify-between gap-4 z-20 shadow-xs">
        {/* Left: Title & Preset Selector */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600">
              <Navigation className="w-4 h-4 transform rotate-45" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-bold text-slate-900 tracking-tight">
                  Конструктор сценариев AMR
                </h1>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 font-semibold">
                  amr-1.0
                </span>
              </div>
              <p className="text-[11px] text-slate-500">
                Визуальное создание, редактирование и экспорт карт полигона
              </p>
            </div>
          </div>

          <div className="h-6 w-px bg-slate-200 mx-1 hidden md:block" />

          {/* Template Preset Selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium hidden lg:inline">Шаблон:</span>
            <select
              value={selectedTemplateId}
              onChange={(e) => handleSelectTemplate(e.target.value)}
              className="bg-slate-50 border border-slate-200 text-slate-800 text-xs font-semibold rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
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

      {/* Main Workspace: Left Inspector & Center Canvas */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Inspector Sidebar */}
        <aside className="w-96 bg-white border-r border-slate-200 flex flex-col z-10 shadow-sm">
          {/* Sidebar Tabs */}
          <div className="flex items-center border-b border-slate-200 px-3 pt-2 gap-1 bg-slate-50/50">
            <button
              onClick={() => setSidebarTab('params')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-t-lg transition-colors border-b-2 ${
                sidebarTab === 'params'
                  ? 'bg-white text-blue-600 border-blue-600 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 border-transparent'
              }`}
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>Параметры</span>
            </button>

            <button
              onClick={() => setSidebarTab('objects')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-t-lg transition-colors border-b-2 ${
                sidebarTab === 'objects'
                  ? 'bg-white text-blue-600 border-blue-600 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 border-transparent'
              }`}
            >
              <List className="w-3.5 h-3.5" />
              <span>Объекты</span>
            </button>

            <button
              onClick={() => setSidebarTab('properties')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-t-lg transition-colors border-b-2 ${
                sidebarTab === 'properties'
                  ? 'bg-white text-blue-600 border-blue-600 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 border-transparent'
              }`}
            >
              <Box className="w-3.5 h-3.5" />
              <span>Свойства</span>
            </button>

            <button
              onClick={() => setSidebarTab('layers')}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-t-lg transition-colors border-b-2 ${
                sidebarTab === 'layers'
                  ? 'bg-white text-blue-600 border-blue-600 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 border-transparent'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Слои</span>
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

                {/* Weather & Environment Settings */}
                <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CloudSnow className="w-4 h-4 text-blue-500" />
                      <span className="text-xs font-bold text-slate-800">Погода: Снег / Осадки</span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={Boolean(scenario.weather?.snow)}
                        onChange={(e) =>
                          setScenario((prev) => ({
                            ...prev,
                            weather: { ...prev.weather, snow: e.target.checked },
                          }))
                        }
                        className="sr-only peer"
                      />
                      <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
                    </label>
                  </div>
                  <p className="text-[11px] text-slate-500 leading-relaxed">
                    При включенном снеге симулятор добавляет ложные эхо-сигналы лидара и утраивает проскальзывание одометрии платформы.
                  </p>
                </div>

                {/* Dynamic Weather Events */}
                <div className="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CloudFog className="w-4 h-4 text-amber-500" />
                      <span className="text-xs font-bold text-slate-800">События тумана и ГНСС</span>
                    </div>
                    <button
                      onClick={() =>
                        setScenario((prev) => ({
                          ...prev,
                          events: [
                            ...(prev.events || []),
                            { type: 'fog_bank', t1: 30.0, t2: 90.0 },
                          ],
                        }))
                      }
                      className="text-[11px] text-blue-600 font-semibold hover:underline flex items-center gap-1"
                    >
                      <Plus className="w-3 h-3" /> Добавить
                    </button>
                  </div>

                  {(!scenario.events || scenario.events.length === 0) ? (
                    <p className="text-[11px] text-slate-400 italic">События не настроены (чистая видимость)</p>
                  ) : (
                    <div className="space-y-2">
                      {scenario.events.map((ev, idx) => (
                        <div
                          key={idx}
                          className="bg-white border border-slate-200 rounded-lg p-2.5 flex items-center justify-between text-xs"
                        >
                          <div className="space-y-1">
                            <span className="font-semibold text-slate-800">
                              {ev.type === 'fog_bank' ? '🌫️ Полоса тумана' : '📡 Сбой ГНСС'}
                            </span>
                            <div className="text-[11px] text-slate-500">
                              t = {ev.t1} с ... {ev.t2} с ({(ev.t2 - ev.t1).toFixed(1)} с)
                            </div>
                          </div>
                          <button
                            onClick={() =>
                              setScenario((prev) => {
                                const evs = [...(prev.events || [])];
                                evs.splice(idx, 1);
                                return { ...prev, events: evs };
                              })
                            }
                            className="p-1 text-slate-400 hover:text-red-600 rounded transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
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
                        <div className="text-xs font-bold text-slate-900">Робот (AMR Платформа)</div>
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
                        AMR
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
                          onChange={(e) =>
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (pts[selectedEntity.id!]) {
                                pts[selectedEntity.id!] = {
                                  ...pts[selectedEntity.id!],
                                  x: parseFloat(e.target.value) || 0,
                                };
                              }
                              return { ...prev, map: { ...prev.map, points: pts } };
                            })
                          }
                          className="w-full bg-slate-50 border border-slate-200 text-xs font-mono rounded-lg px-2.5 py-1.5 focus:ring-1 focus:ring-blue-500 focus:outline-none"
                        />
                      </div>
                      <div>
                        <label className="text-[11px] font-semibold text-slate-600">Y (м):</label>
                        <input
                          type="number"
                          step="0.5"
                          value={scenario.map?.points?.[selectedEntity.id]?.y || 0}
                          onChange={(e) =>
                            setScenario((prev) => {
                              const pts = { ...(prev.map?.points || {}) };
                              if (pts[selectedEntity.id!]) {
                                pts[selectedEntity.id!] = {
                                  ...pts[selectedEntity.id!],
                                  y: parseFloat(e.target.value) || 0,
                                };
                              }
                              return { ...prev, map: { ...prev.map, points: pts } };
                            })
                          }
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
                  { key: 'robot', label: 'Робот (AMR старт)', icon: Navigation },
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
          </div>
        </aside>

        {/* Center Canvas Area with Floating Palette */}
        <main className="flex-1 flex flex-col relative overflow-hidden">
          {/* Floating Canvas Tool Palette */}
          <div className="absolute top-4 left-1/2 transform -translate-x-1/2 z-20 bg-white/95 backdrop-blur-md border border-slate-200/80 rounded-2xl shadow-lg p-1.5 flex items-center gap-1">
            <button
              onClick={() => setActiveTool('select')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'select'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Выбрать / переместить объект"
            >
              <MousePointer className="w-4 h-4" />
              <span className="hidden sm:inline">Выбор</span>
            </button>

            <button
              onClick={() => setActiveTool('pan')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'pan'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Панорамирование карты (или удерживайте Shift / среднюю кнопку мыши)"
            >
              <Hand className="w-4 h-4" />
              <span className="hidden sm:inline">Рука</span>
            </button>

            <div className="h-5 w-px bg-slate-200 mx-1" />

            <button
              onClick={() => setActiveTool('set_robot')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'set_robot'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Установить начальную позицию и курс робота"
            >
              <Navigation className="w-4 h-4" />
              <span className="hidden sm:inline">Робот</span>
            </button>

            <button
              onClick={() => setActiveTool('add_pallet')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'add_pallet'
                  ? 'bg-amber-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Добавить деревянный поддон 1.2 x 0.8 м"
            >
              <Package className="w-4 h-4" />
              <span className="hidden sm:inline">Поддон</span>
            </button>

            <button
              onClick={() => setActiveTool('add_container')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'add_container'
                  ? 'bg-blue-800 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Добавить контейнер 6.0 x 2.4 м"
            >
              <Box className="w-4 h-4" />
              <span className="hidden sm:inline">Контейнер</span>
            </button>

            <button
              onClick={() => setActiveTool('add_pedestrian')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'add_pedestrian'
                  ? 'bg-orange-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Добавить пешехода с маршрутом"
            >
              <User className="w-4 h-4" />
              <span className="hidden sm:inline">Пешеход</span>
            </button>

            <div className="flex items-center gap-0.5">
              <button
                onClick={() => setActiveTool('add_zone')}
                className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                  activeTool === 'add_zone'
                    ? 'bg-purple-600 text-white shadow-xs'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
                }`}
                title="Добавить зону (растяните прямоугольник мышью)"
              >
                <ShieldAlert className="w-4 h-4" />
                <span className="hidden sm:inline">Зона</span>
              </button>
              {activeTool === 'add_zone' && (
                <select
                  value={activeZoneType}
                  onChange={(e) => setActiveZoneType(e.target.value as any)}
                  className="bg-purple-50 text-purple-900 text-[11px] font-semibold rounded-lg px-2 py-1.5 border border-purple-200 outline-none"
                >
                  <option value="speed_limit">⚡ Скорость</option>
                  <option value="forbidden">⛔ Запретная</option>
                  <option value="gnss_shadow">📡 Тень ГНСС</option>
                  <option value="people_area">🚶 Пешеходная</option>
                </select>
              )}
            </div>

            <button
              onClick={() => setActiveTool('add_dock')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'add_dock'
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'
              }`}
              title="Добавить док-станцию или складские ворота"
            >
              <MapPin className="w-4 h-4" />
              <span className="hidden sm:inline">Док</span>
            </button>

            <div className="h-5 w-px bg-slate-200 mx-1" />

            <button
              onClick={() => setActiveTool('delete')}
              className={`p-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTool === 'delete'
                  ? 'bg-red-600 text-white shadow-xs'
                  : 'text-slate-600 hover:text-red-600 hover:bg-red-50'
              }`}
              title="Удалить кликнутый объект"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

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
                  {activeTool === 'set_robot' && 'Установка робота (кликните на карте, потяните для угла)'}
                  {activeTool === 'add_pallet' && 'Добавление поддона (кликните в месте установки)'}
                  {activeTool === 'add_container' && 'Добавление контейнера (кликните в месте установки)'}
                  {activeTool === 'add_pedestrian' && 'Добавление пешехода (кликните для размещения)'}
                  {activeTool === 'add_zone' && 'Создание зоны (растяните прямоугольник мышью)'}
                  {activeTool === 'add_dock' && 'Добавление дока (кликните для размещения)'}
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
      </div>

      {/* IMPORT SCENARIO MODAL */}
      {showImportModal && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4 animate-in fade-in">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <Upload className="w-5 h-5 text-blue-600" />
                <h2 className="text-base font-bold text-slate-900">Импорт сценария AMR</h2>
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
                Поддерживаются файлы сценариев стандарта amr-1.0 (amrsim)
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
                Проверить и загрузить
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
                  Редактор кода сценария (JSON amr-1.0)
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
