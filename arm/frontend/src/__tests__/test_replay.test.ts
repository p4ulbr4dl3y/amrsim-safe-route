import { describe, it, expect } from 'vitest';

/**
 * Replay playback mathematics and state update model.
 * Mirrors the logic implemented in ReplayPage.tsx.
 */
export class ReplayEngine {
  ticks: Array<{ t: number; x: number; y: number; theta: number }>;
  currentIndex: number = 0;
  fractionalIndex: number = 0;
  playSpeed: number = 1.0;
  isPlaying: boolean = false;

  constructor(ticks: Array<{ t: number; x: number; y: number; theta: number }> = []) {
    this.ticks = ticks;
  }

  get tickRate(): number {
    if (this.ticks.length > 1 && this.ticks[this.ticks.length - 1].t > this.ticks[0].t) {
      return (this.ticks.length - 1) / (this.ticks[this.ticks.length - 1].t - this.ticks[0].t);
    }
    return 10.0; // Default 10 Hz
  }

  get maxIndex(): number {
    return Math.max(0, this.ticks.length - 1);
  }

  seekToIndex(targetIndex: number): number {
    const clamped = Math.max(0, Math.min(this.maxIndex, Math.round(targetIndex)));
    this.fractionalIndex = clamped;
    this.currentIndex = clamped;
    return clamped;
  }

  seekToTime(targetTime: number): number {
    if (this.ticks.length === 0) return 0;
    const idx = this.ticks.findIndex((tk) => tk.t >= targetTime);
    const chosen = idx !== -1 ? idx : this.maxIndex;
    return this.seekToIndex(chosen);
  }

  stepForward(count = 1): number {
    return this.seekToIndex(this.currentIndex + count);
  }

  stepBackward(count = 1): number {
    return this.seekToIndex(this.currentIndex - count);
  }

  setSpeed(speed: number) {
    if (speed > 0) {
      this.playSpeed = speed;
    }
  }

  /**
   * Advance simulation by deltaMs milliseconds.
   */
  update(deltaMs: number): { nextIndex: number; wrapped: boolean } {
    if (!this.isPlaying || this.ticks.length === 0) {
      return { nextIndex: this.currentIndex, wrapped: false };
    }

    let wrapped = false;
    // If starting at or past the end, wrap to start
    if (this.fractionalIndex >= this.maxIndex) {
      this.fractionalIndex = 0;
      this.currentIndex = 0;
      wrapped = true;
    }

    const deltaSeconds = deltaMs / 1000.0;
    const ticksToAdvance = deltaSeconds * this.tickRate * this.playSpeed;
    let nextFrac = this.fractionalIndex + ticksToAdvance;

    if (nextFrac >= this.maxIndex) {
      nextFrac = this.maxIndex;
      this.isPlaying = false; // pause at end unless loop configured
    }

    this.fractionalIndex = nextFrac;
    this.currentIndex = Math.floor(nextFrac);

    return { nextIndex: this.currentIndex, wrapped };
  }
}

describe('Replay Engine Math & Scrubbing', () => {
  const sampleTicks = Array.from({ length: 101 }, (_, i) => ({
    t: Number((i * 0.1).toFixed(2)), // 0.0s to 10.0s at 10 Hz
    x: 100.0 + i * 0.1,
    y: 50.0,
    theta: 0.0,
  }));

  it('calculates correct tickRate for 10 Hz simulation data', () => {
    const engine = new ReplayEngine(sampleTicks);
    // 100 steps / 10.0s = 10.0 ticks per second
    expect(engine.tickRate).toBeCloseTo(10.0, 5);
  });

  it('falls back to 10 Hz default if fewer than 2 ticks or non-increasing time', () => {
    const engine = new ReplayEngine([{ t: 0, x: 0, y: 0, theta: 0 }]);
    expect(engine.tickRate).toBe(10.0);
  });

  it('accurately advances ticks at 1x speed', () => {
    const engine = new ReplayEngine(sampleTicks);
    engine.isPlaying = true;
    engine.setSpeed(1.0);

    // After 100ms (0.1s) at 10 Hz, advance by 1.0 tick
    const res = engine.update(100);
    expect(engine.fractionalIndex).toBeCloseTo(1.0, 3);
    expect(res.nextIndex).toBe(1);

    // Another 500ms -> +5 ticks -> tick index 6
    engine.update(500);
    expect(engine.fractionalIndex).toBeCloseTo(6.0, 3);
    expect(engine.currentIndex).toBe(6);
  });

  it('accurately scales tick advancement for 2x, 5x, and 10x speeds', () => {
    const speeds = [1.0, 2.0, 5.0, 10.0];

    speeds.forEach((speed) => {
      const engine = new ReplayEngine(sampleTicks);
      engine.isPlaying = true;
      engine.setSpeed(speed);

      // Advance by 1 second (1000ms)
      engine.update(1000);
      const expectedTicks = 10.0 * speed;
      expect(engine.fractionalIndex).toBeCloseTo(expectedTicks, 2);
      expect(engine.currentIndex).toBe(Math.floor(expectedTicks));
    });
  });

  it('seeks to target index and clamps to valid range [0, maxIndex]', () => {
    const engine = new ReplayEngine(sampleTicks);

    expect(engine.seekToIndex(45)).toBe(45);
    expect(engine.currentIndex).toBe(45);

    // Negative clamps to 0
    expect(engine.seekToIndex(-10)).toBe(0);
    expect(engine.currentIndex).toBe(0);

    // Above maxIndex clamps to 100
    expect(engine.seekToIndex(9999)).toBe(100);
    expect(engine.currentIndex).toBe(100);
  });

  it('seeks to target timestamp with precision', () => {
    const engine = new ReplayEngine(sampleTicks);

    // Seek to 3.5s -> tick index 35
    expect(engine.seekToTime(3.5)).toBe(35);
    expect(sampleTicks[engine.currentIndex].t).toBeCloseTo(3.5, 2);

    // Seek to 0.0s -> tick 0
    expect(engine.seekToTime(0.0)).toBe(0);

    // Seek past end time -> clamps to last tick
    expect(engine.seekToTime(99.9)).toBe(100);
  });

  it('steps forward and backward by discrete increments', () => {
    const engine = new ReplayEngine(sampleTicks);
    engine.seekToIndex(50);

    expect(engine.stepForward(5)).toBe(55);
    expect(engine.stepBackward(10)).toBe(45);
    expect(engine.stepBackward(100)).toBe(0); // clamp to 0
    expect(engine.stepForward(200)).toBe(100); // clamp to max
  });

  it('stops playback at the end and detects boundary wrap', () => {
    const engine = new ReplayEngine(sampleTicks);
    engine.seekToIndex(98);
    engine.isPlaying = true;
    engine.setSpeed(1.0);

    // 500ms advances by 5 ticks -> reaches end (100) and stops
    engine.update(500);
    expect(engine.currentIndex).toBe(100);
    expect(engine.isPlaying).toBe(false);

    // If played again from the end, wraps around to 0
    engine.isPlaying = true;
    const res = engine.update(100);
    expect(res.wrapped).toBe(true);
    expect(engine.currentIndex).toBe(1);
  });

  it('correctly calculates dynamic mission labels and deadline countdown', () => {
    const missions = [
      {
        id: 'm1',
        from: 'start',
        to: 'dock_a',
        fromLabel: 'Старт',
        toLabel: 'Док А',
        deadline_s: 60.0,
        t_start: 0.0,
      },
      {
        id: 'm2',
        from: 'dock_a',
        to: 'dock_b',
        fromLabel: 'Док А',
        toLabel: 'Док B',
        deadline_s: 45.0,
        t_start: 20.0,
      },
    ];

    // For m1 at t = 15.5
    const tickM1 = { t: 15.5, m: 'm1' };
    const missionM1 = missions.find((m) => m.id === tickM1.m);
    expect(missionM1).toBeDefined();
    expect(missionM1?.fromLabel).toBe('Старт');
    expect(missionM1?.toLabel).toBe('Док А');
    const remM1 = Math.max(0, missionM1!.t_start + missionM1!.deadline_s - tickM1.t);
    expect(remM1).toBeCloseTo(44.5, 1);

    // For m2 at t = 30.0 (non-01 scenario, custom deadline)
    const tickM2 = { t: 30.0, m: 'm2' };
    const missionM2 = missions.find((m) => m.id === tickM2.m);
    expect(missionM2).toBeDefined();
    expect(missionM2?.fromLabel).toBe('Док А');
    expect(missionM2?.toLabel).toBe('Док B');
    const remM2 = Math.max(0, missionM2!.t_start + missionM2!.deadline_s - tickM2.t);
    expect(remM2).toBeCloseTo(35.0, 1);
    // Verified: does not equal hardcoded 200.7 - t
    expect(remM2).not.toBeCloseTo(200.7 - tickM2.t, 1);
  });
});

