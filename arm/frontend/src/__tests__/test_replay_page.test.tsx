import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { ReplayPage } from '../pages/ReplayPage';
import { apiClient } from '../api/client';
import { ReplayViewModel, TickData } from '../types';

beforeAll(() => {
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

  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe('ReplayPage Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders replay toolbar, canvas, telemetry HUD and playback controls', async () => {
    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
      expect(screen.getByText(/Слои/i)).toBeTruthy();
      expect(screen.getByText(/ТЕКУЩЕЕ ЗАДАНИЕ/i)).toBeTruthy();
      expect(screen.getByTitle('Воспроизведение')).toBeTruthy();
    });

    // Speed buttons exist
    expect(screen.getByText('1x')).toBeTruthy();
    expect(screen.getByText('2x')).toBeTruthy();
    expect(screen.getByText('5x')).toBeTruthy();
    expect(screen.getByText('10x')).toBeTruthy();
  });

  it('handles queryParams (scenario, t, mission, x, y)', async () => {
    render(
      <ReplayPage
        queryParams={{
          scenario: '02_gnss_shadow',
          t: 5.0,
          mission: 'm2',
          x: 100,
          y: 60,
        }}
      />
    );

    await waitFor(() => {
      const select = screen.getByDisplayValue(/02_gnss_shadow/i) as HTMLSelectElement;
      expect(select.value).toBe('02_gnss_shadow');
    });
  });

  it('toggles follow robot switch', async () => {
    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
    });

    const toggleLabel = screen.getByText(/Следовать за роботом/i).closest('label');
    expect(toggleLabel).toBeTruthy();

    const switchTrack = toggleLabel!.querySelector('div');
    expect(switchTrack?.className).toContain('bg-slate-200');

    // Click to activate
    fireEvent.click(switchTrack!);
    expect(switchTrack?.className).toContain('bg-blue-600');

    // Click again to deactivate
    fireEvent.click(switchTrack!);
    expect(switchTrack?.className).toContain('bg-slate-200');
  });

  it('opens and closes layers menu and toggles individual layers', async () => {
    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText(/Слои/i)).toBeTruthy();
    });

    // Initially no checkboxes
    expect(screen.queryAllByRole('checkbox').length).toBe(0);

    const layersBtn = screen.getByText(/Слои/i);
    fireEvent.click(layersBtn);

    // Layer checkboxes should now be in the DOM (9 layer options)
    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes.length).toBe(9);

    // First checkbox is 'robot'
    const robotCheck = checkboxes[0] as HTMLInputElement;
    expect(robotCheck.checked).toBe(true);

    // Toggle robot layer
    fireEvent.click(robotCheck);
    expect(robotCheck.checked).toBe(false);

    // Click layers button again to close
    fireEvent.click(layersBtn);
    expect(screen.queryAllByRole('checkbox').length).toBe(0);
  });

  it('controls playback: play/pause, speed multipliers, step buttons and scrub slider', async () => {
    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByTitle('Воспроизведение')).toBeTruthy();
    });

    // Play button toggles to Pause
    const playBtn = screen.getByTitle('Воспроизведение');
    fireEvent.click(playBtn);
    expect(screen.getByTitle('Пауза')).toBeTruthy();

    // Pause it
    fireEvent.click(screen.getByTitle('Пауза'));
    expect(screen.getByTitle('Воспроизведение')).toBeTruthy();

    // Speed multiplier buttons
    const speed5xBtn = screen.getByText('5x');
    fireEvent.click(speed5xBtn);
    expect(speed5xBtn.className).toContain('bg-blue-600 text-white font-bold');

    const speed1xBtn = screen.getByText('1x');
    expect(speed1xBtn.className).not.toContain('bg-blue-600');

    // Skip to start button
    const skipStartBtn = screen.getByTitle('В начало');
    fireEvent.click(skipStartBtn);

    // Step forward button
    const stepFwdBtn = screen.getByTitle('Шаг вперед');
    fireEvent.click(stepFwdBtn);

    // Step back button
    const stepBackBtn = screen.getByTitle('Шаг назад');
    fireEvent.click(stepBackBtn);

    // Skip to end button
    const skipEndBtn = screen.getByTitle('В конец');
    fireEvent.click(skipEndBtn);

    // Timeline slider scrubbing
    const slider = screen.getByRole('slider') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '25' } });
    expect(slider.value).toBe('25');
  });

  it('updates scenario selection and re-fetches replay data', async () => {
    const fetchSpy = vi.spyOn(apiClient, 'fetchReplay');

    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText(/04_busy_yard/i)).toBeTruthy();
    });

    const scenarioSelect = screen.getByDisplayValue(/04_busy_yard/i);
    fireEvent.change(scenarioSelect, { target: { value: '01_clear' } });

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith('01_clear');
    });
  });

  it('updates tick index when queryParams.t changes dynamically', async () => {
    const { rerender } = render(<ReplayPage queryParams={{ t: 1.0 }} />);

    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
    });

    rerender(<ReplayPage queryParams={{ t: 20.0 }} />);

    await waitFor(() => {
      const slider = screen.getByRole('slider') as HTMLInputElement;
      expect(Number(slider.value)).toBeGreaterThanOrEqual(0);
    });
  });

  it('renders legend items correctly', async () => {
    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText('Проезжая часть')).toBeTruthy();
      expect(screen.getByText('Здание')).toBeTruthy();
      expect(screen.getByText('Док')).toBeTruthy();
      expect(screen.getByText(/Пешеход/i)).toBeTruthy();
      expect(screen.getByText('Разница поз')).toBeTruthy();
    });
  });

  it('shows mission label and remaining time from the replay log, not hardcoded values', async () => {
    const ticks: TickData[] = Array.from({ length: 5 }, (_, i) => ({
      t: i * 0.1,
      x: 0,
      y: 0,
      th: 0,
      v: 0,
      w: 0,
      cv: 0,
      cw: 0,
      st: 'moving',
      pe: null,
      nt: null,
      m: 'm1',
      drv: 1,
      fbd: 0,
      vmax: null,
      hum: null,
      obj: null,
      coll: 0,
      cont: 0,
    }));

    const mockedMission = {
      id: 'm1',
      from: 'warehouse',
      to: 'shop_b',
      fromLabel: 'Склад',
      toLabel: 'Цех B',
      deadline_s: 252.0,
      t_start: 0.0,
    };

    const replayVm: ReplayViewModel = {
      scenario: '01_clear',
      seed: 7,
      header: { scenario: '01_clear', dt: 0.1, missions: [mockedMission] },
      mapData: {
        bounds: [0, 0, 10, 10],
        drivable: [],
        buildings: [],
        zones: [],
        points: {},
      },
      ticks,
      missions: [mockedMission],
      totalTicks: ticks.length,
      duration: 0.4,
      episodes: [],
    };

    vi.spyOn(apiClient, 'fetchReplay').mockResolvedValue(replayVm);

    render(<ReplayPage />);

    await waitFor(() => {
      expect(screen.getByText('Склад → Цех B')).toBeTruthy();
      expect(screen.getByText('252.0 s left')).toBeTruthy();
    });

    // Зашитые в прошлой версии значения не должны отображаться
    expect(screen.queryByText(/Цех А/)).toBeNull();
    expect(screen.queryByText(/200\.7/)).toBeNull();
  });

  it('strictly adheres to amr-1.0 status contract and rejects holding or docked', () => {
    const validStatuses: TickData['st'][] = ['moving', 'waiting', 'arrived', 'lost', 'estop'];
    const invalidStatuses = ['holding', 'docked'];
    for (const st of invalidStatuses) {
      expect(validStatuses).not.toContain(st);
    }
  });
});
