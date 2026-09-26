import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiClient } from '../api/client';

describe('apiClient & fallbackData', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('fetchScenarios', () => {
    it('returns remote scenario items on HTTP 200', async () => {
      const mockScenarios = [
        { id: 'sc1', name: 'Test Scenario', description: 'Desc', type: 'standard', file: 'f.json', hasReport: true, score: 99 }
      ];
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockScenarios,
      });

      const res = await apiClient.fetchScenarios();
      expect(global.fetch).toHaveBeenCalledWith('/api/scenarios');
      expect(res).toEqual(mockScenarios);
    });

    it('falls back to fallbackData on network rejection', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network disconnected'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchScenarios();
      expect(warnSpy).toHaveBeenCalled();
      expect(res.length).toBeGreaterThan(0);
      expect(res.some((s) => s.id === '04_busy_yard')).toBe(true);
      expect(res.some((s) => s.type === 'custom')).toBe(true);
    });

    it('falls back to fallbackData on HTTP error status (500)', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      });
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchScenarios();
      expect(warnSpy).toHaveBeenCalled();
      expect(res.length).toBeGreaterThanOrEqual(10);
    });
  });

  describe('fetchDashboard', () => {
    it('fetches dashboard data from /api/ui/dashboard with scenario param', async () => {
      const mockVm = { scenario: '01_clear', totalScore: 100 };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockVm,
      });

      const res = await apiClient.fetchDashboard('01_clear');
      expect(global.fetch).toHaveBeenCalledWith('/api/ui/dashboard?scenario=01_clear');
      expect(res).toEqual(mockVm);
    });

    it('uses fallback on HTTP error and populates empty dashboard model', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Server offline'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchDashboard('custom_scenario');
      expect(warnSpy).toHaveBeenCalled();
      expect(res.scenario).toBe('custom_scenario');
      expect(typeof res.totalScore).toBe('number');
      expect(res.totalScore).toBe(0);
      expect(res.totalMax).toBe(100);
      expect(res.speedTimestamps.length).toBe(0);
      expect(res.recentEvents).toEqual([]);
      expect(res.mapData).toBeNull();
    });
  });

  describe('fetchReplay', () => {
    it('fetches replay telemetry with scenario and seed query params', async () => {
      const mockReplay = { scenario: '02_gnss_shadow', seed: 42, ticks: [] };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockReplay,
      });

      const res = await apiClient.fetchReplay('02_gnss_shadow', 42);
      expect(global.fetch).toHaveBeenCalledWith('/api/ui/replay?scenario=02_gnss_shadow&seed=42');
      expect(res).toEqual(mockReplay);
    });

    it('uses fallback replay data on fetch failure', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Fetch error'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchReplay('04_busy_yard', 7);
      expect(warnSpy).toHaveBeenCalled();
      expect(res.scenario).toBe('04_busy_yard');
      expect(res.ticks.length).toBe(0);
      expect(res.episodes.length).toBe(0);
      expect(res.header.dt).toBe(0.1);
    });
  });

  describe('fetchEpisodes', () => {
    it('fetches episodes data successfully', async () => {
      const mockEp = { scenario: 's1_pallet', episodes: [] };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockEp,
      });

      const res = await apiClient.fetchEpisodes('s1_pallet');
      expect(global.fetch).toHaveBeenCalledWith('/api/ui/episodes?scenario=s1_pallet');
      expect(res).toEqual(mockEp);
    });

    it('falls back on failure with calculated summary', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Connection refused'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchEpisodes('04_busy_yard');
      expect(warnSpy).toHaveBeenCalled();
      expect(res.scenario).toBe('04_busy_yard');
      expect(res.summary.totalCost).toBe(0);
      expect(res.episodes.length).toBe(0);
    });
  });

  describe('fetchMissions', () => {
    it('fetches missions performance model', async () => {
      const mockMissions = { scenario: '01_clear', missions: [] };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockMissions,
      });

      const res = await apiClient.fetchMissions('01_clear');
      expect(global.fetch).toHaveBeenCalledWith('/api/ui/missions?scenario=01_clear');
      expect(res).toEqual(mockMissions);
    });

    it('falls back on network error with missions list and score', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Failed to fetch'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchMissions('04_busy_yard');
      expect(warnSpy).toHaveBeenCalled();
      expect(res.summary.completed).toBe(0);
      expect(res.summary.deliveryScore).toBe(0);
      expect(res.missions.length).toBe(0);
    });
  });

  describe('fetchAnalytics', () => {
    it('fetches analytics with 6 regulation blocks and radar chart', async () => {
      const mockAnalytics = { scenario: '04_busy_yard', totalScore: 98.18, blocks: [] };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockAnalytics,
      });

      const res = await apiClient.fetchAnalytics('04_busy_yard');
      expect(global.fetch).toHaveBeenCalledWith('/api/ui/analytics?scenario=04_busy_yard');
      expect(res).toEqual(mockAnalytics);
    });

    it('falls back to 6 regulation blocks on error', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Failed to fetch'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.fetchAnalytics('04_busy_yard');
      expect(warnSpy).toHaveBeenCalled();
      expect(res.blocks.length).toBe(0);
      expect(res.radar.labels.length).toBe(0);
      expect(res.radar.values.length).toBe(0);
      expect(res.sandbox.violations.length).toBe(0);
      expect(res.computeBudget.fact_s).toBeLessThanOrEqual(res.computeBudget.limit_s);
    });
  });

  describe('runSimulation', () => {
    it('executes POST /api/run with simulation parameters', async () => {
      const mockResult = {
        scenario: '01_clear',
        seed: 7,
        exitCode: 0,
        score: 99.72,
        duration: 4.5,
        wallTimeMs: 1200,
        completed: true,
      };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResult,
      });

      const params = { scenario: '01_clear', seed: 7, cheat: false };
      const res = await apiClient.runSimulation(params);
      expect(global.fetch).toHaveBeenCalledWith('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      expect(res).toEqual(mockResult);
    });

    it('throws descriptive error on server failure', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: async () => 'Scenario not found',
      });

      await expect(apiClient.runSimulation({ scenario: 'nonexistent', seed: 1 })).rejects.toThrow(
        'Simulation failed (HTTP 400): Scenario not found'
      );
    });
  });

  describe('getExportCsvUrl', () => {
    it('generates correct CSV export URL with encoded scenarioId', () => {
      const url = apiClient.getExportCsvUrl('s1_pallet 2m');
      expect(url).toBe('/api/export/csv?scenario=s1_pallet%202m');
    });

    it('uses default scenario when none passed', () => {
      const url = apiClient.getExportCsvUrl();
      expect(url).toBe('/api/export/csv?scenario=04_busy_yard');
    });
  });

  describe('saveScenario', () => {
    it('sends scenario data to /api/scenarios/save on HTTP 200', async () => {
      const mockResponse = { ok: true, file: 'scenarios/custom_1.json' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      });

      const res = await apiClient.saveScenario('custom_1', { name: 'custom_1', dt: 0.1 });
      expect(global.fetch).toHaveBeenCalledWith('/api/scenarios/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'custom_1', scenario: { name: 'custom_1', dt: 0.1 } }),
      });
      expect(res).toEqual(mockResponse);
    });

    it('gracefully handles network error and returns ok: true', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const res = await apiClient.saveScenario('test_offline', { name: 'test_offline' });
      expect(warnSpy).toHaveBeenCalled();
      expect(res.ok).toBe(true);
    });
  });

  describe('getApiBase subpath resolution', () => {
    it('returns /api by default on root path', async () => {
      const { getApiBase } = await import('../api/client');
      expect(getApiBase()).toBe('/api');
    });

    it('returns /amr/api when hosted under /amr subpath', async () => {
      const originalPathname = window.location.pathname;
      try {
        Object.defineProperty(window, 'location', {
          value: { ...window.location, pathname: '/amr/' },
          writable: true,
          configurable: true,
        });
        const { getApiBase } = await import('../api/client');
        expect(getApiBase()).toBe('/amr/api');
      } finally {
        Object.defineProperty(window, 'location', {
          value: { ...window.location, pathname: originalPathname },
          writable: true,
          configurable: true,
        });
      }
    });
  });
});

