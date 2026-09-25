import React, { useState, useEffect } from 'react';
import { RouteName } from './types';
import { Header } from './components/Header';
import { DashboardPage } from './pages/DashboardPage';
import { ReplayPage } from './pages/ReplayPage';
import { EpisodesPage } from './pages/EpisodesPage';
import { MissionsPage } from './pages/MissionsPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { RunnerPage } from './pages/RunnerPage';

export const App: React.FC = () => {
  const [currentRoute, setCurrentRoute] = useState<RouteName>('dashboard');
  const [queryParams, setQueryParams] = useState<Record<string, any>>({});

  // Разбор window.location.hash при монтировании и изменении хэша
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (!hash) {
        // Перенаправление корневого пути / на /dashboard
        window.location.hash = '#/dashboard';
        setCurrentRoute('dashboard');
        setQueryParams({});
        return;
      }

      const [path, queryString] = hash.split('?');
      const route = path as RouteName;
      const validRoutes: RouteName[] = ['dashboard', 'replay', 'episodes', 'missions', 'analytics', 'runner'];

      if (validRoutes.includes(route)) {
        setCurrentRoute(route);
      } else {
        window.location.hash = '#/dashboard';
        setCurrentRoute('dashboard');
      }

      // Разбор строки параметров запроса
      const params: Record<string, any> = {};
      if (queryString) {
        const searchParams = new URLSearchParams(queryString);
        searchParams.forEach((val, key) => {
          params[key] = val;
        });
      }
      setQueryParams(params);
    };

    handleHashChange();
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  // Обработчик программной навигации
  const handleNavigate = (route: RouteName, params?: Record<string, any>) => {
    let hash = `#/${route}`;
    if (params && Object.keys(params).length > 0) {
      const search = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) {
          search.set(k, String(v));
        }
      });
      hash += `?${search.toString()}`;
    }
    window.location.hash = hash;
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#F8FAFC]">
      {/* Shared Header across all pages without operator */}
      <Header currentRoute={currentRoute} onNavigate={handleNavigate} />

      {/* Main Page Content */}
      <main className="flex-1 flex flex-col">
        {currentRoute === 'dashboard' && <DashboardPage onNavigate={handleNavigate} />}
        {currentRoute === 'replay' && <ReplayPage queryParams={queryParams} />}
        {currentRoute === 'episodes' && <EpisodesPage onNavigate={handleNavigate} queryParams={queryParams} />}
        {currentRoute === 'missions' && <MissionsPage onNavigate={handleNavigate} queryParams={queryParams} />}
        {currentRoute === 'analytics' && <AnalyticsPage onNavigate={handleNavigate} />}
        {currentRoute === 'runner' && <RunnerPage onNavigate={handleNavigate} />}
      </main>
    </div>
  );
};

export default App;
