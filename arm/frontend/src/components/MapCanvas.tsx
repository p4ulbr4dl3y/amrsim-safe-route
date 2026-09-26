import React, { useRef, useEffect, useState } from 'react';
import { TickData, MapData } from '../types';

export interface MapLayersConfig {
  robot: boolean;
  poseEst: boolean;
  poseDiff: boolean;
  lidar: boolean;
  referencePath: boolean;
  drivable: boolean;
  buildings: boolean;
  docks: boolean;
  pedestrians: boolean;
  obstacles: boolean;
}

interface MapCanvasProps {
  currentTick?: TickData | null;
  historyTicks?: TickData[];
  highlightMission?: string | null;
  targetCoords?: { x: number; y: number } | null;
  layers?: MapLayersConfig;
  followRobot?: boolean;
  className?: string;
  isMiniMap?: boolean;
  mapData?: MapData;
}

const defaultLayers: MapLayersConfig = {
  robot: true,
  poseEst: true,
  poseDiff: true,
  lidar: true,
  referencePath: true,
  drivable: true,
  buildings: true,
  docks: true,
  pedestrians: true,
  obstacles: true,
};

const POINT_LABELS: Record<string, string> = {
  warehouse: 'Склад',
  shop_a: 'Цех A',
  shop_b: 'Цех B',
  charger: 'Зарядка',
  dock_inbound: 'Док разгрузки',
  dock_outbound: 'Док отгрузки',
  dock_sort: 'Сортировка',
  dock_charge: 'Зарядка',
};

const EMPTY_MAP: MapData = {
  bounds: [0, 0, 250, 200],
  drivable: [],
  buildings: [],
  zones: [],
  gates: [],
  crossing: [],
  points: {},
};

export const MapCanvas: React.FC<MapCanvasProps> = ({
  currentTick,
  historyTicks = [],
  highlightMission = null,
  targetCoords = null,
  layers = defaultLayers,
  followRobot = false,
  className = '',
  isMiniMap = false,
  mapData
}) => {
  const activeMap = mapData || EMPTY_MAP;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Viewport transformation: scale and offset
  const [scale, setScale] = useState(isMiniMap ? 1.5 : 3.8);
  const [offset, setOffset] = useState({ x: isMiniMap ? 0 : 30, y: isMiniMap ? 0 : 40 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Auto-fit bounds for map (fit entire warehouse bounds)
  const getBoundsFit = (canvasWidth: number, canvasHeight: number) => {
    const minX = (activeMap.bounds && activeMap.bounds[0]) ?? 0;
    const minY = (activeMap.bounds && activeMap.bounds[1]) ?? 0;
    const maxX = (activeMap.bounds && activeMap.bounds[2]) ?? 250;
    const maxY = (activeMap.bounds && activeMap.bounds[3]) ?? 200;
    const worldW = Math.max(1, maxX - minX);
    const worldH = Math.max(1, maxY - minY);
    const padding = isMiniMap ? 16 : 28;
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
  };

  const boundsKey = activeMap.bounds ? activeMap.bounds.join(',') : '';

  useEffect(() => {
    const updateFit = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const w = rect.width > 0 ? rect.width : (canvas.width || 800);
      const h = rect.height > 0 ? rect.height : (canvas.height || 600);

      const { fitScale, fitOffset } = getBoundsFit(w, h);
      setScale(fitScale);
      setOffset(fitOffset);
    };

    updateFit();

    const canvas = canvasRef.current;
    if (!canvas) return;

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        updateFit();
      });
      resizeObserver.observe(canvas);
    }

    window.addEventListener('resize', updateFit);
    return () => {
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      window.removeEventListener('resize', updateFit);
    };
  }, [boundsKey, isMiniMap]);

  // Handle follow robot or target coordinates (disabled in mini-map)
  useEffect(() => {
    if (isMiniMap) return;
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;

    let targetX = currentTick?.x;
    let targetY = currentTick?.y;

    if (targetCoords) {
      targetX = targetCoords.x;
      targetY = targetCoords.y;
    } else if (!followRobot) {
      return;
    }

    if (targetX !== undefined && targetY !== undefined) {
      const minX = (activeMap.bounds && activeMap.bounds[0]) ?? 0;
      const maxY = (activeMap.bounds && activeMap.bounds[3]) ?? 200;
      const rect = canvas.getBoundingClientRect();
      const canvasX = (rect.width > 0 ? rect.width : (canvas.width || 800)) / 2;
      const canvasY = (rect.height > 0 ? rect.height : (canvas.height || 600)) / 2;

      setOffset({
        x: canvasX - (targetX - minX) * scale,
        y: canvasY - (maxY - targetY) * scale
      });
    }
  }, [followRobot, currentTick?.x, currentTick?.y, targetCoords, isMiniMap, scale, activeMap]);

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Handle high DPI
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    if (!mapData) {
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = '#64748b';
      ctx.font = '13px monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Карта не загружена', rect.width / 2, rect.height / 2);
      ctx.restore();
      return;
    }

    const minX = (activeMap.bounds && activeMap.bounds[0]) ?? 0;
    const minY = (activeMap.bounds && activeMap.bounds[1]) ?? 0;
    const maxX = (activeMap.bounds && activeMap.bounds[2]) ?? 250;
    const maxY = (activeMap.bounds && activeMap.bounds[3]) ?? 200;
    const worldWidth = Math.max(1, maxX - minX);
    const worldHeight = Math.max(1, maxY - minY);

    // Compute active scale and offset (guaranteed fit for mini-map)
    let currentScale = scale;
    let currentOffset = offset;
    if (isMiniMap && rect.width > 0 && rect.height > 0) {
      const padding = 16;
      const availW = Math.max(10, rect.width - 2 * padding);
      const availH = Math.max(10, rect.height - 2 * padding);
      currentScale = Math.min(availW / worldWidth, availH / worldHeight);
      const planW = worldWidth * currentScale;
      const planH = worldHeight * currentScale;
      currentOffset = {
        x: (rect.width - planW) / 2,
        y: (rect.height - planH) / 2,
      };
    }

    // Transform helper: world (X, Y) -> screen (px, py)
    const toScreen = (wx: number, wy: number) => {
      return {
        x: (wx - minX) * currentScale + currentOffset.x,
        y: (maxY - wy) * currentScale + currentOffset.y
      };
    };

    // 1. Background Grid
    ctx.strokeStyle = '#F1F5F9';
    ctx.lineWidth = 1;
    const gridSize = 20; // 20 meters
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

    // Warehouse outer bounds perimeter border
    ctx.strokeStyle = '#CBD5E1';
    ctx.lineWidth = 1.5;
    const pTopLeft = toScreen(minX, maxY);
    const pBotRight = toScreen(maxX, minY);
    ctx.strokeRect(pTopLeft.x, pTopLeft.y, pBotRight.x - pTopLeft.x, pBotRight.y - pTopLeft.y);

    // 2. Drivable Corridors
    if (layers.drivable && activeMap.drivable) {
      ctx.fillStyle = '#E8EEF5';
      ctx.strokeStyle = '#CBD5E1';
      ctx.lineWidth = 1.5;

      activeMap.drivable.forEach((poly: any) => {
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

    // 3. Zones (Forbidden, Speed limit)
    if (activeMap.zones) {
      activeMap.zones.forEach((zone: any) => {
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

    // 4. Buildings (Warehouse blocks)
    if (layers.buildings && activeMap.buildings) {
      ctx.fillStyle = '#DDE3EA';
      ctx.strokeStyle = '#94A3B8';
      ctx.lineWidth = 1.2;

      activeMap.buildings.forEach((b: any) => {
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

    // 4b. Obstacles (Containers, Pallets, and Static Map Patches)
    if (layers.obstacles && activeMap.map_patches && activeMap.map_patches.length > 0) {
      activeMap.map_patches.forEach((patch: any) => {
        if (patch.op && patch.op !== 'add') return;
        const poly = patch.polygon;
        if (!poly || poly.length < 3) return;

        ctx.beginPath();
        const start = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < poly.length; i++) {
          const pt = toScreen(poly[i][0], poly[i][1]);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();

        const patchId = (patch.id || '').toLowerCase();
        const isPallet = patchId.includes('pallet') || patchId.includes('поддон');
        const isContainer = patchId.includes('container') || patchId.includes('can') || patchId.includes('контейнер');

        if (isPallet) {
          ctx.fillStyle = '#FCD34D';
          ctx.strokeStyle = '#D97706';
          ctx.lineWidth = 1.5;
        } else if (isContainer) {
          ctx.fillStyle = '#64748B';
          ctx.strokeStyle = '#1E293B';
          ctx.lineWidth = 1.8;
        } else {
          ctx.fillStyle = '#CBD5E1';
          ctx.strokeStyle = '#475569';
          ctx.lineWidth = 1.5;
        }

        ctx.fill();
        ctx.stroke();

        // For containers with 4 vertices, draw subtle corrugated rib lines
        if (isContainer && poly.length === 4) {
          ctx.save();
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
          ctx.lineWidth = 1;
          const p0 = toScreen(poly[0][0], poly[0][1]);
          const p1 = toScreen(poly[1][0], poly[1][1]);
          const p3 = toScreen(poly[3][0], poly[3][1]);
          const ribCount = 4;
          for (let r = 1; r < ribCount; r++) {
            const frac = r / ribCount;
            const topX = p0.x + (p1.x - p0.x) * frac;
            const topY = p0.y + (p1.y - p0.y) * frac;
            const botX = p3.x + (p1.x - p0.x) * frac;
            const botY = p3.y + (p1.y - p0.y) * frac;
            ctx.beginPath();
            ctx.moveTo(topX, topY);
            ctx.lineTo(botX, botY);
            ctx.stroke();
          }
          ctx.restore();
        }

        // Draw obstacle label badge
        if (!isMiniMap) {
          const centerWx = poly.reduce((acc: number, p: any) => acc + p[0], 0) / poly.length;
          const centerWy = poly.reduce((acc: number, p: any) => acc + p[1], 0) / poly.length;
          const centerSc = toScreen(centerWx, centerWy);

          ctx.save();
          ctx.font = 'bold 9px Inter, sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';

          let label = patch.id || 'Объект';
          if (label.startsWith('CONTAINER_')) {
            label = `Контейнер ${label.replace('CONTAINER_', '')}`;
          } else if (label.startsWith('PALLET_')) {
            label = `Поддон ${label.replace('PALLET_', '')}`;
          }

          const metrics = ctx.measureText(label);
          const padX = 4;
          const padY = 2;
          ctx.fillStyle = isPallet ? 'rgba(254, 243, 199, 0.92)' : 'rgba(30, 41, 59, 0.85)';
          ctx.fillRect(
            centerSc.x - metrics.width / 2 - padX,
            centerSc.y - 6 - padY,
            metrics.width + padX * 2,
            12 + padY * 2
          );
          ctx.fillStyle = isPallet ? '#92400E' : '#FFFFFF';
          ctx.fillText(label, centerSc.x, centerSc.y);
          ctx.restore();
        }
      });
    }

    // 4c. Dynamic Dropped Obstacles (Events: Pallets dropped on road)
    if (layers.obstacles && activeMap.events && activeMap.events.length > 0) {
      activeMap.events.forEach((ev: any) => {
        if (ev.type !== 'object_dropped' || typeof ev.x !== 'number' || typeof ev.y !== 'number') return;

        const isDropped = !currentTick || currentTick.t >= (ev.t ?? 0);
        const screenPt = toScreen(ev.x, ev.y);
        const r = ev.r || 0.4;
        const radiusPx = Math.max(6, r * currentScale);

        // Standard pallet dimensions: 1.2m x 0.8m
        const palletW = Math.max(12, 1.2 * currentScale);
        const palletH = Math.max(8, 0.8 * currentScale);

        ctx.save();

        if (isDropped) {
          // Safety / danger halo around dropped pallet
          ctx.beginPath();
          ctx.arc(screenPt.x, screenPt.y, radiusPx + Math.max(4, 0.4 * currentScale), 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(245, 158, 11, 0.15)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(217, 119, 6, 0.4)';
          ctx.lineWidth = 1;
          ctx.setLineDash([3, 3]);
          ctx.stroke();
          ctx.setLineDash([]);

          // Pallet body rectangle
          const px = screenPt.x - palletW / 2;
          const py = screenPt.y - palletH / 2;
          ctx.fillStyle = '#FCD34D';
          ctx.fillRect(px, py, palletW, palletH);
          ctx.strokeStyle = '#B45309';
          ctx.lineWidth = 1.5;
          ctx.strokeRect(px, py, palletW, palletH);

          // Wood slats (horizontal boards across pallet)
          ctx.strokeStyle = '#D97706';
          ctx.lineWidth = 1;
          for (let s = 1; s <= 2; s++) {
            const slatY = py + (palletH * s) / 3;
            ctx.beginPath();
            ctx.moveTo(px + 1, slatY);
            ctx.lineTo(px + palletW - 1, slatY);
            ctx.stroke();
          }

          // Center cross/dot
          ctx.beginPath();
          ctx.arc(screenPt.x, screenPt.y, 2, 0, Math.PI * 2);
          ctx.fillStyle = '#B45309';
          ctx.fill();

          // Label
          if (!isMiniMap) {
            const label = `Поддон (${ev.t !== undefined ? ev.t + 'с' : '0.4м'})`;
            ctx.font = 'bold 9px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            const metrics = ctx.measureText(label);
            const padX = 4;
            const padY = 2;
            const labelY = py - 3;

            ctx.fillStyle = 'rgba(254, 243, 199, 0.95)';
            ctx.strokeStyle = '#D97706';
            ctx.lineWidth = 1;
            ctx.strokeRect(
              screenPt.x - metrics.width / 2 - padX,
              labelY - 10 - padY,
              metrics.width + padX * 2,
              12 + padY
            );
            ctx.fillRect(
              screenPt.x - metrics.width / 2 - padX,
              labelY - 10 - padY,
              metrics.width + padX * 2,
              12 + padY
            );
            ctx.fillStyle = '#92400E';
            ctx.fillText(label, screenPt.x, labelY);
          }
        } else {
          // Pre-drop ghost marker (future dropped pallet)
          const px = screenPt.x - palletW / 2;
          const py = screenPt.y - palletH / 2;
          ctx.fillStyle = 'rgba(254, 243, 199, 0.3)';
          ctx.fillRect(px, py, palletW, palletH);
          ctx.strokeStyle = 'rgba(217, 119, 6, 0.55)';
          ctx.lineWidth = 1.2;
          ctx.setLineDash([3, 2]);
          ctx.strokeRect(px, py, palletW, palletH);
          ctx.setLineDash([]);

          if (!isMiniMap) {
            const label = `Поддон (t=${ev.t}с)`;
            ctx.font = 'bold 9px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillStyle = 'rgba(180, 83, 9, 0.7)';
            ctx.fillText(label, screenPt.x, py - 2);
          }
        }

        ctx.restore();
      });
    }

    // 5. Reference Path (if specified in activeMap or mission)
    if (layers.referencePath && activeMap.points && activeMap.points['warehouse'] && activeMap.points['shop_a']) {
      ctx.strokeStyle = '#93C5FD';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      const pStart = toScreen(activeMap.points['warehouse'].x, activeMap.points['warehouse'].y);
      const pEnd = toScreen(activeMap.points['shop_a'].x, activeMap.points['shop_a'].y);
      ctx.moveTo(pStart.x, pStart.y);
      ctx.lineTo(pEnd.x, pEnd.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 6. Dock Stations
    if (layers.docks && activeMap.points) {
      Object.entries(activeMap.points).forEach(([id, pt]: [string, any]) => {
        const screenPt = toScreen(pt.x, pt.y);

        // Outer circle (tolerance radius)
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, Math.max(7, (pt.tol || 0.2) * currentScale * 10), 0, Math.PI * 2);
        ctx.strokeStyle = '#2563EB';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Inner solid dot
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#2563EB';
        ctx.fill();

        // Dock Label (translated)
        if (!isMiniMap) {
          ctx.font = '10px Inter, sans-serif';
          ctx.fillStyle = '#475569';
          ctx.textAlign = 'left';
          const labelText = POINT_LABELS[pt.label || id] || pt.label || id;
          ctx.fillText(labelText, screenPt.x + 10, screenPt.y + 3);
        }
      });
    }

    // 7. AMR Trajectory History Trail
    if (historyTicks.length > 1) {
      ctx.beginPath();
      const firstPt = toScreen(historyTicks[0].x, historyTicks[0].y);
      ctx.moveTo(firstPt.x, firstPt.y);
      for (let i = 1; i < historyTicks.length; i++) {
        const pt = toScreen(historyTicks[i].x, historyTicks[i].y);
        ctx.lineTo(pt.x, pt.y);
      }
      ctx.strokeStyle = '#059669'; // Teal-emerald trail
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }

    // 8. Active Tick: AMR Platform & Sensors
    if (currentTick) {
      const robotScreen = toScreen(currentTick.x, currentTick.y);
      const robotRadius = 0.9 * currentScale; // 0.9m physical footprint
      const effRadius = Math.max(6, robotRadius);

      // 8a. 9-Ray Lidar Fan
      if (layers.lidar && currentTick.lidarRays && currentTick.lidarRays.length > 0) {
        currentTick.lidarRays.forEach(ray => {
          const hitX = currentTick.x + ray.dist * Math.cos(currentTick.th + ray.angle);
          const hitY = currentTick.y + ray.dist * Math.sin(currentTick.th + ray.angle);
          const hitScreen = toScreen(hitX, hitY);

          ctx.beginPath();
          ctx.moveTo(robotScreen.x, robotScreen.y);
          ctx.lineTo(hitScreen.x, hitScreen.y);
          ctx.strokeStyle = 'rgba(96, 165, 250, 0.4)';
          ctx.lineWidth = 1;
          ctx.stroke();

          // Ray endpoint dot
          ctx.beginPath();
          ctx.arc(hitScreen.x, hitScreen.y, 2, 0, Math.PI * 2);
          ctx.fillStyle = '#3B82F6';
          ctx.fill();
        });
      }

      // 8b. Pose Estimation vs Real Pose
      if (layers.poseEst && currentTick.pe) {
        const peScreen = toScreen(currentTick.pe[0], currentTick.pe[1]);

        // Red dashed line showing drift
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

        // Purple hollow marker
        ctx.beginPath();
        ctx.arc(peScreen.x, peScreen.y, Math.max(5, robotRadius), 0, Math.PI * 2);
        ctx.strokeStyle = '#8B5CF6';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // 8c. Pedestrians
      if (layers.pedestrians && currentTick.peds) {
        currentTick.peds.forEach(ped => {
          const pedScreen = toScreen(ped[0], ped[1]);

          // Danger circle (3.0 m radius)
          ctx.beginPath();
          ctx.arc(pedScreen.x, pedScreen.y, 3.0 * currentScale, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(251, 146, 60, 0.15)';
          ctx.strokeStyle = 'rgba(251, 146, 60, 0.4)';
          ctx.lineWidth = 1;
          ctx.fill();
          ctx.stroke();

          // Pedestrian core marker
          ctx.beginPath();
          ctx.arc(pedScreen.x, pedScreen.y, Math.max(4, 0.3 * currentScale), 0, Math.PI * 2);
          ctx.fillStyle = '#F97316';
          ctx.fill();
          ctx.strokeStyle = '#FFFFFF';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        });
      }

      // 8d. True AMR Robot (Green / Emerald glyph with heading arrow)
      if (layers.robot) {
        ctx.save();
        ctx.translate(robotScreen.x, robotScreen.y);
        ctx.rotate(-currentTick.th); // Invert theta because screen Y is flipped

        // Outer body ring
        ctx.beginPath();
        ctx.arc(0, 0, effRadius, 0, Math.PI * 2);
        ctx.fillStyle = '#10B981';
        ctx.fill();
        ctx.strokeStyle = '#065F46';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Directional arrow pointing forward (along heading)
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

    ctx.restore();
  }, [currentTick, historyTicks, layers, scale, offset, isMiniMap, activeMap, mapData]);

  // Mouse pan & zoom handlers (disabled in mini-map mode)
  const handleMouseDown = (e: React.MouseEvent) => {
    if (isMiniMap) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isMiniMap || !isDragging) return;
    setOffset({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y
    });
  };

  const handleMouseUp = () => {
    if (isMiniMap) return;
    setIsDragging(false);
  };

  const handleWheel = (e: React.WheelEvent) => {
    if (isMiniMap) return;
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const newScale = Math.min(12, Math.max(1.0, scale * zoomFactor));
    setScale(newScale);
  };

  return (
    <div className={`relative overflow-hidden w-full h-full select-none ${className}`}>
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        className={`w-full h-full block ${
          isMiniMap ? 'cursor-default' : isDragging ? 'cursor-grabbing' : 'cursor-grab'
        }`}
      />

      {/* Compass rose on top-left (Север) */}
      <div className="absolute top-4 left-4 flex flex-col items-center pointer-events-none opacity-80 select-none">
        <span className="text-[11px] font-bold text-slate-500">С</span>
        <svg className="w-3.5 h-3.5 text-slate-500" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="12,2 18,22 12,17 6,22" />
        </svg>
      </div>

      {/* Zoom / Pan controls */}
      {!isMiniMap && (
        <div className="absolute bottom-4 right-4 flex flex-col gap-1 bg-white border border-slate-200 rounded-lg shadow-sm p-1 z-10">
          <button
            onClick={() => setScale(s => Math.min(12, s * 1.2))}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
            title="Приблизить (+)"
          >
            +
          </button>
          <button
            onClick={() => setScale(s => Math.max(1.0, s * 0.8))}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
            title="Отдалить (-)"
          >
            -
          </button>
          <button
            onClick={() => {
              setScale(3.8);
              setOffset({ x: 30, y: 40 });
            }}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-xs font-semibold"
            title="Сбросить масштаб (1:1)"
          >
            1:1
          </button>
        </div>
      )}
    </div>
  );
};
