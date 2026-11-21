import React, { useEffect, useState, useCallback, useRef } from 'react';
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
  PaginationInfo,
  QrQueueSnapshot,
} from './types/sentinel';
import { TopTelemetryBar } from './components/TopTelemetryBar';
import { MediaScannerPanel } from './components/MediaScannerPanel';
import { ActuatorTestPanel } from './components/ActuatorTestPanel';
import { EventLogGallery } from './components/EventLogGallery';
import { EventDetailModal } from './components/EventDetailModal';
import { FullPageLiveCamera } from './components/FullPageLiveCamera';
import { QrUploadModal } from './components/QrUploadModal';
import { MobileQrUploadPage } from './components/MobileQrUploadPage';
import { notificationService } from './services/notificationService';

async function parseJsonSafely<T = Record<string, unknown>>(
  res: Response,
  fallbackError: string
): Promise<T> {
  const text = await res.text();
  let parsed: Record<string, unknown> = {};
  if (text) {
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      parsed = {};
    }
  }
  if (!res.ok) {
    const serverMsg =
      typeof parsed.error === 'string' && parsed.error.trim().length > 0
        ? parsed.error
        : `${fallbackError} (HTTP ${res.status})`;
    throw new Error(serverMsg);
  }
  return parsed as T;
}

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

  const [targetFilter, setTargetFilter] = useState<string>('ALL');
  const [mediaFilter, setMediaFilter] = useState<string>('ALL');
  const [page, setPage] = useState<number>(1);
  const [actionError, setActionError] = useState<string | null>(null);

  const [selectedEvent, setSelectedEvent] = useState<DeterrentEventRecord | null>(null);
  const [autoSyncVideoHardware, setAutoSyncVideoHardware] = useState<boolean>(false);
  const [isLiveCameraOpen, setIsLiveCameraOpen] = useState<boolean>(false);
  const [isQrModalOpen, setIsQrModalOpen] = useState<boolean>(false);
  const [qrQueueSnapshot, setQrQueueSnapshot] = useState<QrQueueSnapshot>({
    queued_count: 0,
    processing_count: 0,
    active_count: 0,
    completed_count: 0,
    failed_count: 0,
    jobs: [],
    network: {
      ips: [],
      on_esp32_ap: false,
      port: 5002,
      primary_url: '',
      urls: [],
    },
  });
  const lastCompletedCountRef = useRef<number | null>(null);
  const dashboardAbortRef = useRef<AbortController | null>(null);
  const queueFetchInFlightRef = useRef<boolean>(false);
  const statusFetchInFlightRef = useRef<boolean>(false);

  const isMobileQrRoute =
    typeof window !== 'undefined' &&
    (window.location.pathname.startsWith('/qr-upload') ||
      window.location.pathname.startsWith('/mobile-upload') ||
      new URLSearchParams(window.location.search).get('mode') === 'mobile');

  // Live Camera stays exclusively on the Primary Host (127.0.0.1 / localhost);
  // External PCs on the ESP32 Wi-Fi network (192.168.4.x) operate in Remote Upload Mode.
  const isPrimaryHost =
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1' ||
      window.location.hostname === '::1' ||
      new URLSearchParams(window.location.search).get('host') === '1');

  const [isMuted, setIsMuted] = useState<boolean>(notificationService.getMuted());
  const [notifPerm, setNotifPerm] = useState<NotificationPermission>(
    notificationService.getPermissionState()
  );

  const fetchDashboard = useCallback(async () => {
    dashboardAbortRef.current?.abort();
    const controller = new AbortController();
    dashboardAbortRef.current = controller;
    try {
      const params = new URLSearchParams({
        target: targetFilter,
        media_type: mediaFilter,
        page: String(page),
        per_page: '24',
      });
      const res = await fetch(`/api/dashboard?${params.toString()}`, {
        signal: controller.signal,
      });
      if (!res.ok) return;
      const data: DashboardResponse = await res.json();
      setMetrics(data.metrics);
      setEvents(data.events);
      setPagination(data.pagination);
      setTelemetry(data.telemetry);
    } catch {
      // Ignore aborted or transient network errors
    } finally {
      if (dashboardAbortRef.current === controller) {
        dashboardAbortRef.current = null;
      }
    }
  }, [targetFilter, mediaFilter, page]);

  const fetchQrQueue = useCallback(async () => {
    if (queueFetchInFlightRef.current) return;
    queueFetchInFlightRef.current = true;
    try {
      const res = await fetch('/api/qr/queue');
      if (!res.ok) return;
      const snap: QrQueueSnapshot = await res.json();
      setQrQueueSnapshot(snap);
      if (
        lastCompletedCountRef.current !== null &&
        snap.completed_count > lastCompletedCountRef.current
      ) {
        void fetchDashboard();
      }
      lastCompletedCountRef.current = snap.completed_count;
    } catch {
      // Ignore transient network errors
    } finally {
      queueFetchInFlightRef.current = false;
    }
  }, [fetchDashboard]);

  useEffect(() => {
    if (isMobileQrRoute) return;
    void fetchDashboard();
    void fetchQrQueue();
    const syncTimer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      void fetchDashboard();
      void fetchQrQueue();
    }, 8000);
    return () => {
      clearInterval(syncTimer);
      dashboardAbortRef.current?.abort();
    };
  }, [fetchDashboard, fetchQrQueue, isMobileQrRoute]);

  const hasActiveQueue = qrQueueSnapshot.active_count > 0;
  useEffect(() => {
    if (isMobileQrRoute) return;
    if (!isQrModalOpen && !hasActiveQueue) return;
    if (isQrModalOpen) {
      void fetchQrQueue();
    }
    const fastTimer = window.setInterval(() => {
      void fetchQrQueue();
    }, 1200);
    return () => clearInterval(fastTimer);
  }, [isQrModalOpen, hasActiveQueue, fetchQrQueue, isMobileQrRoute]);

  // Smooth telemetry countdown polling while actuators are active + periodic ESP32 status check
  useEffect(() => {
    if (isMobileQrRoute) return;
    const intervalMs = telemetry.is_active ? 200 : 3000;
    const timer = window.setInterval(async () => {
      if (statusFetchInFlightRef.current) return;
      statusFetchInFlightRef.current = true;
      try {
        const res = await fetch('/api/esp32/status');
        if (res.ok) {
          const t: DeterrentTelemetry = await res.json();
          setTelemetry(t);
        }
      } catch {
        // Ignore
      } finally {
        statusFetchInFlightRef.current = false;
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }, [telemetry.is_active, isMobileQrRoute]);

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
    const data = await parseJsonSafely<{
      event: DeterrentEventRecord;
      telemetry?: DeterrentTelemetry;
    }>(res, 'Upload scan failed');

    const ev: DeterrentEventRecord = data.event;
    if (data.telemetry) {
      setTelemetry(data.telemetry);
    }

    if (ev.media_type === 'video') {
      setAutoSyncVideoHardware(true);
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

  const handleTestActuator = async (
    actuator: ActuatorType,
    pattern: string,
    durationMs?: number
  ) => {
    try {
      setActionError(null);
      const res = await fetch('/api/deterrent/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actuator,
          pattern,
          duration_ms: durationMs && durationMs > 0 ? durationMs : 0,
        }),
      });
      const data = await parseJsonSafely<{ telemetry?: DeterrentTelemetry }>(
        res,
        'Hardware test trigger failed'
      );
      if (data.telemetry) {
        setTelemetry(data.telemetry);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Hardware test trigger failed');
    }
  };

  const handleStopAll = async () => {
    try {
      setActionError(null);
      const res = await fetch('/api/deterrent/stop', { method: 'POST' });
      const data = await parseJsonSafely<{ telemetry?: DeterrentTelemetry }>(
        res,
        'Emergency stop command failed'
      );
      if (data.telemetry) {
        setTelemetry(data.telemetry);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Emergency stop command failed');
    }
  };

  const handleDeleteEvent = async (id: number) => {
    try {
      setActionError(null);
      const res = await fetch(`/api/events/${id}`, { method: 'DELETE' });
      await parseJsonSafely(res, 'Failed to delete event record');
      await fetchDashboard();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete event record');
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Permanently delete all logged pictures, videos, and deterrent records?')) {
      return;
    }
    try {
      setActionError(null);
      const res = await fetch('/api/events/clear', { method: 'POST' });
      await parseJsonSafely(res, 'Failed to clear event history');
      setPage(1);
      await fetchDashboard();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to clear event history');
    }
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

  const handleEnqueueFiles = async (files: FileList | File[], uploader = 'Dashboard Queue') => {
    const formData = new FormData();
    Array.from(files).forEach((f) => {
      formData.append('files', f);
    });
    formData.append('conf', '0.50');
    formData.append('uploader', uploader);

    const res = await fetch('/api/qr/enqueue', {
      method: 'POST',
      body: formData,
    });
    const data = await parseJsonSafely<{ queue?: QrQueueSnapshot }>(
      res,
      'Failed to enqueue files'
    );
    if (data.queue) {
      setQrQueueSnapshot(data.queue);
    }
  };

  const handleClearCompletedQueue = async () => {
    try {
      const res = await fetch('/api/qr/queue/clear', { method: 'POST' });
      const snap = await parseJsonSafely<QrQueueSnapshot>(res, 'Failed to clear queue');
      setQrQueueSnapshot(snap);
      lastCompletedCountRef.current = snap.completed_count;
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to clear queue');
    }
  };

  if (isMobileQrRoute) {
    return <MobileQrUploadPage />;
  }

  const openArchivedEvent = (ev: DeterrentEventRecord) => {
    setAutoSyncVideoHardware(false);
    setSelectedEvent(ev);
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#090d14] text-slate-100">
      {/* Top Command & Telemetry Header */}
      <TopTelemetryBar
        telemetry={telemetry}
        isPrimaryHost={isPrimaryHost}
        isMuted={isMuted}
        notificationPermission={notifPerm}
        activeQueueCount={qrQueueSnapshot.active_count}
        onToggleMute={handleToggleMute}
        onRequestNotifications={handleRequestNotifications}
        onOpenLiveCamera={() => {
          if (isPrimaryHost) setIsLiveCameraOpen(true);
        }}
        onOpenQrModal={() => setIsQrModalOpen(true)}
        onStopAll={handleStopAll}
      />

      {/* Main Content Container */}
      <main className="mx-auto flex w-full max-w-[1680px] flex-1 flex-col gap-6 px-6 py-6">
        {actionError && (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 font-mono-tabular text-xs text-rose-300"
          >
            <span>{actionError}</span>
            <button
              type="button"
              onClick={() => setActionError(null)}
              className="rounded border border-rose-500/40 px-2 py-0.5 text-[10px] font-bold hover:bg-rose-500/20 cursor-pointer"
            >
              DISMISS
            </button>
          </div>
        )}

        {/* 5-Card Incursion Telemetry Strip (Semantic Native Buttons) */}
        <section className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <button
            type="button"
            onClick={() => {
              setTargetFilter('ALL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 text-left transition cursor-pointer ${
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
          </button>

          <button
            type="button"
            onClick={() => {
              setTargetFilter('LARGE MAMMAL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 text-left transition cursor-pointer ${
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
          </button>

          <button
            type="button"
            onClick={() => {
              setTargetFilter('SMALL MAMMAL');
              setPage(1);
            }}
            className={`rounded-xl border p-4 text-left transition cursor-pointer ${
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
          </button>

          <button
            type="button"
            onClick={() => {
              setTargetFilter('BIRD');
              setPage(1);
            }}
            className={`rounded-xl border p-4 text-left transition cursor-pointer ${
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
          </button>

          <button
            type="button"
            onClick={() => {
              setTargetFilter('SAFE');
              setPage(1);
            }}
            className={`rounded-xl border p-4 text-left transition cursor-pointer ${
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
          </button>
        </section>

        {/* Two-Column Tactical Workspace */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left Control Column (4 cols) */}
          <div className="flex flex-col gap-6 lg:col-span-4 xl:col-span-3">
            <MediaScannerPanel
              isPrimaryHost={isPrimaryHost}
              onUploadMedia={handleUploadMedia}
              onOpenLiveCamera={() => {
                if (isPrimaryHost) setIsLiveCameraOpen(true);
              }}
              onOpenQrModal={() => setIsQrModalOpen(true)}
              qrQueueSnapshot={qrQueueSnapshot}
              onSelectEvent={openArchivedEvent}
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
              onSelectEvent={openArchivedEvent}
              onDeleteEvent={handleDeleteEvent}
              onClearAll={handleClearAll}
            />
          </div>
        </div>
      </main>

      {/* Full-Screen Live Camera Optical HUD Modal (Primary Host Only) */}
      {isPrimaryHost && (
        <FullPageLiveCamera
          isOpen={isLiveCameraOpen}
          onClose={() => setIsLiveCameraOpen(false)}
          telemetry={telemetry}
          onTelemetryUpdate={(t) => setTelemetry(t)}
          onSnapshotSaved={() => void fetchDashboard()}
          onStopAll={handleStopAll}
        />
      )}

      {/* Event Detail & Video Timeline Inspection Modal */}
      <EventDetailModal
        event={selectedEvent}
        autoSyncHardware={autoSyncVideoHardware}
        onTelemetryUpdate={(t) => setTelemetry(t)}
        onClose={() => {
          setSelectedEvent(null);
          setAutoSyncVideoHardware(false);
        }}
        onDelete={handleDeleteEvent}
      />

      {/* QR Code Mobile Upload & FIFO Automatic Scan Queue Modal */}
      <QrUploadModal
        isOpen={isQrModalOpen}
        onClose={() => setIsQrModalOpen(false)}
        queueSnapshot={qrQueueSnapshot}
        onEnqueueFiles={handleEnqueueFiles}
        onClearCompleted={handleClearCompletedQueue}
        onSelectEvent={openArchivedEvent}
      />
    </div>
  );
};
