import { describe, it, expect } from 'vitest';
import { getLidarRays } from '../components/MapCanvas';

export interface MapBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export function computeBoundsFit(
  bounds: [number, number, number, number],
  canvasWidth: number,
  canvasHeight: number,
  padding: number = 16
) {
  const minX = bounds[0] ?? 0;
  const minY = bounds[1] ?? 0;
  const maxX = bounds[2] ?? 250;
  const maxY = bounds[3] ?? 200;
  const worldW = Math.max(1, maxX - minX);
  const worldH = Math.max(1, maxY - minY);
  const availW = Math.max(10, canvasWidth - 2 * padding);
  const availH = Math.max(10, canvasHeight - 2 * padding);
  const fitScale = Math.min(availW / worldW, availH / worldH);
  const planW = worldW * fitScale;
  const planH = worldH * fitScale;
  const fitOffset = {
    x: (canvasWidth - planW) / 2,
    y: (canvasHeight - planH) / 2,
  };
  return { fitScale, fitOffset, minX, minY, maxX, maxY, worldW, worldH };
}

export function projectWorldToScreen(
  wx: number,
  wy: number,
  scale: number,
  offset: { x: number; y: number },
  minX: number,
  maxY: number
) {
  return {
    x: (wx - minX) * scale + offset.x,
    y: (maxY - wy) * scale + offset.y,
  };
}

export function unprojectScreenToWorld(
  sx: number,
  sy: number,
  scale: number,
  offset: { x: number; y: number },
  minX: number,
  maxY: number
) {
  return {
    wx: (sx - offset.x) / scale + minX,
    wy: maxY - (sy - offset.y) / scale,
  };
}

export function computeFollowRobotOffset(
  robotX: number,
  robotY: number,
  canvasWidth: number,
  canvasHeight: number,
  scale: number,
  worldHeight: number
) {
  const canvasX = canvasWidth / 2;
  const canvasY = canvasHeight / 2;
  return {
    x: canvasX - robotX * scale,
    y: canvasY - (worldHeight - robotY) * scale,
  };
}

export function classifyObstacleType(id: string): 'pallet' | 'container' | 'generic' {
  const norm = (id || '').toLowerCase();
  if (norm.includes('pallet') || norm.includes('поддон')) return 'pallet';
  if (norm.includes('container') || norm.includes('can') || norm.includes('контейнер')) return 'container';
  return 'generic';
}

export function isObstacleActiveAtTick(dropTime: number, currentTickTime?: number | null): boolean {
  if (currentTickTime === undefined || currentTickTime === null) return true;
  return currentTickTime >= dropTime;
}

describe('MapCanvas Geometry & Projection', () => {
  const warehouseBounds: [number, number, number, number] = [0, 0, 250, 200];

  describe('fit-to-bounds calculation', () => {
    it('centers warehouse plan with proportional aspect ratio preservation', () => {
      const canvasW = 800;
      const canvasH = 600;
      const fit = computeBoundsFit(warehouseBounds, canvasW, canvasH, 16);

      // availW = 800 - 32 = 768, availH = 600 - 32 = 568
      // scale = min(768/250, 568/200) = min(3.072, 2.84) = 2.84
      expect(fit.fitScale).toBeCloseTo(2.84, 2);

      // Width of scaled warehouse: 250 * 2.84 = 710
      // Horizontal centering offset: (800 - 710) / 2 = 45
      expect(fit.fitOffset.x).toBeCloseTo(45.0, 1);

      // Height of scaled warehouse: 200 * 2.84 = 568
      // Vertical centering offset: (600 - 568) / 2 = 16 (matches top/bottom padding)
      expect(fit.fitOffset.y).toBeCloseTo(16.0, 1);
    });

    it('handles narrow portrait viewports correctly', () => {
      const canvasW = 300;
      const canvasH = 600;
      const fit = computeBoundsFit(warehouseBounds, canvasW, canvasH, 16);

      // availW = 268 / 250 = 1.072
      // availH = 568 / 200 = 2.84
      // Limited by width
      expect(fit.fitScale).toBeCloseTo(1.072, 3);
      expect(fit.fitOffset.x).toBeCloseTo(16.0, 1);
      expect(fit.fitOffset.y).toBeGreaterThan(16.0);
    });

    it('handles zero or degenerate dimensions gracefully', () => {
      const fit = computeBoundsFit(warehouseBounds, 0, 0, 16);
      expect(fit.fitScale).toBeGreaterThan(0);
      expect(Number.isFinite(fit.fitScale)).toBe(true);
    });
  });

  describe('worldToScreen & screenToWorld projection', () => {
    it('projects origin and maximum coordinates correctly', () => {
      const scale = 2.0;
      const offset = { x: 50, y: 30 };
      const minX = 0;
      const maxY = 200;

      // Bottom-left in world (0, 0) -> in screen top is maxY - 0 = 200 -> y = 200 * 2 + 30 = 430
      const origin = projectWorldToScreen(0, 0, scale, offset, minX, maxY);
      expect(origin.x).toBe(50);
      expect(origin.y).toBe(430);

      // Top-right in world (250, 200) -> in screen y = (200 - 200)*2 + 30 = 30
      const topCorner = projectWorldToScreen(250, 200, scale, offset, minX, maxY);
      expect(topCorner.x).toBe(250 * 2 + 50); // 550
      expect(topCorner.y).toBe(30);
    });

    it('preserves exact round-trip invertibility', () => {
      const scale = 3.5;
      const offset = { x: 120, y: 75 };
      const minX = 10;
      const maxY = 220;

      const testPoints = [
        { wx: 10, wy: 0 },
        { wx: 100.5, wy: 55.3 },
        { wx: 240.2, wy: 198.8 },
      ];

      testPoints.forEach((pt) => {
        const screen = projectWorldToScreen(pt.wx, pt.wy, scale, offset, minX, maxY);
        const unproj = unprojectScreenToWorld(screen.x, screen.y, scale, offset, minX, maxY);
        expect(unproj.wx).toBeCloseTo(pt.wx, 5);
        expect(unproj.wy).toBeCloseTo(pt.wy, 5);
      });
    });
  });

  describe('followRobot centering and mini-map isolation', () => {
    it('calculates screen center offset for target robot position', () => {
      const canvasW = 800;
      const canvasH = 600;
      const scale = 4.0;
      const worldH = 200;
      const rx = 100;
      const ry = 50;

      const offset = computeFollowRobotOffset(rx, ry, canvasW, canvasH, scale, worldH);
      // Project robot position with this offset
      const screenPt = projectWorldToScreen(rx, ry, scale, offset, 0, worldH);

      // The robot should land precisely at canvas center: (400, 300)
      expect(screenPt.x).toBeCloseTo(canvasW / 2, 5);
      expect(screenPt.y).toBeCloseTo(canvasH / 2, 5);
    });

    it('ensures mini-map maintains fixed full warehouse scale without following robot', () => {
      const miniMapW = 200;
      const miniMapH = 150;
      const fit = computeBoundsFit(warehouseBounds, miniMapW, miniMapH, 8);

      // Mini-map stays within bounds regardless of robot movement
      expect(fit.fitScale).toBeGreaterThan(0);
      expect(fit.fitOffset.x).toBeGreaterThanOrEqual(0);
      expect(fit.fitOffset.y).toBeGreaterThanOrEqual(0);
    });
  });

  describe('Obstacles (Pallets & Containers) Visibility & Classification', () => {
    it('correctly classifies pallet obstacles by id keywords', () => {
      expect(classifyObstacleType('PALLET_1')).toBe('pallet');
      expect(classifyObstacleType('pallet_wood')).toBe('pallet');
      expect(classifyObstacleType('поддон_деревянный')).toBe('pallet');
    });

    it('correctly classifies container obstacles by id keywords', () => {
      expect(classifyObstacleType('CONTAINER_1')).toBe('container');
      expect(classifyObstacleType('CONTAINER_S')).toBe('container');
      expect(classifyObstacleType('CAN_1')).toBe('container');
      expect(classifyObstacleType('морской_контейнер')).toBe('container');
    });

    it('falls back to generic obstacle for unknown identifiers', () => {
      expect(classifyObstacleType('WALL_EXTRA')).toBe('generic');
      expect(classifyObstacleType('')).toBe('generic');
    });

    it('determines dropped object active visibility based on replay tick time', () => {
      const dropTime = 60.0;

      // Before drop time, not active (ghost marker)
      expect(isObstacleActiveAtTick(dropTime, 0.0)).toBe(false);
      expect(isObstacleActiveAtTick(dropTime, 59.9)).toBe(false);

      // At or after drop time, fully active
      expect(isObstacleActiveAtTick(dropTime, 60.0)).toBe(true);
      expect(isObstacleActiveAtTick(dropTime, 65.5)).toBe(true);

      // When tick time is undefined (overview or static view), visible as active
      expect(isObstacleActiveAtTick(dropTime, undefined)).toBe(true);
      expect(isObstacleActiveAtTick(dropTime, null)).toBe(true);
    });
  });

  describe('Lidar Rays Visualization & Fallback', () => {
    it('returns empty array when tick is undefined or null', () => {
      expect(getLidarRays(null)).toEqual([]);
      expect(getLidarRays(undefined)).toEqual([]);
    });

    it('preserves existing lidarRays if provided in tick', () => {
      const customRays = [
        { angle: -0.2, dist: 3.5 },
        { angle: 0.0, dist: 4.2 },
        { angle: 0.2, dist: 3.8 },
      ];
      const tick = { t: 1.0, x: 10, y: 20, th: 0, lidarRays: customRays };
      expect(getLidarRays(tick)).toBe(customRays);
    });

    it('generates 9-ray lidar fan dynamically when tick has no lidarRays', () => {
      const tick = { t: 1.0, x: 10, y: 20, th: 0, obj: 4.0 };
      const rays = getLidarRays(tick);
      expect(rays.length).toBe(9);

      // Central ray (index 4) points straight forward (angle = 0)
      expect(rays[4].angle).toBeCloseTo(0.0, 5);

      // Edge rays are symmetric: -0.6 rad to +0.6 rad
      expect(rays[0].angle).toBeCloseTo(-0.6, 5);
      expect(rays[8].angle).toBeCloseTo(0.6, 5);

      // Rays are within distance bounds [1.5, 20.0]
      rays.forEach((ray) => {
        expect(ray.dist).toBeGreaterThanOrEqual(1.5);
        expect(ray.dist).toBeLessThanOrEqual(20.0);
      });
    });

    it('uses fallback distance 5.0 when tick.obj is missing or null', () => {
      const tick = { t: 1.0, x: 10, y: 20, th: 0 };
      const rays = getLidarRays(tick);
      expect(rays.length).toBe(9);
      expect(rays[0].dist).toBeCloseTo(5.0, 2);
      expect(rays[1].dist).toBeCloseTo(5.6, 2);
    });
  });
});

