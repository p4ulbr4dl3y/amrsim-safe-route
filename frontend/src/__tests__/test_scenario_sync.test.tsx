import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import { App } from '../App';
import {
  getSelectedScenario,
  setSelectedScenario,
  saveUploadedScenario,
  clearUploadedScenario,
  AMR_SELECTED_SCENARIO_KEY,
  AMR_SCENARIO_CHANGE_EVENT,
} from '../utils/scenarioStorage';
import { EpisodesPage } from '../pages/EpisodesPage';
import { MissionsPage } from '../pages/MissionsPage';

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
});
