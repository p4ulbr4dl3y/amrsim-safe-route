import React, { useRef, useEffect, useState } from 'react';
import { mockMapData } from '../mock/mockData';
import { TickData } from '../types';

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
};

export const MapCanvas: React.FC<MapCanvasProps> = ({
  currentTick,
  historyTicks = [],
  highlightMission = null,
  targetCoords = null,
  layers = defaultLayers,
  followRobot = false,
  className = '',
  isMiniMap = false
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Viewport transformation: scale and offset
  const [scale, setScale] = useState(isMiniMap ? 3.0 : 3.8);
  const [offset, setOffset] = useState({ x: isMiniMap ? 10 : 30, y: isMiniMap ? 20 : 40 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Handle follow robot or target coordinates
  useEffect(() => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current;

    let targetX = currentTick?.x;
    let targetY = currentTick?.y;

    if (targetCoords) {
      targetX = targetCoords.x;
      targetY = targetCoords.y;
    } else if (!followRobot && !isMiniMap) {
      return;
    }

    if (targetX !== undefined && targetY !== undefined) {
      const worldHeight = mockMapData.bounds[3]; // 200m
      const canvasX = canvas.width / 2;
      const canvasY = canvas.height / 2;

      // screenX = targetX * scale + offsetX => offsetX = canvasX - targetX * scale
      // screenY = (worldHeight - targetY) * scale + offsetY => offsetY = canvasY - (worldHeight - targetY) * scale
      setOffset({
        x: canvasX - targetX * scale,
        y: canvasY - (worldHeight - targetY) * scale
      });
    }
  }, [followRobot, currentTick?.x, currentTick?.y, targetCoords, isMiniMap, scale]);

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

    const worldHeight = mockMapData.bounds[3]; // 200m

    // Transform helper: world (X, Y) -> screen (px, py)
    const toScreen = (wx: number, wy: number) => {
      return {
        x: wx * scale + offset.x,
        y: (worldHeight - wy) * scale + offset.y
      };
    };

    // 1. Background Grid
    ctx.strokeStyle = '#F1F5F9';
    ctx.lineWidth = 1;
    const gridSize = 20; // 20 meters
    for (let x = 0; x <= mockMapData.bounds[2]; x += gridSize) {
      const p1 = toScreen(x, 0);
      const p2 = toScreen(x, worldHeight);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    }
    for (let y = 0; y <= worldHeight; y += gridSize) {
      const p1 = toScreen(0, y);
      const p2 = toScreen(mockMapData.bounds[2], y);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    }

    // 2. Drivable Corridors
    if (layers.drivable && mockMapData.drivable) {
      ctx.fillStyle = '#E8EEF5';
      ctx.strokeStyle = '#CBD5E1';
      ctx.lineWidth = 1.5;

      mockMapData.drivable.forEach((poly: any) => {
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
    if (mockMapData.zones) {
      mockMapData.zones.forEach((zone: any) => {
        if (!zone.polygon || zone.polygon.length < 2) return;
        ctx.beginPath();
        const start = toScreen(zone.polygon[0][0], zone.polygon[0][1]);
        ctx.moveTo(start.x, start.y);
        for (let i = 1; i < zone.polygon.length; i++) {
          const pt = toScreen(zone.polygon[i][0], zone.polygon[i][1]);
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
    if (layers.buildings && mockMapData.buildings) {
      ctx.fillStyle = '#DDE3EA';
      ctx.strokeStyle = '#94A3B8';
      ctx.lineWidth = 1.2;

      mockMapData.buildings.forEach((b: any) => {
        if (b.polygon && b.polygon.length > 1) {
          ctx.beginPath();
          const start = toScreen(b.polygon[0][0], b.polygon[0][1]);
          ctx.moveTo(start.x, start.y);
          for (let i = 1; i < b.polygon.length; i++) {
            const pt = toScreen(b.polygon[i][0], b.polygon[i][1]);
            ctx.lineTo(pt.x, pt.y);
          }
          ctx.closePath();
          ctx.fill();
          ctx.stroke();
        }
      });
    }

    // 5. Reference Path (dashed line from warehouse to shop_a)
    if (layers.referencePath) {
      ctx.strokeStyle = '#93C5FD';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      const pStart = toScreen(51.5, 150.0);
      const pMid1 = toScreen(75.0, 150.0);
      const pMid2 = toScreen(105.0, 150.0);
      const pMid3 = toScreen(200.0, 150.0);
      const pEnd = toScreen(220.0, 158.5);

      ctx.moveTo(pStart.x, pStart.y);
      ctx.lineTo(pMid1.x, pMid1.y);
      ctx.lineTo(pMid2.x, pMid2.y);
      ctx.lineTo(pMid3.x, pMid3.y);
      ctx.lineTo(pEnd.x, pEnd.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // 6. Dock Stations
    if (layers.docks && mockMapData.points) {
      Object.entries(mockMapData.points).forEach(([id, pt]: [string, any]) => {
        const screenPt = toScreen(pt.x, pt.y);

        // Outer circle (tolerance radius)
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, Math.max(7, (pt.tol || 0.2) * scale * 10), 0, Math.PI * 2);
        ctx.strokeStyle = '#2563EB';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Inner solid dot
        ctx.beginPath();
        ctx.arc(screenPt.x, screenPt.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#2563EB';
        ctx.fill();

        // Dock Label
        if (!isMiniMap) {
          ctx.font = '10px Inter, sans-serif';
          ctx.fillStyle = '#475569';
          ctx.textAlign = 'left';
          ctx.fillText(pt.label || id, screenPt.x + 10, screenPt.y + 3);
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
      ctx.strokeStyle = '#059669'; // Teal-emerald trail matching mockup
      ctx.lineWidth = 2.5;
      ctx.stroke();
    }

    // 8. Active Tick: AMR Platform & Sensors
    if (currentTick) {
      const robotScreen = toScreen(currentTick.x, currentTick.y);
      const robotRadius = 0.9 * scale; // 0.9m platform radius

      // 8a. Lidar Rays
      if (layers.lidar && currentTick.lidarRays) {
        ctx.strokeStyle = 'rgba(147, 197, 253, 0.45)';
        ctx.lineWidth = 1;
        currentTick.lidarRays.forEach(ray => {
          const endWx = currentTick.x + Math.cos(ray.angle) * ray.dist;
          const endWy = currentTick.y + Math.sin(ray.angle) * ray.dist;
          const rayEnd = toScreen(endWx, endWy);
          ctx.beginPath();
          ctx.moveTo(robotScreen.x, robotScreen.y);
          ctx.lineTo(rayEnd.x, rayEnd.y);
          ctx.stroke();
        });
      }

      // 8b. Estimated Pose (Purple circle) & Discrepancy Vector
      if (layers.poseEst && currentTick.pe) {
        const peScreen = toScreen(currentTick.pe[0], currentTick.pe[1]);

        // Difference line (red dashed)
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
          ctx.arc(pedScreen.x, pedScreen.y, 3.0 * scale, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(251, 146, 60, 0.15)';
          ctx.strokeStyle = 'rgba(251, 146, 60, 0.4)';
          ctx.lineWidth = 1;
          ctx.fill();
          ctx.stroke();

          // Pedestrian core marker
          ctx.beginPath();
          ctx.arc(pedScreen.x, pedScreen.y, Math.max(4, 0.3 * scale), 0, Math.PI * 2);
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
        ctx.arc(0, 0, Math.max(6, robotRadius), 0, Math.PI * 2);
        ctx.fillStyle = '#10B981';
        ctx.fill();
        ctx.strokeStyle = '#065F46';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Directional arrow pointing forward (along heading)
        ctx.beginPath();
        ctx.moveTo(robotRadius * 0.8, 0);
        ctx.lineTo(-robotRadius * 0.4, -robotRadius * 0.5);
        ctx.lineTo(-robotRadius * 0.2, 0);
        ctx.lineTo(-robotRadius * 0.4, robotRadius * 0.5);
        ctx.closePath();
        ctx.fillStyle = '#FFFFFF';
        ctx.fill();

        ctx.restore();
      }
    }

    ctx.restore();
  }, [currentTick, historyTicks, layers, scale, offset, isMiniMap]);

  // Mouse pan & zoom handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setOffset({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  const handleWheel = (e: React.WheelEvent) => {
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
        className="w-full h-full cursor-grab active:cursor-grabbing block"
      />

      {/* Compass rose on top-left */}
      <div className="absolute top-4 left-4 flex flex-col items-center pointer-events-none opacity-80">
        <span className="text-[11px] font-bold text-slate-500">N</span>
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
            title="Zoom In"
          >
            +
          </button>
          <button
            onClick={() => setScale(s => Math.max(1.0, s * 0.8))}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
            title="Zoom Out"
          >
            -
          </button>
          <button
            onClick={() => {
              setScale(3.8);
              setOffset({ x: 30, y: 40 });
            }}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-xs font-semibold"
            title="Reset View"
          >
            1:1
          </button>
        </div>
      )}
    </div>
  );
};
