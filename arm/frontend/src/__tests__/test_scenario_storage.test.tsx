import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import {
  saveUploadedScenario,
  getUploadedScenario,
  clearUploadedScenario,
  hasUploadedScenario,
  UploadedScenarioData,
  AMR_STORAGE_EVENT,
} from '../utils/scenarioStorage';
import { apiClient } from '../api/client';
import { DashboardPage } from '../pages/DashboardPage';

beforeAll(() => {
  // Mock canvas 2D context for jsdom
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

describe('scenarioStorage and Upload Workflow', () => {
  const onNavigateMock = vi.fn();

  beforeEach(() => {
    clearUploadedScenario();
    sessionStorage.clear();
    localStorage.clear();
    vi.clearAllMocks();
  });

  it('correctly saves, retrieves, checks presence, and clears uploaded scenario in storage', () => {
    expect(hasUploadedScenario()).toBe(false);
    expect(getUploadedScenario()).toBeNull();

    const mockData: UploadedScenarioData = {
      id: 'c1_logistics_hub',
      name: 'c1_logistics_hub',
      fileName: 'c1_logistics_hub.json',
      fileType: 'scenario',
      uploadedAt: 1234567890,
      mapData: {
        bounds: [0, 0, 160, 140],
        drivable: [],
        buildings: [],
        zones: [],
        points: {},
      },
      dashboardViewModel: {
        scenario: 'c1_logistics_hub',
        totalScore: 100,
        totalMax: 100,
        deliveriesCount: 0,
        deliveriesTotal: 2,
        safetyFatal: 0,
        safetyWarnings: 0,
        localizationError: 0.0,
        recentEvents: [],
        controllerState: {
          online: true,
          meanDelayMs: 2.1,
          maxDelayMs: 15.0,
        },
        speedHistory: [0, 0],
        speedTimestamps: ['00:00', '01:00'],
        previewTick: null,
        historyTicks: [],
        mapData: {
          bounds: [0, 0, 160, 140],
          drivable: [],
          buildings: [],
          zones: [],
          points: {},
        },
      },
    };

    saveUploadedScenario(mockData);
    expect(hasUploadedScenario()).toBe(true);

    const retrieved = getUploadedScenario();
    expect(retrieved).not.toBeNull();
    expect(retrieved?.id).toBe('c1_logistics_hub');
    expect(retrieved?.fileType).toBe('scenario');
    expect(retrieved?.mapData?.bounds).toEqual([0, 0, 160, 140]);

    clearUploadedScenario();
    expect(hasUploadedScenario()).toBe(false);
    expect(getUploadedScenario()).toBeNull();
  });

  it('dispatches CustomEvent on save and clear', () => {
    const listener = vi.fn();
    window.addEventListener(AMR_STORAGE_EVENT as any, listener);

    const mockData: UploadedScenarioData = {
      id: 'test_s',
      name: 'test_s',
      fileName: 'test_s.json',
      fileType: 'scenario',
      uploadedAt: Date.now(),
    };

    saveUploadedScenario(mockData);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0][0].detail.id).toBe('test_s');

    clearUploadedScenario();
    expect(listener).toHaveBeenCalledTimes(2);
    expect(listener.mock.calls[1][0].detail).toBeNull();

    window.removeEventListener(AMR_STORAGE_EVENT as any, listener);
  });

  it('resets storage when beforeunload event fires', () => {
    saveUploadedScenario({
      id: 'temp_scenario',
      name: 'temp',
      fileName: 'temp.json',
      fileType: 'scenario',
      uploadedAt: Date.now(),
    });

    expect(hasUploadedScenario()).toBe(true);

    window.dispatchEvent(new Event('beforeunload'));
    expect(hasUploadedScenario()).toBe(false);
  });

  it('apiClient integrates with scenarioStorage for scenarios, dashboard, replay, and missions', async () => {
    const uploadedData: UploadedScenarioData = {
      id: 'c1_logistics_hub',
      name: 'c1_logistics_hub',
      fileName: 'c1_logistics_hub.json',
      fileType: 'scenario',
      uploadedAt: Date.now(),
      dashboardViewModel: {
        scenario: 'c1_logistics_hub',
        totalScore: 95.5,
        totalMax: 100,
        deliveriesCount: 1,
        deliveriesTotal: 2,
        safetyFatal: 0,
        safetyWarnings: 1,
        localizationError: 0.04,
        recentEvents: [],
        controllerState: {
          online: true,
          meanDelayMs: 2.2,
          maxDelayMs: 14.5,
        },
        speedHistory: [0, 0.5],
        speedTimestamps: ['00:00', '00:30'],
        previewTick: {
          t: 0,
          x: 31.5,
          y: 70.0,
          th: 0,
          v: 0,
          w: 0,
          cv: 0,
          cw: 0,
          st: 'idle',
          pe: [31.5, 70.0, 0],
          nt: null,
          m: 'm1',
          drv: 1,
          fbd: 0,
          vmax: null,
          hum: null,
          obj: null,
          coll: 0,
          cont: 0,
        },
        historyTicks: [],
        mapData: {
          bounds: [0, 0, 160, 140],
          drivable: [],
          buildings: [],
          zones: [],
          points: {},
        },
      },
      replayViewModel: {
        scenario: 'c1_logistics_hub',
        seed: 7,
        header: { scenario: 'c1_logistics_hub', dt: 0.1 },
        mapData: {
          bounds: [0, 0, 160, 140],
          drivable: [],
          buildings: [],
          zones: [],
          points: {},
        },
        ticks: [],
        totalTicks: 0,
        duration: 320,
        episodes: [],
      },
      missionsViewModel: {
        scenario: 'c1_logistics_hub',
        summary: {
          completed: 1,
          total: 2,
          deliveryScore: 40.0,
          maxDeliveryScore: 40.0,
          efficiencyScore: 14.2,
          maxEfficiencyScore: 15.0,
        },
        missions: [
          {
            id: 'm1',
            from: 'dock_inbound',
            to: 'dock_outbound',
            fromLabel: 'Док Приемки',
            toLabel: 'Док Отгрузки',
            status: 'DELIVERED',
            t_start: 0,
            t_end: 160,
            t_arrival: 110,
            hold_duration_s: 3.0,
            hold_ticks: 30,
            max_hold_dist: 0.1,
            tol: 0.3,
            deadline_s: 160,
            safety_margin_s: 50,
            reference_length_m: 97,
            actual_time_s: 110,
          },
        ],
      },
    };

    saveUploadedScenario(uploadedData);

    // 1. fetchScenarios prepends the uploaded item
    const scenarios = await apiClient.fetchScenarios();
    expect(scenarios[0].id).toBe('c1_logistics_hub');
    expect(scenarios[0].name).toContain('(Загружен)');

    // 2. fetchDashboard returns the stored dashboardViewModel
    const dashboard = await apiClient.fetchDashboard('c1_logistics_hub');
    expect(dashboard.scenario).toBe('c1_logistics_hub');
    expect(dashboard.totalScore).toBe(95.5);
    expect(dashboard.mapData.bounds).toEqual([0, 0, 160, 140]);

    // 3. fetchReplay returns the stored replayViewModel
    const replay = await apiClient.fetchReplay('c1_logistics_hub');
    expect(replay.scenario).toBe('c1_logistics_hub');
    expect(replay.duration).toBe(320);

    // 4. fetchMissions returns the stored missionsViewModel
    const missions = await apiClient.fetchMissions('c1_logistics_hub');
    expect(missions.scenario).toBe('c1_logistics_hub');
    expect(missions.missions.length).toBe(1);
    expect(missions.missions[0].toLabel).toBe('Док Отгрузки');
  });

  it('DashboardPage parses scenario JSON (c1_logistics_hub), renders immediately, and supports reset', async () => {
    const { container } = render(<DashboardPage onNavigate={onNavigateMock} />);

    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });

    const fileInput = screen.getByTestId('upload-log-input') as HTMLInputElement;

    const scenarioJson = {
      schema: 'amr-1.0',
      name: 'c1_logistics_hub',
      description: 'Logistics hub 160x140m test scenario',
      dt: 0.1,
      duration_s: 320.0,
      map: {
        bounds: [0, 0, 160, 140],
        drivable: [
          [
            [30, 67.5],
            [36, 67.5],
            [36, 72.5],
            [30, 72.5],
          ],
        ],
        buildings: [],
        zones: [
          {
            id: 'Z_SLOW',
            type: 'speed_limit',
            v_max: 0.8,
            polygon: [
              [50, 50],
              [70, 50],
              [70, 70],
              [50, 70],
            ],
          },
        ],
        points: {
          dock_inbound: { x: 31.5, y: 70.0, heading: 0.0, tol: 0.3, label: 'Док Приемки' },
          dock_outbound: { x: 128.5, y: 70.0, heading: 3.14, tol: 0.3, label: 'Док Отгрузки' },
        },
      },
      start: {
        x: 31.5,
        y: 70.0,
        theta: 0.0,
      },
      missions: [
        {
          id: 'm1',
          from: 'dock_inbound',
          to: 'dock_outbound',
          deadline_s: 160.0,
          reference_length_m: 97.0,
        },
        {
          id: 'm2',
          from: 'dock_outbound',
          to: 'dock_inbound',
          deadline_s: 160.0,
          reference_length_m: 97.0,
        },
      ],
    };

    const file = new File([JSON.stringify(scenarioJson)], 'c1_logistics_hub.json', {
      type: 'application/json',
    });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      // Scenario indicator updated to c1_logistics_hub
      expect(container.textContent).toContain('(c1_logistics_hub)');
      // Total deliveries updated to 0 / 2
      expect(container.textContent).toContain('0 / 2');
      // Reset button should now be visible
      expect(screen.getByTestId('clear-uploaded-btn')).toBeTruthy();
      // Storage contains scenario
      expect(hasUploadedScenario()).toBe(true);
    });

    // Click "Сбросить сценарий"
    const clearBtn = screen.getByTestId('clear-uploaded-btn');
    fireEvent.click(clearBtn);

    await waitFor(() => {
      // Storage cleared
      expect(hasUploadedScenario()).toBe(false);
      // Reset button disappears
      expect(screen.queryByTestId('clear-uploaded-btn')).toBeNull();
      // Returns to default scenario 04_busy_yard
      expect(container.textContent).toContain('(04_busy_yard)');
    });
  });
});
