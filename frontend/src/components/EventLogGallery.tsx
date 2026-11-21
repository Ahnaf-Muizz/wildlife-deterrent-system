import React from 'react';
import {
  Trash2,
  Film,
  Image as ImageIcon,
  Camera,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  AlertTriangle,
  Volume2,
  Droplets,
  Zap,
  Clock,
  Database,
} from 'lucide-react';
import { DeterrentEventRecord, PaginationInfo } from '../types/sentinel';

interface EventLogGalleryProps {
  events: DeterrentEventRecord[];
  pagination: PaginationInfo;
  targetFilter: string;
  mediaFilter: string;
  onTargetFilterChange: (target: string) => void;
  onMediaFilterChange: (media: string) => void;
  onPageChange: (page: number) => void;
  onSelectEvent: (ev: DeterrentEventRecord) => void;
  onDeleteEvent: (id: number) => Promise<void>;
  onClearAll: () => Promise<void>;
}

export const EventLogGallery: React.FC<EventLogGalleryProps> = ({
  events,
  pagination,
  targetFilter,
  mediaFilter,
  onTargetFilterChange,
  onMediaFilterChange,
  onPageChange,
  onSelectEvent,
  onDeleteEvent,
  onClearAll,
}) => {
  const targetTabs = [
    { key: 'ALL', label: 'ALL LOGS' },
    { key: 'LARGE MAMMAL', label: 'LARGE MAMMAL' },
    { key: 'SMALL MAMMAL', label: 'SMALL MAMMAL' },
    { key: 'BIRD', label: 'BIRD' },
    { key: 'SAFE', label: 'SAFE / HUMAN' },
  ];

  const mediaTabs = [
    { key: 'ALL', label: 'All Media' },
    { key: 'image', label: 'Pictures' },
    { key: 'video', label: 'Videos' },
    { key: 'live_snapshot', label: 'Live Captures' },
  ];

  const getTargetBadgeStyle = (target: string) => {
    switch (target) {
      case 'LARGE MAMMAL':
        return 'border-rose-500/40 bg-rose-500/15 text-rose-300';
      case 'SMALL MAMMAL':
        return 'border-amber-500/40 bg-amber-500/15 text-amber-300';
      case 'BIRD':
        return 'border-sky-500/40 bg-sky-500/15 text-sky-300';
      case 'SAFE':
        return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300';
      default:
        return 'border-slate-700 bg-slate-800/80 text-slate-300';
    }
  };

  return (
    <div className="flex flex-1 flex-col">
      {/* Header & Filter Bar */}
      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-slate-800/90 bg-[#0d1320] p-4 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
          <div className="flex items-center gap-2.5">
            <Database className="h-4 w-4 text-sky-400" />
            <h2 className="font-mono-tabular text-sm font-bold uppercase tracking-wider text-white">
              Persistent Deterrent Activity Archive
            </h2>
            <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono-tabular text-xs font-semibold text-slate-300">
              {pagination.total_items} RECORDS
            </span>
          </div>

          {pagination.total_items > 0 && (
            <button
              type="button"
              onClick={onClearAll}
              className="flex items-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 font-mono-tabular text-xs font-bold text-rose-400 transition hover:bg-rose-500 hover:text-white cursor-pointer"
            >
              <Trash2 className="h-3.5 w-3.5" />
              CLEAR ALL HISTORY
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {targetTabs.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => onTargetFilterChange(t.key)}
                className={`rounded-md px-3 py-1.5 font-mono-tabular text-xs font-semibold transition cursor-pointer ${
                  targetFilter === t.key
                    ? 'border border-sky-500/50 bg-sky-500/20 text-sky-300'
                    : 'border border-slate-800 bg-[#080c14] text-slate-400 hover:text-slate-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            {mediaTabs.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => onMediaFilterChange(m.key)}
                className={`rounded-md px-2.5 py-1 font-mono-tabular text-xs transition cursor-pointer ${
                  mediaFilter === m.key
                    ? 'border border-slate-600 bg-slate-800 text-white font-semibold'
                    : 'border border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Gallery Grid */}
      {events.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-slate-800/80 bg-[#0d1320]/60 p-16 text-center">
          <ShieldCheck className="mb-3 h-10 w-10 text-slate-600" />
          <div className="font-mono-tabular text-sm font-bold text-slate-300">
            No Deterrent Records Match Current Filter
          </div>
          <p className="mt-1 max-w-md font-mono-tabular text-xs text-slate-500">
            Upload pictures or videos on the left panel, or launch the Full-Page Live Camera HUD to log real-time detections.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {events.map((ev) => (
            <article
              key={ev.id}
              tabIndex={0}
              onClick={() => onSelectEvent(ev)}
              onKeyDown={(e) => {
                if ((e.target as HTMLElement).closest('button')) return;
                if (e.key === 'Enter') {
                  e.preventDefault();
                  onSelectEvent(ev);
                } else if (e.key === ' ') {
                  e.preventDefault();
                }
              }}
              onKeyUp={(e) => {
                if ((e.target as HTMLElement).closest('button')) return;
                if (e.key === ' ') {
                  e.preventDefault();
                  onSelectEvent(ev);
                }
              }}
              className="group relative flex flex-col overflow-hidden rounded-xl border border-slate-800/90 bg-[#0d1320] transition hover:-translate-y-0.5 hover:border-sky-500/50 hover:shadow-[0_8px_30px_rgba(0,0,0,0.45)] cursor-pointer focus-visible:outline-2 focus-visible:outline-sky-400"
            >
              {/* Media Thumbnail Preview */}
              <div className="relative h-52 w-full overflow-hidden border-b border-slate-800/80 bg-black">
                <img
                  src={ev.thumbnail_url}
                  alt={ev.primary_target}
                  loading="lazy"
                  className="h-full w-full object-contain transition duration-300 group-hover:scale-[1.02]"
                />

                {/* Media Type Pill */}
                <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5 rounded border border-slate-700/80 bg-slate-950/85 px-2 py-1 font-mono-tabular text-[10px] font-bold uppercase text-slate-200 backdrop-blur-sm">
                  {ev.media_type === 'video' ? (
                    <>
                      <Film className="h-3 w-3 text-amber-400" />
                      <span>VIDEO ({ev.video_duration_sec}s)</span>
                    </>
                  ) : ev.media_type === 'live_snapshot' ? (
                    <>
                      <Camera className="h-3 w-3 text-emerald-400" />
                      <span>LIVE CAPTURE</span>
                    </>
                  ) : (
                    <>
                      <ImageIcon className="h-3 w-3 text-sky-400" />
                      <span>PICTURE</span>
                    </>
                  )}
                </div>

                {/* Single Delete Button */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteEvent(ev.id);
                  }}
                  className="absolute top-2.5 right-2.5 flex h-7 w-7 items-center justify-center rounded border border-slate-700 bg-slate-950/85 text-slate-400 transition hover:border-rose-500 hover:bg-rose-500 hover:text-white cursor-pointer"
                  title="Delete event record"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>

                {/* Confidence Overlay Pill */}
                {ev.confidence > 0 && (
                  <div className="absolute bottom-2.5 right-2.5 rounded border border-slate-700/80 bg-slate-950/90 px-2 py-0.5 font-mono-tabular text-[11px] font-bold text-sky-400">
                    {(ev.confidence * 100).toFixed(1)}% CONF
                  </div>
                )}
              </div>

              {/* Card Telemetry Body */}
              <div className="flex flex-1 flex-col justify-between gap-3 p-4">
                <div>
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 font-mono-tabular text-[11px] text-slate-400">
                      <Clock className="h-3 w-3 text-slate-500" />
                      {ev.timestamp}
                    </span>
                    <span className="font-mono-tabular text-[10px] text-slate-500">
                      #{ev.id} • {ev.resolution}
                    </span>
                  </div>

                  {/* Target Classification Tag */}
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 font-mono-tabular text-xs font-bold ${getTargetBadgeStyle(
                        ev.primary_target
                      )}`}
                    >
                      {ev.primary_target === 'SAFE' || ev.primary_target === 'None' ? (
                        <ShieldCheck className="h-3.5 w-3.5" />
                      ) : (
                        <AlertTriangle className="h-3.5 w-3.5" />
                      )}
                      {ev.primary_target === 'SAFE'
                        ? 'SAFE (HUMAN VERIFIED)'
                        : ev.primary_target === 'None'
                        ? 'AREA CLEAR'
                        : ev.primary_target}
                    </span>

                    {ev.sound_duration_ms > 0 && (
                      <span className="font-mono-tabular text-[11px] font-semibold text-rose-400">
                        {(ev.sound_duration_ms / 1000).toFixed(1)}s AUDIO
                      </span>
                    )}
                  </div>
                </div>

                {/* Deployed Actuators Strip */}
                <div className="flex items-center justify-between border-t border-slate-800/80 pt-2.5">
                  <span className="font-mono-tabular text-[10px] uppercase tracking-wider text-slate-500">
                    DEPLOYED:
                  </span>
                  {ev.actuators.length === 0 ? (
                    <span className="font-mono-tabular text-[11px] font-semibold text-emerald-400">
                      0 DETERRENTS (SAFE)
                    </span>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      {ev.actuators.includes('SOUND') && (
                        <span className="inline-flex items-center gap-1 rounded border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold text-rose-300">
                          <Volume2 className="h-3 w-3" />
                          SOUND
                        </span>
                      )}
                      {ev.actuators.includes('WATER') && (
                        <span className="inline-flex items-center gap-1 rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold text-sky-300">
                          <Droplets className="h-3 w-3" />
                          WATER
                        </span>
                      )}
                      {ev.actuators.includes('LIGHT') && (
                        <span className="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 font-mono-tabular text-[10px] font-bold text-amber-300">
                          <Zap className="h-3 w-3" />
                          LIGHT
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Pagination Footer */}
      {pagination.total_pages > 1 && (
        <div className="mt-6 flex items-center justify-between rounded-xl border border-slate-800 bg-[#0d1320] px-4 py-3">
          <span className="font-mono-tabular text-xs text-slate-400">
            Page {pagination.page} of {pagination.total_pages} ({pagination.total_items} total events)
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!pagination.has_prev}
              onClick={() => onPageChange(pagination.page - 1)}
              className="flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono-tabular text-xs font-semibold text-slate-200 disabled:opacity-40 cursor-pointer"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Prev
            </button>
            <button
              type="button"
              disabled={!pagination.has_next}
              onClick={() => onPageChange(pagination.page + 1)}
              className="flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono-tabular text-xs font-semibold text-slate-200 disabled:opacity-40 cursor-pointer"
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
