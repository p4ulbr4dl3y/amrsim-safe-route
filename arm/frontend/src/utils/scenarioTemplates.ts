import { AmrScenario } from '../types';
import { mockMapData } from '../mock/mockData';

export interface ScenarioTemplateOption {
  id: string;
  name: string;
  description: string;
  createScenario: () => AmrScenario;
}

/**
 * Создает глубокую копию базовой геометрии карты полигона.
 */
export function getBaseWarehouseMap() {
  return JSON.parse(JSON.stringify(mockMapData));
}

export const scenarioTemplates: ScenarioTemplateOption[] = [
  {
    id: '01_clear',
    name: '01_clear (Ясная погода и штатная доставка)',
    description: 'Базовый склад 250×200м: ясная погода, 2 пешехода во дворе, доставка между складом и цехом А.',
    createScenario: (): AmrScenario => {
      const map = getBaseWarehouseMap();
      return {
        schema: 'amr-1.0',
        name: '01_clear_custom',
        description: 'Пользовательский сценарий на базе ясной погоды. Доставка Склад <-> Цех А.',
        dt: 0.1,
        duration_s: 411.3,
        hidden: false,
        provide_detections: false,
        weather: {
          snow: false,
        },
        map: {
          frame: 'x east, y north, meters; heading radians from +x counterclockwise',
          bounds: map.bounds || [0, 0, 250, 200],
          drivable: map.drivable || [],
          buildings: map.buildings || [],
          points: map.points || {},
          zones: map.zones || [],
          gates: map.gates || [],
          crossing: map.crossing || [],
        },
        map_patches: [],
        start: {
          x: 51.5,
          y: 150.0,
          theta: 0.0,
        },
        missions: [
          {
            id: 'm1',
            from: 'warehouse',
            to: 'shop_a',
            deadline_s: 200.7,
            reference_length_m: 174.32,
            reference_path: [
              [51.5, 150.0],
              [55.0, 150.0],
              [217.5, 151.0],
              [219.0, 152.5],
              [220.0, 155.0],
              [220.0, 158.5],
            ],
          },
          {
            id: 'm2',
            from: 'shop_a',
            to: 'warehouse',
            deadline_s: 200.6,
            reference_length_m: 174.27,
            reference_path: [
              [220.0, 158.5],
              [220.0, 155.0],
              [218.5, 152.0],
              [217.5, 151.0],
              [55.0, 150.0],
              [51.5, 150.0],
            ],
          },
        ],
        pedestrians: [
          {
            id: 'p1',
            waypoints: [
              [125, 130],
              [125, 163],
            ],
            speed: 1.0,
            inattentive: false,
            loop: true,
            t_start: 15.0,
          },
          {
            id: 'p2',
            waypoints: [
              [140, 163],
              [140, 128],
            ],
            speed: 1.2,
            inattentive: false,
            loop: true,
            t_start: 60.0,
          },
        ],
        events: [],
      };
    },
  },
  {
    id: '04_busy_yard',
    name: '04_busy_yard (Оживленный двор с поддонами и контейнерами)',
    description: 'Интенсивное движение, динамические пешеходы, статические препятствия (контейнеры и паллеты).',
    createScenario: (): AmrScenario => {
      const base = scenarioTemplates[0].createScenario();
      return {
        ...base,
        name: '04_busy_yard_custom',
        description: 'Оживленный двор складского комплекса с препятствиями и несколькими пешеходами.',
        map_patches: [
          {
            id: 'PALLET_1',
            op: 'add',
            polygon: [
              [120, 148],
              [121.2, 148],
              [121.2, 148.8],
              [120, 148.8],
            ],
          },
          {
            id: 'CONTAINER_1',
            op: 'add',
            polygon: [
              [110, 132],
              [116, 132],
              [116, 134.5],
              [110, 134.5],
            ],
          },
        ],
        pedestrians: [
          ...base.pedestrians,
          {
            id: 'p3',
            waypoints: [
              [170, 135],
              [170, 155],
            ],
            speed: 0.9,
            inattentive: true,
            loop: true,
            t_start: 35.0,
          },
        ],
      };
    },
  },
  {
    id: '03_fog_snow',
    name: '03_fog_snow (Туман, метель и зоны тени ГНСС)',
    description: 'Включен снег (зашумление лидара и проскальзывание колес), события полос тумана и сбоев спутников.',
    createScenario: (): AmrScenario => {
      const base = scenarioTemplates[0].createScenario();
      return {
        ...base,
        name: '03_fog_snow_custom',
        description: 'Зимние экстремальные условия: метель, два фронта плотного тумана и пропадание GNSS.',
        weather: {
          snow: true,
        },
        events: [
          {
            type: 'fog_bank',
            t1: 40.0,
            t2: 110.0,
          },
          {
            type: 'gnss_outage',
            t1: 55.0,
            t2: 100.0,
          },
          {
            type: 'fog_bank',
            t1: 230.0,
            t2: 300.0,
          },
        ],
      };
    },
  },
  {
    id: 'empty_warehouse',
    name: 'Пустой склад (Без препятствий и пешеходов)',
    description: 'Чистая геометрия склада и проездов, готовая для ручной расстановки объектов с нуля.',
    createScenario: (): AmrScenario => {
      const base = scenarioTemplates[0].createScenario();
      return {
        ...base,
        name: 'new_scenario',
        description: 'Новый пользовательский сценарий.',
        map_patches: [],
        pedestrians: [],
        events: [],
      };
    },
  },
];
