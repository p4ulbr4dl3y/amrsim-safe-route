import { MapData, TickData } from '../../../types';
import { MapLayersConfig } from '../../MapCanvas';

export interface DrawPathsOptions {
  ctx: CanvasRenderingContext2D;
  mapData: MapData;
  toScreen: (wx: number, wy: number) => { x: number; y: number };
  historyTicks?: TickData[];
  layers: Pick<MapLayersConfig, 'referencePath'>;
}

/**
 * Draws reference routes and robot historical trajectory path.
 */
export function drawPaths({
  ctx,
  mapData,
  toScreen,
  historyTicks = [],
  layers,
}: DrawPathsOptions): void {
  // 1. Опорный путь: пунктирная линия из данных сценария
  if (layers.referencePath) {
    const paths = mapData.referencePaths;
    if (paths && paths.length > 0) {
      ctx.strokeStyle = '#93C5FD';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      paths.forEach((path: [number, number][]) => {
        if (!path || path.length < 2) return;
        ctx.beginPath();
        const pStart = toScreen(path[0][0], path[0][1]);
        ctx.moveTo(pStart.x, pStart.y);
        for (let i = 1; i < path.length; i++) {
          const p = toScreen(path[i][0], path[i][1]);
          ctx.lineTo(p.x, p.y);
        }
        ctx.stroke();
      });
      ctx.setLineDash([]);
    }
  }

  // 2. След истории траектории робота
  if (historyTicks.length > 1) {
    ctx.beginPath();
    const firstPt = toScreen(historyTicks[0].x, historyTicks[0].y);
    ctx.moveTo(firstPt.x, firstPt.y);
    for (let i = 1; i < historyTicks.length; i++) {
      const pt = toScreen(historyTicks[i].x, historyTicks[i].y);
      ctx.lineTo(pt.x, pt.y);
    }
    ctx.strokeStyle = '#059669'; // Изумрудный след траектории
    ctx.lineWidth = 2.5;
    ctx.stroke();
  }
}
