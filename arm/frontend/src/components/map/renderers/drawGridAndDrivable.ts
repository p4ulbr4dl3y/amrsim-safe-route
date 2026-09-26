import { MapData } from '../../../types';
import { MapLayersConfig } from '../../MapCanvas';

export interface DrawGridAndDrivableOptions {
  ctx: CanvasRenderingContext2D;
  mapData: MapData;
  bounds: { minX: number; minY: number; maxX: number; maxY: number };
  toScreen: (wx: number, wy: number) => { x: number; y: number };
  scale: number;
  layers: Pick<MapLayersConfig, 'drivable' | 'buildings' | 'docks'>;
  isMiniMap?: boolean;
}

/**
 * Draws background grid, warehouse perimeter, drivable lanes, zones, buildings, and dock stations.
 */
export function drawGridAndDrivable({
  ctx,
  mapData,
  bounds: { minX, minY, maxX, maxY },
  toScreen,
  scale,
  layers,
  isMiniMap = false,
}: DrawGridAndDrivableOptions): void {
  // 1. Фоновая сетка
  ctx.strokeStyle = '#F1F5F9';
  ctx.lineWidth = 1;
  const gridSize = 20; // 20 метров
  for (let x = minX; x <= maxX; x += gridSize) {
    const p1 = toScreen(x, minY);
    const p2 = toScreen(x, maxY);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }
  for (let y = minY; y <= maxY; y += gridSize) {
    const p1 = toScreen(minX, y);
    const p2 = toScreen(maxX, y);
    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
  }

  // Внешний периметр склада
  ctx.strokeStyle = '#CBD5E1';
  ctx.lineWidth = 1.5;
  const pTopLeft = toScreen(minX, maxY);
  const pBotRight = toScreen(maxX, minY);
  ctx.strokeRect(pTopLeft.x, pTopLeft.y, pBotRight.x - pTopLeft.x, pBotRight.y - pTopLeft.y);

  // 2. Проезжие коридоры
  if (layers.drivable && mapData.drivable) {
    ctx.fillStyle = '#E8EEF5';
    ctx.strokeStyle = '#CBD5E1';
    ctx.lineWidth = 1.5;

    mapData.drivable.forEach((poly: any) => {
      if (poly && poly.length > 1) {
        ctx.beginPath();
        const start = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < poly.length; i++) {
          const pt = toScreen(poly[i][0], poly[i][1]);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    });
  }

  // 3. Зоны: запретные и с ограничением скорости
  if (mapData.zones) {
    mapData.zones.forEach((zone: any) => {
      const poly = zone.polygon || zone.points;
      if (!poly || poly.length < 2) return;
      ctx.beginPath();
      const start = toScreen(poly[0][0], poly[0][1]);
      ctx.moveTo(start.x, start.y);
      for (let i = 1; i < poly.length; i++) {
        const pt = toScreen(poly[i][0], poly[i][1]);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.closePath();

      if (zone.type === 'forbidden') {
        ctx.fillStyle = 'rgba(239, 68, 68, 0.12)';
        ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
        ctx.lineWidth = 1.5;
        ctx.fill();
        ctx.stroke();
      } else if (zone.type === 'speed_limit') {
        ctx.fillStyle = 'rgba(245, 158, 11, 0.08)';
        ctx.strokeStyle = 'rgba(245, 158, 11, 0.35)';
        ctx.lineWidth = 1;
        ctx.fill();
        ctx.stroke();
      }
    });
  }

  // 4. Здания: складские блоки
  if (layers.buildings && mapData.buildings) {
    ctx.fillStyle = '#DDE3EA';
    ctx.strokeStyle = '#94A3B8';
    ctx.lineWidth = 1.2;

    mapData.buildings.forEach((b: any) => {
      const poly = b.polygon || b.points;
      if (poly && poly.length > 1) {
        ctx.beginPath();
        const start = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < poly.length; i++) {
          const pt = toScreen(poly[i][0], poly[i][1]);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    });
  }

  // 5. Станции доков
  if (layers.docks && mapData.points) {
    Object.entries(mapData.points).forEach(([id, pt]: [string, any]) => {
      const screenPt = toScreen(pt.x, pt.y);

      // Внешний круг: радиус допуска
      ctx.beginPath();
      ctx.arc(screenPt.x, screenPt.y, Math.max(7, (pt.tol || 0.2) * scale * 10), 0, Math.PI * 2);
      ctx.strokeStyle = '#2563EB';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Внутренняя точка
      ctx.beginPath();
      ctx.arc(screenPt.x, screenPt.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = '#2563EB';
      ctx.fill();

      // Метка дока
      if (!isMiniMap) {
        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = '#475569';
        ctx.textAlign = 'left';
        ctx.fillText(pt.label || id, screenPt.x + 10, screenPt.y + 3);
      }
    });
  }
}
