import React, { useId, useState } from 'react';
import { Volume2, Droplets, Zap, Square, Sliders, ShieldAlert, Shuffle } from 'lucide-react';
import { ActuatorType, DeterrentTelemetry } from '../types/sentinel';

interface ActuatorTestPanelProps {
  telemetry: DeterrentTelemetry;
  onTestActuator: (actuator: ActuatorType, pattern: string, durationMs?: number) => Promise<void>;
  onStopAll: () => Promise<void>;
}

export const ActuatorTestPanel: React.FC<ActuatorTestPanelProps> = ({
  telemetry,
  onTestActuator,
  onStopAll,
}) => {
  const soundSliderId = useId();
  const waterSliderId = useId();
  const lightSliderId = useId();

  const [selectedPattern, setSelectedPattern] = useState<'BIRD' | 'SMALL' | 'LARGE'>('LARGE');
  const [busyActuator, setBusyActuator] = useState<ActuatorType | null>(null);

  const [soundDurationSec, setSoundDurationSec] = useState<number>(5.0);
  const [soundRandom, setSoundRandom] = useState<boolean>(false);

  const [waterDurationSec, setWaterDurationSec] = useState<number>(4.0);
  const [waterRandom, setWaterRandom] = useState<boolean>(false);

  const [lightDurationSec, setLightDurationSec] = useState<number>(5.0);
  const [lightRandom, setLightRandom] = useState<boolean>(false);

  const handleTest = async (actuator: ActuatorType, durationMs?: number) => {
    setBusyActuator(actuator);
    try {
      const pattern = actuator === 'SOUND' ? selectedPattern : actuator;
      await onTestActuator(actuator, pattern, durationMs);
    } finally {
      setBusyActuator(null);
    }
  };

  const activeSound = telemetry.is_active && telemetry.active_actuators.includes('SOUND');
  const activeWater = telemetry.is_active && telemetry.active_actuators.includes('WATER');
  const activeLight = telemetry.is_active && telemetry.active_actuators.includes('LIGHT');

  return (
    <section className="rounded-xl border border-slate-800/90 bg-[#0d1320] p-5 shadow-lg">
      <div className="mb-4 flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-sky-400" />
          <h2 className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-slate-200">
            Hardware Deterrent Diagnostics
          </h2>
        </div>
        <span className="font-mono-tabular text-[11px] text-slate-400">
          3 INDEPENDENT CHANNELS
        </span>
      </div>

      {/* 3 Independent Deterrent Trigger Cards with Per-Channel Duration Control */}
      <div className="grid grid-cols-1 gap-3">
        {/* Channel 1 — Sound Buzzer (GPIO 17) */}
        <div
          className={`rounded-lg border p-3.5 transition ${
            activeSound
              ? 'border-rose-500 bg-rose-500/15 shadow-[0_0_15px_rgba(244,63,94,0.22)]'
              : 'border-slate-800 bg-[#0b111d]'
          }`}
        >
          {/* Acoustic Pattern Tier Selector */}
          <div className="mb-2.5">
            <span className="mb-1.5 block font-mono-tabular text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Acoustic Pattern Tier (GPIO 17)
            </span>
            <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-slate-800 bg-[#080c14] p-1">
              <button
                type="button"
                onClick={() => setSelectedPattern('BIRD')}
                className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-semibold transition cursor-pointer ${
                  selectedPattern === 'BIRD'
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                BIRD
              </button>
              <button
                type="button"
                onClick={() => setSelectedPattern('SMALL')}
                className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-semibold transition cursor-pointer ${
                  selectedPattern === 'SMALL'
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                SMALL
              </button>
              <button
                type="button"
                onClick={() => setSelectedPattern('LARGE')}
                className={`rounded-md px-2 py-1 font-mono-tabular text-[10px] font-semibold transition cursor-pointer ${
                  selectedPattern === 'LARGE'
                    ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                LARGE
              </button>
            </div>
          </div>

          {/* Independent Sound Duration Control */}
          <div className="mb-3 rounded-lg border border-slate-800/80 bg-[#080c14] px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <label
                htmlFor={soundSliderId}
                className="font-mono-tabular text-[10px] font-semibold uppercase tracking-wider text-slate-400"
              >
                Sound Duration
              </label>
              <div className="flex items-center gap-2">
                <span className="font-mono-tabular text-xs font-bold text-rose-300">
                  {soundRandom ? 'RANDOM' : `${soundDurationSec.toFixed(1)}s`}
                </span>
                <button
                  type="button"
                  aria-pressed={soundRandom}
                  onClick={() => setSoundRandom((prev) => !prev)}
                  className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    soundRandom
                      ? 'border-rose-400 bg-rose-500/25 text-rose-200'
                      : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Shuffle className="h-2.5 w-2.5" />
                  RANDOM
                </button>
              </div>
            </div>
            <input
              id={soundSliderId}
              type="range"
              min={1}
              max={15}
              step={0.5}
              disabled={soundRandom}
              value={soundDurationSec}
              onChange={(e) => setSoundDurationSec(parseFloat(e.target.value))}
              className="h-1.5 w-full accent-rose-400 disabled:opacity-40 cursor-pointer"
            />
          </div>

          <button
            type="button"
            onClick={() =>
              handleTest('SOUND', soundRandom ? 0 : Math.round(soundDurationSec * 1000))
            }
            disabled={busyActuator !== null}
            className="flex w-full items-center justify-between rounded-lg border border-rose-500/30 bg-[#11192a] px-3.5 py-2.5 text-left text-slate-200 transition hover:border-rose-500/60 hover:bg-rose-500/15 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-md border border-rose-500/30 bg-rose-500/10 text-rose-400">
                <Volume2 className="h-4 w-4" />
              </div>
              <div>
                <div className="font-mono-tabular text-xs font-bold tracking-wide">
                  TEST SOUND BUZZER
                </div>
                <div className="font-mono-tabular text-[11px] text-slate-400">
                  GPIO 17 • {selectedPattern} • {soundRandom ? 'Random Tier' : `${soundDurationSec.toFixed(1)}s`}
                </div>
              </div>
            </div>
            <span className="rounded border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
              {activeSound ? 'FIRING' : 'TRIGGER'}
            </span>
          </button>
        </div>

        {/* Channel 2 — Water Sprinkler (GPIO 18) */}
        <div
          className={`rounded-lg border p-3.5 transition ${
            activeWater
              ? 'border-sky-500 bg-sky-500/15 shadow-[0_0_15px_rgba(14,165,233,0.22)]'
              : 'border-slate-800 bg-[#0b111d]'
          }`}
        >
          <div className="mb-3 rounded-lg border border-slate-800/80 bg-[#080c14] px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <label
                htmlFor={waterSliderId}
                className="font-mono-tabular text-[10px] font-semibold uppercase tracking-wider text-slate-400"
              >
                Water Pump Duration (GPIO 18)
              </label>
              <div className="flex items-center gap-2">
                <span className="font-mono-tabular text-xs font-bold text-sky-300">
                  {waterRandom ? 'RANDOM' : `${waterDurationSec.toFixed(1)}s`}
                </span>
                <button
                  type="button"
                  aria-pressed={waterRandom}
                  onClick={() => setWaterRandom((prev) => !prev)}
                  className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    waterRandom
                      ? 'border-sky-400 bg-sky-500/25 text-sky-200'
                      : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Shuffle className="h-2.5 w-2.5" />
                  RANDOM
                </button>
              </div>
            </div>
            <input
              id={waterSliderId}
              type="range"
              min={1}
              max={15}
              step={0.5}
              disabled={waterRandom}
              value={waterDurationSec}
              onChange={(e) => setWaterDurationSec(parseFloat(e.target.value))}
              className="h-1.5 w-full accent-sky-400 disabled:opacity-40 cursor-pointer"
            />
          </div>

          <button
            type="button"
            onClick={() =>
              handleTest('WATER', waterRandom ? 0 : Math.round(waterDurationSec * 1000))
            }
            disabled={busyActuator !== null}
            className="flex w-full items-center justify-between rounded-lg border border-sky-500/30 bg-[#11192a] px-3.5 py-2.5 text-left text-slate-200 transition hover:border-sky-500/60 hover:bg-sky-500/15 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-md border border-sky-500/30 bg-sky-500/10 text-sky-400">
                <Droplets className="h-4 w-4" />
              </div>
              <div>
                <div className="font-mono-tabular text-xs font-bold tracking-wide">
                  TEST WATER SPRINKLER
                </div>
                <div className="font-mono-tabular text-[11px] text-slate-400">
                  GPIO 18 Pump • {waterRandom ? 'Random 2.5–6s' : `${waterDurationSec.toFixed(1)}s`}
                </div>
              </div>
            </div>
            <span className="rounded border border-sky-500/40 bg-sky-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
              {activeWater ? 'ACTIVE' : 'TRIGGER'}
            </span>
          </button>
        </div>

        {/* Channel 3 — Flashing Light (GPIO 16) */}
        <div
          className={`rounded-lg border p-3.5 transition ${
            activeLight
              ? 'border-amber-500 bg-amber-500/15 shadow-[0_0_15px_rgba(245,158,11,0.22)]'
              : 'border-slate-800 bg-[#0b111d]'
          }`}
        >
          <div className="mb-3 rounded-lg border border-slate-800/80 bg-[#080c14] px-3 py-2">
            <div className="mb-1 flex items-center justify-between gap-2">
              <label
                htmlFor={lightSliderId}
                className="font-mono-tabular text-[10px] font-semibold uppercase tracking-wider text-slate-400"
              >
                LED Strobe Duration (GPIO 16)
              </label>
              <div className="flex items-center gap-2">
                <span className="font-mono-tabular text-xs font-bold text-amber-300">
                  {lightRandom ? 'RANDOM' : `${lightDurationSec.toFixed(1)}s`}
                </span>
                <button
                  type="button"
                  aria-pressed={lightRandom}
                  onClick={() => setLightRandom((prev) => !prev)}
                  className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold transition cursor-pointer ${
                    lightRandom
                      ? 'border-amber-400 bg-amber-500/25 text-amber-200'
                      : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Shuffle className="h-2.5 w-2.5" />
                  RANDOM
                </button>
              </div>
            </div>
            <input
              id={lightSliderId}
              type="range"
              min={1}
              max={15}
              step={0.5}
              disabled={lightRandom}
              value={lightDurationSec}
              onChange={(e) => setLightDurationSec(parseFloat(e.target.value))}
              className="h-1.5 w-full accent-amber-400 disabled:opacity-40 cursor-pointer"
            />
          </div>

          <button
            type="button"
            onClick={() =>
              handleTest('LIGHT', lightRandom ? 0 : Math.round(lightDurationSec * 1000))
            }
            disabled={busyActuator !== null}
            className="flex w-full items-center justify-between rounded-lg border border-amber-500/30 bg-[#11192a] px-3.5 py-2.5 text-left text-slate-200 transition hover:border-amber-500/60 hover:bg-amber-500/15 disabled:opacity-50 cursor-pointer"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-md border border-amber-500/30 bg-amber-500/10 text-amber-400">
                <Zap className="h-4 w-4" />
              </div>
              <div>
                <div className="font-mono-tabular text-xs font-bold tracking-wide">
                  TEST FLASHING LIGHT
                </div>
                <div className="font-mono-tabular text-[11px] text-slate-400">
                  GPIO 16 Strobe • {lightRandom ? 'Random 3.5–7.5s' : `${lightDurationSec.toFixed(1)}s`}
                </div>
              </div>
            </div>
            <span className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
              {activeLight ? 'STROBING' : 'TRIGGER'}
            </span>
          </button>
        </div>
      </div>

      {/* Silence / Emergency Stop */}
      <button
        type="button"
        onClick={onStopAll}
        className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-900 py-2.5 font-mono-tabular text-xs font-bold text-rose-400 transition hover:border-rose-500 hover:bg-rose-500 hover:text-white cursor-pointer"
      >
        <Square className="h-3.5 w-3.5 fill-current" />
        SILENCE & HALT ALL DETERRENTS
      </button>

      {/* Deterministic Threat Matrix Reference */}
      <div className="mt-4 rounded-lg border border-slate-800/80 bg-[#080c14] p-3">
        <div className="mb-2 flex items-center gap-1.5 font-mono-tabular text-[11px] font-bold uppercase tracking-wider text-slate-400">
          <ShieldAlert className="h-3.5 w-3.5 text-sky-400" />
          Escalation Hierarchy (Higher Threat Wins)
        </div>
        <div className="space-y-1.5 font-mono-tabular text-[11px]">
          <div className="flex items-center justify-between text-slate-300">
            <span className="text-emerald-400 font-semibold">HUMAN (CLASS 3)</span>
            <span>OVERRIDE TO SAFE • 0 DETERRENTS</span>
          </div>
          <div className="flex items-center justify-between text-slate-300">
            <span className="text-rose-400 font-semibold">1. LARGE MAMMAL</span>
            <span>SOUND + LIGHT + WATER (8–14s)</span>
          </div>
          <div className="flex items-center justify-between text-slate-300">
            <span className="text-amber-400 font-semibold">2. SMALL MAMMAL / PETS</span>
            <span>WATER + SOUND (5–9s)</span>
          </div>
          <div className="flex items-center justify-between text-slate-300">
            <span className="text-sky-400 font-semibold">3. BIRD</span>
            <span>SOUND + LIGHT (3–6s)</span>
          </div>
        </div>
      </div>
    </section>
  );
};
