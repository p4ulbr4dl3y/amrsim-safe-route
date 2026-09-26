import React, { useRef, useEffect, useState, useCallback } from 'react';
import { AmrScenario, ScenarioMapPatch, ScenarioPedestrian, ScenarioZone } from '../../types';

export type ConstructorTool =
  | 'select'
  | 'pan'
  | 'set_robot'
  | 'add_pallet'
  | 'add_container'
  | 'add_pedestrian'
  | 'add_zone'
  | 'add_dock'
  | 'delete';

export interface SelectedEntity {
  type: 'robot' | 'obstacle' | 'pedestrian' | 'pedestrian_waypoint' | 'zone' | 'dock';
  id?: string;
  index?: number;
  waypointIndex?: number;
}

export interface ConstructorLayers {
  robot: boolean;
  corridors: boolean;
  buildings: boolean;
  obstacles: boolean;
  pedestrians: boolean;
  zones: boolean;
  docks: boolean;
  grid: boolean;
}

interface ConstructorCanvasProps {
  scenario: AmrScenario;
  activeTool: ConstructorTool;
  activeZoneType?: 'speed_limit' | 'forbidden' | 'gnss_shadow' | 'people_area';
  selectedEntity: SelectedEntity | null;
  layers: ConstructorLayers;
  onSelect: (entity: SelectedEntity | null) => void;
  onUpdateScenario: (updater: (prev: AmrScenario) => AmrScenario) => void;
  className?: string;
}

export const ConstructorCanvas: React.FC<ConstructorCanvasProps> = ({
  scenario,
  activeTool,
  activeZoneType = 'speed_limit',
  selectedEntity,
  layers,
  onSelect,
  onUpdateScenario,
  className = '',
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Viewport parameters
  const [scale, setScale] = useState(3.5);
  const [offset, setOffset] = useState({ x: 30, y: 30 });
  const [cursorCoords, setCursorCoords] = useState<{ x: number; y: number } | null>(null);

  // Mouse interaction state
  const [isMouseDown, setIsMouseDown] = useState(false);
  const [dragAction, setDragAction] = useState<
    | { type: 'pan'; startClientX: number; startClientY: number; initialOffset: { x: number; y: number } }
    | { type: 'move_entity'; entity: SelectedEntity; startWorldX: number; startWorldY: number; initialObjState: any }
    | { type: 'rotate_robot'; centerWorldX: number; centerWorldY: number }
    | { type: 'box_draw'; startWorldX: number; startWorldY: number }
    | null
  >(null);

  const [boxDrawEnd, setBoxDrawEnd] = useState<{ x: number; y: number } | null>(null);

  // Map boundaries
  const bounds = scenario.map?.bounds || [0, 0, 250, 200];
  const [minX, minY, maxX, maxY] = bounds;
  const worldW = Math.max(1, maxX - minX);
  const worldH = Math.max(1, maxY - minY);

  // Fit to screen helper
  const fitToBounds = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width || 800;
    const h = rect.height || 600;
    const pad = 36;
    const availW = Math.max(20, w - pad * 2);
    const availH = Math.max(20, h - pad * 2);
    const fitScale = Math.min(availW / worldW, availH / worldH);
    const planW = worldW * fitScale;
    const planH = worldH * fitScale;
    setScale(fitScale);
    setOffset({
      x: (w - planW) / 2,
      y: (h - planH) / 2,
    });
  }, [worldW, worldH]);

  useEffect(() => {
    fitToBounds();
  }, [fitToBounds]);

  // Coordinate transforms
  const toScreen = useCallback(
    (wx: number, wy: number) => {
      return {
        x: (wx - minX) * scale + offset.x,
        y: (maxY - wy) * scale + offset.y,
      };
    },
    [minX, maxY, scale, offset]
  );

  const toWorld = useCallback(
    (sx: number, sy: number) => {
      return {
        x: minX + (sx - offset.x) / scale,
        y: maxY - (sy - offset.y) / scale,
      };
    },
    [minX, maxY, scale, offset]
  );

  // Hit test helper
  const findEntityAt = useCallback(
    (wx: number, wy: number): SelectedEntity | null => {
      const hitRadiusWorld = 15 / scale; // ~15 pixels in world coords

      // 1. Robot start check
      if (layers.robot && scenario.start) {
        const dist = Math.hypot(scenario.start.x - wx, scenario.start.y - wy);
        if (dist <= Math.max(1.2, hitRadiusWorld)) {
          return { type: 'robot' };
        }
      }

      // 2. Pedestrian waypoints & positions
      if (layers.pedestrians && scenario.pedestrians) {
        for (let pIdx = 0; pIdx < scenario.pedestrians.length; pIdx++) {
          const ped = scenario.pedestrians[pIdx];
          for (let wIdx = 0; wIdx < ped.waypoints.length; wIdx++) {
            const [wX, wY] = ped.waypoints[wIdx];
            if (Math.hypot(wX - wx, wY - wy) <= Math.max(0.8, hitRadiusWorld)) {
              return {
                type: 'pedestrian_waypoint',
                index: pIdx,
                waypointIndex: wIdx,
                id: ped.id,
              };
            }
          }
        }
      }

      // 3. Obstacles (map_patches)
      if (layers.obstacles && scenario.map_patches) {
        for (let i = scenario.map_patches.length - 1; i >= 0; i--) {
          const patch = scenario.map_patches[i];
          if (patch.polygon && patch.polygon.length >= 3) {
            // Check polygon bounding box or point-in-polygon
            let minPx = Infinity,
              maxPx = -Infinity,
              minPy = Infinity,
              maxPy = -Infinity;
            patch.polygon.forEach(([px, py]) => {
              minPx = Math.min(minPx, px);
              maxPx = Math.max(maxPx, px);
              minPy = Math.min(minPy, py);
              maxPy = Math.max(maxPy, py);
            });
            if (
              wx >= minPx - hitRadiusWorld * 0.5 &&
              wx <= maxPx + hitRadiusWorld * 0.5 &&
              wy >= minPy - hitRadiusWorld * 0.5 &&
              wy <= maxPy + hitRadiusWorld * 0.5
            ) {
              return { type: 'obstacle', index: i, id: patch.id };
            }
          }
        }
      }

      // 4. Docks / target points
      if (layers.docks && scenario.map?.points) {
        for (const [id, pt] of Object.entries(scenario.map.points)) {
          const dist = Math.hypot(pt.x - wx, pt.y - wy);
          if (dist <= Math.max(1.0, hitRadiusWorld)) {
            return { type: 'dock', id };
          }
        }
      }

      // 5. Zones
      if (layers.zones && scenario.map?.zones) {
        for (let i = scenario.map.zones.length - 1; i >= 0; i--) {
          const z = scenario.map.zones[i];
          if (z.polygon && z.polygon.length >= 3) {
            let minZx = Infinity,
              maxZx = -Infinity,
              minZy = Infinity,
              maxZy = -Infinity;
            z.polygon.forEach(([zx, zy]) => {
              minZx = Math.min(minZx, zx);
              maxZx = Math.max(maxZx, zx);
              minZy = Math.min(minZy, zy);
              maxZy = Math.max(maxZy, zy);
            });
            if (wx >= minZx && wx <= maxZx && wy >= minZy && wy <= maxZy) {
              return { type: 'zone', index: i, id: z.id };
            }
          }
        }
      }

      return null;
    },
    [layers, scenario, scale]
  );

  // Main Canvas Render Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // High DPI scaling
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    // 1. Grid & Coordinates
    if (layers.grid) {
      ctx.strokeStyle = '#F1F5F9';
      ctx.lineWidth = 1;
      const step = 20; // 20m grid
      for (let x = minX; x <= maxX; x += step) {
        const p1 = toScreen(x, minY);
        const p2 = toScreen(x, maxY);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
      for (let y = minY; y <= maxY; y += step) {
        const p1 = toScreen(minX, y);
        const p2 = toScreen(maxX, y);
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }

      // World boundary border
      ctx.strokeStyle = '#94A3B8';
      ctx.lineWidth = 1.5;
      const bTopLeft = toScreen(minX, maxY);
      const bBotRight = toScreen(maxX, minY);
      ctx.strokeRect(bTopLeft.x, bTopLeft.y, bBotRight.x - bTopLeft.x, bBotRight.y - bTopLeft.y);

      // Axis labels
      ctx.fillStyle = '#94A3B8';
      ctx.font = '10px Inter, sans-serif';
      for (let x = minX + step; x < maxX; x += step) {
        const p = toScreen(x, minY);
        ctx.fillText(`${x}m`, p.x - 10, p.y - 4);
      }
      for (let y = minY + step; y < maxY; y += step) {
        const p = toScreen(minX, y);
        ctx.fillText(`${y}m`, p.x + 4, p.y + 3);
      }
    }

    // 2. Drivable Corridors
    if (layers.corridors && scenario.map?.drivable) {
      ctx.fillStyle = '#E8EEF5';
      ctx.strokeStyle = '#CBD5E1';
      ctx.lineWidth = 1;

      scenario.map.drivable.forEach((poly) => {
        if (poly && poly.length > 2) {
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

    // 3. Buildings & Walls
    if (layers.buildings && scenario.map?.buildings) {
      ctx.fillStyle = '#DDE3EA';
      ctx.strokeStyle = '#94A3B8';
      ctx.lineWidth = 1.2;

      scenario.map.buildings.forEach((b) => {
        const poly = b.polygon;
        if (poly && poly.length > 2) {
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

          // Building label
          if (b.id && !b.id.includes('_bay_') && !b.id.startsWith('CAN_')) {
            const centerWx = poly.reduce((acc, p) => acc + p[0], 0) / poly.length;
            const centerWy = poly.reduce((acc, p) => acc + p[1], 0) / poly.length;
            const centerSc = toScreen(centerWx, centerWy);
            ctx.font = '11px Inter, sans-serif';
            ctx.fillStyle = '#64748B';
            ctx.textAlign = 'center';
            ctx.fillText(b.id, centerSc.x, centerSc.y);
          }
        }
      });
    }

    // 4. Zones (Speed limits, Forbidden, GNSS Shadow, People Area)
    if (layers.zones && scenario.map?.zones) {
      scenario.map.zones.forEach((z, idx) => {
        const poly = z.polygon;
        if (!poly || poly.length < 3) return;

        const isSelected = selectedEntity?.type === 'zone' && selectedEntity.index === idx;

        ctx.beginPath();
        const start = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < poly.length; i++) {
          const pt = toScreen(poly[i][0], poly[i][1]);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();

        let fillColor = 'rgba(203, 213, 225, 0.2)';
        let strokeColor = '#94A3B8';
        let labelText = z.id;

        if (z.type === 'forbidden') {
          fillColor = 'rgba(239, 68, 68, 0.16)';
          strokeColor = '#EF4444';
          labelText = `⛔ Запретная (${z.id})`;
        } else if (z.type === 'speed_limit') {
          fillColor = 'rgba(245, 158, 11, 0.14)';
          strokeColor = '#F59E0B';
          labelText = `⚡ Ограничение ${z.v_max ?? 0.8} м/с (${z.id})`;
        } else if (z.type === 'gnss_shadow') {
          fillColor = 'rgba(147, 51, 234, 0.14)';
          strokeColor = '#A855F7';
          labelText = `📡 Тень ГНСС (${z.id})`;
        } else if (z.type === 'people_area') {
          fillColor = 'rgba(14, 165, 233, 0.12)';
          strokeColor = '#0EA5E9';
          labelText = `🚶 Зона людей (${z.id})`;
        }

        ctx.fillStyle = fillColor;
        ctx.strokeStyle = isSelected ? '#2563EB' : strokeColor;
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        if (z.type === 'speed_limit' || z.type === 'people_area') {
          ctx.setLineDash([4, 4]);
        } else {
          ctx.setLineDash([]);
        }
        ctx.fill();
        ctx.stroke();
        ctx.setLineDash([]);

        // Zone label in center
        const centerWx = poly.reduce((acc, p) => acc + p[0], 0) / poly.length;
        const centerWy = poly.reduce((acc, p) => acc + p[1], 0) / poly.length;
        const centerSc = toScreen(centerWx, centerWy);
        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = isSelected ? '#1D4ED8' : strokeColor;
        ctx.textAlign = 'center';
        ctx.fillText(labelText, centerSc.x, centerSc.y);
      });
    }

    // 5. Static Obstacles / Map Patches (Pallets, Containers, etc.)
    if (layers.obstacles && scenario.map_patches) {
      scenario.map_patches.forEach((patch, idx) => {
        const poly = patch.polygon;
        if (!poly || poly.length < 3) return;

        const isSelected = selectedEntity?.type === 'obstacle' && selectedEntity.index === idx;

        ctx.beginPath();
        const start = toScreen(poly[0][0], poly[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < poly.length; i++) {
          const pt = toScreen(poly[i][0], poly[i][1]);
          ctx.lineTo(pt.x, pt.y);
        }
        ctx.closePath();

        const isPallet = patch.id.toLowerCase().includes('pallet');
        const isContainer = patch.id.toLowerCase().includes('container') || patch.id.toLowerCase().includes('can');

        if (isPallet) {
          ctx.fillStyle = isSelected ? '#FDE68A' : '#FCD34D';
          ctx.strokeStyle = isSelected ? '#2563EB' : '#D97706';
        } else if (isContainer) {
          ctx.fillStyle = isSelected ? '#93C5FD' : '#64748B';
          ctx.strokeStyle = isSelected ? '#2563EB' : '#1E293B';
        } else {
          ctx.fillStyle = isSelected ? '#CBD5E1' : '#E2E8F0';
          ctx.strokeStyle = isSelected ? '#2563EB' : '#475569';
        }

        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.fill();
        ctx.stroke();

        // Label
        const centerWx = poly.reduce((acc, p) => acc + p[0], 0) / poly.length;
        const centerWy = poly.reduce((acc, p) => acc + p[1], 0) / poly.length;
        const centerSc = toScreen(centerWx, centerWy);
        ctx.font = '10px Inter, sans-serif';
        ctx.fillStyle = isSelected ? '#1D4ED8' : '#334155';
        ctx.textAlign = 'center';
        ctx.fillText(patch.id, centerSc.x, centerSc.y);
      });
    }

    // 6. Dock Stations
    if (layers.docks && scenario.map?.points) {
      Object.entries(scenario.map.points).forEach(([id, pt]) => {
        const isSelected = selectedEntity?.type === 'dock' && selectedEntity.id === id;
        const screenPt = toScreen(pt.x, pt.y);

        // Tolerance radius ring
        const tolRadiusPx = Math.max(7, (pt.tol || 0.2) * scale * 10);
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, tolRadiusPx, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? '#1D4ED8' : '#3B82F6';
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.fillStyle = isSelected ? 'rgba(59, 130, 246, 0.25)' : 'rgba(59, 130, 246, 0.1)';
        ctx.fill();
        ctx.stroke();

        // Heading arrow for dock
        if (pt.heading !== undefined) {
          const arrowLen = tolRadiusPx + 8;
          const arrowEnd = {
            x: screenPt.x + Math.cos(pt.heading) * arrowLen,
            y: screenPt.y - Math.sin(pt.heading) * arrowLen,
          };
          ctx.beginPath();
          ctx.moveTo(screenPt.x, screenPt.y);
          ctx.lineTo(arrowEnd.x, arrowEnd.y);
          ctx.strokeStyle = '#2563EB';
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        // Center dot
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#2563EB';
        ctx.fill();

        // Label
        ctx.font = '11px Inter, sans-serif';
        ctx.fillStyle = isSelected ? '#1D4ED8' : '#1E40AF';
        ctx.textAlign = 'left';
        ctx.fillText(`Док: ${pt.label || id}`, screenPt.x + tolRadiusPx + 4, screenPt.y + 3);
      });
    }

    // 7. Pedestrians & Waypoints
    if (layers.pedestrians && scenario.pedestrians) {
      scenario.pedestrians.forEach((ped, pIdx) => {
        const isPedSelected = selectedEntity?.type === 'pedestrian' && selectedEntity.index === pIdx;

        if (ped.waypoints && ped.waypoints.length > 0) {
          // Trajectory connecting line
          ctx.beginPath();
          const firstScreen = toScreen(ped.waypoints[0][0], ped.waypoints[0][1]);
          ctx.moveTo(firstScreen.x, firstScreen.y);
          for (let w = 1; w < ped.waypoints.length; w++) {
            const ptScreen = toScreen(ped.waypoints[w][0], ped.waypoints[w][1]);
            ctx.lineTo(ptScreen.x, ptScreen.y);
          }
          if (ped.loop && ped.waypoints.length > 2) {
            ctx.lineTo(firstScreen.x, firstScreen.y);
          }
          ctx.strokeStyle = isPedSelected ? '#2563EB' : '#F97316';
          ctx.lineWidth = isPedSelected ? 2.5 : 1.8;
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.setLineDash([]);

          // Waypoints
          ped.waypoints.forEach(([wx, wy], wIdx) => {
            const isWpSelected =
              selectedEntity?.type === 'pedestrian_waypoint' &&
              selectedEntity.index === pIdx &&
              selectedEntity.waypointIndex === wIdx;

            const sc = toScreen(wx, wy);

            // Distance caution aura (3.0 m) for primary position
            if (wIdx === 0) {
              ctx.beginPath();
              ctx.arc(sc.x, sc.y, 3.0 * scale, 0, Math.PI * 2);
              ctx.fillStyle = 'rgba(251, 146, 60, 0.12)';
              ctx.strokeStyle = 'rgba(251, 146, 60, 0.4)';
              ctx.lineWidth = 1;
              ctx.fill();
              ctx.stroke();
            }

            // Waypoint node
            ctx.beginPath();
            ctx.arc(sc.x, sc.y, isWpSelected ? 7 : wIdx === 0 ? 6 : 5, 0, Math.PI * 2);
            ctx.fillStyle = isWpSelected ? '#2563EB' : wIdx === 0 ? '#EA580C' : '#F97316';
            ctx.fill();
            ctx.strokeStyle = '#FFFFFF';
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Waypoint number
            ctx.font = '9px Inter, sans-serif';
            ctx.fillStyle = '#FFFFFF';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(`${wIdx + 1}`, sc.x, sc.y);
          });

          // Pedestrian label
          const firstSc = toScreen(ped.waypoints[0][0], ped.waypoints[0][1]);
          ctx.font = '10px Inter, sans-serif';
          ctx.fillStyle = isPedSelected ? '#1D4ED8' : '#C2410C';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'bottom';
          ctx.fillText(
            `Пешеход ${ped.id} (${ped.speed} м/с${ped.inattentive ? ', невнимателен' : ''})`,
            firstSc.x + 8,
            firstSc.y - 6
          );
        }
      });
    }

    // 8. Robot Start Position
    if (layers.robot && scenario.start) {
      const isRobotSelected = selectedEntity?.type === 'robot';
      const robotSc = toScreen(scenario.start.x, scenario.start.y);
      const robotRadiusPx = Math.max(8, 0.9 * scale); // 0.9m physical AMR footprint

      // Selection ring
      if (isRobotSelected) {
        ctx.beginPath();
        ctx.arc(robotSc.x, robotSc.y, robotRadiusPx + 6, 0, Math.PI * 2);
        ctx.strokeStyle = '#2563EB';
        ctx.lineWidth = 2.5;
        ctx.setLineDash([4, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Robot chassis body
      ctx.beginPath();
      ctx.arc(robotSc.x, robotSc.y, robotRadiusPx, 0, Math.PI * 2);
      ctx.fillStyle = '#10B981';
      ctx.fill();
      ctx.strokeStyle = '#065F46';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Heading directional arrow
      const theta = scenario.start.theta || 0;
      const arrowLen = robotRadiusPx * 1.5;
      const arrowTip = {
        x: robotSc.x + Math.cos(theta) * arrowLen,
        y: robotSc.y - Math.sin(theta) * arrowLen,
      };

      ctx.beginPath();
      ctx.moveTo(robotSc.x, robotSc.y);
      ctx.lineTo(arrowTip.x, arrowTip.y);
      ctx.strokeStyle = '#064E3B';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // Heading tip handle
      ctx.beginPath();
      ctx.arc(arrowTip.x, arrowTip.y, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = isRobotSelected ? '#2563EB' : '#FFFFFF';
      ctx.fill();
      ctx.strokeStyle = '#064E3B';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Start label
      ctx.font = '11px Inter, sans-serif';
      ctx.fillStyle = '#065F46';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(
        `Старт Робота (${scenario.start.x.toFixed(1)}, ${scenario.start.y.toFixed(1)})`,
        robotSc.x,
        robotSc.y + robotRadiusPx + 6
      );
    }

    // 9. Interactive Box Draw Preview (when placing zone or box)
    if (dragAction?.type === 'box_draw' && boxDrawEnd) {
      const p1 = toScreen(dragAction.startWorldX, dragAction.startWorldY);
      const p2 = toScreen(boxDrawEnd.x, boxDrawEnd.y);
      const minSx = Math.min(p1.x, p2.x);
      const minSy = Math.min(p1.y, p2.y);
      const boxW = Math.abs(p2.x - p1.x);
      const boxH = Math.abs(p2.y - p1.y);

      ctx.strokeStyle = '#2563EB';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(minSx, minSy, boxW, boxH);
      ctx.fillStyle = 'rgba(37, 99, 235, 0.15)';
      ctx.fillRect(minSx, minSy, boxW, boxH);
      ctx.setLineDash([]);
    }

    ctx.restore();
  }, [
    scenario,
    layers,
    selectedEntity,
    scale,
    offset,
    minX,
    minY,
    maxX,
    maxY,
    toScreen,
    dragAction,
    boxDrawEnd,
  ]);

  // Mouse Handlers
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const { x: wx, y: wy } = toWorld(sx, sy);

    setIsMouseDown(true);

    // Pan tool or middle click
    if (activeTool === 'pan' || e.button === 1 || e.altKey) {
      setDragAction({
        type: 'pan',
        startClientX: e.clientX,
        startClientY: e.clientY,
        initialOffset: { ...offset },
      });
      return;
    }

    // Delete tool
    if (activeTool === 'delete') {
      const hit = findEntityAt(wx, wy);
      if (hit) {
        deleteEntity(hit);
      }
      return;
    }

    // Set Robot Start tool
    if (activeTool === 'set_robot') {
      onUpdateScenario((prev) => ({
        ...prev,
        start: {
          x: Math.round(wx * 10) / 10,
          y: Math.round(wy * 10) / 10,
          theta: prev.start?.theta ?? 0,
        },
      }));
      onSelect({ type: 'robot' });
      setDragAction({
        type: 'rotate_robot',
        centerWorldX: wx,
        centerWorldY: wy,
      });
      return;
    }

    // Add Pallet tool (1.2m x 0.8m)
    if (activeTool === 'add_pallet') {
      const w = 1.2;
      const h = 0.8;
      const patchCount = (scenario.map_patches || []).length;
      const newPatch: ScenarioMapPatch = {
        id: `PALLET_${patchCount + 1}`,
        op: 'add',
        polygon: [
          [Math.round((wx - w / 2) * 10) / 10, Math.round((wy - h / 2) * 10) / 10],
          [Math.round((wx + w / 2) * 10) / 10, Math.round((wy - h / 2) * 10) / 10],
          [Math.round((wx + w / 2) * 10) / 10, Math.round((wy + h / 2) * 10) / 10],
          [Math.round((wx - w / 2) * 10) / 10, Math.round((wy + h / 2) * 10) / 10],
        ],
      };
      onUpdateScenario((prev) => ({
        ...prev,
        map_patches: [...(prev.map_patches || []), newPatch],
      }));
      onSelect({ type: 'obstacle', index: patchCount, id: newPatch.id });
      return;
    }

    // Add Container tool (6.0m x 2.4m)
    if (activeTool === 'add_container') {
      const w = 6.0;
      const h = 2.4;
      const patchCount = (scenario.map_patches || []).length;
      const newPatch: ScenarioMapPatch = {
        id: `CONTAINER_${patchCount + 1}`,
        op: 'add',
        polygon: [
          [Math.round((wx - w / 2) * 10) / 10, Math.round((wy - h / 2) * 10) / 10],
          [Math.round((wx + w / 2) * 10) / 10, Math.round((wy - h / 2) * 10) / 10],
          [Math.round((wx + w / 2) * 10) / 10, Math.round((wy + h / 2) * 10) / 10],
          [Math.round((wx - w / 2) * 10) / 10, Math.round((wy + h / 2) * 10) / 10],
        ],
      };
      onUpdateScenario((prev) => ({
        ...prev,
        map_patches: [...(prev.map_patches || []), newPatch],
      }));
      onSelect({ type: 'obstacle', index: patchCount, id: newPatch.id });
      return;
    }

    // Add Pedestrian tool (places start and destination waypoint)
    if (activeTool === 'add_pedestrian') {
      const pedCount = (scenario.pedestrians || []).length;
      const newPed: ScenarioPedestrian = {
        id: `p${pedCount + 1}`,
        waypoints: [
          [Math.round(wx * 10) / 10, Math.round(wy * 10) / 10],
          [Math.round(wx * 10) / 10, Math.round((wy + 15) * 10) / 10],
        ],
        speed: 1.0,
        inattentive: false,
        loop: true,
        t_start: 10.0,
      };
      onUpdateScenario((prev) => ({
        ...prev,
        pedestrians: [...(prev.pedestrians || []), newPed],
      }));
      onSelect({ type: 'pedestrian', index: pedCount, id: newPed.id });
      return;
    }

    // Add Zone tool (start drag box)
    if (activeTool === 'add_zone') {
      setDragAction({
        type: 'box_draw',
        startWorldX: wx,
        startWorldY: wy,
      });
      setBoxDrawEnd({ x: wx, y: wy });
      return;
    }

    // Add Dock tool
    if (activeTool === 'add_dock') {
      const dockCount = Object.keys(scenario.map?.points || {}).length;
      const dockId = `dock_${dockCount + 1}`;
      onUpdateScenario((prev) => ({
        ...prev,
        map: {
          ...prev.map,
          points: {
            ...prev.map?.points,
            [dockId]: {
              x: Math.round(wx * 10) / 10,
              y: Math.round(wy * 10) / 10,
              heading: 0,
              tol: 0.2,
              label: `Док ${dockCount + 1}`,
            },
          },
        },
      }));
      onSelect({ type: 'dock', id: dockId });
      return;
    }

    // Select Tool: hit test and drag
    if (activeTool === 'select') {
      const hit = findEntityAt(wx, wy);
      onSelect(hit);

      if (hit) {
        let initialObjState: any = null;
        if (hit.type === 'robot') {
          initialObjState = { ...scenario.start };
        } else if (hit.type === 'obstacle' && hit.index !== undefined) {
          initialObjState = JSON.parse(JSON.stringify(scenario.map_patches?.[hit.index]));
        } else if (hit.type === 'pedestrian_waypoint' && hit.index !== undefined && hit.waypointIndex !== undefined) {
          initialObjState = [...(scenario.pedestrians[hit.index].waypoints[hit.waypointIndex] || [0, 0])];
        } else if (hit.type === 'dock' && hit.id) {
          initialObjState = { ...(scenario.map?.points?.[hit.id] || { x: 0, y: 0 }) };
        }

        setDragAction({
          type: 'move_entity',
          entity: hit,
          startWorldX: wx,
          startWorldY: wy,
          initialObjState,
        });
      } else {
        // Click on empty space: pan canvas
        setDragAction({
          type: 'pan',
          startClientX: e.clientX,
          startClientY: e.clientY,
          initialOffset: { ...offset },
        });
      }
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const { x: wx, y: wy } = toWorld(sx, sy);

    setCursorCoords({
      x: Math.round(wx * 10) / 10,
      y: Math.round(wy * 10) / 10,
    });

    if (!isMouseDown || !dragAction) return;

    if (dragAction.type === 'pan') {
      const dx = e.clientX - dragAction.startClientX;
      const dy = e.clientY - dragAction.startClientY;
      setOffset({
        x: dragAction.initialOffset.x + dx,
        y: dragAction.initialOffset.y + dy,
      });
      return;
    }

    if (dragAction.type === 'rotate_robot') {
      const dx = wx - dragAction.centerWorldX;
      const dy = wy - dragAction.centerWorldY;
      const theta = Math.atan2(dy, dx);
      onUpdateScenario((prev) => ({
        ...prev,
        start: {
          ...prev.start,
          theta: Math.round(theta * 100) / 100,
        },
      }));
      return;
    }

    if (dragAction.type === 'box_draw') {
      setBoxDrawEnd({ x: wx, y: wy });
      return;
    }

    if (dragAction.type === 'move_entity') {
      const deltaX = wx - dragAction.startWorldX;
      const deltaY = wy - dragAction.startWorldY;
      const ent = dragAction.entity;

      if (ent.type === 'robot') {
        onUpdateScenario((prev) => ({
          ...prev,
          start: {
            ...prev.start,
            x: Math.round((dragAction.initialObjState.x + deltaX) * 10) / 10,
            y: Math.round((dragAction.initialObjState.y + deltaY) * 10) / 10,
          },
        }));
      } else if (ent.type === 'obstacle' && ent.index !== undefined) {
        onUpdateScenario((prev) => {
          const patches = [...(prev.map_patches || [])];
          if (!patches[ent.index!]) return prev;
          const initialPoly: [number, number][] = dragAction.initialObjState.polygon;
          patches[ent.index!] = {
            ...patches[ent.index!],
            polygon: initialPoly.map(([px, py]) => [
              Math.round((px + deltaX) * 10) / 10,
              Math.round((py + deltaY) * 10) / 10,
            ]),
          };
          return { ...prev, map_patches: patches };
        });
      } else if (
        ent.type === 'pedestrian_waypoint' &&
        ent.index !== undefined &&
        ent.waypointIndex !== undefined
      ) {
        onUpdateScenario((prev) => {
          const peds = [...(prev.pedestrians || [])];
          if (!peds[ent.index!]) return prev;
          const waypoints = [...peds[ent.index!].waypoints];
          waypoints[ent.waypointIndex!] = [
            Math.round((dragAction.initialObjState[0] + deltaX) * 10) / 10,
            Math.round((dragAction.initialObjState[1] + deltaY) * 10) / 10,
          ];
          peds[ent.index!] = { ...peds[ent.index!], waypoints };
          return { ...prev, pedestrians: peds };
        });
      } else if (ent.type === 'dock' && ent.id) {
        onUpdateScenario((prev) => {
          const pts = { ...(prev.map?.points || {}) };
          if (!pts[ent.id!]) return prev;
          pts[ent.id!] = {
            ...pts[ent.id!],
            x: Math.round((dragAction.initialObjState.x + deltaX) * 10) / 10,
            y: Math.round((dragAction.initialObjState.y + deltaY) * 10) / 10,
          };
          return {
            ...prev,
            map: { ...prev.map, points: pts },
          };
        });
      }
    }
  };

  const handleMouseUp = () => {
    if (dragAction?.type === 'box_draw' && boxDrawEnd) {
      const minXBox = Math.min(dragAction.startWorldX, boxDrawEnd.x);
      const maxXBox = Math.max(dragAction.startWorldX, boxDrawEnd.x);
      const minYBox = Math.min(dragAction.startWorldY, boxDrawEnd.y);
      const maxYBox = Math.max(dragAction.startWorldY, boxDrawEnd.y);

      // Only create if not a tiny jitter click (> 1m width & height)
      if (maxXBox - minXBox > 1 && maxYBox - minYBox > 1) {
        const zoneCount = (scenario.map?.zones || []).length;
        const prefixMap = {
          speed_limit: 'SL',
          forbidden: 'FB',
          gnss_shadow: 'SH',
          people_area: 'PA',
        };
        const prefix = prefixMap[activeZoneType] || 'ZN';
        const newZone: ScenarioZone = {
          id: `${prefix}_${zoneCount + 1}`,
          type: activeZoneType,
          v_max: activeZoneType === 'speed_limit' ? 0.8 : undefined,
          polygon: [
            [Math.round(minXBox * 10) / 10, Math.round(minYBox * 10) / 10],
            [Math.round(maxXBox * 10) / 10, Math.round(minYBox * 10) / 10],
            [Math.round(maxXBox * 10) / 10, Math.round(maxYBox * 10) / 10],
            [Math.round(minXBox * 10) / 10, Math.round(maxYBox * 10) / 10],
          ],
        };

        onUpdateScenario((prev) => ({
          ...prev,
          map: {
            ...prev.map,
            zones: [...(prev.map?.zones || []), newZone],
          },
        }));
        onSelect({ type: 'zone', index: zoneCount, id: newZone.id });
      }
      setBoxDrawEnd(null);
    }

    setIsMouseDown(false);
    setDragAction(null);
  };

  const deleteEntity = (ent: SelectedEntity) => {
    if (ent.type === 'obstacle' && ent.index !== undefined) {
      onUpdateScenario((prev) => {
        const patches = [...(prev.map_patches || [])];
        patches.splice(ent.index!, 1);
        return { ...prev, map_patches: patches };
      });
      onSelect(null);
    } else if (ent.type === 'pedestrian' && ent.index !== undefined) {
      onUpdateScenario((prev) => {
        const peds = [...(prev.pedestrians || [])];
        peds.splice(ent.index!, 1);
        return { ...prev, pedestrians: peds };
      });
      onSelect(null);
    } else if (ent.type === 'zone' && ent.index !== undefined) {
      onUpdateScenario((prev) => {
        const zones = [...(prev.map?.zones || [])];
        zones.splice(ent.index!, 1);
        return { ...prev, map: { ...prev.map, zones } };
      });
      onSelect(null);
    } else if (ent.type === 'dock' && ent.id) {
      onUpdateScenario((prev) => {
        const pts = { ...(prev.map?.points || {}) };
        delete pts[ent.id!];
        return { ...prev, map: { ...prev.map, points: pts } };
      });
      onSelect(null);
    }
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
    const newScale = Math.min(15, Math.max(0.8, scale * zoomFactor));

    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    // Zoom towards mouse pointer
    setOffset({
      x: mouseX - (mouseX - offset.x) * (newScale / scale),
      y: mouseY - (mouseY - offset.y) * (newScale / scale),
    });
    setScale(newScale);
  };

  return (
    <div className={`relative w-full h-full overflow-hidden select-none bg-slate-50 ${className}`}>
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onWheel={handleWheel}
        className={`w-full h-full block ${
          activeTool === 'pan' || dragAction?.type === 'pan'
            ? 'cursor-grab'
            : activeTool === 'delete'
            ? 'cursor-crosshair'
            : activeTool === 'select'
            ? 'cursor-default'
            : 'cursor-crosshair'
        }`}
      />

      {/* Top-left: Compass and Coordinates */}
      <div className="absolute top-3 left-3 bg-white/90 backdrop-blur-sm border border-slate-200 rounded-lg px-2.5 py-1.5 shadow-sm text-xs text-slate-700 flex items-center gap-3 pointer-events-none">
        <div className="flex items-center gap-1 font-bold text-slate-500">
          <span>С</span>
          <svg className="w-3 h-3 text-blue-600" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="12,2 18,22 12,17 6,22" />
          </svg>
        </div>
        <div className="h-3 w-px bg-slate-300" />
        {cursorCoords ? (
          <span className="font-mono text-[11px]">
            X: <strong className="text-slate-900">{cursorCoords.x.toFixed(1)}</strong> м, Y:{' '}
            <strong className="text-slate-900">{cursorCoords.y.toFixed(1)}</strong> м
          </span>
        ) : (
          <span className="text-slate-400">Наведите на карту</span>
        )}
      </div>

      {/* Bottom-right: Zoom controls */}
      <div className="absolute bottom-3 right-3 flex flex-col gap-1 bg-white border border-slate-200 rounded-lg shadow-sm p-1 z-10">
        <button
          onClick={() => setScale((s) => Math.min(15, s * 1.25))}
          className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
          title="Приблизить"
        >
          +
        </button>
        <button
          onClick={() => setScale((s) => Math.max(0.8, s * 0.8))}
          className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
          title="Отдалить"
        >
          -
        </button>
        <button
          onClick={fitToBounds}
          className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-[11px] font-semibold"
          title="Вписать полигон"
        >
          1:1
        </button>
      </div>
    </div>
  );
};
