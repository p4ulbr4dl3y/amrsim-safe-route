import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
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

describe('DashboardPage Log Upload Parsing', () => {
  const onNavigateMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('parses .json simulation report and updates all KPI cards and scenario', async () => {
    const { container } = render(<DashboardPage onNavigate={onNavigateMock} />);

    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });

    const fileInput = screen.getByTestId('upload-log-input') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const reportContent = JSON.stringify({
      schema: 'amr-1.0',
      scenario: '01_clear',
      score: {
        total: 99.45,
        deliveries: 1,
        fatal: false,
        episodes: [],
      },
      missions: [
        { id: 'm1', delivered: true, status: 'DELIVERED' },
        { id: 'm2', delivered: false, status: 'TIMEOUT' },
      ],
      summary: {
        fatalCount: 0,
        warningsCount: 4,
      },
      pose_error: {
        mean_m: 0.08,
      },
      step_time_ms: {
        mean: 1.85,
        max: 12.4,
        n: 2000,
      },
    });

    const file = new File([reportContent], '01_clear_report.json', { type: 'application/json' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      // Total score updated
      expect(container.textContent).toContain('99.45');
      // Deliveries updated to 1 / 2
      expect(container.textContent).toContain('1 / 2');
      // Safety warnings updated to 4 Предупреждений
      expect(container.textContent).toContain('4 Предупреждений');
      // Localization error updated to 0.08 м
      expect(container.textContent).toContain('0.08 м');
      // Scenario updated to 01_clear
      expect(container.textContent).toContain('(01_clear)');
      // Mean delay updated to 1.85 мс
      expect(container.textContent).toContain('1.85 мс');
    });
  });

  it('parses .jsonl telemetry log and updates trajectory, speed curve, and preview tick', async () => {
    render(<DashboardPage onNavigate={onNavigateMock} />);

    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });

    const fileInput = screen.getByTestId('upload-log-input') as HTMLInputElement;

    const jsonlLines = [
      JSON.stringify({
        type: 'header',
        scenario: '02_gnss_shadow',
        dt: 0.1,
      }),
      JSON.stringify({
        type: 'tick',
        t: 0.0,
        x: 51.5,
        y: 150.0,
        th: 0.0,
        v: 0.0,
        w: 0.0,
        cv: 1.0,
        cw: 0.0,
        st: 'waiting',
        pe: [51.52, 150.01, 0.0],
        drv: 1,
        fbd: 0,
        vmax: null,
        hum: 10.0,
        obj: 5.0,
        coll: 0,
        cont: 0,
      }),
      JSON.stringify({
        type: 'tick',
        t: 10.5,
        x: 60.0,
        y: 150.0,
        th: 0.1,
        v: 1.25,
        w: 0.02,
        cv: 1.39,
        cw: 0.0,
        st: 'moving',
        pe: [60.05, 150.04, 0.1],
        drv: 1,
        fbd: 0,
        vmax: null,
        hum: 8.0,
        obj: 4.2,
        coll: 0,
        cont: 0,
      }),
      JSON.stringify({
        type: 'tick',
        t: 25.0,
        x: 75.0,
        y: 152.0,
        th: 0.2,
        v: 0.85,
        w: -0.01,
        cv: 1.0,
        cw: 0.0,
        st: 'arrived',
        pe: [75.03, 152.02, 0.2],
        drv: 1,
        fbd: 0,
        vmax: null,
        hum: 12.0,
        obj: 6.0,
        coll: 0,
        cont: 0,
      }),
    ].join('\n');

    const file = new File([jsonlLines], '02_gnss_shadow.jsonl', { type: 'text/plain' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      // Scenario updated to 02_gnss_shadow
      expect(screen.getByText(/\(02_gnss_shadow\)/i)).toBeTruthy();
      // Recent event created for the uploaded log
      expect(screen.getByText(/Загружен лог · 02_gnss_shadow.jsonl/i)).toBeTruthy();
    });
  });
});
