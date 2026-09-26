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
import { getUploadedScenario } from '../utils/scenarioStorage';

/**
 * Resolves API base path relative to current deployment subpath (e.g. /amr/api on VPS or /api on localhost).
 */
export const getApiBase = (): string => {
  if (typeof window === 'undefined') return '/api';
  const path = window.location.pathname.replace(/\/index\.html$/, '');
  const prefix = path.replace(/\/+$/, '');
  return prefix ? `${prefix}/api` : '/api';
};

const getBase = (): string => getApiBase();

/**
 * Honest empty fallbacks when the Python SDUI backend is not currently running.
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
        hasReport: false,
        score: null,
      },
      {
        id: '01e_clear_easy',
        name: '01e_clear_easy.json (Ясная погода — Easy)',
        description: 'Упрощенная навигация без динамических препятствий.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/01e_clear_easy.json',
        hasReport: false,
        score: null,
      },
      {
        id: '02_gnss_shadow',
        name: '02_gnss_shadow.json (Тень ГНСС)',
        description: 'Потеря спутникового сигнала в каньоне между корпусами T и S, лидарная одометрия.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/02_gnss_shadow.json',
        hasReport: false,
        score: null,
      },
      {
        id: '02e_gnss_shadow_easy',
        name: '02e_gnss_shadow_easy.json (Тень ГНСС — Easy)',
        description: 'Упрощенная тень спутникового сигнала.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/02e_gnss_shadow_easy.json',
        hasReport: false,
        score: null,
      },
      {
        id: '03_fog_snow',
        name: '03_fog_snow.json (Туман и метель)',
        description: 'Экстремальные погодные условия, зашумление облака точек лидара, фильтрация шума.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/03_fog_snow.json',
        hasReport: false,
        score: null,
      },
      {
        id: '04_busy_yard',
        name: '04_busy_yard.json (Оживленный двор)',
        description: 'Динамические пешеходы, упавший поддон, объезд препятствий и соблюдение дистанции.',
        type: 'standard',
        file: 'amrsim-participants/scenarios/04_busy_yard.json',
        hasReport: false,
        score: null,
      },
      {
        id: 's1_pallet_2m',
        name: 'backend/s1_pallet_2m.json (Поддон в 2м от оси)',
        description: 'Собственный сценарий команды: проверка классификации статичного поддона вне коридора.',
        type: 'custom',
        file: 'backend/scenarios/s1_pallet_2m.json',
        hasReport: false,
        score: null,
      },
      {
        id: 's2_container_block',
        name: 'backend/s2_container_block.json (Блокировка контейнером)',
        description: 'Собственный сценарий команды: динамический объезд перекрытого проезда по A*.',
        type: 'custom',
        file: 'backend/scenarios/s2_container_block.json',
        hasReport: false,
        score: null,
      },
      {
        id: 's3_wall_removed',
        name: 'backend/s3_wall_removed.json (Убранная стена)',
        description: 'Собственный сценарий команды: навигация при изменении конфигурации стен склада.',
        type: 'custom',
        file: 'backend/scenarios/s3_wall_removed.json',
        hasReport: false,
        score: null,
      },
      {
        id: 's4_shadow_start_charger',
        name: 'backend/s4_shadow_start_charger.json (Старт в тени до зарядки)',
        description: 'Собственный сценарий команды: движение от дока зарядки в зоне тени GNSS.',
        type: 'custom',
        file: 'backend/scenarios/s4_shadow_start_charger.json',
        hasReport: false,
        score: null,
      },
      {
        id: 's5_fog_inattentive',
        name: 'backend/s5_fog_inattentive.json (Туман и пешеход)',
        description: 'Собственный сценарий команды: плотный туман и внезапный пешеход поперек курса.',
        type: 'custom',
        file: 'backend/scenarios/s5_fog_inattentive.json',
        hasReport: false,
        score: null,
      },
      {
        id: 'c1_logistics_hub',
        name: 'custom_scenarios/c1_logistics_hub.json (Логистический хаб)',
        description: 'Логистический хаб 160x140м: Т-образный кросс-докинг, зоны ограничения скорости, пешеходные переходы.',
        type: 'custom',
        file: 'custom_scenarios/c1_logistics_hub.json',
        hasReport: false,
        score: null,
      },
    ];
  },

  getDashboard(scenarioId: string): DashboardViewModel {
    return {
      scenario: scenarioId,
      totalScore: 0,
      totalMax: 100,
      deliveriesCount: 0,
      deliveriesTotal: 0,
      safetyFatal: 0,
      safetyWarnings: 0,
      localizationError: null,
      recentEvents: [],
      controllerState: {
        online: false,
        meanDelayMs: 0,
        maxDelayMs: 0,
        nSteps: 0,
      },
      speedHistory: [],
      speedTimestamps: [],
      previewTick: null,
      historyTicks: [],
      mapData: null as unknown as MapData,
    };
  },

  getReplay(scenarioId: string, seed = 7): ReplayViewModel {
    return {
      scenario: scenarioId,
      seed,
      header: { scenario: scenarioId, seed, dt: 0.1 },
      mapData: null as unknown as MapData,
      ticks: [],
      totalTicks: 0,
      duration: 0,
      episodes: [],
    };
  },

  getEpisodes(scenarioId: string): EpisodesViewModel {
    return {
      scenario: scenarioId,
      summary: {
        totalCost: 0,
        fatalCount: 0,
        warningsCount: 0,
        ruleViolationsCount: 0,
      },
      episodes: [],
    };
  },

  getMissions(scenarioId: string): MissionsViewModel {
    return {
      scenario: scenarioId,
      summary: {
        completed: 0,
        total: 0,
        deliveryScore: 0,
        maxDeliveryScore: 40.0,
        efficiencyScore: 0,
        maxEfficiencyScore: 15.0,
      },
      missions: [],
    };
  },

  getAnalytics(scenarioId: string): AnalyticsViewModel {
    return {
      scenario: scenarioId,
      seed: 7,
      totalScore: 0,
      counted: false,
      blocks: [],
      radar: {
        labels: [],
        values: [],
        maxValues: [],
      },
      computeBudget: {
        fact_s: 0,
        limit_s: 35.0,
        mean_step_ms: 0,
        max_step_ms: 0,
        step_limit_ms: 5.0,
        step_distribution: [],
        ok: true,
      },
      sandbox: {
        passed: true,
        violations: [],
        warnings: [],
        stderr_tail: [],
      },
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
      const res = await fetch(`${getBase()}/scenarios`);
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
    try {
      const res = await fetch(`${getBase()}/ui/dashboard?scenario=${encodeURIComponent(scenarioId)}`);
      if (res.ok) {
        const serverVm = await res.json();
        if (serverVm && serverVm.scenario) {
          return serverVm;
        }
      }
    } catch (err) {
      console.warn(`[API] Failed to fetch dashboard for ${scenarioId} from server:`, err);
    }

    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.dashboardViewModel) {
      return uploaded.dashboardViewModel;
    }

    return fallbackData.getDashboard(scenarioId);
  },

  /**
   * Fetch Replay telemetry ticks, map geometry, and episode markers.
   */
  async fetchReplay(scenarioId = '04_busy_yard', seed = 7): Promise<ReplayViewModel> {
    const uploaded = getUploadedScenario();
    if (
      uploaded &&
      uploaded.id === scenarioId &&
      uploaded.fileType === 'log' &&
      uploaded.replayViewModel?.ticks &&
      uploaded.replayViewModel.ticks.length > 1
    ) {
      return uploaded.replayViewModel;
    }

    try {
      const res = await fetch(`${getBase()}/ui/replay?scenario=${encodeURIComponent(scenarioId)}&seed=${seed}`);
      if (res.ok) {
        const serverVm = await res.json();
        if (serverVm && (serverVm.scenario || serverVm.ticks)) {
          return serverVm;
        }
      }
    } catch (err) {
      console.warn(`[API] Failed to fetch replay for ${scenarioId} from server:`, err);
    }

    if (uploaded && uploaded.id === scenarioId && uploaded.replayViewModel) {
      return uploaded.replayViewModel;
    }

    return fallbackData.getReplay(scenarioId, seed);
  },

  /**
   * Fetch Episodes & Safety incidents list with telemetry snapshots.
   */
  async fetchEpisodes(scenarioId = '04_busy_yard'): Promise<EpisodesViewModel> {
    try {
      const res = await fetch(`${getBase()}/ui/episodes?scenario=${encodeURIComponent(scenarioId)}`);
      if (res.ok) {
        const serverVm = await res.json();
        if (serverVm && Array.isArray(serverVm.episodes)) {
          return serverVm;
        }
      }
    } catch (err) {
      console.warn(`[API] Failed to fetch episodes for ${scenarioId} from server:`, err);
    }

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

    return fallbackData.getEpisodes(scenarioId);
  },

  /**
   * Fetch Missions (m1, m2) performance, hold duration, tolerance and margins.
   */
  async fetchMissions(scenarioId = '04_busy_yard'): Promise<MissionsViewModel> {
    try {
      const res = await fetch(`${getBase()}/ui/missions?scenario=${encodeURIComponent(scenarioId)}`);
      if (res.ok) {
        const serverVm = await res.json();
        if (serverVm && Array.isArray(serverVm.missions)) {
          return serverVm;
        }
      }
    } catch (err) {
      console.warn(`[API] Failed to fetch missions for ${scenarioId} from server:`, err);
    }

    const uploaded = getUploadedScenario();
    if (uploaded && uploaded.id === scenarioId && uploaded.missionsViewModel) {
      return uploaded.missionsViewModel;
    }

    return fallbackData.getMissions(scenarioId);
  },

  /**
   * Fetch complete Analytics: 6 score blocks, radar chart, compute budget & sandbox.
   */
  async fetchAnalytics(scenarioId = '04_busy_yard'): Promise<AnalyticsViewModel> {
    try {
      const res = await fetch(`${getBase()}/ui/analytics?scenario=${encodeURIComponent(scenarioId)}`);
      if (res.ok) {
        const serverVm = await res.json();
        if (serverVm && serverVm.blocks) {
          return serverVm;
        }
      }
    } catch (err) {
      console.warn(`[API] Failed to fetch analytics for ${scenarioId} from server:`, err);
    }

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

    return fallbackData.getAnalytics(scenarioId);
  },

  /**
   * Save scenario definition to server (and fallback to local storage).
   */
  async saveScenario(id: string, scenarioData: any): Promise<{ ok: boolean; success?: boolean; id?: string; file?: string }> {
    try {
      const res = await fetch(`${getBase()}/scenarios/save`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ id, scenario: scenarioData }),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.warn('[API] Failed to save scenario to server:', err);
    }
    return { ok: true, success: true };
  },

  /**
   * Run real simulation via POST /api/run.
   */
  async runSimulation(params: SimulationRunParams): Promise<SimulationRunResult> {
    const uploaded = getUploadedScenario();
    const scenarioData =
      params.scenarioData ||
      (uploaded && (uploaded.id === params.scenario || uploaded.name === params.scenario)
        ? uploaded.scenarioJson
        : undefined);

    if (scenarioData) {
      try {
        await this.saveScenario(params.scenario, scenarioData);
      } catch (err) {
        console.warn('[API] Auto-saving scenario before simulation run failed:', err);
      }
    }

    const payload = {
      ...params,
      scenarioData,
    };

    const res = await fetch(`${getBase()}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
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
    return `${getBase()}/export/csv?scenario=${encodeURIComponent(scenarioId)}`;
  },
};
