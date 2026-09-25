import React, { useState } from 'react';
import { RouteName } from '../types';
import { Play, Terminal as TerminalIcon, ExternalLink, ChevronDown } from 'lucide-react';

interface RunnerPageProps {
  onNavigate: (route: RouteName, params?: Record<string, any>) => void;
}

export const RunnerPage: React.FC<RunnerPageProps> = ({ onNavigate }) => {
  const [scenario, setScenario] = useState('04_busy_yard');
  const [controller, setController] = useState('team/controller.py');
  const [seed, setSeed] = useState(7);
  const [genReport, setGenReport] = useState(true);
  const [detailedLog, setDetailedLog] = useState(true);
  const [cheatPose, setCheatPose] = useState(false);

  // Execution state
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(100); // Default simulated complete state
  const [isCompleted, setIsCompleted] = useState(true);
  const [outputLogs, setOutputLogs] = useState<string[]>([
    '$ python -m amrsim run scenarios/04_busy_yard.json --controller team/controller.py --seed 7 --report out/report.json --log out/log.jsonl',
    '',
    '[INFO] Loading scenario: 04_busy_yard',
    '[INFO] Loading controller: team/controller.py',
    '[INFO] Setting seed: 7',
    '[INFO] Output report: out/report.json',
    '[INFO] Output log: out/log.jsonl',
    '[INFO] Initializing simulation...',
    '[INFO] Spawning entities...',
    '[INFO] Starting run...',
    '',
    '[STEP 0500]  t= 76.3s | progress: 15.3% | score: 62.17',
    '[STEP 1500]  t= 229.8s | progress: 46.0% | score: 85.42',
    '[STEP 3287]  t= 528.6s | progress: 100.0% | score: 97.31',
    '',
    '[SUCCESS] Run completed with score 97.31'
  ]);

  const handleLaunch = () => {
    setIsRunning(true);
    setIsCompleted(false);
    setProgress(0);
    setOutputLogs([
      `$ python -m amrsim run scenarios/${scenario}.json --controller ${controller} --seed ${seed} ${genReport ? '--report out/report.json' : ''} ${detailedLog ? '--log out/log.jsonl' : ''} ${cheatPose ? '--cheat' : ''}`,
      '',
      `[INFO] Loading scenario: ${scenario}`,
      `[INFO] Loading controller: ${controller}`,
      `[INFO] Setting seed: ${seed}`,
      '[INFO] Initializing simulation...'
    ]);

    let step = 0;
    const interval = setInterval(() => {
      step++;
      setProgress(p => Math.min(100, p + 25));

      if (step === 1) {
        setOutputLogs(prev => [...prev, '[STEP 0500]  t= 76.3s | progress: 25.0% | score: 65.40']);
      } else if (step === 2) {
        setOutputLogs(prev => [...prev, '[STEP 1500]  t= 180.2s | progress: 50.0% | score: 82.10']);
      } else if (step === 3) {
        setOutputLogs(prev => [...prev, '[STEP 2500]  t= 295.4s | progress: 75.0% | score: 91.80']);
      } else if (step >= 4) {
        clearInterval(interval);
        setIsRunning(false);
        setIsCompleted(true);
        setProgress(100);
        setOutputLogs(prev => [
          ...prev,
          '[STEP 3287]  t= 328.7s | progress: 100.0% | score: 97.31',
          '',
          '[SUCCESS] Run completed with score 97.31'
        ]);
      }
    }, 450);
  };

  return (
    <div className="flex-1 flex flex-col p-6 max-w-7xl mx-auto w-full gap-5">
      {/* Top Main Grid: Configuration (4 cols) & Terminal (8 cols) matching runner.png */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 flex-1">
        {/* Form Panel (4 cols) */}
        <div className="lg:col-span-4 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
          <div className="flex flex-col gap-4">
            <h2 className="text-base font-semibold text-slate-800">Запуск симуляции</h2>

            {/* Scenario */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-500 font-medium">Сценарий</label>
              <div className="relative">
                <select
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-2.5 appearance-none focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                >
                  <option value="01_clear">01_clear</option>
                  <option value="02_gnss_shadow">02_gnss_shadow</option>
                  <option value="03_fog_snow">03_fog_snow</option>
                  <option value="04_busy_yard">04_busy_yard</option>
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
                  <option value="team/controller.py">team/controller.py</option>
                  <option value="baseline/controller.py">baseline/controller.py</option>
                </select>
                <ChevronDown className="w-4 h-4 text-slate-400 absolute right-3 top-3 pointer-events-none" />
              </div>
            </div>

            {/* Seed */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-500 font-medium">Seed</label>
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
                <span>Генерировать отчёт</span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={detailedLog}
                  onChange={(e) => setDetailedLog(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Детальный лог телеметрии</span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={cheatPose}
                  onChange={(e) => setCheatPose(e.target.checked)}
                  className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Чит-поза /oracle</span>
              </label>
            </div>
          </div>

          {/* Launch Button */}
          <button
            onClick={handleLaunch}
            disabled={isRunning}
            className="w-full mt-6 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-semibold py-3 px-4 rounded-lg flex items-center justify-center gap-2 shadow-sm transition-colors"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>{isRunning ? 'Симуляция выполняется...' : 'Запустить симуляцию'}</span>
          </button>
        </div>

        {/* Terminal Panel (8 cols) matching runner.png */}
        <div className="lg:col-span-8 bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col gap-3 min-h-[460px]">
          <div className="flex items-center gap-2 text-xs font-mono font-medium text-slate-600 pb-2 border-b border-slate-100">
            <TerminalIcon className="w-4 h-4 text-slate-500" />
            <span>Терминал</span>
          </div>

          <div className="flex-1 bg-slate-50 border border-slate-200 rounded-lg p-4 font-mono text-xs text-slate-700 overflow-y-auto max-h-[420px] space-y-1">
            {outputLogs.map((line, idx) => {
              const isCommand = line.startsWith('$');
              const isSuccess = line.startsWith('[SUCCESS]');
              const isStep = line.startsWith('[STEP');

              return (
                <div
                  key={idx}
                  className={`${
                    isCommand 
                      ? 'text-slate-900 font-semibold' 
                      : isSuccess 
                      ? 'text-emerald-600 font-bold' 
                      : isStep 
                      ? 'text-blue-700' 
                      : 'text-slate-600'
                  }`}
                >
                  {line}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom Completion & Open in Replay Dock matching runner.png */}
      <div className="bg-white p-4 px-6 rounded-xl border border-slate-200 shadow-sm flex flex-col sm:flex-row items-center justify-between gap-4">
        {/* Progress Bar & Status */}
        <div className="flex-1 w-full mr-4 flex flex-col gap-1.5">
          <div className="flex justify-between text-xs font-mono">
            <span className="text-slate-600">
              {isRunning ? 'Running simulation...' : 'Run complete · Score 97.31'}
            </span>
            <span className="text-slate-400 font-semibold">{progress}%</span>
          </div>

          <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
            <div
              className="bg-blue-600 h-full rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>

        {/* Open in Replay button: ONLY visible after run is complete as per frontend.md */}
        {isCompleted && (
          <button
            onClick={() => onNavigate('replay', { run: 'latest' })}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg border border-blue-600 bg-white hover:bg-blue-50 text-blue-600 text-xs font-semibold shadow-sm transition-colors whitespace-nowrap"
          >
            <ExternalLink className="w-4 h-4" />
            <span>Open in Replay</span>
          </button>
        )}
      </div>
    </div>
  );
};
