export type RouteName = 'dashboard' | 'replay' | 'episodes' | 'missions' | 'analytics' | 'runner';

export interface TickData {
  t: number;
  x: number;
  y: number;
  th: number;
  v: number;
  w: number;
  cv: number;
  cw: number;
  st: 'moving' | 'arrived' | 'waiting' | 'lost' | 'estop' | string;
  pe: [number, number, number] | null;
  nt: string | null;
  m: string | null;
  drv: 1 | 0;
  fbd: 1 | 0;
  vmax: number | null;
  hum: number | null;
  obj: number | null;
  coll: 1 | 0;
  cont: 1 | 0;
  pe_error?: number;
  peds?: [number, number][];
  lidarRays?: { angle: number; dist: number }[];
}

export interface EpisodeData {
  id: string;
  severity: 'warning' | 'info' | 'critical' | 'success';
  type: string;
  category: string;
  source?: 'report' | 'mission' | 'telemetry' | 'checkpoint' | string;
  t_start: number;
  t_end: number;
  x: number;
  y: number;
  cost: number;
  ruleExplanation?: string;
  telemetrySnapshot?: {
    v: number;
    cv: number;
    hum: number | null;
    obj: number | null;
    pe_error: number;
    status: string;
    note: string;
  };
}

export interface MissionData {
  id: string;
  from: string;
  to: string;
  fromLabel: string;
  toLabel: string;
  status: 'DELIVERED' | 'TIMEOUT' | 'FAILED';
  t_start: number;
  t_end: number;
  t_arrival: number;
  hold_duration_s: number;
  hold_ticks: number;
  max_hold_dist: number;
  tol: number;
  deadline_s: number;
  safety_margin_s: number;
  reference_length_m: number;
  actual_time_s: number;
}

export interface ScoreBlock {
  key: string;
  name: string;
  achieved: number;
  max: number;
  percentage: number;
}

export interface ReportData {
  scenario: string;
  seed: number;
  totalScore: number;
  counted: boolean;
  blocks: ScoreBlock[];
  computeBudget: {
    limit_s: number;
    fact_s: number;
    mean_step_ms: number;
    max_step_ms: number;
    step_distribution: { bin: number; count: number }[];
  };
  sandbox: {
    violations: string[];
    stderr_tail: string[];
  };
}

export interface MapData {
  bounds: [number, number, number, number];
  drivable: any[];
  buildings: any[];
  zones: any[];
  gates?: any[];
  crossing?: any[];
  points: Record<string, { x: number; y: number; heading: number; tol: number; label: string }>;
  referencePaths?: [number, number][][];
  map_patches?: Array<{
    id: string;
    op?: string;
    polygon?: [number, number][];
    [key: string]: any;
  }>;
  events?: Array<{
    type: string;
    t?: number;
    x?: number;
    y?: number;
    r?: number;
    [key: string]: any;
  }>;
}

export interface ScenarioItem {
  id: string;
  name: string;
  description: string;
  type: 'standard' | 'custom';
  file: string;
  hasReport: boolean;
  score: number | null;
}

export interface RecentEvent {
  id: string;
  title: string;
  detail: string;
  time: string;
  status: 'success' | 'warning' | 'info' | 'critical';
}

export interface DashboardViewModel {
  scenario: string;
  totalScore: number;
  totalMax: number;
  deliveriesCount: number;
  deliveriesTotal: number;
  safetyFatal: number;
  safetyWarnings: number;
  localizationError: number | null;
  recentEvents: RecentEvent[];
  controllerState: {
    online: boolean;
    meanDelayMs: number;
    maxDelayMs: number;
    nSteps?: number;
  };
  speedHistory: number[];
  speedTimestamps: string[];
  previewTick: TickData | null;
  historyTicks: TickData[];
  mapData: MapData;
}

export interface ReplayMissionData {
  id: string;
  from: string;
  to: string;
  fromLabel: string;
  toLabel: string;
  deadline_s: number;
  t_start: number;
}

export interface ReplayViewModel {
  scenario: string;
  seed: number;
  header: any;
  mapData: MapData;
  ticks: TickData[];
  missions?: ReplayMissionData[];
  totalTicks: number;
  duration: number;
  episodes: {
    id?: string;
    t_start: number;
    t_end: number;
    type: string;
    category?: string;
    cost: number;
    x: number;
    y: number;
  }[];
}

export interface EpisodesViewModel {
  scenario: string;
  summary: {
    totalCost: number;
    fatalCount: number;
    warningsCount: number;
    ruleViolationsCount: number;
  };
  episodes: EpisodeData[];
}

export interface MissionsViewModel {
  scenario: string;
  summary: {
    completed: number;
    total: number;
    deliveryScore: number;
    maxDeliveryScore: number;
    efficiencyScore: number;
    maxEfficiencyScore: number;
  };
  missions: MissionData[];
}

export interface AnalyticsViewModel {
  scenario: string;
  seed: number;
  totalScore: number;
  counted: boolean;
  blocks: ScoreBlock[];
  radar: {
    labels: string[];
    values: number[];
    maxValues: number[];
  };
  computeBudget: {
    limit_s: number;
    fact_s: number;
    mean_step_ms: number;
    max_step_ms: number;
    step_limit_ms?: number;
    ok?: boolean;
    step_distribution: { bin: number; count: number }[];
  };
  sandbox: {
    passed?: boolean;
    violations: string[];
    warnings?: string[];
    stderr_tail: string[];
  };
}

export interface SimulationRunParams {
  scenario: string;
  controller?: string;
  seed?: number;
  cheatPose?: boolean;
  scenarioData?: any;
}

export interface SimulationRunResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  reportPath: string;
  logPath: string;
  report?: any;
  score: number | null;
  logs?: string[];
}

export interface ScenarioMapPatch {
  id: string;
  op: string;
  polygon: [number, number][];
  heading?: number;
  [key: string]: any;
}

export interface ScenarioPedestrian {
  id: string;
  waypoints: [number, number][];
  speed?: number;
  inattentive?: boolean;
  loop?: boolean;
  t_start?: number;
  heading?: number;
  [key: string]: any;
}

export interface ScenarioZone {
  id?: string;
  type: 'speed_limit' | 'forbidden' | 'gnss_shadow' | 'people_area' | string;
  polygon?: [number, number][];
  max_speed?: number;
  [key: string]: any;
}

export interface AmrScenario {
  schema?: string;
  name: string;
  description?: string;
  dt?: number;
  duration_s?: number;
  hidden?: boolean;
  provide_detections?: boolean;
  weather?: {
    snow?: boolean;
    [key: string]: any;
  };
  events?: {
    type: string;
    t1: number;
    t2: number;
    [key: string]: any;
  }[];
  start: {
    x: number;
    y: number;
    theta: number;
    [key: string]: any;
  };
  map: {
    frame?: string;
    bounds?: [number, number, number, number];
    drivable?: any[];
    buildings?: any[];
    points?: Record<string, any>;
    zones?: ScenarioZone[];
    gates?: any[];
    crossing?: any[];
    [key: string]: any;
  };
  map_patches?: ScenarioMapPatch[];
  pedestrians?: ScenarioPedestrian[];
  missions?: any[];
  [key: string]: any;
}

