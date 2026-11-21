import React from 'react';
import {
  Shield,
  Camera,
  Radio,
  Volume2,
  VolumeX,
  Bell,
  BellOff,
  Square,
  Droplets,
  Zap,
  Wifi,
  QrCode,
  Loader2,
} from 'lucide-react';
import { DeterrentTelemetry } from '../types/sentinel';

interface TopTelemetryBarProps {
  telemetry: DeterrentTelemetry;
  isPrimaryHost?: boolean;
  isMuted: boolean;
  notificationPermission: NotificationPermission;
  activeQueueCount?: number;
  onToggleMute: () => void;
  onRequestNotifications: () => void;
  onOpenLiveCamera: () => void;
  onOpenQrModal: () => void;
  onStopAll: () => void;
}

export const TopTelemetryBar: React.FC<TopTelemetryBarProps> = ({
  telemetry,
  isPrimaryHost = true,
  isMuted,
  notificationPermission,
  activeQueueCount = 0,
  onToggleMute,
  onRequestNotifications,
  onOpenLiveCamera,
  onOpenQrModal,
  onStopAll,
}) => {
  const progressPct =
    telemetry.is_active && telemetry.duration_ms > 0
      ? Math.min(100, Math.max(0, (telemetry.remaining_ms / telemetry.duration_ms) * 100))
      : 0;

  const hasSound = telemetry.active_actuators.includes('SOUND');
  const hasWater = telemetry.active_actuators.includes('WATER');
  const hasLight = telemetry.active_actuators.includes('LIGHT');

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/90 bg-[#0b101b]/95 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-4 px-6 py-3.5">
        {/* Brand Title */}
        <div className="flex items-center gap-3.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-400">
            <Shield className="h-5 w-5" />
          </div>
          <div className="flex items-center gap-2.5">
            <h1 className="font-mono-tabular text-sm font-bold tracking-wide text-white">
              Wildlife Deterrent System | ECE 3332: Microcontroller Project Lab | Group 8
            </h1>
          </div>
        </div>

        {/* Center Live Actuator Telemetry Strip */}
        <div className="flex flex-1 items-center justify-center">
          <div className="flex w-full max-w-xl items-center justify-between gap-4 rounded-lg border border-slate-800 bg-[#070a12] px-4 py-2">
            {/* ESP32 Node Status */}
            <div className="flex items-center gap-2.5 border-r border-slate-800 pr-4">
              <span
                className={`h-2.5 w-2.5 rounded-full ${
                  telemetry.esp32_online
                    ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'
                    : 'bg-amber-400'
                }`}
              />
              <div className="leading-tight">
                <div className="flex items-center gap-1 font-mono-tabular text-[11px] font-semibold text-slate-300">
                  <Wifi className="h-3 w-3 text-sky-400" />
                  ESP32 SOFTAP
                </div>
                <div className="font-mono-tabular text-[10px] text-slate-500">
                  {telemetry.esp32_ip} {telemetry.esp32_online ? '(LINKED)' : '(STANDBY)'}
                </div>
              </div>
            </div>

            {/* Active Hardware Indicators */}
            <div className="flex flex-1 flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[11px] font-semibold transition ${
                      hasSound
                        ? 'border border-rose-500/50 bg-rose-500/20 text-rose-300'
                        : 'border border-slate-800 bg-slate-900/60 text-slate-500'
                    }`}
                  >
                    <Volume2 className="h-3 w-3" />
                    SOUND
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[11px] font-semibold transition ${
                      hasWater
                        ? 'border border-sky-500/50 bg-sky-500/20 text-sky-300'
                        : 'border border-slate-800 bg-slate-900/60 text-slate-500'
                    }`}
                  >
                    <Droplets className="h-3 w-3" />
                    WATER
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[11px] font-semibold transition ${
                      hasLight
                        ? 'border border-amber-500/50 bg-amber-500/20 text-amber-300'
                        : 'border border-slate-800 bg-slate-900/60 text-slate-500'
                    }`}
                  >
                    <Zap className="h-3 w-3" />
                    LIGHT
                  </span>
                </div>

                <span className="font-mono-tabular text-xs font-semibold text-slate-300">
                  {telemetry.is_active
                    ? `${(telemetry.remaining_ms / 1000).toFixed(1)}s / ${(
                        telemetry.duration_ms / 1000
                      ).toFixed(1)}s`
                    : 'IDLE'}
                </span>
              </div>

              {/* Countdown Progress Bar */}
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-900">
                <div
                  className={`h-full transition-all duration-150 ${
                    telemetry.is_active ? 'bg-rose-500' : 'bg-slate-800'
                  }`}
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>

            {/* Instant Hardware Stop Button */}
            <button
              type="button"
              onClick={onStopAll}
              className="flex items-center gap-1.5 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 font-mono-tabular text-xs font-semibold text-rose-400 transition hover:bg-rose-500 hover:text-white cursor-pointer"
              title="Immediately silence buzzer and halt all actuators"
            >
              <Square className="h-3.5 w-3.5 fill-current" />
              STOP
            </button>
          </div>
        </div>

        {/* Right Controls: Notifications, Audio & Full-Screen Live Camera Button */}
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onRequestNotifications}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 font-mono-tabular text-xs font-medium transition cursor-pointer ${
              notificationPermission === 'granted'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20'
            }`}
            title="Enable background desktop notifications when window is minimized"
          >
            {notificationPermission === 'granted' ? (
              <>
                <Bell className="h-3.5 w-3.5" />
                <span>ALERTS ON</span>
              </>
            ) : (
              <>
                <BellOff className="h-3.5 w-3.5" />
                <span>ENABLE OS ALERTS</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={onToggleMute}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-800 bg-slate-900/80 text-slate-300 transition hover:border-slate-700 hover:text-white cursor-pointer"
            title={isMuted ? 'Unmute dashboard alert chime' : 'Mute dashboard alert chime'}
            aria-label={isMuted ? 'Unmute dashboard alert chime' : 'Mute dashboard alert chime'}
          >
            {isMuted ? <VolumeX className="h-4 w-4 text-rose-400" /> : <Volume2 className="h-4 w-4 text-sky-400" />}
          </button>

          <button
            type="button"
            onClick={onOpenQrModal}
            className="flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 font-mono-tabular text-xs font-bold tracking-wide text-emerald-300 transition hover:bg-emerald-500/25 cursor-pointer"
            title="Open QR Code for Mobile Picture/Video Upload & Auto-Scan Queue"
          >
            <QrCode className="h-4 w-4 text-emerald-400" />
            <span>QR UPLOAD</span>
            {activeQueueCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/30 px-1.5 py-0.5 text-[10px] font-bold text-sky-200">
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
                {activeQueueCount}
              </span>
            )}
          </button>

          {isPrimaryHost ? (
            <button
              type="button"
              onClick={onOpenLiveCamera}
              className="flex items-center gap-2 rounded-lg border border-sky-400/40 bg-sky-500 px-4 py-2 font-mono-tabular text-xs font-bold tracking-wide text-slate-950 shadow-[0_0_20px_rgba(56,189,248,0.25)] transition hover:bg-sky-400 cursor-pointer"
            >
              <Camera className="h-4 w-4" />
              <span>LIVE CAMERA HUD</span>
              <Radio className="h-3.5 w-3.5 animate-pulse" />
            </button>
          ) : (
            <div
              className="flex items-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3.5 py-2 font-mono-tabular text-xs font-bold tracking-wide text-sky-300"
              title="External PC connected via ESP32 Wi-Fi network — Live Camera remains active on the primary device"
            >
              <Wifi className="h-3.5 w-3.5 text-sky-400" />
              <span>REMOTE UPLOAD NODE</span>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
