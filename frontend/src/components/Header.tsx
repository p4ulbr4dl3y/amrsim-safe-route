import React from 'react';
import { RouteName } from '../types';

interface HeaderProps {
  currentRoute: RouteName;
  onNavigate: (route: RouteName) => void;
}

export const Header: React.FC<HeaderProps> = ({ currentRoute, onNavigate }) => {
  const navItems: { route: RouteName; label: string }[] = [
    { route: 'dashboard', label: 'Дашборд' },
    { route: 'replay', label: 'Просмотр' },
    { route: 'episodes', label: 'Инциденты' },
    { route: 'missions', label: 'Миссии' },
    { route: 'analytics', label: 'Аналитика' },
  ];

  return (
    <header className="bg-white border-b border-slate-200 sticky top-0 z-40 px-6 py-2.5 flex items-center justify-between shadow-sm">
      {/* Left: Brand Logo & Title */}
      <div 
        onClick={() => onNavigate('dashboard')}
        className="flex items-center gap-3 cursor-pointer group select-none"
      >
        {/* Slanted 3 bars logo matching mockup */}
        <div className="flex gap-1 items-center h-6">
          <span className="w-1.5 h-5 bg-blue-600 rounded-sm transform -skew-x-12"></span>
          <span className="w-1.5 h-5 bg-blue-500 rounded-sm transform -skew-x-12"></span>
          <span className="w-1.5 h-5 bg-blue-400 rounded-sm transform -skew-x-12"></span>
        </div>
        <div className="flex items-center gap-2.5">
          <span className="font-bold text-slate-900 tracking-tight text-lg">
            AMR <span className="text-blue-600">SafeRoute</span>
          </span>
        </div>
      </div>

      {/* Center: Main Navigation (5 items) */}
      <nav className="flex items-center gap-8">
        {navItems.map((item) => {
          const isActive = currentRoute === item.route;
          return (
            <button
              key={item.route}
              onClick={() => onNavigate(item.route)}
              className={`relative py-1.5 text-sm font-medium transition-colors select-none ${
                isActive 
                  ? 'text-blue-600 font-semibold' 
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {item.label}
              {isActive && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600 rounded-full" />
              )}
            </button>
          );
        })}
      </nav>

      {/* Right placeholder to keep nav centered */}
      <div className="w-48 hidden md:block"></div>
    </header>
  );
};
