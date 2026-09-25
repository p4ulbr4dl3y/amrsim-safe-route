import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { App } from '../App';

beforeAll(() => {
  // Canvas mock
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

describe('App Component Routing & Navigation', () => {
  beforeEach(() => {
    window.location.hash = '';
    vi.clearAllMocks();
  });

  it('redirects to #/dashboard when initial hash is empty and renders DashboardPage', async () => {
    window.location.hash = '';
    render(<App />);

    expect(window.location.hash).toBe('#/dashboard');
    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });
    expect(screen.getByText('AMR')).toBeTruthy();
    expect(screen.getByText('SafeRoute')).toBeTruthy();
  });

  it('redirects to #/dashboard when initial hash is invalid route', async () => {
    window.location.hash = '#/non_existent_page';
    render(<App />);

    expect(window.location.hash).toBe('#/dashboard');
    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });
  });

  it('renders ReplayPage when initialized with #/replay', async () => {
    window.location.hash = '#/replay';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
    });
  });

  it('renders EpisodesPage when initialized with #/episodes', async () => {
    window.location.hash = '#/episodes';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Эпизоды безопасности/i)).toBeTruthy();
    });
  });

  it('renders MissionsPage when initialized with #/missions', async () => {
    window.location.hash = '#/missions';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Задания и Доставка/i)).toBeTruthy();
    });
  });

  it('renders AnalyticsPage when initialized with #/analytics', async () => {
    window.location.hash = '#/analytics';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Показатели по 6 блокам скоринга/i)).toBeTruthy();
    });
  });

  it('renders RunnerPage when initialized with #/runner', async () => {
    window.location.hash = '#/runner';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Параметры симуляции/i)).toBeTruthy();
      expect(screen.getByText(/Терминал симулятора amrsim/i)).toBeTruthy();
    });
  });

  it('parses query params from hash and updates route on hashchange', async () => {
    window.location.hash = '#/dashboard';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });

    act(() => {
      window.location.hash = '#/replay?scenario=01_clear&t=45&mission=m1';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
    });
  });

  it('navigates when header navigation buttons are clicked', async () => {
    window.location.hash = '#/dashboard';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Общий балл/i)).toBeTruthy();
    });

    const missionsBtn = screen.getByText('Миссии');
    fireEvent.click(missionsBtn);

    expect(window.location.hash).toBe('#/missions');
    await waitFor(() => {
      expect(screen.getByText(/Задания и Доставка/i)).toBeTruthy();
    });

    const analyticsBtn = screen.getByText('Аналитика');
    fireEvent.click(analyticsBtn);

    expect(window.location.hash).toBe('#/analytics');
    await waitFor(() => {
      expect(screen.getByText(/Показатели по 6 блокам скоринга/i)).toBeTruthy();
    });
  });

  it('programmatic navigation with query parameters from Dashboard to Replay', async () => {
    window.location.hash = '#/dashboard';
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Открыть полную карту в Replay/i)).toBeTruthy();
    });

    const replayBtn = screen.getByText(/Открыть полную карту в Replay/i);
    fireEvent.click(replayBtn);

    expect(window.location.hash).toContain('#/replay?scenario=');
    await waitFor(() => {
      expect(screen.getByText(/Следовать за роботом/i)).toBeTruthy();
    });
  });

  it('removes hashchange event listener when unmounted', () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');
    const { unmount } = render(<App />);

    unmount();
    expect(removeEventListenerSpy).toHaveBeenCalledWith('hashchange', expect.any(Function));
  });
});
