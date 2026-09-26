import React, { useState, useEffect } from 'react';
import { RouteName } from './types';
import { Header } from './components/Header';
import {
  clearUploadedScenario,
  getSelectedScenario,
  setSelectedScenario,
  AMR_SCENARIO_CHANGE_EVENT,
} from './utils/scenarioStorage';
import { DashboardPage } from './pages/DashboardPage';
import { ReplayPage } from './pages/ReplayPage';
import { EpisodesPage } from './pages/EpisodesPage';
import { MissionsPage } from './pages/MissionsPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { RunnerPage } from './pages/RunnerPage';
import { ConstructorPage } from './pages/ConstructorPage';

export const App: React.FC = () => {
  const [currentRoute, setCurrentRoute] = useState<RouteName>('dashboard');
  const [queryParams, setQueryParams] = useState<Record<string, any>>({});
  const [activeScenario, setActiveScenario] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const hash = window.location.hash.replace(/^#\/?/, '');
      const [, queryString] = hash.split('?');
      if (queryString) {
        const sp = new URLSearchParams(queryString);
        const sc = sp.get('scenario');
        if (sc) return sc;
      }
    }
    return getSelectedScenario();
  });

  // Reset uploaded scenario on page reload
  useEffect(() => {
    try {
      const navEntries = performance.getEntriesByType?.('navigation') as PerformanceNavigationTiming[];
      if (navEntries && navEntries.length > 0 && navEntries[0]?.type === 'reload') {
        clearUploadedScenario();
      }
    } catch (err) {
      console.warn('[App] Navigation reload check failed:', err);
    }
  }, []);

  // Listen for scenario change event across application
  useEffect(() => {
    const handleScenarioEvent = (e: any) => {
      const sc = e.detail;
      if (sc && sc !== activeScenario) {
        setActiveScenario(sc);
      }
    };
    window.addEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleScenarioEvent);
    return () => {
      window.removeEventListener(AMR_SCENARIO_CHANGE_EVENT as any, handleScenarioEvent);
    };
  }, [activeScenario]);

  // Parse window.location.hash on mount and on hashchange
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (!hash) {
        // Root / redirects to /dashboard with active scenario
        window.location.hash = `#/dashboard?scenario=${activeScenario}`;
        setCurrentRoute('dashboard');
        setQueryParams({ scenario: activeScenario });
        return;
      }

      const [path, queryString] = hash.split('?');
      const route = path as RouteName;
      const validRoutes: RouteName[] = ['dashboard', 'replay', 'episodes', 'missions', 'analytics', 'runner', 'constructor'];

      if (validRoutes.includes(route)) {
        setCurrentRoute(route);
      } else {
        window.location.hash = `#/dashboard?scenario=${activeScenario}`;
        setCurrentRoute('dashboard');
      }

      // Parse query string
      const params: Record<string, any> = {};
      if (queryString) {
        const searchParams = new URLSearchParams(queryString);
        searchParams.forEach((val, key) => {
          params[key] = val;
        });
      }
      setQueryParams(params);

      if (params.scenario && params.scenario !== activeScenario) {
        setActiveScenario(params.scenario);
        setSelectedScenario(params.scenario);
      }
    };

    handleHashChange();
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [activeScenario]);

  // Programmatic navigation handler
  const handleNavigate = (route: RouteName, params?: Record<string, any>) => {
    const finalParams = params?.scenario ? { ...params } : { scenario: activeScenario, ...params };
    let hash = `#/${route}`;
    if (finalParams && Object.keys(finalParams).length > 0) {
      const search = new URLSearchParams();
      Object.entries(finalParams).forEach(([k, v]) => {
        if (v !== undefined && v !== null) {
          search.set(k, String(v));
        }
      });
      const searchStr = search.toString();
      if (searchStr) {
        hash += `?${searchStr}`;
      }
    }
    window.location.hash = hash;
  };

  const handleScenarioChange = (sc: string) => {
    setActiveScenario(sc);
    setSelectedScenario(sc);
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#F8FAFC] min-w-[1280px] w-full overflow-x-auto">
      {/* Shared Header across all pages without operator */}
      <Header currentRoute={currentRoute} onNavigate={handleNavigate} />

      {/* Main Page Content */}
      <main className="flex-1 flex flex-col min-w-[1280px] w-full">
        {currentRoute === 'dashboard' && (
          <DashboardPage
            onNavigate={handleNavigate}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'replay' && (
          <ReplayPage
            queryParams={queryParams}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'episodes' && (
          <EpisodesPage
            onNavigate={handleNavigate}
            queryParams={queryParams}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'missions' && (
          <MissionsPage
            onNavigate={handleNavigate}
            queryParams={queryParams}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'analytics' && (
          <AnalyticsPage
            onNavigate={handleNavigate}
            queryParams={queryParams}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'runner' && (
          <RunnerPage
            onNavigate={handleNavigate}
            queryParams={queryParams}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
        {currentRoute === 'constructor' && (
          <ConstructorPage
            onNavigate={handleNavigate}
            activeScenario={activeScenario}
            onScenarioChange={handleScenarioChange}
          />
        )}
      </main>
    </div>
  );
};

export default App;
