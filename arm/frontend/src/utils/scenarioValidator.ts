import { AmrScenario } from '../types';

export interface ScenarioValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  scenario?: AmrScenario;
}

/**
 * Валидатор структуры сценария AMR (формат amrsim, схема amr-1.0).
 * Возвращает статус валидации, список критических ошибок и предупреждений на русском языке.
 */
export function validateScenario(jsonInput: unknown): ScenarioValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!jsonInput || typeof jsonInput !== 'object' || Array.isArray(jsonInput)) {
    return {
      valid: false,
      errors: ['Файл не содержит корректного JSON-объекта сценария'],
      warnings: [],
    };
  }

  const data = jsonInput as Record<string, any>;

  // 1. Схема
  if (!data.schema) {
    errors.push('Отсутствует обязательное поле "schema"');
  } else if (data.schema !== 'amr-1.0') {
    errors.push(`Неподдерживаемая схема "${data.schema}". Требуется "amr-1.0"`);
  }

  // 2. Имя сценария
  if (!data.name || typeof data.name !== 'string' || data.name.trim() === '') {
    errors.push('Поле "name" должно содержать непустую строку (идентификатор сценария)');
  }

  // 3. Параметры времени
  if (data.dt === undefined || typeof data.dt !== 'number' || data.dt <= 0) {
    errors.push('Шаг времени "dt" должен быть положительным числом (например, 0.1)');
  }

  if (data.duration_s === undefined || typeof data.duration_s !== 'number' || data.duration_s <= 0) {
    errors.push('Длительность симуляции "duration_s" должна быть положительным числом в секундах');
  }

  // 4. Начальная позиция робота (start)
  if (!data.start || typeof data.start !== 'object') {
    errors.push('Отсутствует объект "start" с начальными координатами робота');
  } else {
    if (typeof data.start.x !== 'number') {
      errors.push('Начальная координата робота "start.x" должна быть числом');
    }
    if (typeof data.start.y !== 'number') {
      errors.push('Начальная координата робота "start.y" должна быть числом');
    }
    if (typeof data.start.theta !== 'number') {
      warnings.push('Угол ориентации "start.theta" не указан или некорректен, будет использован 0.0');
    }
  }

  // 5. Карта (map)
  if (!data.map || typeof data.map !== 'object') {
    errors.push('Отсутствует объект карты "map"');
  } else {
    const map = data.map;

    // Границы карты (bounds)
    if (!Array.isArray(map.bounds) || map.bounds.length !== 4) {
      errors.push('Поле "map.bounds" должно содержать массив из 4 чисел [minX, minY, maxX, maxY]');
    } else {
      const [minX, minY, maxX, maxY] = map.bounds;
      if (typeof minX !== 'number' || typeof minY !== 'number' || typeof maxX !== 'number' || typeof maxY !== 'number') {
        errors.push('Все элементы "map.bounds" должны быть числами');
      } else if (minX >= maxX || minY >= maxY) {
        errors.push(`Некорректные границы карты: [${minX}, ${minY}, ${maxX}, ${maxY}]. Ожидается minX < maxX и minY < maxY`);
      }
    }

    // Проезжаемые зоны (drivable)
    if (!Array.isArray(map.drivable)) {
      warnings.push('В карте отсутствует массив проезжаемых зон "map.drivable"');
    } else if (map.drivable.length === 0) {
      warnings.push('Список проезжаемых зон "map.drivable" пуст');
    }

    // Точки назначения и доки (points)
    const points = map.points || data.points;
    if (!points || typeof points !== 'object') {
      warnings.push('Не заданы целевые док-станции ("map.points")');
    }

    // Зоны (zones)
    if (map.zones && Array.isArray(map.zones)) {
      map.zones.forEach((z: any, idx: number) => {
        if (!z.id) warnings.push(`Зона #${idx + 1} не имеет поля "id"`);
        if (!z.type) warnings.push(`Зона #${z.id || idx + 1} не имеет поля "type"`);
        if (!Array.isArray(z.polygon) || z.polygon.length < 3) {
          errors.push(`Зона "${z.id || idx + 1}" имеет некорректный полигон (минимум 3 вершины)`);
        }
        if (z.type === 'speed_limit' && (typeof z.v_max !== 'number' || z.v_max <= 0)) {
          errors.push(`Зона ограничения скорости "${z.id || idx + 1}" требует положительное значение "v_max"`);
        }
      });
    }
  }

  // 6. Пешеходы (pedestrians)
  if (data.pedestrians) {
    if (!Array.isArray(data.pedestrians)) {
      errors.push('Поле "pedestrians" должно быть массивом');
    } else {
      data.pedestrians.forEach((p: any, idx: number) => {
        const id = p.id || `p_${idx + 1}`;
        if (!Array.isArray(p.waypoints) || p.waypoints.length === 0) {
          errors.push(`Пешеход "${id}" не имеет точек маршрута ("waypoints")`);
        }
        if (typeof p.speed !== 'number' || p.speed <= 0) {
          warnings.push(`Пешеход "${id}": скорость должна быть положительным числом`);
        }
      });
    }
  }

  // 7. Погода (weather)
  if (data.weather && typeof data.weather !== 'object') {
    warnings.push('Поле "weather" должно быть объектом { snow: boolean }');
  }

  const valid = errors.length === 0;

  // Если валидно, формируем нормализованный объект AmrScenario
  let scenario: AmrScenario | undefined = undefined;
  if (valid) {
    const rawMap = data.map || {};
    scenario = {
      schema: 'amr-1.0',
      name: String(data.name).trim(),
      description: String(data.description || '').trim(),
      dt: Number(data.dt) || 0.1,
      duration_s: Number(data.duration_s) || 400.0,
      hidden: Boolean(data.hidden),
      provide_detections: Boolean(data.provide_detections),
      weather: {
        snow: Boolean(data.weather?.snow),
      },
      map: {
        frame: rawMap.frame || 'x east, y north, meters; heading radians from +x counterclockwise',
        bounds: rawMap.bounds || [0, 0, 250, 200],
        drivable: Array.isArray(rawMap.drivable) ? rawMap.drivable : [],
        buildings: Array.isArray(rawMap.buildings) ? rawMap.buildings : [],
        points: rawMap.points || data.points || {},
        zones: Array.isArray(rawMap.zones) ? rawMap.zones : [],
        gates: Array.isArray(rawMap.gates) ? rawMap.gates : [],
        crossing: Array.isArray(rawMap.crossing) ? rawMap.crossing : [],
      },
      map_patches: Array.isArray(data.map_patches) ? data.map_patches : [],
      start: {
        x: Number(data.start.x),
        y: Number(data.start.y),
        theta: Number(data.start.theta) || 0,
      },
      missions: Array.isArray(data.missions) ? data.missions : [],
      pedestrians: Array.isArray(data.pedestrians) ? data.pedestrians : [],
      events: Array.isArray(data.events) ? data.events : [],
    };
  }

  return {
    valid,
    errors,
    warnings,
    scenario,
  };
}
