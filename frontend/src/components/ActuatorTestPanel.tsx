import React, { useState } from 'react';
import { Volume2, Droplets, Zap, Square, Sliders, ShieldAlert } from 'lucide-react';
import { ActuatorType, DeterrentTelemetry } from '../types/sentinel';

interface ActuatorTestPanelProps {
  telemetry: DeterrentTelemetry;
  onTestActuator: (actuator: ActuatorType, pattern: string) => Promise<void>;
  onStopAll: () => Promise<void>;
}

export const ActuatorTestPanel: React.FC<ActuatorTestPanelProps> = ({
  telemetry,
  onTestActuator,
  onStopAll,
}) => {
  const [selectedPattern, setSelectedPattern] = useState<'BIRD' | 'SMALL' | 'LARGE'>('LARGE');
  const [busyActuator, setBusyActuator] = useState<ActuatorType | null>(null);

  const handleTest = async (actuator: ActuatorType) => {
    setBusyActuator(actuator);
    try {
      await onTestActuator(actuator, selectedPattern);
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

      {/* Sound Pattern Tier Selector for Buzzer Testing */}
      <div className="mb-4">
        <label className="mb-1.5 block font-mono-tabular text-[11px] uppercase tracking-wider text-slate-400">
          Acoustic Buzzer Pattern & Randomized Duration Tier
        </label>
        <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-slate-800 bg-[#080c14] p-1">
          <button
            type="button"
            onClick={() => setSelectedPattern('BIRD')}
            className={`rounded-md px-2 py-1.5 font-mono-tabular text-[11px] font-semibold transition cursor-pointer ${
              selectedPattern === 'BIRD'
                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            BIRD (3–6s)
          </button>
          <button
            type="button"
            onClick={() => setSelectedPattern('SMALL')}
            className={`rounded-md px-2 py-1.5 font-mono-tabular text-[11px] font-semibold transition cursor-pointer ${
              selectedPattern === 'SMALL'
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            SMALL (5–9s)
          </button>
          <button
            type="button"
            onClick={() => setSelectedPattern('LARGE')}
            className={`rounded-md px-2 py-1.5 font-mono-tabular text-[11px] font-semibold transition cursor-pointer ${
              selectedPattern === 'LARGE'
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            LARGE (8–14s)
          </button>
        </div>
      </div>

      {/* 3 Independent Deterrent Trigger Buttons */}
      <div className="grid grid-cols-1 gap-2.5">
        <button
          type="button"
          onClick={() => handleTest('SOUND')}
          disabled={busyActuator !== null}
          className={`flex items-center justify-between rounded-lg border px-4 py-3 text-left transition cursor-pointer ${
            activeSound
              ? 'border-rose-500 bg-rose-500/20 text-white shadow-[0_0_15px_rgba(244,63,94,0.25)]'
              : 'border-slate-800 bg-[#11192a] text-slate-200 hover:border-rose-500/50 hover:bg-rose-500/10'
          }`}
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
                GPIO 17 Piezo • Pattern: {selectedPattern}
              </div>
            </div>
          </div>
          <span className="rounded border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
            {activeSound ? 'FIRING' : 'TRIGGER'}
          </span>
        </button>

        <button
          type="button"
          onClick={() => handleTest('WATER')}
          disabled={busyActuator !== null}
          className={`flex items-center justify-between rounded-lg border px-4 py-3 text-left transition cursor-pointer ${
            activeWater
              ? 'border-sky-500 bg-sky-500/20 text-white shadow-[0_0_15px_rgba(14,165,233,0.25)]'
              : 'border-slate-800 bg-[#11192a] text-slate-200 hover:border-sky-500/50 hover:bg-sky-500/10'
          }`}
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
                MOSFET Pump Valve • 5.0s Pulse
              </div>
            </div>
          </div>
          <span className="rounded border border-sky-500/40 bg-sky-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
            {activeWater ? 'ACTIVE' : 'TRIGGER'}
          </span>
        </button>

        <button
          type="button"
          onClick={() => handleTest('LIGHT')}
          disabled={busyActuator !== null}
          className={`flex items-center justify-between rounded-lg border px-4 py-3 text-left transition cursor-pointer ${
            activeLight
              ? 'border-amber-500 bg-amber-500/20 text-white shadow-[0_0_15px_rgba(245,158,11,0.25)]'
              : 'border-slate-800 bg-[#11192a] text-slate-200 hover:border-amber-500/50 hover:bg-amber-500/10'
          }`}
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
                3W COB LED Strobe • 5.0s Pulse
              </div>
            </div>
          </div>
          <span className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
            {activeLight ? 'STROBING' : 'TRIGGER'}
          </span>
        </button>
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
