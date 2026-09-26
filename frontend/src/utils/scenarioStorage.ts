import { DashboardViewModel, ReplayViewModel, MissionsViewModel, MapData } from '../types';

export const AMR_UPLOADED_SCENARIO_KEY = 'amr_uploaded_scenario';
export const AMR_STORAGE_EVENT = 'amr-scenario-storage-change';

export interface UploadedScenarioData {
  id: string;
  name: string;
  fileName: string;
  fileType: 'scenario' | 'report' | 'log';
  mapData?: MapData;
  scenarioJson?: any;
  reportJson?: any;
  dashboardViewModel?: DashboardViewModel;
  replayViewModel?: ReplayViewModel;
  missionsViewModel?: MissionsViewModel;
  uploadedAt: number;
}

/**
 * Saves uploaded scenario to sessionStorage and synchronizes with localStorage.
 * Dispatches 'amr-scenario-storage-change' CustomEvent for multi-component synchronization.
 */
export function saveUploadedScenario(data: UploadedScenarioData): void {
  try {
    const serialized = JSON.stringify(data);
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem(AMR_UPLOADED_SCENARIO_KEY, serialized);
    }
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(AMR_UPLOADED_SCENARIO_KEY, serialized);
    }
  } catch (e) {
    console.warn('[scenarioStorage] Failed to save uploaded scenario:', e);
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(AMR_STORAGE_EVENT, { detail: data }));
  }
}

/**
 * Retrieves uploaded scenario from sessionStorage (or localStorage fallback).
 */
export function getUploadedScenario(): UploadedScenarioData | null {
  try {
    let serialized: string | null = null;
    if (typeof sessionStorage !== 'undefined') {
      serialized = sessionStorage.getItem(AMR_UPLOADED_SCENARIO_KEY);
    }
    if (!serialized && typeof localStorage !== 'undefined') {
      serialized = localStorage.getItem(AMR_UPLOADED_SCENARIO_KEY);
    }
    if (!serialized) return null;
    return JSON.parse(serialized) as UploadedScenarioData;
  } catch (e) {
    console.warn('[scenarioStorage] Failed to read uploaded scenario:', e);
    return null;
  }
}

/**
 * Clears uploaded scenario from sessionStorage and localStorage.
 * Dispatches 'amr-scenario-storage-change' CustomEvent.
 */
export function clearUploadedScenario(): void {
  try {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem(AMR_UPLOADED_SCENARIO_KEY);
    }
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(AMR_UPLOADED_SCENARIO_KEY);
    }
  } catch (e) {
    console.warn('[scenarioStorage] Failed to clear uploaded scenario:', e);
  }

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(AMR_STORAGE_EVENT, { detail: null }));
  }
}

/**
 * Checks whether an uploaded scenario is currently stored.
 */
export function hasUploadedScenario(): boolean {
  return getUploadedScenario() !== null;
}

// Window lifecycle listeners: clear on reload or closing page
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    clearUploadedScenario();
  });
  window.addEventListener('pagehide', () => {
    clearUploadedScenario();
  });
}
