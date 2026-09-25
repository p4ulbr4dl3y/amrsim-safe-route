import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { RunnerPage } from '../pages/RunnerPage';
import { apiClient } from '../api/client';

describe('RunnerPage Component', () => {
  const onNavigateMock = vi.fn();

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders default controls and initial terminal output', async () => {
    render(<RunnerPage onNavigate={onNavigateMock} />);

    expect(screen.getByText('Параметры симуляции')).toBeTruthy();
    expect(screen.getByText('Терминал симулятора amrsim')).toBeTruthy();
    expect(screen.getByText('Запустить симуляцию')).toBeTruthy();

    // Default values
    const seedInput = screen.getByDisplayValue('7') as HTMLInputElement;
    expect(seedInput).toBeTruthy();
    expect(seedInput.type).toBe('number');

    // Default checkboxes
    const genReportCheck = screen.getByLabelText(/Генерировать отчёт JSON/i) as HTMLInputElement;
    const detailedLogCheck = screen.getByLabelText(/Детальный лог телеметрии/i) as HTMLInputElement;
    const cheatPoseCheck = screen.getByLabelText(/Идеальная поза/i) as HTMLInputElement;

    expect(genReportCheck.checked).toBe(true);
    expect(detailedLogCheck.checked).toBe(true);
    expect(cheatPoseCheck.checked).toBe(false);

    // Initial terminal lines
    expect(screen.getByText(/Simulation finished with exit code 0/i)).toBeTruthy();
  });

  it('uses scenario from queryParams if provided', async () => {
    render(<RunnerPage onNavigate={onNavigateMock} queryParams={{ scenario: '02_gnss_shadow' }} />);

    await waitFor(() => {
      const select = screen.getByDisplayValue(/02_gnss_shadow/i) as HTMLSelectElement;
      expect(select.value).toBe('02_gnss_shadow');
    });
  });

  it('loads scenario list from apiClient.fetchScenarios', async () => {
    const mockList = [
      { id: 'sc_custom_1', name: 'Custom Scenario 1', description: '', type: 'custom', file: '', hasReport: true, score: 95 }
    ];
    vi.spyOn(apiClient, 'fetchScenarios').mockResolvedValue(mockList as any);

    render(<RunnerPage onNavigate={onNavigateMock} />);

    await waitFor(() => {
      expect(screen.getByText('Custom Scenario 1')).toBeTruthy();
    });
  });

  it('allows changing scenario, controller, seed, and checkboxes', async () => {
    render(<RunnerPage onNavigate={onNavigateMock} />);

    // Change controller
    const controllerSelect = screen.getByDisplayValue(/backend\/controller\.py/i);
    fireEvent.change(controllerSelect, { target: { value: 'team/controller.py' } });
    expect((controllerSelect as HTMLSelectElement).value).toBe('team/controller.py');

    // Change seed
    const seedInput = screen.getByDisplayValue('7');
    fireEvent.change(seedInput, { target: { value: '42' } });
    expect((seedInput as HTMLInputElement).value).toBe('42');

    // Toggle checkboxes
    const genReportCheck = screen.getByLabelText(/Генерировать отчёт JSON/i);
    fireEvent.click(genReportCheck);
    expect((genReportCheck as HTMLInputElement).checked).toBe(false);

    const cheatPoseCheck = screen.getByLabelText(/Идеальная поза/i);
    fireEvent.click(cheatPoseCheck);
    expect((cheatPoseCheck as HTMLInputElement).checked).toBe(true);
  });

  it('updates scenario when queryParams change after mount', async () => {
    const { rerender } = render(<RunnerPage onNavigate={onNavigateMock} queryParams={{ scenario: '01_clear' }} />);

    await waitFor(() => {
      expect((screen.getByDisplayValue(/01_clear/i) as HTMLSelectElement).value).toBe('01_clear');
    });

    rerender(<RunnerPage onNavigate={onNavigateMock} queryParams={{ scenario: '03_fog_snow' }} />);

    await waitFor(() => {
      expect((screen.getByDisplayValue(/03_fog_snow/i) as HTMLSelectElement).value).toBe('03_fog_snow');
    });
  });

  it('handles successful simulation launch and displays score & action buttons', async () => {
    const runSpy = vi.spyOn(apiClient, 'runSimulation').mockResolvedValue({
      scenario: '04_busy_yard',
      seed: 7,
      exitCode: 0,
      score: 99.4,
      duration: 10.2,
      wallTimeMs: 1500,
      completed: true,
      stdout: '[STEP 100] Reached dock\n[STEP 200] Unloaded pallet',
      stderr: '',
    });

    render(<RunnerPage onNavigate={onNavigateMock} />);

    const launchBtn = screen.getByText('Запустить симуляцию');
    fireEvent.click(launchBtn);

    await waitFor(() => {
      expect(runSpy).toHaveBeenCalledWith({
        scenario: '04_busy_yard',
        controller: 'backend/controller.py',
        seed: 7,
        cheatPose: false,
      });
    });

    // Check terminal output contains stdout and final score
    await waitFor(() => {
      expect(screen.getByText('[STEP 100] Reached dock')).toBeTruthy();
      expect(screen.getByText('[STEP 200] Unloaded pallet')).toBeTruthy();
      expect(screen.getByText(/Final score: 99.40 \/ 100/i)).toBeTruthy();
      expect(screen.getByText(/Балл 99.40 \/ 100/i)).toBeTruthy();
    });

    // Action buttons visible on completion
    const replayBtn = screen.getByText('Открыть в Replay');
    expect(replayBtn).toBeTruthy();
    fireEvent.click(replayBtn);
    expect(onNavigateMock).toHaveBeenCalledWith('replay', { scenario: '04_busy_yard' });

    const analyticsBtn = screen.getByText('Аналитика');
    expect(analyticsBtn).toBeTruthy();
    fireEvent.click(analyticsBtn);
    expect(onNavigateMock).toHaveBeenCalledWith('analytics', { scenario: '04_busy_yard' });
  });

  it('includes --cheat flag in initial command when cheatPose is enabled', async () => {
    let capturedResolve: (val: any) => void;
    const runPromise = new Promise((resolve) => {
      capturedResolve = resolve;
    });
    vi.spyOn(apiClient, 'runSimulation').mockReturnValue(runPromise as any);

    render(<RunnerPage onNavigate={onNavigateMock} />);

    // Enable cheat pose
    const cheatCheck = screen.getByLabelText(/Идеальная поза/i);
    fireEvent.click(cheatCheck);

    const launchBtn = screen.getByText('Запустить симуляцию');
    fireEvent.click(launchBtn);

    // Terminal command should include --cheat
    await waitFor(() => {
      expect(screen.getByText(/\$ python .* --cheat/i)).toBeTruthy();
      expect(screen.getByText('Симуляция выполняется...')).toBeTruthy();
    });

    // Resolve the promise
    await act(async () => {
      capturedResolve!({
        scenario: '04_busy_yard',
        seed: 7,
        exitCode: 0,
        score: 95.0,
        completed: true,
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Запустить симуляцию')).toBeTruthy();
    });
  });

  it('handles simulation failure with error message in terminal', async () => {
    vi.spyOn(apiClient, 'runSimulation').mockRejectedValue(new Error('Process terminated by OOM killer'));

    render(<RunnerPage onNavigate={onNavigateMock} />);

    const launchBtn = screen.getByText('Запустить симуляцию');
    fireEvent.click(launchBtn);

    await waitFor(() => {
      expect(screen.getByText(/Execution failed: Process terminated by OOM killer/i)).toBeTruthy();
      expect(screen.getByText(/Make sure the SDUI server is running/i)).toBeTruthy();
    });

    // Button should be re-enabled after failure
    expect(screen.getByText('Запустить симуляцию')).toBeTruthy();
  });
});
