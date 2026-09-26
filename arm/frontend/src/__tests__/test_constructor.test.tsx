import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ConstructorPage } from '../pages/ConstructorPage';
import { ConstructorCanvas } from '../components/constructor/ConstructorCanvas';
import { validateScenario } from '../utils/scenarioValidator';
import { scenarioTemplates } from '../utils/scenarioTemplates';
import { getUploadedScenario, clearUploadedScenario } from '../utils/scenarioStorage';

beforeAll(() => {
  clearUploadedScenario();
  // Mock HTMLCanvasElement 2D context for jsdom
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
  });

  // Mock ResizeObserver
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };

  // Mock navigator.clipboard
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

describe('Scenario Constructor Page', () => {
  const onNavigateMock = vi.fn();
  const onScenarioChangeMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    clearUploadedScenario();
    sessionStorage.clear();
    localStorage.clear();
  });

  afterEach(() => {
    clearUploadedScenario();
    sessionStorage.clear();
    localStorage.clear();
  });

  afterAll(() => {
    clearUploadedScenario();
    sessionStorage.clear();
    localStorage.clear();
  });

  it('renders ConstructorPage with Russian title, toolbar, and templates selector', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Title and badge
    expect(screen.getByText('Конструктор сценариев AMR')).toBeTruthy();
    expect(screen.getByText('amr-1.0')).toBeTruthy();

    // Top action buttons in Russian
    expect(screen.getByText('Импорт')).toBeTruthy();
    expect(screen.getByText('JSON')).toBeTruthy();
    expect(screen.getByText('Копировать')).toBeTruthy();
    expect(screen.getByText('Экспорт')).toBeTruthy();
    expect(screen.getByText('Сохранить')).toBeTruthy();
    expect(screen.getByText('Запустить в симуляторе')).toBeTruthy();

    // Inspector tabs in Russian
    expect(screen.getByText('Параметры')).toBeTruthy();
    expect(screen.getByText('Объекты')).toBeTruthy();
    expect(screen.getByText('Свойства')).toBeTruthy();
    expect(screen.getByText('Слои')).toBeTruthy();

    // Floating palette tools in Russian
    expect(screen.getByText('Выбор')).toBeTruthy();
    expect(screen.getByText('Рука')).toBeTruthy();
    expect(screen.getByText('Робот')).toBeTruthy();
    expect(screen.getByText('Поддон')).toBeTruthy();
    expect(screen.getByText('Контейнер')).toBeTruthy();
    expect(screen.getByText('Пешеход')).toBeTruthy();
    expect(screen.getByText('Зона')).toBeTruthy();
    expect(screen.getByText('Док')).toBeTruthy();
    expect(screen.getByText('Стена')).toBeTruthy();
    expect(screen.getByText('Проезд')).toBeTruthy();
  });

  it('allows editing scenario metadata and toggling weather', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Edit scenario name
    const nameInput = screen.getByPlaceholderText('my_scenario') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'custom_warehouse_v1' } });
    expect(nameInput.value).toBe('custom_warehouse_v1');

    // Toggle snow weather checkbox
    const snowCheckbox = screen.getByRole('checkbox', { name: '' });
    expect((snowCheckbox as HTMLInputElement).checked).toBe(false);
    fireEvent.click(snowCheckbox);
    expect((snowCheckbox as HTMLInputElement).checked).toBe(true);
  });

  it('switches between presets / templates', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    const templateSelect = screen.getByRole('combobox');
    fireEvent.change(templateSelect, { target: { value: '04_busy_yard' } });

    // The name input should now reflect the loaded 04_busy_yard template
    const nameInput = screen.getByPlaceholderText('my_scenario') as HTMLInputElement;
    expect(nameInput.value).toBe('04_busy_yard_custom');
  });

  it('navigates objects list and opens properties for selected item', async () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Switch to Objects tab
    fireEvent.click(screen.getByText('Объекты'));
    expect(screen.getByText('Робот (AMR Платформа)')).toBeTruthy();
    expect(screen.getByText(/Док-станции и ворота/i)).toBeTruthy();

    // Click on Robot to open Properties
    fireEvent.click(screen.getByText('Робот (AMR Платформа)'));

    // Should switch to Properties tab and display Robot start position form
    expect(screen.getByText('Робот: Позиция старта')).toBeTruthy();
    expect(screen.getByText(/Угол ориентации θ/i)).toBeTruthy();
  });

  it('toggles map layer checkboxes in Layers tab', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Switch to Layers tab
    fireEvent.click(screen.getByText('Слои'));
    expect(screen.getByText('Отображение слоев карты:')).toBeTruthy();
    expect(screen.getByText('Робот (AMR старт)')).toBeTruthy();
    expect(screen.getByText('Проезды и коридоры')).toBeTruthy();
    expect(screen.getByText('Препятствия (паллеты, контейнеры)')).toBeTruthy();
    expect(screen.getByText('Пешеходы и траектории')).toBeTruthy();
    expect(screen.getByText('Зоны (скорость, запретные, ГНСС)')).toBeTruthy();
    expect(screen.getByText('Координатная сетка и рамка')).toBeTruthy();
  });

  it('imports valid JSON scenario and rejects invalid syntax', async () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Open import modal
    fireEvent.click(screen.getByText('Импорт'));
    expect(screen.getByText('Импорт сценария AMR')).toBeTruthy();

    // Paste invalid JSON
    const textarea = screen.getByPlaceholderText(/\{ "schema": "amr-1.0"/i);
    fireEvent.change(textarea, { target: { value: '{ invalid_json: ' } });
    fireEvent.click(screen.getByText('Проверить и загрузить'));

    // Should display error in Russian
    await waitFor(() => {
      expect(screen.getByText(/Ошибка синтаксиса JSON/i)).toBeTruthy();
    });

    // Paste valid AMR scenario
    const validSample = JSON.stringify(scenarioTemplates[0].createScenario());
    fireEvent.change(textarea, { target: { value: validSample } });
    fireEvent.click(screen.getByText('Проверить и загрузить'));

    // Modal should close on success
    await waitFor(() => {
      expect(screen.queryByText('Импорт сценария AMR')).toBeNull();
    });
  });

  it('copies scenario JSON to clipboard on Copy button click', async () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    const copyBtn = screen.getByText('Копировать');
    fireEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalled();
  });

  it('opens and closes raw JSON viewer modal', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Open JSON modal
    fireEvent.click(screen.getByText('JSON'));
    expect(screen.getByText('Редактор кода сценария (JSON amr-1.0)')).toBeTruthy();

    // Close modal
    fireEvent.click(screen.getByText('Закрыть'));
    expect(screen.queryByText('Редактор кода сценария (JSON amr-1.0)')).toBeNull();
  });

  it('saves scenario to storage and launches in simulator', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Click "Сохранить"
    fireEvent.click(screen.getByText('Сохранить'));
    const stored = getUploadedScenario();
    expect(stored).not.toBeNull();
    expect(stored?.fileType).toBe('scenario');

    // Click "Запустить в симуляторе"
    fireEvent.click(screen.getByText('Запустить в симуляторе'));
    expect(onNavigateMock).toHaveBeenCalledWith('runner', expect.objectContaining({ scenario: expect.any(String) }));
  });

  it('toggles compact weather buttons for snow, fog, and gnss in toolbar', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Fog toggle button
    const fogBtn = screen.getByText('Туман');
    expect(fogBtn).toBeTruthy();
    fireEvent.click(fogBtn);

    // GNSS toggle button
    const gnssBtn = screen.getByText('ГНСС');
    expect(gnssBtn).toBeTruthy();
    fireEvent.click(gnssBtn);

    // Snow toggle button
    const snowBtn = screen.getByText('Снег');
    expect(snowBtn).toBeTruthy();
    fireEvent.click(snowBtn);
  });

  it('creates clean map with custom dimensions and base lane in Map tab', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Open "Карта" tab
    fireEvent.click(screen.getByText('Карта'));
    expect(screen.getByText('Чистая карта полигона')).toBeTruthy();
    expect(screen.getByText('Ширина карты (м):')).toBeTruthy();
    expect(screen.getByText('Длина карты (м):')).toBeTruthy();

    // Click "Создать чистую карту"
    const createMapBtn = screen.getByRole('button', { name: /Создать чистую карту/i });
    fireEvent.click(createMapBtn);

    // Toast notification should appear
    expect(screen.getByText(/Чистая карта 120×100м создана/i)).toBeTruthy();
  });

  it('displays rotation angle, slider, and quick buttons for pedestrian in Properties tab', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    // Switch to Objects tab and pick pedestrian
    fireEvent.click(screen.getByText('Объекты'));
    const pedItem = screen.getByText(/p1 \(/i);
    fireEvent.click(pedItem);

    // Should switch to Properties tab and show rotation controls
    expect(screen.getByText('Угол направления:')).toBeTruthy();
    expect(screen.getByText('+45°')).toBeTruthy();
    expect(screen.getByText('+90°')).toBeTruthy();
    expect(screen.getByText('-90°')).toBeTruthy();

    // Click quick rotation button (+45 deg: 90 -> 135)
    fireEvent.click(screen.getByText('+45°'));
    expect(screen.getByText(/135°/)).toBeTruthy();
  });

  it('activates wall and drivable tools when toolbar buttons are clicked', () => {
    render(
      <ConstructorPage
        onNavigate={onNavigateMock}
        onScenarioChange={onScenarioChangeMock}
      />
    );

    const wallBtn = screen.getByRole('button', { name: /Стена/i });
    fireEvent.click(wallBtn);
    expect(wallBtn.className).toContain('bg-slate-700');

    const drivableBtn = screen.getByRole('button', { name: /Проезд/i });
    fireEvent.click(drivableBtn);
    expect(drivableBtn.className).toContain('bg-indigo-600');
  });

  it('attaches wheel listener with { passive: false } and prevents default scrolling on canvas', () => {
    const tmpl = scenarioTemplates[0].createScenario();
    const addEventListenerSpy = vi.spyOn(HTMLCanvasElement.prototype, 'addEventListener');

    const { container } = render(
      <ConstructorCanvas
        scenario={tmpl}
        selectedEntity={null}
        onSelectEntity={vi.fn()}
        onUpdateScenario={vi.fn()}
        activeTool="select"
        activeZoneType="speed_limit"
        layers={{
          robot: true,
          corridors: true,
          obstacles: true,
          pedestrians: true,
          zones: true,
          grid: true,
        }}
      />
    );

    const canvas = container.querySelector('canvas')!;
    expect(canvas).toBeTruthy();

    const wheelCall = addEventListenerSpy.mock.calls.find(
      (call) => call[0] === 'wheel'
    );
    expect(wheelCall).toBeDefined();
    expect(wheelCall?.[2]).toEqual({ passive: false });

    // Test preventDefault when wheel event is dispatched
    const wheelEvent = new WheelEvent('wheel', {
      deltaY: -100,
      cancelable: true,
      bubbles: true,
    });
    canvas.dispatchEvent(wheelEvent);
    expect(wheelEvent.defaultPrevented).toBe(true);

    addEventListenerSpy.mockRestore();
  });
});

describe('Scenario Validator Unit Tests', () => {
  it('passes on valid template scenario', () => {
    const tmpl = scenarioTemplates[0].createScenario();
    const res = validateScenario(tmpl);
    expect(res.valid).toBe(true);
    expect(res.errors.length).toBe(0);
    expect(res.scenario?.schema).toBe('amr-1.0');
  });

  it('fails if schema is not amr-1.0', () => {
    const tmpl = scenarioTemplates[0].createScenario();
    (tmpl as any).schema = 'unknown-2.0';
    const res = validateScenario(tmpl);
    expect(res.valid).toBe(false);
    expect(res.errors).toContain('Неподдерживаемая схема "unknown-2.0". Требуется "amr-1.0"');
  });

  it('fails if robot start coordinates are missing', () => {
    const tmpl = scenarioTemplates[0].createScenario();
    delete (tmpl as any).start;
    const res = validateScenario(tmpl);
    expect(res.valid).toBe(false);
    expect(res.errors).toContain('Отсутствует объект "start" с начальными координатами робота');
  });

  it('fails if bounds are invalid', () => {
    const tmpl = scenarioTemplates[0].createScenario();
    tmpl.map.bounds = [200, 200, 50, 50]; // minX > maxX
    const res = validateScenario(tmpl);
    expect(res.valid).toBe(false);
    expect(res.errors.some((e) => e.includes('Некорректные границы карты'))).toBe(true);
  });
});
