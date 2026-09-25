import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { Header } from '../components/Header';
import { RouteName } from '../types';

describe('Header component', () => {
  it('renders brand title and logo', () => {
    const onNavigate = vi.fn();
    render(<Header currentRoute="dashboard" onNavigate={onNavigate} />);

    expect(screen.getByText(/AMR/i)).toBeTruthy();
    expect(screen.getByText(/SafeRoute/i)).toBeTruthy();
  });

  it('clicking brand logo triggers navigation to dashboard', () => {
    const onNavigate = vi.fn();
    render(<Header currentRoute="replay" onNavigate={onNavigate} />);

    const brand = screen.getByText(/SafeRoute/i).closest('div');
    expect(brand).toBeTruthy();
    fireEvent.click(brand!);
    expect(onNavigate).toHaveBeenCalledWith('dashboard');
  });

  it('renders all 5 main navigation items', () => {
    const onNavigate = vi.fn();
    render(<Header currentRoute="dashboard" onNavigate={onNavigate} />);

    expect(screen.getByText('Дашборд')).toBeTruthy();
    expect(screen.getByText('Просмотр')).toBeTruthy();
    expect(screen.getByText('Инциденты')).toBeTruthy();
    expect(screen.getByText('Миссии')).toBeTruthy();
    expect(screen.getByText('Аналитика')).toBeTruthy();
  });

  it('highlights the active route with active styles and indicator bar', () => {
    const routes: RouteName[] = ['dashboard', 'replay', 'episodes', 'missions', 'analytics'];
    const labelMap: Record<RouteName, string> = {
      dashboard: 'Дашборд',
      replay: 'Просмотр',
      episodes: 'Инциденты',
      missions: 'Миссии',
      analytics: 'Аналитика',
      runner: 'Симуляция',
    };

    routes.forEach((route) => {
      const { unmount } = render(<Header currentRoute={route} onNavigate={vi.fn()} />);
      const activeBtn = screen.getByText(labelMap[route]);

      expect(activeBtn.className).toContain('text-blue-600 font-semibold');
      unmount();
    });
  });

  it('applies inactive styles to non-active routes', () => {
    render(<Header currentRoute="dashboard" onNavigate={vi.fn()} />);
    const inactiveBtn = screen.getByText('Просмотр');
    expect(inactiveBtn.className).toContain('text-slate-600');
    expect(inactiveBtn.className).not.toContain('text-blue-600 font-semibold');
  });

  it('calls onNavigate with appropriate route when nav buttons are clicked', () => {
    const onNavigate = vi.fn();
    render(<Header currentRoute="dashboard" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByText('Просмотр'));
    expect(onNavigate).toHaveBeenCalledWith('replay');

    fireEvent.click(screen.getByText('Инциденты'));
    expect(onNavigate).toHaveBeenCalledWith('episodes');

    fireEvent.click(screen.getByText('Миссии'));
    expect(onNavigate).toHaveBeenCalledWith('missions');

    fireEvent.click(screen.getByText('Аналитика'));
    expect(onNavigate).toHaveBeenCalledWith('analytics');

    fireEvent.click(screen.getByText('Дашборд'));
    expect(onNavigate).toHaveBeenCalledWith('dashboard');
  });
});
