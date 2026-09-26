import React, { useRef, useEffect, useState } from 'react';
import { mockMapData } from '../mock/mockData';
import { TickData, MapData } from '../types';
import {
  drawGridAndDrivable,
  drawPaths,
  drawDynamicEntities,
} from './map/renderers';

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
  mapData,
}) => {
  const activeMap = mapData || (mockMapData as unknown as MapData);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Преобразование области просмотра: масштаб и смещение
  const [scale, setScale] = useState(isMiniMap ? 1.5 : 3.8);
  const [offset, setOffset] = useState({ x: isMiniMap ? 0 : 30, y: isMiniMap ? 0 : 40 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });

  // Автоматическое масштабирование для миникарты по границам склада
  const getBoundsFit = (canvasWidth: number, canvasHeight: number) => {
    const minX = (activeMap.bounds && activeMap.bounds[0]) ?? 0;
    const minY = (activeMap.bounds && activeMap.bounds[1]) ?? 0;
    const maxX = (activeMap.bounds && activeMap.bounds[2]) ?? 250;
    const maxY = (activeMap.bounds && activeMap.bounds[3]) ?? 200;
    const worldW = Math.max(1, maxX - minX);
    const worldH = Math.max(1, maxY - minY);
    const padding = 16;
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

  useEffect(() => {
    if (!isMiniMap) return;

    const updateFit = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      const { fitScale, fitOffset } = getBoundsFit(rect.width, rect.height);
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
  }, [isMiniMap, activeMap]);

  // Следование за роботом или центрирование по координатам (отключено на миникарте)
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
      const worldHeight = (activeMap.bounds && activeMap.bounds[3]) || 200; // 200m
      const canvasX = canvas.width / 2;
      const canvasY = canvas.height / 2;

      setOffset({
        x: canvasX - targetX * scale,
        y: canvasY - (worldHeight - targetY) * scale,
      });
    }
  }, [followRobot, currentTick?.x, currentTick?.y, targetCoords, isMiniMap, scale, activeMap]);

  // Цикл отрисовки через модульные рендереры
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // High-DPI support
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const minX = (activeMap.bounds && activeMap.bounds[0]) ?? 0;
    const minY = (activeMap.bounds && activeMap.bounds[1]) ?? 0;
    const maxX = (activeMap.bounds && activeMap.bounds[2]) ?? 250;
    const maxY = (activeMap.bounds && activeMap.bounds[3]) ?? 200;
    const worldWidth = Math.max(1, maxX - minX);
    const worldHeight = Math.max(1, maxY - minY);

    // Вычисление активного масштаба и смещения
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

    // Преобразование мировых координат (X, Y) в экранные (px, py)
    const toScreen = (wx: number, wy: number) => ({
      x: (wx - minX) * currentScale + currentOffset.x,
      y: (maxY - wy) * currentScale + currentOffset.y,
    });

    // 1. Статические элементы карты: сетка, периметр, проезды, зоны, здания, доки
    drawGridAndDrivable({
      ctx,
      mapData: activeMap,
      bounds: { minX, minY, maxX, maxY },
      toScreen,
      scale: currentScale,
      layers,
      isMiniMap,
    });

    // 2. Траектории: опорный маршрут и след истории
    drawPaths({
      ctx,
      mapData: activeMap,
      toScreen,
      historyTicks,
      layers,
    });

    // 3. Динамические сущности: робот, оценка позы, лидар, пешеходы
    drawDynamicEntities({
      ctx,
      currentTick,
      toScreen,
      scale: currentScale,
      layers,
    });

    ctx.restore();
  }, [currentTick, historyTicks, layers, scale, offset, isMiniMap, activeMap]);

  // Обработчики панорамирования и масштабирования мыши
  const handleMouseDown = (e: React.MouseEvent) => {
    if (isMiniMap) return;
    setIsDragging(true);
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isMiniMap || !isDragging) return;
    setOffset({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y,
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
            onClick={() => setScale((s) => Math.min(12, s * 1.2))}
            className="w-7 h-7 flex items-center justify-center text-slate-600 hover:bg-slate-100 rounded text-base font-bold"
            title="Zoom In"
          >
            +
          </button>
          <button
            onClick={() => setScale((s) => Math.max(1.0, s * 0.8))}
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
