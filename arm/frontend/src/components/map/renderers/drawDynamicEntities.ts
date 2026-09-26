import { TickData } from '../../../types';
import { MapLayersConfig } from '../../MapCanvas';

export interface DrawDynamicEntitiesOptions {
  ctx: CanvasRenderingContext2D;
  currentTick: TickData | null | undefined;
  toScreen: (wx: number, wy: number) => { x: number; y: number };
  scale: number;
  layers: Pick<MapLayersConfig, 'robot' | 'poseEst' | 'poseDiff' | 'lidar' | 'pedestrians'>;
}

/**
 * Draws active robot platform, pose estimation, lidar scan rays, pedestrians, and pedestrian danger zones.
 */
export function drawDynamicEntities({
  ctx,
  currentTick,
  toScreen,
  scale,
  layers,
}: DrawDynamicEntitiesOptions): void {
  if (!currentTick) return;

  const robotScreen = toScreen(currentTick.x, currentTick.y);
  const robotRadius = 0.9 * scale; // Радиус платформы 0.9 м
  const effRadius = Math.max(6, robotRadius);

  // 1. Лучи лидара
  if (layers.lidar && currentTick.lidarRays) {
    ctx.strokeStyle = 'rgba(147, 197, 253, 0.45)';
    ctx.lineWidth = 1;
    currentTick.lidarRays.forEach(ray => {
      // Луч лидара направлен по курсу платформы currentTick.th плюс относительный угол луча
      const rayAngle = currentTick.th + ray.angle;
      const endWx = currentTick.x + Math.cos(rayAngle) * ray.dist;
      const endWy = currentTick.y + Math.sin(rayAngle) * ray.dist;
      const rayEnd = toScreen(endWx, endWy);

      ctx.beginPath();
      ctx.moveTo(robotScreen.x, robotScreen.y);
      ctx.lineTo(rayEnd.x, rayEnd.y);
      ctx.stroke();

      // Точка отражения на конце луча (согласно макету АРМ)
      ctx.beginPath();
      ctx.arc(rayEnd.x, rayEnd.y, Math.max(2, 0.25 * scale), 0, Math.PI * 2);
      ctx.fillStyle = '#2563EB';
      ctx.fill();
    });
  }

  // 2. Оценка позы и вектор невязки
  if (layers.poseEst && currentTick.pe) {
    const peScreen = toScreen(currentTick.pe[0], currentTick.pe[1]);

    // Линия расхождения (красный пунктир)
    if (layers.poseDiff) {
      ctx.beginPath();
      ctx.moveTo(robotScreen.x, robotScreen.y);
      ctx.lineTo(peScreen.x, peScreen.y);
      ctx.strokeStyle = '#EF4444';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Фиолетовый маркер оценки
    ctx.beginPath();
    ctx.arc(peScreen.x, peScreen.y, Math.max(5, robotRadius), 0, Math.PI * 2);
    ctx.strokeStyle = '#8B5CF6';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // 3. Пешеходы
  if (layers.pedestrians && currentTick.peds) {
    currentTick.peds.forEach(ped => {
      const pedScreen = toScreen(ped[0], ped[1]);

      // Зона опасности: радиус 3.0 м
      ctx.beginPath();
      ctx.arc(pedScreen.x, pedScreen.y, 3.0 * scale, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(251, 146, 60, 0.15)';
      ctx.strokeStyle = 'rgba(251, 146, 60, 0.4)';
      ctx.lineWidth = 1;
      ctx.fill();
      ctx.stroke();

      // Маркер пешехода
      ctx.beginPath();
      ctx.arc(pedScreen.x, pedScreen.y, Math.max(4, 0.3 * scale), 0, Math.PI * 2);
      ctx.fillStyle = '#F97316';
      ctx.fill();
      ctx.strokeStyle = '#FFFFFF';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
  }

  // 4. Истинная поза робота со стрелкой курса
  if (layers.robot) {
    ctx.save();
    ctx.translate(robotScreen.x, robotScreen.y);
    ctx.rotate(-currentTick.th); // Инверсия угла th из-за перевернутой экранной оси Y

    // Внешнее кольцо корпуса
    ctx.beginPath();
    ctx.arc(0, 0, effRadius, 0, Math.PI * 2);
    ctx.fillStyle = '#10B981';
    ctx.fill();
    ctx.strokeStyle = '#065F46';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Стрелка направления курса
    ctx.beginPath();
    ctx.moveTo(effRadius * 0.8, 0);
    ctx.lineTo(-effRadius * 0.4, -effRadius * 0.5);
    ctx.lineTo(-effRadius * 0.2, 0);
    ctx.lineTo(-effRadius * 0.4, effRadius * 0.5);
    ctx.closePath();
    ctx.fillStyle = '#FFFFFF';
    ctx.fill();

    ctx.restore();
  }
}
