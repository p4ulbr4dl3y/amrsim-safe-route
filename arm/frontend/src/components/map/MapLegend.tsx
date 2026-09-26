import React from 'react';

export const MapLegend: React.FC = () => {
  return (
    <div className="bg-white border-t border-slate-100 px-4 py-2.5 flex flex-wrap items-center justify-between gap-y-2 text-[11px] text-slate-600">
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block"></span>
        <span>Робот</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-full border-2 border-purple-500 inline-block"></span>
        <span>Оценка позы</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 border-b-2 border-dashed border-red-500 inline-block"></span>
        <span>Разница поз</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-0.5 bg-blue-300 inline-block"></span>
        <span>Лидар</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 border-b-2 border-dashed border-blue-400 inline-block"></span>
        <span>Опорный маршрут</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-2 bg-slate-200 rounded-sm inline-block"></span>
        <span>Проезжая часть</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-2 bg-slate-300 rounded-sm inline-block"></span>
        <span>Здание</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-full border-2 border-blue-600 inline-block"></span>
        <span>Док</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-2.5 h-2.5 rounded-full bg-orange-500 inline-block"></span>
        <span>Пешеход (3 м)</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-2 bg-amber-400 border border-amber-600 rounded-sm inline-block"></span>
        <span>Поддон</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-3 h-2 bg-slate-500 border border-slate-800 rounded-sm inline-block"></span>
        <span>Контейнер</span>
      </div>
    </div>
  );
};
