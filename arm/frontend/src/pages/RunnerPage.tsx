import React, { useState, useEffect } from 'react';
import { RouteName, ScenarioItem } from '../types';
import { apiClient } from '../api/client';
import { Play, Terminal as TerminalIcon, ExternalLink, ChevronDown, RefreshCw, BarChart2 } from 'lucide-react';

interface RunnerPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
  queryParams?: {
    scenario?: string;
  };
}

export const RunnerPage: React.FC<RunnerPageProps> = ({ onNavigate, queryParams }) => {
  const [scenario, setScenario] = useState(queryParams?.scenario || '04_busy_yard');
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [controller, setController] = useState('team_dreamteam_4_0/controller.py');
  const [seed, setSeed] = useState(7);
  const [genReport, setGenReport] = useState(true);
  const [detailedLog, setDetailedLog] = useState(true);
  const [cheatPose, setCheatPose] = useState(false);

  // Состояние выполнения
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [isCompleted, setIsCompleted] = useState(false);
  const [finalScore, setFinalScore] = useState<number | null>(null);
  const [outputLogs, setOutputLogs] = useState<string[]>([]);

  // Загрузка сценариев при монтировании
  useEffect(() => {
    let mounted = true;
    apiClient.fetchScenarios().then((list) => {
      if (mounted) setScenarios(list);
    });
    return () => {
      mounted = false;
    };
  }, []);

  // Обновление сценария из параметров URL при изменении
  useEffect(() => {
    if (queryParams?.scenario && queryParams.scenario !== scenario) {
      setScenario(queryParams.scenario);
    }
  }, [queryParams?.scenario]);

  const handleLaunch = async () => {
    setIsRunning(true);
    setIsCompleted(false);
    setProgress(15);
    setFinalScore(null);

    const initialCommand = `$ python -m amrsim run ${scenario}.json --controller ${controller} --seed ${seed} ${
      cheatPose ? '--cheat' : ''
    }`;

    setOutputLogs([
      initialCommand,
      '',
      `[INFO] Starting simulation runner on backend...`,
      `[INFO] Scenario: ${scenario}`,
      `[INFO] Controller: ${controller}`,
      `[INFO] Seed: ${seed}`,
      `[INFO] Report: out/${scenario}.json`,
      `[INFO] Log: out/${scenario}.jsonl`,
      `[INFO] Executing controller with Python sandbox isolation...`,
    ]);

    // Симуляция прироста прогресса во время ожидания ответа
    const progressTimer = setInterval(() => {
      setProgress((p) => (p < 85 ? p + 15 : p));
    }, 400);

    try {
      const res = await apiClient.runSimulation({
        scenario,
        controller,
        seed,
        cheatPose,
      });

      clearInterval(progressTimer);
      setProgress(100);
      setIsRunning(false);
      setIsCompleted(true);
      setFinalScore(res.score);

      const logs: string[] = [initialCommand, ''];
      if (res.stdout) {
        logs.push(...res.stdout.split('\n').filter(Boolean));
      }
      if (res.stderr) {
        logs.push(...res.stderr.split('\n').filter(Boolean));
      }
      logs.push('');
      logs.push(`[SUCCESS] Simulation finished with exit code ${res.exitCode}`);
      if (res.score !== null && res.score !== undefined) {
        logs.push(`[SCORE] Final score: ${res.score.toFixed(2)} / 100`);
      }

      setOutputLogs(logs);
    } catch (err: any) {
      clearInterval(progressTimer);
      setProgress(100);
      setIsRunning(false);
      setIsCompleted(false);
      setOutputLogs((prev) => [
        ...prev,
        '',
        `[ERROR] Execution failed: ${err.message || String(err)}`,
        '[HINT] Make sure the SDUI server is running: python scripts/server.py',
      ]);
    }
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Top Main Grid: Configuration (4 cols) & Terminal (8 cols) matching runner.png */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1">
        {/* Form Panel (4 cols) */}
        <div className="lg:col-span-4 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div className="flex flex-col gap-4">
            <h2 className="text-base font-semibold text-slate-800">Параметры симуляции</h2>

            {/* Scenario */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-500 font-medium">Сценарий</label>
              <div className="relative">
                <select
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                >
                  {scenarios.length > 0 ? (
                    scenarios.map((sc) => (
                      <option key={sc.id} value={sc.id}>
                        {sc.name}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="01_clear">01_clear</option>
                      <option value="01e_clear_easy">01e_clear_easy</option>
                      <option value="02_gnss_shadow">02_gnss_shadow</option>
                      <option value="02e_gnss_shadow_easy">02e_gnss_shadow_easy</option>
                      <option value="03_fog_snow">03_fog_snow</option>
                      <option value="04_busy_yard">04_busy_yard</option>
                      <option value="s1_pallet_2m">backend/s1_pallet_2m</option>
                      <option value="s2_container_block">backend/s2_container_block</option>
                      <option value="s3_wall_removed">backend/s3_wall_removed</option>
                      <option value="s4_shadow_start_charger">backend/s4_shadow_start_charger</option>
                      <option value="s5_fog_inattentive">backend/s5_fog_inattentive</option>
                    </>
                  )}
                </select>
                <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
              </div>
            </div>

            {/* Controller */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-500 font-medium">Контроллер</label>
              <div className="relative">
                <select
                  value={controller}
                  onChange={(e) => setController(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                >
                  <option value="team_dreamteam_4_0/controller.py">
                    team_dreamteam_4_0/controller.py (Командный)
                  </option>
                  <option value="backend/controller.py">backend/controller.py (Алиас)</option>
                  <option value="team/controller.py">team/controller.py (Алиас)</option>
                  <option value="amrsim-participants/baseline/controller.py">
                    amrsim-participants/baseline/controller.py (Базовый)
                  </option>
                </select>
                <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
              </div>
            </div>

            {/* Seed */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-500 font-medium">Случайное зерно (Seed)</label>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            {/* Checkboxes */}
            <div className="flex flex-col gap-2.5 pt-2">
              <label className="flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={genReport}
                  onChange={(e) => setGenReport(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Генерировать отчёт JSON</span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={detailedLog}
                  onChange={(e) => setDetailedLog(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Детальный лог телеметрии JSONL</span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={cheatPose}
                  onChange={(e) => setCheatPose(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Идеальная поза (--cheat)</span>
              </label>
            </div>
          </div>

          {/* Launch Button */}
          <button
            onClick={handleLaunch}
            disabled={isRunning}
            className="w-full mt-6 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-semibold py-3 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors"
          >
            {isRunning ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{isRunning ? 'Симуляция выполняется...' : 'Запустить симуляцию'}</span>
          </button>
        </div>

        {/* Terminal Panel (8 cols) matching runner.png */}
        <div className="lg:col-span-8 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3 min-h-[460px]">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <div className="flex items-center gap-2 text-xs font-mono font-medium text-slate-600">
              <TerminalIcon className="w-4 h-4 text-slate-500" />
              <span>Терминал симулятора amrsim</span>
            </div>
            {isRunning && (
              <span className="text-[11px] font-mono text-blue-600 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-blue-600 animate-ping"></span>
                Выполнение...
              </span>
            )}
          </div>

          <div className="flex-1 bg-slate-900 border border-slate-800 rounded-lg p-4 font-mono text-xs text-slate-200 overflow-y-auto max-h-[420px] space-y-1">
            {outputLogs.length === 0 ? (
              <div className="text-slate-500 italic select-none py-2">
                Терминал ожидает запуска симуляции...
              </div>
            ) : (
              outputLogs.map((line, idx) => {
              const isCommand = line.startsWith('$');
              const isSuccess = line.startsWith('[SUCCESS]') || line.startsWith('[SCORE]');
              const isError = line.startsWith('[ERROR]');
              const isStep = line.startsWith('[STEP') || line.startsWith('[INFO]');

              return (
                <div
                  key={idx}
                  className={`${
                    isCommand
                      ? 'text-white font-bold'
                      : isSuccess
                      ? 'text-emerald-400 font-bold'
                      : isError
                      ? 'text-red-400 font-bold'
                      : isStep
                      ? 'text-cyan-300'
                      : 'text-slate-400'
                  }`}
                >
                  {line}
                </div>
              );
            }))}
          </div>
        </div>
      </div>

      {/* Bottom Completion & Actions Dock */}
      <div className="bg-white p-4 px-6 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
        {/* Progress Bar & Status */}
        <div className="flex-1 w-full mr-4 flex flex-col gap-1.5">
          <div className="flex justify-between text-xs font-mono">
            <span className="text-slate-700 font-medium">
              {isRunning
                ? 'Выполнение симуляции контроллера...'
                : isCompleted && finalScore !== null
                ? `Симуляция завершена · Балл ${finalScore.toFixed(2)} / 100`
                : 'Готов к запуску'}
            </span>
            <span className="text-slate-400 font-semibold">{progress}%</span>
          </div>

          <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                isRunning ? 'bg-blue-600' : 'bg-emerald-600'
              }`}
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>

        {/* Action Buttons: Visible when complete */}
        {isCompleted && (
          <div className="flex items-center gap-3">
            <button
              onClick={() => onNavigate('replay', { scenario })}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-blue-600 bg-white hover:bg-blue-50 text-blue-600 text-xs font-semibold shadow-sm transition-colors whitespace-nowrap"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Открыть в Replay</span>
            </button>
            <button
              onClick={() => onNavigate('analytics', { scenario })}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-sm transition-colors whitespace-nowrap"
            >
              <BarChart2 className="w-3.5 h-3.5" />
              <span>Аналитика</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
