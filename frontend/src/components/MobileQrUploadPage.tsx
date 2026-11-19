import React, { useCallback, useEffect, useId, useState } from 'react';
import {
  Shield,
  Upload,
  Camera,
  Loader2,
  CheckCircle2,
  Clock,
  AlertTriangle,
  ArrowLeft,
  Sparkles,
} from 'lucide-react';
import { QrQueueSnapshot } from '../types/sentinel';

const EMPTY_SNAPSHOT: QrQueueSnapshot = {
  queued_count: 0,
  processing_count: 0,
  active_count: 0,
  completed_count: 0,
  failed_count: 0,
  jobs: [],
  network: {
    ips: ['192.168.4.2'],
    port: 5002,
    primary_url: 'http://192.168.4.2:5002/mobile-upload',
    urls: ['http://192.168.4.2:5002/mobile-upload'],
  },
};

export const MobileQrUploadPage: React.FC = () => {
  const galleryInputId = useId();
  const cameraInputId = useId();
  const formHeadingId = useId();

  const [queueSnapshot, setQueueSnapshot] = useState<QrQueueSnapshot>(EMPTY_SNAPSHOT);
  const [isUploading, setIsUploading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchQueue = useCallback(async () => {
    try {
      const res = await fetch('/api/qr/queue');
      if (!res.ok) return;
      const data: QrQueueSnapshot = await res.json();
      setQueueSnapshot(data);
    } catch {
      // Ignore transient mobile polling errors
    }
  }, []);

  useEffect(() => {
    fetchQueue();
    const timer = window.setInterval(fetchQueue, 1500);
    return () => clearInterval(timer);
  }, [fetchQueue]);

  const enqueueFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setIsUploading(true);
    setErrorMsg(null);
    setStatusMessage(`Uploading ${files.length} file${files.length > 1 ? 's' : ''} to scan queue...`);

    const formData = new FormData();
    Array.from(files).forEach((f) => {
      formData.append('files', f);
    });
    formData.append('conf', '0.50');
    formData.append('uploader', 'Mobile QR Scanner');

    try {
      const res = await fetch('/api/qr/enqueue', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Upload failed');
      }
      if (data.queue) {
        setQueueSnapshot(data.queue);
      }
      setStatusMessage(
        `Queued ${data.enqueued_count} file${data.enqueued_count > 1 ? 's' : ''} for automatic AI scanning!`
      );
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Could not upload media');
      setStatusMessage(null);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#090d14] text-slate-100">
      {/* Top Mobile Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-[#0b101b]/95 px-4 py-3.5 backdrop-blur-md">
        <div className="mx-auto flex max-w-lg items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-400">
              <Shield className="h-5 w-5" />
            </div>
            <div>
              <h1 className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-white">
                Sentinel Mobile Uploader
              </h1>
              <p className="font-mono-tabular text-[10px] text-slate-400">
                Automatic Dual-Model YOLO Queue
              </p>
            </div>
          </div>

          <a
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono-tabular text-[11px] font-bold text-slate-200 transition hover:border-sky-400/50 hover:text-sky-300"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            DASHBOARD
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-lg space-y-5 px-4 py-5">
        {/* Upload Action Card */}
        <section className="rounded-2xl border border-slate-800 bg-[#0d1320] p-5 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <h2
              id={formHeadingId}
              className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-sky-300"
            >
              Instant Media Upload & Auto-Scan
            </h2>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2.5 py-0.5 font-mono-tabular text-[10px] font-bold text-emerald-300">
              <Sparkles className="h-3 w-3" />
              AUTO-QUEUE ON
            </span>
          </div>

          <p className="mb-4 font-mono-tabular text-xs text-slate-300">
            Select one or multiple photos/videos below. Each upload is automatically queued, scanned by the AI model, and added to the main dashboard history.
          </p>

          <form
            aria-labelledby={formHeadingId}
            action="/api/qr/enqueue"
            method="POST"
            encType="multipart/form-data"
            onSubmit={(e) => e.preventDefault()}
            className="space-y-3"
          >
            {/* Multi-File Gallery Input (Accessible visually-hidden) */}
            <input
              id={galleryInputId}
              name="files"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska,application/zip,.jpg,.jpeg,.png,.webp,.mp4,.mov,.avi,.webm,.mkv,.zip"
              onChange={(e) => {
                enqueueFiles(e.target.files);
                e.target.value = '';
              }}
              className="visually-hidden"
            />
            <label
              htmlFor={galleryInputId}
              style={{ minHeight: '54px', fontSize: 'max(1rem, 1em)' }}
              className="flex w-full items-center justify-center gap-2.5 rounded-xl bg-sky-500 px-4 py-3.5 font-mono-tabular font-bold text-slate-950 shadow-[0_0_24px_rgba(56,189,248,0.25)] transition hover:bg-sky-400 cursor-pointer"
            >
              {isUploading ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span>UPLOADING TO QUEUE...</span>
                </>
              ) : (
                <>
                  <Upload className="h-5 w-5" />
                  <span>UPLOAD PHOTOS / VIDEOS</span>
                </>
              )}
            </label>

            {/* Direct Mobile Camera Capture Input */}
            <input
              id={cameraInputId}
              name="camera_file"
              type="file"
              capture="environment"
              accept="image/*,video/*"
              onChange={(e) => {
                enqueueFiles(e.target.files);
                e.target.value = '';
              }}
              className="visually-hidden"
            />
            <label
              htmlFor={cameraInputId}
              style={{ minHeight: '52px', fontSize: 'max(1rem, 1em)' }}
              className="flex w-full items-center justify-center gap-2.5 rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 font-mono-tabular font-bold text-slate-100 transition hover:border-sky-400/50 hover:text-sky-300 cursor-pointer"
            >
              <Camera className="h-5 w-5 text-sky-400" />
              <span>TAKE CAMERA PHOTO / VIDEO</span>
            </label>
          </form>

          {/* Accessible Live Feedback Banner */}
          <div role="status" aria-live="polite" className="mt-3">
            {statusMessage && (
              <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-3 font-mono-tabular text-xs font-semibold text-emerald-300">
                {statusMessage}
              </div>
            )}
            {errorMsg && (
              <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 font-mono-tabular text-xs font-semibold text-rose-300">
                {errorMsg}
              </div>
            )}
          </div>
        </section>

        {/* Live Queue Status & Results Card */}
        <section className="rounded-2xl border border-slate-800 bg-[#0d1320] p-5 shadow-xl">
          <div className="mb-3 flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-white">
              Live Scan Queue ({queueSnapshot.jobs.length})
            </span>
            <div className="flex items-center gap-3 font-mono-tabular text-[11px]">
              <span className="text-amber-300">
                Queued: <strong>{queueSnapshot.queued_count}</strong>
              </span>
              <span className="text-sky-300">
                Scanning: <strong>{queueSnapshot.processing_count}</strong>
              </span>
              <span className="text-emerald-300">
                Done: <strong>{queueSnapshot.completed_count}</strong>
              </span>
            </div>
          </div>

          <div className="space-y-3">
            {queueSnapshot.jobs.length === 0 ? (
              <div className="rounded-xl border border-slate-800/80 bg-[#080c14] py-8 text-center font-mono-tabular text-xs text-slate-400">
                No uploads in queue yet. Tap above to upload photos or videos!
              </div>
            ) : (
              queueSnapshot.jobs.map((job) => {
                const ev = job.event;
                return (
                  <div
                    key={job.job_id}
                    className={`rounded-xl border p-3 ${
                      job.status === 'processing'
                        ? 'border-sky-500/50 bg-sky-500/10'
                        : job.status === 'queued'
                        ? 'border-amber-500/40 bg-amber-500/5'
                        : job.status === 'completed'
                        ? 'border-slate-800 bg-[#080c14]'
                        : 'border-rose-500/40 bg-rose-500/10'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate font-mono-tabular text-xs font-bold text-white">
                        {job.original_name}
                      </div>
                      {job.status === 'queued' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-amber-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
                          <Clock className="h-3 w-3" />
                          QUEUED #{job.position}
                        </span>
                      )}
                      {job.status === 'processing' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-sky-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          SCANNING...
                        </span>
                      )}
                      {job.status === 'completed' && ev && (
                        <span
                          className={`inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 font-mono-tabular text-[10px] font-bold ${
                            ev.primary_target === 'LARGE MAMMAL'
                              ? 'bg-rose-500/20 text-rose-300'
                              : ev.primary_target === 'SMALL MAMMAL'
                              ? 'bg-amber-500/20 text-amber-300'
                              : ev.primary_target === 'BIRD'
                              ? 'bg-sky-500/20 text-sky-300'
                              : 'bg-emerald-500/20 text-emerald-300'
                          }`}
                        >
                          <CheckCircle2 className="h-3 w-3" />
                          {ev.primary_target === 'None' ? 'CLEAR' : ev.primary_target} (
                          {Math.round(ev.confidence * 100)}%)
                        </span>
                      )}
                      {job.status === 'failed' && (
                        <span className="inline-flex shrink-0 items-center gap-1 rounded bg-rose-500/20 px-2 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
                          <AlertTriangle className="h-3 w-3" />
                          FAILED
                        </span>
                      )}
                    </div>

                    {ev && (
                      <div className="mt-2.5 flex items-center gap-3 border-t border-slate-800/80 pt-2.5">
                        <img
                          src={ev.thumbnail_url}
                          alt={ev.primary_target}
                          className="h-16 w-24 shrink-0 rounded-lg border border-slate-700 object-cover"
                        />
                        <div className="min-w-0 font-mono-tabular text-[11px]">
                          <div className="font-bold text-slate-200">
                            Event #{ev.id} • {ev.action_taken}
                          </div>
                          <div className="mt-0.5 text-slate-400">
                            {ev.resolution} • Saved to Dashboard History
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </main>
    </div>
  );
};
