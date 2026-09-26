import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import { App } from '../App';
import {
  getSelectedScenario,
  setSelectedScenario,
  saveUploadedScenario,
  clearUploadedScenario,
  hasUploadedScenario,
  AMR_SELECTED_SCENARIO_KEY,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';
import { EpisodesPage } from '../pages/EpisodesPage';
import { MissionsPage } from '../pages/MissionsPage';
import { DashboardPage } from '../pages/DashboardPage';
import { RunnerPage } from '../pages/RunnerPage';
import { apiClient } from '../api/client';

beforeAll(() => {
  // Mock canvas 2D context
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({
    fillRect: vi.fn(),
    clearRect: vi.fn(),
    getImageData: vi.fn(),
    putImageData: vi.fn(),
    createImageData: vi.fn(),
    setTransform: vi.fn(),
    drawImage: vi.fn(),
    save: vi.fn(),
    fillText: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    rotate: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    strokeRect: vi.fn(),
    measureText: vi.fn().mockReturnValue({ width: 0 }),
    transform: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: vi.fn(),
    getLineDash: vi.fn().mockReturnValue([]),
    arcTo: vi.fn(),
    createLinearGradient: vi.fn().mockReturnValue({
      addColorStop: vi.fn(),
    }),
  });

  // Mock ResizeObserver
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe('Global Scenario Synchronization', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    window.location.hash = '';
    vi.clearAllMocks();
  });

  describe('scenarioStorage selected scenario management', () => {
    it('returns 04_busy_yard fallback when nothing is stored', () => {
      expect(getSelectedScenario()).toBe('04_busy_yard');
    });

    it('persists selected scenario to localStorage and dispatches CustomEvent', () => {
      const listener = vi.fn();
      window.addEventListener(AMR_SCENARIO_CHANGE_EVENT, listener);

      setSelectedScenario('01_clear');

      expect(localStorage.getItem(AMR_SELECTED_SCENARIO_KEY)).toBe('01_clear');
      expect(getSelectedScenario()).toBe('01_clear');
      expect(listener).toHaveBeenCalled();
      const eventDetail = listener.mock.calls[0][0].detail;
      expect(eventDetail).toBe('01_clear');

      window.removeEventListener(AMR_SCENARIO_CHANGE_EVENT, listener);
    });

    it('prioritizes uploaded scenario over localStorage value', () => {
      setSelectedScenario('01_clear');
      expect(getSelectedScenario()).toBe('01_clear');

      saveUploadedScenario({
        id: 'uploaded_scenario_custom',
        name: 'Custom Warehouse',
        fileName: 'custom.json',
        fileType: 'scenario',
        uploadedAt: Date.now(),
      });

      expect(getSelectedScenario()).toBe('uploaded_scenario_custom');

      clearUploadedScenario();
      expect(getSelectedScenario()).toBe('01_clear');
    });
  });

  describe('Page scenario sync and App hash propagation', () => {
    it('synchronizes scenario change from EpisodesPage to URL hash and storage', async () => {
      const onNavigateMock = vi.fn();
      const onScenarioChangeMock = vi.fn();

      render(
        <EpisodesPage
          onNavigate={onNavigateMock}
          activeScenario="04_busy_yard"
          onScenarioChange={onScenarioChangeMock}
        />
      );

      await waitFor(() => {
        expect(screen.getByText(/Штрафные баллы/i)).toBeTruthy();
      });

      const selects = screen.getAllByRole('combobox') as HTMLSelectElement[];
      const scenarioSelect = selects[0];
      expect(scenarioSelect.value).toBe('04_busy_yard');

      fireEvent.change(scenarioSelect, { target: { value: '02_gnss_shadow' } });

      expect(onScenarioChangeMock).toHaveBeenCalledWith('02_gnss_shadow');
      expect(getSelectedScenario()).toBe('02_gnss_shadow');
      expect(window.location.hash).toContain('scenario=02_gnss_shadow');
    });

    it('synchronizes scenario change in MissionsPage', async () => {
      const onNavigateMock = vi.fn();
      const onScenarioChangeMock = vi.fn();

      render(
        <MissionsPage
          onNavigate={onNavigateMock}
          activeScenario="04_busy_yard"
          onScenarioChange={onScenarioChangeMock}
        />
      );

      await waitFor(() => {
        expect(screen.getByText(/Результат доставки/i)).toBeTruthy();
      });

      const select = screen.getByRole('combobox') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: '01_clear' } });

      expect(onScenarioChangeMock).toHaveBeenCalledWith('01_clear');
      expect(getSelectedScenario()).toBe('01_clear');
      expect(window.location.hash).toContain('scenario=01_clear');
    });

    it('App auto-injects selected scenario into URL hash on tab clicks', async () => {
      setSelectedScenario('02_gnss_shadow');

      render(<App />);

      await waitFor(() => {
        expect(screen.getByText('SafeRoute')).toBeTruthy();
      });

      // Click on "Инциденты" header button
      const episodesTab = screen.getByText('Инциденты');
      fireEvent.click(episodesTab);

      // Verify that URL hash includes the active scenario
      expect(window.location.hash).toBe('#/episodes?scenario=02_gnss_shadow');

      // Click on "Миссии" header button
      const missionsTab = screen.getByText('Миссии');
      fireEvent.click(missionsTab);
      expect(window.location.hash).toBe('#/missions?scenario=02_gnss_shadow');

      // Click on "Просмотр" (Replay) header button
      const replayTab = screen.getByText('Просмотр');
      fireEvent.click(replayTab);
      expect(window.location.hash).toBe('#/replay?scenario=02_gnss_shadow');
    });
  });

  describe('DashboardPage single scenario selector and Quick Launch', () => {
    it('renders only one scenario select (in toolbar) without duplicate in Quick Launch card', async () => {
      const onNavigateMock = vi.fn();
      render(<DashboardPage onNavigate={onNavigateMock} activeScenario="04_busy_yard" />);

      await waitFor(() => {
        expect(screen.getByText(/Быстрый запуск/i)).toBeTruthy();
      });

      // Ensure duplicate selector and labels are NOT present
      expect(screen.queryByText(/Выбор сценария/i)).toBeNull();
      expect(screen.queryByText(/Сценарий тестирования/i)).toBeNull();

      // Only one select should be present on the page (the toolbar one)
      const selects = screen.getAllByRole('combobox');
      expect(selects.length).toBe(1);

      // Launch simulation button works and triggers navigation with current scenario
      const launchBtn = screen.getByRole('button', { name: /Запустить симуляцию/i });
      expect(launchBtn).toBeTruthy();
      fireEvent.click(launchBtn);
      expect(onNavigateMock).toHaveBeenCalledWith('runner', { scenario: '04_busy_yard' });
    });
  });

  describe('API client server priority vs uploaded scenario stubs', () => {
    it('prioritizes server data for episodes and missions when server is available', async () => {
      // 1. Upload a stub scenario without telemetry
      saveUploadedScenario({
        id: 'c1_logistics_hub',
        name: 'c1_logistics_hub',
        fileName: 'c1_logistics_hub.json',
        fileType: 'scenario',
        missionsViewModel: {
          scenario: 'c1_logistics_hub',
          summary: {
            completed: 0,
            total: 2,
            deliveryScore: 0,
            maxDeliveryScore: 40,
            efficiencyScore: 0,
            maxEfficiencyScore: 15,
          },
          missions: [],
        },
        uploadedAt: Date.now(),
      });

      // 2. Mock global.fetch returning actual server results
      const originalFetch = global.fetch;
      const serverEpisodes = {
        scenario: 'c1_logistics_hub',
        summary: { totalCost: -0.4, fatalCount: 0, warningsCount: 2, ruleViolationsCount: 2 },
        episodes: [
          { id: 'ep-1', type: 'person_near_fast', cost: -0.2, severity: 'warning' },
          { id: 'ep-2', type: 'person_near_fast', cost: -0.2, severity: 'warning' },
        ],
      };
      const serverMissions = {
        scenario: 'c1_logistics_hub',
        summary: {
          completed: 2,
          total: 2,
          deliveryScore: 40.0,
          maxDeliveryScore: 40.0,
          efficiencyScore: 14.5,
          maxEfficiencyScore: 15.0,
        },
        missions: [
          { id: 'm1', status: 'DELIVERED', actual_time_s: 45 },
          { id: 'm2', status: 'DELIVERED', actual_time_s: 60 },
        ],
      };

      global.fetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('/api/ui/episodes')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(serverEpisodes),
          });
        }
        if (url.includes('/api/ui/missions')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(serverMissions),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({}),
        });
      }) as any;

      try {
        const episodes = await apiClient.fetchEpisodes('c1_logistics_hub');
        expect(episodes.episodes.length).toBe(2);
        expect(episodes.episodes[0].type).toBe('person_near_fast');
        expect(episodes.summary.warningsCount).toBe(2);

        const missions = await apiClient.fetchMissions('c1_logistics_hub');
        expect(missions.summary.completed).toBe(2);
        expect(missions.missions.length).toBe(2);
        expect(missions.missions[0].status).toBe('DELIVERED');
      } finally {
        global.fetch = originalFetch;
      }
    });

    it('falls back to uploaded stub when server is unavailable or returns error', async () => {
      saveUploadedScenario({
        id: 'c1_offline',
        name: 'c1_offline',
        fileName: 'c1_offline.json',
        fileType: 'scenario',
        missionsViewModel: {
          scenario: 'c1_offline',
          summary: {
            completed: 0,
            total: 2,
            deliveryScore: 0,
            maxDeliveryScore: 40,
            efficiencyScore: 0,
            maxEfficiencyScore: 15,
          },
          missions: [],
        },
        uploadedAt: Date.now(),
      });

      const originalFetch = global.fetch;
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error / Server offline'));

      try {
        const missions = await apiClient.fetchMissions('c1_offline');
        expect(missions.summary.completed).toBe(0);
        expect(missions.scenario).toBe('c1_offline');
      } finally {
        global.fetch = originalFetch;
      }
    });
  });

  describe('RunnerPage uploaded scenario synchronization', () => {
    it('clears uploaded scenario stub after simulation finishes successfully (exitCode === 0)', async () => {
      saveUploadedScenario({
        id: 'c1_logistics_hub',
        name: 'c1_logistics_hub',
        fileName: 'c1_logistics_hub.json',
        fileType: 'scenario',
        uploadedAt: Date.now(),
      });
      expect(hasUploadedScenario()).toBe(true);

      const runSimSpy = vi.spyOn(apiClient, 'runSimulation').mockResolvedValueOnce({
        exitCode: 0,
        stdout: '[INFO] Completed successfully',
        stderr: '',
        reportPath: 'out/c1_logistics_hub.json',
        logPath: 'out/c1_logistics_hub.jsonl',
        score: 94.74,
      });

      render(
        <RunnerPage
          onNavigate={vi.fn()}
          activeScenario="c1_logistics_hub"
        />
      );

      const launchBtn = screen.getByRole('button', { name: /Запустить симуляцию/i });
      fireEvent.click(launchBtn);

      await waitFor(() => {
        expect(screen.getByText(/Simulation finished with exit code 0/i)).toBeTruthy();
      });

      expect(hasUploadedScenario()).toBe(false);
      expect(getSelectedScenario()).toBe('c1_logistics_hub');
      runSimSpy.mockRestore();
    });
  });
});
