import mapDataJson from './mapData.json';
import { EpisodeData, MissionData, ReportData, TickData } from '../types';

export const mockMapData = mapDataJson;

let cachedTicks: TickData[] | null = null;
export async function getMockTicks(): Promise<TickData[]> {
  if (cachedTicks) return cachedTicks;
  const mod = await import('./ticksData.json');
  cachedTicks = (mod.default || mod) as TickData[];
  return cachedTicks;
}

export const mockEpisodes: EpisodeData[] = [
  {
    id: 'ep-1',
    severity: 'warning',
    type: 'person_near_fast',
    category: 'Близость к человеку',
    t_start: 60.4,
    t_end: 61.8,
    x: 120.5,
    y: 150.4,
    cost: -2.00,
    ruleExplanation: 'Робот приближается к человеку на расстояние меньше порогового значения ($d_{\\text{hum}} < 3.0\\,\\text{м}$) при высокой скорости ($|v| > 0.28\\,\\text{м/с}$). Требуется снижение скорости и сохранение безопасной дистанции.',
    telemetrySnapshot: {
      v: 1.15,
      cv: 1.39,
      hum: 2.45,
      obj: 1.80,
      pe_error: 0.62,
      status: 'MOVING',
      note: 'person_near_fast'
    }
  },
  {
    id: 'ep-2',
    severity: 'info',
    type: 'pose_drift',
    category: 'Дрейф позы',
    t_start: 142.7,
    t_end: 144.1,
    x: 87.2,
    y: 95.6,
    cost: -0.69,
    ruleExplanation: 'Ошибка оценки позы pose_est ($\\|\\mathbf{e}_{\\text{pose}}\\| > 1.0\\,\\text{м}$) превысила порог во время движения ($|v| > 0.05\\,\\text{м/с}$) при отсутствии прямой видимости ориентиров GNSS.',
    telemetrySnapshot: {
      v: 0.95,
      cv: 1.00,
      hum: null,
      obj: 3.20,
      pe_error: 1.14,
      status: 'MOVING',
      note: 'scan_match_correction'
    }
  },
  {
    id: 'ep-3',
    severity: 'success',
    type: 'obstacle_close',
    category: 'Близость к препятствию',
    t_start: 215.3,
    t_end: 216.8,
    x: 65.4,
    y: 210.2,
    cost: -0.42,
    ruleExplanation: 'Дистанция до статического препятствия сократилась ($d_{\\text{obj}} = 0.45\\,\\text{м} < 0.8\\,\\text{м}$). Контроллер применил безопасное торможение.',
    telemetrySnapshot: {
      v: 0.40,
      cv: 0.50,
      hum: null,
      obj: 0.45,
      pe_error: 0.18,
      status: 'MOVING',
      note: 'obstacle_slowdown'
    }
  },
  {
    id: 'ep-4',
    severity: 'warning',
    type: 'person_near_slow',
    category: 'Близость к человеку',
    t_start: 298.1,
    t_end: 299.6,
    x: 142.7,
    y: 88.3,
    cost: -0.31,
    ruleExplanation: 'Движение в зоне действия пешеходного перехода вблизи идущего человека.',
    telemetrySnapshot: {
      v: 0.25,
      cv: 0.30,
      hum: 1.85,
      obj: 2.10,
      pe_error: 0.22,
      status: 'MOVING',
      note: 'person_near'
    }
  },
  {
    id: 'ep-5',
    severity: 'info',
    type: 'pose_drift',
    category: 'Дрейф позы',
    t_start: 341.9,
    t_end: 343.2,
    x: 98.6,
    y: 167.5,
    cost: -0.28,
    ruleExplanation: 'Кратковременный уход ориентации heading на повороте платформы.',
    telemetrySnapshot: {
      v: 0.80,
      cv: 1.00,
      hum: null,
      obj: 4.10,
      pe_error: 0.85,
      status: 'MOVING',
      note: 'heading_align'
    }
  },
  {
    id: 'ep-6',
    severity: 'success',
    type: 'speed_limit',
    category: 'Превышение скорости',
    t_start: 402.6,
    t_end: 404.0,
    x: 76.3,
    y: 120.8,
    cost: -0.24,
    ruleExplanation: 'Скорость превысила предел зоны $v_{\\max} = 1.0\\,\\text{м/с}$ более чем на $0.05\\,\\text{м/с}$ ($|v| > v_{\\max} + 0.05\\,\\text{м/с}$) при входе на перекресток.',
    telemetrySnapshot: {
      v: 1.08,
      cv: 1.10,
      hum: null,
      obj: 2.90,
      pe_error: 0.12,
      status: 'MOVING',
      note: 'speed_limited'
    }
  },
  {
    id: 'ep-7',
    severity: 'warning',
    type: 'person_near_fast',
    category: 'Близость к человеку',
    t_start: 468.2,
    t_end: 469.7,
    x: 110.4,
    y: 73.1,
    cost: -0.20,
    ruleExplanation: 'Пешеход вышел из слепой зоны за строением.',
    telemetrySnapshot: {
      v: 0.85,
      cv: 1.20,
      hum: 2.70,
      obj: 1.90,
      pe_error: 0.30,
      status: 'MOVING',
      note: 'ped_avoidance'
    }
  },
  {
    id: 'ep-8',
    severity: 'success',
    type: 'obstacle_close',
    category: 'Близость к препятствию',
    t_start: 523.7,
    t_end: 525.1,
    x: 155.8,
    y: 182.4,
    cost: -0.18,
    ruleExplanation: 'Маневрирование в узком кармане дока B.',
    telemetrySnapshot: {
      v: 0.35,
      cv: 0.35,
      hum: null,
      obj: 0.52,
      pe_error: 0.08,
      status: 'MOVING',
      note: 'dock_align'
    }
  },
  {
    id: 'ep-9',
    severity: 'info',
    type: 'pose_drift',
    category: 'Дрейф позы',
    t_start: 571.0,
    t_end: 572.6,
    x: 62.7,
    y: 144.9,
    cost: -0.16,
    ruleExplanation: 'Инерциальный уход в тени здания склада.',
    telemetrySnapshot: {
      v: 0.60,
      cv: 0.60,
      hum: null,
      obj: 1.50,
      pe_error: 0.72,
      status: 'MOVING',
      note: 'gnss_shadow'
    }
  },
  {
    id: 'ep-10',
    severity: 'success',
    type: 'speed_limit',
    category: 'Превышение скорости',
    t_start: 618.8,
    t_end: 620.2,
    x: 134.6,
    y: 96.7,
    cost: -0.12,
    ruleExplanation: 'Коррекция скорости на выезде из зоны ограничения.',
    telemetrySnapshot: {
      v: 1.04,
      cv: 1.00,
      hum: null,
      obj: 3.80,
      pe_error: 0.15,
      status: 'MOVING',
      note: 'vmax_exit'
    }
  },
  {
    id: 'ep-m-start-m1',
    severity: 'info',
    type: 'mission_start',
    category: 'Старт миссии',
    source: 'mission',
    t_start: 0.0,
    t_end: 1.0,
    x: 20.0,
    y: 30.0,
    cost: 0.0,
    ruleExplanation: 'Старт доставки m1: warehouse $\\rightarrow$ shop_a',
    telemetrySnapshot: {
      v: 0.0,
      cv: 0.0,
      hum: null,
      obj: null,
      pe_error: 0.0,
      status: 'MOVING',
      note: 'start_m1'
    }
  },
  {
    id: 'ep-chk-1',
    severity: 'info',
    type: 'checkpoint',
    category: 'Контрольная точка',
    source: 'checkpoint',
    t_start: 100.0,
    t_end: 101.0,
    x: 50.0,
    y: 60.0,
    cost: 0.0,
    ruleExplanation: 'Штатная контрольная точка на траектории движения.',
    telemetrySnapshot: {
      v: 0.8,
      cv: 0.8,
      hum: null,
      obj: 2.5,
      pe_error: 0.05,
      status: 'MOVING',
      note: 'checkpoint_100'
    }
  }
];

export const mockMissions: MissionData[] = [
  {
    id: 'm1',
    from: 'warehouse',
    to: 'shop_a',
    fromLabel: 'warehouse',
    toLabel: 'shop_a',
    status: 'DELIVERED',
    t_start: 0.0,
    t_end: 159.2,
    t_arrival: 158.3,
    hold_duration_s: 1.0,
    hold_ticks: 10,
    max_hold_dist: 0.0098,
    tol: 0.20,
    deadline_s: 200.7,
    safety_margin_s: 41.5,
    reference_length_m: 174.3,
    actual_time_s: 159.2
  },
  {
    id: 'm2',
    from: 'shop_a',
    to: 'warehouse',
    fromLabel: 'shop_a',
    toLabel: 'warehouse',
    status: 'DELIVERED',
    t_start: 159.2,
    t_end: 328.7,
    t_arrival: 327.8,
    hold_duration_s: 1.0,
    hold_ticks: 10,
    max_hold_dist: 0.0124,
    tol: 0.20,
    deadline_s: 200.7,
    safety_margin_s: 31.2,
    reference_length_m: 174.3,
    actual_time_s: 169.5
  }
];

export const mockReport: ReportData = {
  scenario: '04_busy_yard',
  seed: 7,
  totalScore: 97.31,
  counted: true,
  blocks: [
    { key: 'delivery', name: 'Delivery', achieved: 20.00, max: 20.00, percentage: 100.0 },
    { key: 'efficiency', name: 'Efficiency', achieved: 18.72, max: 20.00, percentage: 93.6 },
    { key: 'safety', name: 'Safety', achieved: 19.64, max: 20.00, percentage: 98.2 },
    { key: 'rules', name: 'Rules', achieved: 19.27, max: 20.00, percentage: 96.4 },
    { key: 'pose', name: 'Pose', achieved: 18.95, max: 20.00, percentage: 94.7 },
    { key: 'collisions', name: 'Collisions', achieved: 19.78, max: 20.00, percentage: 98.9 }
  ],
  computeBudget: {
    limit_s: 600,
    fact_s: 1.55,
    mean_step_ms: 0.22,
    max_step_ms: 21.34,
    step_distribution: [
      { bin: 0, count: 42 },
      { bin: 1, count: 145 },
      { bin: 2, count: 128 },
      { bin: 3, count: 110 },
      { bin: 4, count: 94 },
      { bin: 5, count: 72 },
      { bin: 6, count: 58 },
      { bin: 7, count: 45 },
      { bin: 8, count: 34 },
      { bin: 9, count: 28 },
      { bin: 10, count: 22 },
      { bin: 12, count: 16 },
      { bin: 14, count: 12 },
      { bin: 16, count: 8 },
      { bin: 18, count: 5 },
      { bin: 20, count: 3 },
      { bin: 22, count: 1 }
    ]
  },
  sandbox: {
    violations: [],
    stderr_tail: [
      '[INFO] Sandbox initialized successfully',
      '[INFO] Loading scenario: 04_busy_yard',
      '[INFO] Running simulation...',
      '[INFO] No violations detected',
      '[INFO] Simulation finished'
    ]
  }
};

export const mockDashboardData = {
  totalScore: 97.31,
  totalMax: 100,
  deliveriesCount: 2,
  deliveriesTotal: 2,
  safetyFatal: 0,
  safetyWarnings: 3,
  localizationError: 0.18,
  recentEvents: [
    {
      id: 'e1',
      title: 'AMR-1  Доставка завершена (Док 2)',
      detail: 'Задача #D-042, 12.6 м',
      time: '10:24',
      status: 'success'
    },
    {
      id: 'e2',
      title: 'AMR-2  Предупреждение: близость к препятствию',
      detail: 'Расстояние 1.2 м',
      time: '10:21',
      status: 'warning'
    },
    {
      id: 'e3',
      title: 'Система  Изменение сценария на 04_busy_yard',
      detail: 'Пользователь: operator',
      time: '10:00',
      status: 'info'
    }
  ],
  controllerState: {
    online: true,
    meanDelayMs: 0.22,
    maxDelayMs: 21.3
  },
  speedHistory: [
    0.0, 0.2, 0.35, 0.4, 0.3, 0.45, 0.55, 0.5, 0.38, 0.42,
    0.5, 0.6, 0.55, 0.42, 0.3, 0.1, 0.4, 0.5, 0.52, 0.48,
    0.35, 0.4, 0.2, 0.1, 0.35, 0.5, 0.45, 0.3, 0.15, 0.3,
    0.55, 0.65, 0.62, 0.5, 0.35, 0.15, 0.4, 0.65, 0.75, 0.6
  ]
};
