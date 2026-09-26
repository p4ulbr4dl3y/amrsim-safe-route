import {
  ScenarioItem,
  DashboardViewModel,
  ReplayViewModel,
  EpisodesViewModel,
  MissionsViewModel,
  AnalyticsViewModel,
  SimulationRunParams,
  SimulationRunResult,
  MapData,
} from '../types';
import {
  mockDashboardData,
  mockTicks,
  mockMapData,
  mockEpisodes,
  mockMissions,
  mockReport,
} from '../mock/mockData';
import { getUploadedScenario } from '../utils/scenarioStorage';

const API_BASE = '/api';

/**
 * Fallback generator in case the Python SDUI backend is not currently running.
 */
const fallbackData = {
  getScenarios(): ScenarioItem[] {
    return [
      {
        id: '01_clear',
        name: '01_clear.json (Ясная погода)',
        description: 'Базовые условия, ясная погода, штатная доставка между складом и цехом А.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/01_clear.json',
        hasReport: true,
        score: 99.72,
      },
      {
        id: '01e_clear_easy',
        name: '01e_clear_easy.json (Ясная погода — Easy)',
        description: 'Упрощенная навигация без динамических препятствий.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/01e_clear_easy.json',
        hasReport: true,
        score: 100.0,
      },
      {
        id: '02_gnss_shadow',
        name: '02_gnss_shadow.json (Тень ГНСС)',
        description: 'Потеря спутникового сигнала в каньоне между корпусами T и S, лидарная одометрия.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/02_gnss_shadow.json',
        hasReport: true,
        score: 100.0,
      },
      {
        id: '02e_gnss_shadow_easy',
        name: '02e_gnss_shadow_easy.json (Тень ГНСС — Easy)',
        description: 'Упрощенная тень спутникового сигнала.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/02e_gnss_shadow_easy.json',
        hasReport: true,
        score: 100.0,
      },
      {
        id: '03_fog_snow',
        name: '03_fog_snow.json (Туман и метель)',
        description: 'Экстремальные погодные условия, зашумление облака точек лидара, фильтрация шума.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/03_fog_snow.json',
        hasReport: true,
        score: 98.6,
      },
      {
        id: '04_busy_yard',
        name: '04_busy_yard.json (Оживленный двор)',
        description: 'Динамические пешеходы, упавший поддон, объезд препятствий и соблюдение дистанции.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/04_busy_yard.json',
        hasReport: true,
        score: 98.18,
      },
      {
        id: 's1_pallet_2m',
        name: 'backend/s1_pallet_2m.json (Поддон в 2м от оси)',
        description: 'Собственный сценарий команды: проверка классификации статичного поддона вне коридора.',
        type: 'custom',
        file: 'backend/scenarios/s1_pallet_2m.json',
        hasReport: true,
        score: 99.04,
      },
      {
        id: 's2_container_block',
        name: 'backend/s2_container_block.json (Блокировка контейнером)',
        description: 'Собственный сценарий команды: динамический объезд перекрытого проезда по A*.',
        type: 'custom',
        file: 'backend/scenarios/s2_container_block.json',
        hasReport: true,
        score: 98.7,
      },
      {
        id: 's3_wall_removed',
        name: 'backend/s3_wall_removed.json (Убранная стена)',
        description: 'Собственный сценарий команды: навигация при изменении конфигурации стен склада.',
        type: 'custom',
        file: 'backend/scenarios/s3_wall_removed.json',
        hasReport: true,
        score: 97.0,
      },
      {
        id: 's4_shadow_start_charger',
        name: 'backend/s4_shadow_start_charger.json (Старт в тени до зарядки)',
        description: 'Собственный сценарий команды: движение от дока зарядки в зоне тени GNSS.',
        type: 'custom',
        file: 'backend/scenarios/s4_shadow_start_charger.json',
        hasReport: true,
        score: 97.0,
      },
      {
        id: 's5_fog_inattentive',
        name: 'backend/s5_fog_inattentive.json (Туман и пешеход)',
        description: 'Собственный сценарий команды: плотный туман и внезапный пешеход поперек курса.',
        type: 'custom',
        file: 'backend/scenarios/s5_fog_inattentive.json',
        hasReport: true,
        score: 99.27,
      },
      {
        id: 'c1_logistics_hub',
        name: 'custom_scenarios/c1_logistics_hub.json (Логистический хаб)',
        description: 'Логистический хаб 160x140м: Т-образный кросс-докинг, зоны ограничения скорости, пешеходные переходы.',
        type: 'custom',
        file: 'custom_scenarios/c1_logistics_hub.json',
        hasReport: true,
        score: 94.74,
      },
    ];
  },

  getDashboard(scenarioId: string): DashboardViewModel {
    return {
      scenario: scenarioId,
      totalScore: mockDashboardData.totalScore,
      totalMax: mockDashboardData.totalMax,
      deliveriesCount: mockDashboardData.deliveriesCount,
      deliveriesTotal: mockDashboardData.deliveriesTotal,
      safetyFatal: mockDashboardData.safetyFatal,
      safetyWarnings: mockDashboardData.safetyWarnings,
      localizationError: mockDashboardData.localizationError,
      recentEvents: mockDashboardData.recentEvents.map(e => ({
        ...e,
        status: e.status as 'success' | 'warning' | 'info' | 'critical',
      })),
      controllerState: mockDashboardData.controllerState,
      speedHistory: mockDashboardData.speedHistory,
      speedTimestamps: [
        '00:00', '00:30', '01:00', '01:30', '02:00', '02:30', '03:00', '03:30',
        '04:00', '04:30', '05:00', '05:30', '06:00', '06:30', '07:00', '07:30',
        '08:00', '08:30', '09:00', '09:30', '10:00', '10:30', '11:00', '11:30',
        '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '15:00', '15:30',
        '16:00', '16:30', '17:00', '17:30', '18:00', '18:30', '19:00', '19:30'
      ],
      previewTick: mockTicks[150] || mockTicks[0] || null,
      historyTicks: mockTicks.slice(0, 150),
      mapData: mockMapData as unknown as MapData,
    };
  },

  getReplay(scenarioId: string, seed = 7): ReplayViewModel {
    return {
      scenario: scenarioId,
      seed,
      header: { scenario: scenarioId, seed, dt: 0.1 },
      mapData: mockMapData as unknown as MapData,
      ticks: mockTicks,
      totalTicks: mockTicks.length,
      duration: mockTicks[mockTicks.length - 1]?.t || 341.0,
      episodes: mockEpisodes.map(ep => ({
        id: ep.id,
        t_start: ep.t_start,
        t_end: ep.t_end,
        type: ep.type,
        category: ep.category,
        cost: ep.cost,
        x: ep.x,
        y: ep.y,
      })),
    };
  },

  getEpisodes(scenarioId: string): EpisodesViewModel {
    return {
      scenario: scenarioId,
      summary: {
        totalCost: -0.6,
        fatalCount: 0,
        warningsCount: mockEpisodes.length,
        ruleViolationsCount: 1,
      },
      episodes: mockEpisodes,
    };
  },

  getMissions(scenarioId: string): MissionsViewModel {
    return {
      scenario: scenarioId,
      summary: {
        completed: 2,
        total: 2,
        deliveryScore: 40.0,
        maxDeliveryScore: 40.0,
        efficiencyScore: 13.78,
        maxEfficiencyScore: 15.0,
      },
      missions: mockMissions,
    };
  },

  getAnalytics(scenarioId: string): AnalyticsViewModel {
    return {
      scenario: scenarioId,
      seed: 7,
      totalScore: mockReport.totalScore,
      counted: mockReport.counted,
      blocks: mockReport.blocks,
      radar: {
        labels: mockReport.blocks.map(b => b.name),
        values: mockReport.blocks.map(b => b.percentage / 100),
        maxValues: mockReport.blocks.map(() => 1.0),
      },
      computeBudget: mockReport.computeBudget,
      sandbox: mockReport.sandbox,
    };
  },
};

/**
 * Centralized API Client for Server-Driven UI.
 */
export const apiClient = {
  /**
   * Fetch list of available scenarios (standard + team + uploaded).
   */
  async fetchScenarios(): Promise<ScenarioItem[]> {
    let list: ScenarioItem[];
    try {
      const res = await fetch(`${API_BASE}/scenarios`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      list = await res.json();
    } catch (err) {
      console.warn('[API] Failed to fetch scenarios, using fallback:', err);
      list = fallbackData.getScenarios();
    }

    const uploaded = getUploadedScenario();
    if (uploaded) {
      const filtered = list.filter((s) => s.id !== uploaded.id);
      const uploadedItem: ScenarioItem = {
        id: uploaded.id,
        name: `${uploaded.name} (Загружен)`,
        description: `Загруженный ${
          uploaded.fileType === 'scenario'
            ? 'сценарий'
            : uploaded.fileType === 'report'
            ? 'отчет'
            : 'лог'
        }: ${uploaded.fileName}`,
        type: 'custom',
        file: uploaded.fileName,
        hasReport: !!uploaded.reportJson || uploaded.fileType === 'report',
        score: uploaded.dashboardViewModel?.totalScore ?? null,
      };
      return [uploadedItem, ...filtered];
    }

    return list;
  },

  /**
   * Fetch ready-to-render Dashboard View Model.
   */
  async fetchDashboard(scenarioId = '04_busy_yard'): Promise<DashboardViewModel> {
    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.dashboardViewModel) {
      return uploaded.dashboardViewModel;
    }

    try {
      const res = await fetch(`${API_BASE}/ui/dashboard?scenario=${encodeURIComponent(scenarioId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] Failed to fetch dashboard for ${scenarioId}, using fallback:`, err);
      return fallbackData.getDashboard(scenarioId);
    }
  },

  /**
   * Fetch Replay telemetry ticks, map geometry, and episode markers.
   */
  async fetchReplay(scenarioId = '04_busy_yard', seed = 7): Promise<ReplayViewModel> {
    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.replayViewModel) {
      return uploaded.replayViewModel;
    }

    try {
      const res = await fetch(`${API_BASE}/ui/replay?scenario=${encodeURIComponent(scenarioId)}&seed=${seed}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] Failed to fetch replay for ${scenarioId}, using fallback:`, err);
      return fallbackData.getReplay(scenarioId, seed);
    }
  },

  /**
   * Fetch Episodes & Safety incidents list with telemetry snapshots.
   */
  async fetchEpisodes(scenarioId = '04_busy_yard'): Promise<EpisodesViewModel> {
    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId) {
      const eps = uploaded.reportJson?.episodes || uploaded.replayViewModel?.episodes || [];
      return {
        scenario: scenarioId,
        summary: {
          totalCost: eps.reduce((sum: number, ep: any) => sum + (ep.cost || 0), 0),
          fatalCount: uploaded.dashboardViewModel?.safetyFatal || 0,
          warningsCount: uploaded.dashboardViewModel?.safetyWarnings || eps.length,
          ruleViolationsCount: eps.length,
        },
        episodes: eps,
      };
    }

    try {
      const res = await fetch(`${API_BASE}/ui/episodes?scenario=${encodeURIComponent(scenarioId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] Failed to fetch episodes for ${scenarioId}, using fallback:`, err);
      return fallbackData.getEpisodes(scenarioId);
    }
  },

  /**
   * Fetch Missions (m1, m2) performance, hold duration, tolerance and margins.
   */
  async fetchMissions(scenarioId = '04_busy_yard'): Promise<MissionsViewModel> {
    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.missionsViewModel) {
      return uploaded.missionsViewModel;
    }

    try {
      const res = await fetch(`${API_BASE}/ui/missions?scenario=${encodeURIComponent(scenarioId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] Failed to fetch missions for ${scenarioId}, using fallback:`, err);
      return fallbackData.getMissions(scenarioId);
    }
  },

  /**
   * Fetch complete Analytics: 6 score blocks, radar chart, compute budget & sandbox.
   */
  async fetchAnalytics(scenarioId = '04_busy_yard'): Promise<AnalyticsViewModel> {
    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.reportJson) {
      const rep = uploaded.reportJson;
      const totalScore = uploaded.dashboardViewModel?.totalScore ?? (rep?.score?.total || 100);
      const blocks = rep?.blocks || rep?.score?.blocks || fallbackData.getAnalytics(scenarioId).blocks;
      return {
        scenario: scenarioId,
        seed: rep?.seed || 7,
        totalScore,
        counted: true,
        blocks,
        radar: {
          labels: blocks.map((b: any) => b.name),
          values: blocks.map((b: any) => (b.percentage ?? 100) / 100),
          maxValues: blocks.map(() => 1.0),
        },
        computeBudget: rep?.computeBudget || fallbackData.getAnalytics(scenarioId).computeBudget,
        sandbox: rep?.sandbox || { violations: [], stderr_tail: [] },
      };
    }

    try {
      const res = await fetch(`${API_BASE}/ui/analytics?scenario=${encodeURIComponent(scenarioId)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn(`[API] Failed to fetch analytics for ${scenarioId}, using fallback:`, err);
      return fallbackData.getAnalytics(scenarioId);
    }
  },

  /**
   * Run real simulation via POST /api/run.
   */
  async runSimulation(params: SimulationRunParams): Promise<SimulationRunResult> {
    const res = await fetch(`${API_BASE}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(params),
    });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Simulation failed (HTTP ${res.status}): ${errorText}`);
    }
    return await res.json();
  },

  /**
   * Get direct download URL for real incidents CSV export.
   */
  getExportCsvUrl(scenarioId = '04_busy_yard'): string {
    return `${API_BASE}/export/csv?scenario=${encodeURIComponent(scenarioId)}`;
  },
};
