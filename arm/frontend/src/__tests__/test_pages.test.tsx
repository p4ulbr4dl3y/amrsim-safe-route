import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import React from 'react';
import { DashboardPage } from '../pages/DashboardPage';
import { EpisodesPage } from '../pages/EpisodesPage';
import { MissionsPage } from '../pages/MissionsPage';
import { AnalyticsPage } from '../pages/AnalyticsPage';

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

describe('Operator Workstation Pages', () => {
  const onNavigateMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('DashboardPage', () => {
    it('renders KPI cards and scoring breakdown', async () => {
      render(<DashboardPage onNavigate={onNavigateMock} />);

      await waitFor(() => {
        expect(screen.getByText(/Общий балл/i)).toBeTruthy();
      });

      // KPI elements
      expect(screen.getByText(/Доставки/i)).toBeTruthy();
      expect(screen.getByText(/Безопасность/i)).toBeTruthy();
      expect(screen.getByText(/Ошибка позы/i)).toBeTruthy();

      // Check quick action button to replay
      const replayBtn = screen.getByText(/Открыть полную карту в Replay/i);
      expect(replayBtn).toBeTruthy();
      fireEvent.click(replayBtn);
      expect(onNavigateMock).toHaveBeenCalledWith('replay', expect.any(Object));
    });
  });

  describe('EpisodesPage', () => {
    it('renders episode incidents, type filters, and search bar', async () => {
      render(<EpisodesPage onNavigate={onNavigateMock} />);

      await waitFor(() => {
        expect(screen.getByText(/Эпизоды безопасности/i)).toBeTruthy();
      });

      // Metric summary cards
      expect(screen.getByText(/Штрафные баллы/i)).toBeTruthy();
      expect(screen.getByText(/Фатальные ошибки/i)).toBeTruthy();
      expect(screen.getByText(/Предупреждения безопасности/i)).toBeTruthy();

      // CSV export button
      const exportBtn = screen.getByText(/Экспорт CSV/i);
      expect(exportBtn).toBeTruthy();

      // Search input interaction
      const searchInput = screen.getByPlaceholderText(/Поиск по событиям/i);
      expect(searchInput).toBeTruthy();
      fireEvent.change(searchInput, { target: { value: 'person' } });
      expect((searchInput as HTMLInputElement).value).toBe('person');
    });

    it('separates rows by source and formats penalty column properly (dash for non-report)', async () => {
      render(<EpisodesPage onNavigate={onNavigateMock} />);

      await waitFor(() => {
        expect(screen.getByText(/Эпизоды безопасности/i)).toBeTruthy();
      });

      // Check header column for Source
      const table = screen.getByRole('table');
      expect(within(table).getByRole('columnheader', { name: /Источник/i })).toBeTruthy();

      // Check source badges in table rows: report, mission, checkpoint
      expect(within(table).getAllByText('Отчет').length).toBeGreaterThan(0);
      expect(within(table).getAllByText('Миссия').length).toBeGreaterThan(0);
      expect(within(table).getAllByText('Чекпоинт').length).toBeGreaterThan(0);

      // Verify that non-report milestones display dash "—" in penalty column
      const dashes = within(table).getAllByText('—');
      expect(dashes.length).toBeGreaterThan(0);

      // Click on a mission milestone row to verify details panel displays dash for cost and source badge
      const missionCell = within(table).getAllByText('Миссия')[0];
      const missionRow = missionCell.closest('tr');
      expect(missionRow).toBeTruthy();
      if (missionRow) {
        fireEvent.click(missionRow);
      }

      // In details panel, cost for mission should display dash "—" rather than numeric penalty
      const detailTitle = screen.getByText('Детали эпизода');
      const detailContainer = detailTitle.parentElement?.parentElement;
      expect(detailContainer).toBeTruthy();
      if (detailContainer) {
        expect(within(detailContainer).getAllByText('—').length).toBeGreaterThan(0);
        expect(within(detailContainer).getByText('Миссия')).toBeTruthy();
      }
    });
  });

  describe('MissionsPage', () => {
    it('renders mission cards with hold duration and tolerance margins', async () => {
      render(<MissionsPage onNavigate={onNavigateMock} />);

      await waitFor(() => {
        expect(screen.getByText(/Задания и Доставка/i)).toBeTruthy();
      });

      // Missions summary and labels
      expect(screen.getAllByText(/Миссии/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/Результат доставки/i)).toBeTruthy();
      expect(screen.getByText(/Эффективность/i)).toBeTruthy();

      // Check presence of mission IDs m1 and m2
      expect(screen.getByText('m1')).toBeTruthy();
      expect(screen.getByText('m2')).toBeTruthy();
    });
  });

  describe('AnalyticsPage', () => {
    it('renders 6 regulation score blocks, sandbox status, and radar chart', async () => {
      render(<AnalyticsPage onNavigate={onNavigateMock} />);

      await waitFor(() => {
        expect(screen.getByText(/Показатели по 6 блокам скоринга/i)).toBeTruthy();
      });

      // Check regulation score blocks presence
      expect(screen.getAllByText(/Доставка/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Безопасность/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Правила/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Поза/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Коллизии/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/Эффективность/i).length).toBeGreaterThan(0);

      // Sandbox & budget status
      expect(screen.getByText(/Аудит изоляции песочницы/i)).toBeTruthy();
      expect(screen.getByText(/Compute Budget/i)).toBeTruthy();

      // Formulas initially collapsed
      const toggleBtn = screen.getByText(/Развернуть формулы/i);
      expect(toggleBtn).toBeTruthy();
      expect(screen.queryByText(/Итоговая целевая функция сценария/i)).toBeNull();

      // Click expands formulas
      fireEvent.click(toggleBtn);
      expect(screen.getByText(/Свернуть формулы/i)).toBeTruthy();
      expect(screen.getByText(/Итоговая целевая функция сценария/i)).toBeTruthy();
    });
  });
});
