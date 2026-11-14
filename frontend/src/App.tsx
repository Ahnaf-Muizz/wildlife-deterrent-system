import React, { useEffect, useState, useCallback } from 'react';
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  Bird,
  ShieldCheck,
} from 'lucide-react';
import {
  ActuatorType,
  DashboardMetrics,
  DashboardResponse,
  DeterrentEventRecord,
  DeterrentTelemetry,
  ModelStatusInfo,
  PaginationInfo,
} from './types/sentinel';
import { TopTelemetryBar } from './components/TopTelemetryBar';
import { MediaScannerPanel } from './components/MediaScannerPanel';
import { ActuatorTestPanel } from './components/ActuatorTestPanel';
import { EventLogGallery } from './components/EventLogGallery';
import { EventDetailModal } from './components/EventDetailModal';
import { FullPageLiveCamera } from './components/FullPageLiveCamera';
import { notificationService } from './services/notificationService';

export const App: React.FC = () => {
  const [metrics, setMetrics] = useState<DashboardMetrics>({
    total_scans: 0,
    large_mammals: 0,
    small_mammals: 0,
    birds: 0,
    safe_humans: 0,
    clear_scans: 0,
    safe_total: 0,
  });

  const [events, setEvents] = useState<DeterrentEventRecord[]>([]);
  const [pagination, setPagination] = useState<PaginationInfo>({
    page: 1,
    per_page: 24,
    total_items: 0,
    total_pages: 1,
    has_next: false,
    has_prev: false,
  });

  const [telemetry, setTelemetry] = useState<DeterrentTelemetry>({
    esp32_online: false,
    esp32_ip: '192.168.4.1',
    is_active: false,
    last_target: 'NONE',
    active_actuators: [],
    duration_ms: 0,
    remaining_ms: 0,
  });

  const [models, setModels] = useState<ModelStatusInfo>({
    primary: 'best.pt',
    secondary: 'yolo11n.pt (COCO Offline Cascade)',
    device: 'GPU / CPU',
    offline_mode: true,
  });

  const [targetFilter, setTargetFilter] = useState<string>('ALL');
  const [mediaFilter, setMediaFilter] = useState<string>('ALL');
  const [page, setPage] = useState<number>(1);

  const [selectedEvent, setSelectedEvent] = useState<DeterrentEventRecord | null>(null);
  const [isLiveCameraOpen, setIsLiveCameraOpen] = useState<boolean>(false);

  const [isMuted, setIsMuted] = useState<boolean>(notificationService.getMuted());
  const [notifPerm, setNotifPerm] = useState<NotificationPermission>(
    notificationService.getPermissionState()
  );

  const fetchDashboard = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        target: targetFilter,
        media_type: mediaFilter,
        page: String(page),
        per_page: '24',
      });
      const res = await fetch(`/api/dashboard?${params.toString()}`);
      if (!res.ok) return;
      const data: DashboardResponse = await res.json();
      setMetrics(data.metrics);
      setEvents(data.events);
      setPagination(data.pagination);
      setTelemetry(data.telemetry);
      setModels(data.models);
    } catch {
      // Ignore transient network errors
    }
  }, [targetFilter, mediaFilter, page]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  // Smooth telemetry countdown polling while actuators are active + periodic ESP32 status check
  useEffect(() => {
    const intervalMs = telemetry.is_active ? 200 : 3000;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch('/api/esp32/status');
        if (res.ok) {
          const t: DeterrentTelemetry = await res.json();
          setTelemetry(t);
        }
      } catch {
        // Ignore
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }, [telemetry.is_active]);

  const handleUploadMedia = async (
    file: File,
    conf: number
  ): Promise<DeterrentEventRecord | null> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('conf', String(conf));
    formData.append('source_mode', 'upload');

    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Upload scan failed');
    }

    const ev: DeterrentEventRecord = data.event;
    if (data.telemetry) {
      setTelemetry(data.telemetry);
    }

    if (ev.media_type === 'video') {
      setSelectedEvent(ev);
    } else if (ev.primary_target !== 'None') {
      notificationService.notifyDetection(
        ev.primary_target,
        ev.confidence,
        ev.actuators,
        ev.sound_duration_ms,
        true
      );
    }

    await fetchDashboard();
    return ev;
  };

  const handleTestActuator = async (actuator: ActuatorType, pattern: string) => {
    const res = await fetch('/api/deterrent/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actuator, pattern }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.telemetry) {
        setTelemetry(data.telemetry);
      }
    }
  };

  const handleStopAll = async () => {
    const res = await fetch('/api/deterrent/stop', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      if (data.telemetry) {
        setTelemetry(data.telemetry);
      }
    }
  };

  const handleDeleteEvent = async (id: number) => {
    await fetch(`/api/events/${id}`, { method: 'DELETE' });
    await fetchDashboard();
  };

  const handleClearAll = async () => {
    if (!window.confirm('Permanently delete all logged pictures, videos, and deterrent records?')) {
      return;
    }
    await fetch('/api/events/clear', { method: 'POST' });
    setPage(1);
    await fetchDashboard();
  };

  const handleToggleMute = () => {
    const next = !isMuted;
    notificationService.setMuted(next);
    setIsMuted(next);
  };

  const handleRequestNotifications = async () => {
    const perm = await notificationService.requestPermission();
    setNotifPerm(perm);
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#090d14] text-slate-100">
      {/* Top Command & Telemetry Header */}
      <TopTelemetryBar
        telemetry={telemetry}
        models={models}
        isMuted={isMuted}
        notificationPermission={notifPerm}
        onToggleMute={handleToggleMute}
        onRequestNotifications={handleRequestNotifications}
        onOpenLiveCamera={() => setIsLiveCameraOpen(true)}
        onStopAll={handleStopAll}
      />

      {/* Main Content Container */}
      <main className="mx-auto flex w-full max-w-[1680px] flex-1 flex-col gap-6 px-6 py-6">
        {/* 5-Card Incursion Telemetry Strip (Preserving & Enhancing Existing Metrics) */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <div
            onClick={() => {
              setTargetFilter('ALL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 transition cursor-pointer ${
              targetFilter === 'ALL'
                ? 'border-sky-500/50 bg-[#101829]'
                : 'border-slate-800/90 bg-[#0d1320] hover:border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider">
                TOTAL SCANS
              </span>
              <Activity className="h-4 w-4 text-sky-400" />
            </div>
            <div className="mt-2 font-mono-tabular text-2xl font-bold text-white">
              {metrics.total_scans}
            </div>
            <div className="mt-1 font-mono-tabular text-[11px] text-slate-500">
              Persistent SQLite WAL Archive
            </div>
          </div>

          <div
            onClick={() => {
              setTargetFilter('LARGE MAMMAL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 transition cursor-pointer ${
              targetFilter === 'LARGE MAMMAL'
                ? 'border-rose-500/60 bg-rose-500/10'
                : 'border-slate-800/90 bg-[#0d1320] hover:border-rose-500/40'
            }`}
          >
            <div className="flex items-center justify-between text-rose-400">
              <span className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider">
                LARGE MAMMALS
              </span>
              <AlertOctagon className="h-4 w-4" />
            </div>
            <div className="mt-2 font-mono-tabular text-2xl font-bold text-rose-400">
              {metrics.large_mammals}
            </div>
            <div className="mt-1 font-mono-tabular text-[11px] text-slate-400">
              Sound + Light + Water (8–14s)
            </div>
          </div>

          <div
            onClick={() => {
              setTargetFilter('SMALL MAMMAL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 transition cursor-pointer ${
              targetFilter === 'SMALL MAMMAL'
                ? 'border-amber-500/60 bg-amber-500/10'
                : 'border-slate-800/90 bg-[#0d1320] hover:border-amber-500/40'
            }`}
          >
            <div className="flex items-center justify-between text-amber-400">
              <span className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider">
                SMALL MAMMALS & PETS
              </span>
              <AlertTriangle className="h-4 w-4" />
            </div>
            <div className="mt-2 font-mono-tabular text-2xl font-bold text-amber-400">
              {metrics.small_mammals}
            </div>
            <div className="mt-1 font-mono-tabular text-[11px] text-slate-400">
              Water + Sound (5–9s)
            </div>
          </div>

          <div
            onClick={() => {
              setTargetFilter('BIRD');
              setPage(1);
            }}
            className={`rounded-xl border p-4 transition cursor-pointer ${
              targetFilter === 'BIRD'
                ? 'border-sky-500/60 bg-sky-500/10'
                : 'border-slate-800/90 bg-[#0d1320] hover:border-sky-500/40'
            }`}
          >
            <div className="flex items-center justify-between text-sky-400">
              <span className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider">
                BIRDS
              </span>
              <Bird className="h-4 w-4" />
            </div>
            <div className="mt-2 font-mono-tabular text-2xl font-bold text-sky-400">
              {metrics.birds}
            </div>
            <div className="mt-1 font-mono-tabular text-[11px] text-slate-400">
              Sound + Light (3–6s)
            </div>
          </div>

          <div
            onClick={() => {
              setTargetFilter('SAFE');
              setPage(1);
            }}
            className={`rounded-xl border p-4 transition cursor-pointer ${
              targetFilter === 'SAFE'
                ? 'border-emerald-500/60 bg-emerald-500/10'
                : 'border-slate-800/90 bg-[#0d1320] hover:border-emerald-500/40'
            }`}
          >
            <div className="flex items-center justify-between text-emerald-400">
              <span className="font-mono-tabular text-[11px] font-bold uppercase tracking-wider">
                HUMAN / SAFE
              </span>
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="mt-2 font-mono-tabular text-2xl font-bold text-emerald-400">
              {metrics.safe_total}
            </div>
            <div className="mt-1 font-mono-tabular text-[11px] text-slate-400">
              {metrics.safe_humans} Humans • {metrics.clear_scans} Clear (0 Triggers)
            </div>
          </div>
        </section>

        {/* Two-Column Tactical Workspace */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left Control Column (4 cols) */}
          <div className="flex flex-col gap-6 lg:col-span-4 xl:col-span-3">
            <MediaScannerPanel
              onUploadMedia={handleUploadMedia}
              onOpenLiveCamera={() => setIsLiveCameraOpen(true)}
              onSelectEvent={(ev) => setSelectedEvent(ev)}
            />

            <ActuatorTestPanel
              telemetry={telemetry}
              onTestActuator={handleTestActuator}
              onStopAll={handleStopAll}
            />
          </div>

          {/* Right Archive & Analytics Column (8-9 cols) */}
          <div className="flex flex-col lg:col-span-8 xl:col-span-9">
            <EventLogGallery
              events={events}
              pagination={pagination}
              targetFilter={targetFilter}
              mediaFilter={mediaFilter}
              onTargetFilterChange={(t) => {
                setTargetFilter(t);
                setPage(1);
              }}
              onMediaFilterChange={(m) => {
                setMediaFilter(m);
                setPage(1);
              }}
              onPageChange={(p) => setPage(p)}
              onSelectEvent={(ev) => setSelectedEvent(ev)}
              onDeleteEvent={handleDeleteEvent}
              onClearAll={handleClearAll}
            />
          </div>
        </div>
      </main>

      {/* Full-Screen Live Camera Optical HUD Modal */}
      <FullPageLiveCamera
        isOpen={isLiveCameraOpen}
        onClose={() => setIsLiveCameraOpen(false)}
        telemetry={telemetry}
        onTelemetryUpdate={(t) => setTelemetry(t)}
        onSnapshotSaved={() => fetchDashboard()}
        onStopAll={handleStopAll}
      />

      {/* Event Detail & Video Timeline Inspection Modal */}
      <EventDetailModal
        event={selectedEvent}
        telemetry={telemetry}
        onTelemetryUpdate={(t) => setTelemetry(t)}
        onClose={() => setSelectedEvent(null)}
        onDelete={handleDeleteEvent}
      />
    </div>
  );
};
