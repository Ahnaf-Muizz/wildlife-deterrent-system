import React, { useRef, useState } from 'react';
import { Upload, FileImage, FileVideo, Loader2, Camera, CheckCircle2, AlertTriangle, QrCode } from 'lucide-react';
import { DeterrentEventRecord, QrQueueSnapshot } from '../types/sentinel';

interface MediaScannerPanelProps {
  isPrimaryHost?: boolean;
  onUploadMedia: (file: File, conf: number) => Promise<DeterrentEventRecord | null>;
  onOpenLiveCamera: () => void;
  onOpenQrModal: () => void;
  qrQueueSnapshot?: QrQueueSnapshot;
  onSelectEvent: (ev: DeterrentEventRecord) => void;
}

export const MediaScannerPanel: React.FC<MediaScannerPanelProps> = ({
  isPrimaryHost = true,
  onUploadMedia,
  onOpenLiveCamera,
  onOpenQrModal,
  qrQueueSnapshot,
  onSelectEvent,
}) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [confThreshold, setConfThreshold] = useState(0.5);
  const [dragActive, setDragActive] = useState(false);
  const [lastResult, setLastResult] = useState<DeterrentEventRecord | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    if (file) {
      setSelectedFile(file);
      setErrorMsg(null);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0] || null;
    if (file) {
      setSelectedFile(file);
      setErrorMsg(null);
    }
  };

  const handleScanSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile || isScanning) return;
    setIsScanning(true);
    setErrorMsg(null);
    try {
      const eventRecord = await onUploadMedia(selectedFile, confThreshold);
      if (eventRecord) {
        setLastResult(eventRecord);
        setSelectedFile(null);
        if (fileInputRef.current) {
          fileInputRef.current.value = '';
        }
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setIsScanning(false);
    }
  };

  const isVideoFile = selectedFile
    ? /\.(mp4|mov|avi|webm|mkv)$/i.test(selectedFile.name)
    : false;
  const isZipFile = selectedFile ? /\.zip$/i.test(selectedFile.name) : false;

  return (
    <section className="rounded-xl border border-slate-800/90 bg-[#0d1320] p-5 shadow-lg">
      <div className="mb-4 flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2">
          <Upload className="h-4 w-4 text-sky-400" />
          <h2 className="font-mono-tabular text-xs font-bold uppercase tracking-wider text-slate-200">
            Threat Media Scanner
          </h2>
        </div>
        <span className="font-mono-tabular text-[11px] text-slate-400">
          IMAGE & VIDEO AI
        </span>
      </div>

      {/* Mode Switch Buttons */}
      <div className="mb-3 flex flex-col gap-2">
        <div className={`grid gap-2 ${isPrimaryHost ? 'grid-cols-2' : 'grid-cols-1'}`}>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center justify-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/15 py-2.5 font-mono-tabular text-xs font-bold text-sky-300 transition hover:bg-sky-500/25 cursor-pointer"
          >
            <Upload className="h-3.5 w-3.5" />
            {isPrimaryHost ? 'UPLOAD MEDIA' : 'UPLOAD MEDIA ONLY (REMOTE PC)'}
          </button>
          {isPrimaryHost && (
            <button
              type="button"
              onClick={onOpenLiveCamera}
              className="flex items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-900 py-2.5 font-mono-tabular text-xs font-bold text-slate-200 transition hover:border-sky-400/50 hover:text-sky-300 cursor-pointer"
            >
              <Camera className="h-3.5 w-3.5 text-sky-400" />
              FULLSCREEN LIVE CAM
            </button>
          )}
        </div>

        {/* QR Code Mobile Upload & Queue Button */}
        <button
          type="button"
          onClick={onOpenQrModal}
          className="flex w-full items-center justify-between rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3.5 py-2.5 font-mono-tabular text-xs font-bold text-emerald-300 transition hover:border-emerald-400 hover:bg-emerald-500/20 cursor-pointer"
        >
          <span className="flex items-center gap-2">
            <QrCode className="h-4 w-4 text-emerald-400" />
            <span>QR CODE UPLOAD & AUTO-QUEUE</span>
          </span>
          {qrQueueSnapshot && qrQueueSnapshot.active_count > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/20 px-2 py-0.5 text-[10px] font-bold text-sky-300">
              <Loader2 className="h-3 w-3 animate-spin" />
              {qrQueueSnapshot.active_count} IN QUEUE
            </span>
          ) : (
            <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-[10px] text-emerald-300">
              MULTI-USER
            </span>
          )}
        </button>
      </div>

      <form onSubmit={handleScanSubmit}>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-5 text-center transition cursor-pointer ${
            dragActive
              ? 'border-sky-400 bg-sky-500/10'
              : selectedFile
              ? 'border-emerald-500/50 bg-emerald-500/5'
              : 'border-slate-800 bg-[#080c14] hover:border-slate-700'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/bmp,image/gif,video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska,video/x-m4v,video/3gpp,application/zip,.jpg,.jpeg,.png,.webp,.bmp,.jfif,.mp4,.mov,.avi,.webm,.mkv,.m4v,.3gp,.zip"
            onChange={handleFileChange}
            className="hidden"
          />

          {selectedFile ? (
            <div className="flex flex-col items-center gap-1.5">
              {isVideoFile ? (
                <FileVideo className="h-8 w-8 text-sky-400" />
              ) : (
                <FileImage className="h-8 w-8 text-emerald-400" />
              )}
              <div className="max-w-[260px] truncate font-mono-tabular text-xs font-bold text-white">
                {selectedFile.name}
              </div>
              <div className="font-mono-tabular text-[11px] text-slate-400">
                {(selectedFile.size / 1024).toFixed(1)} KB •{' '}
                {isZipFile ? 'BATCH ZIP IMAGE SCAN' : isVideoFile ? 'VIDEO STREAM SCAN' : 'HIGH-RES FRAME SCAN'}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1.5">
              <div className="flex items-center gap-2 text-slate-400">
                <FileImage className="h-6 w-6 text-sky-400" />
                <FileVideo className="h-6 w-6 text-amber-400" />
              </div>
              <div className="font-mono-tabular text-xs font-semibold text-slate-300">
                Drop Picture or Video file here
              </div>
              <div className="font-mono-tabular text-[11px] text-slate-500">
                Supports JPG, PNG, WEBP, MP4, MOV, AVI, WEBM, ZIP
              </div>
            </div>
          )}
        </div>

        {/* Confidence Sensitivity Control */}
        <div className="mt-3 flex items-center justify-between rounded-lg border border-slate-800/80 bg-[#080c14] px-3 py-2">
          <span className="font-mono-tabular text-[11px] text-slate-400">
            AI CONFIDENCE FLOOR
          </span>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min="0.50"
              max="0.90"
              step="0.05"
              value={confThreshold}
              onChange={(e) => setConfThreshold(parseFloat(e.target.value))}
              className="h-1.5 w-24 accent-sky-400 cursor-pointer"
            />
            <span className="w-10 text-right font-mono-tabular text-xs font-bold text-sky-400">
              {Math.round(confThreshold * 100)}%
            </span>
          </div>
        </div>

        {errorMsg && (
          <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 font-mono-tabular text-xs text-rose-300">
            {errorMsg}
          </div>
        )}

        <button
          type="submit"
          disabled={!selectedFile || isScanning}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-sky-500 py-3 font-mono-tabular text-xs font-bold uppercase tracking-wider text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
        >
          {isScanning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>
                {isZipFile
                  ? 'BATCH SCANNING ZIP IMAGES...'
                  : isVideoFile
                  ? 'ANALYZING VIDEO FRAMES & TIMELINE...'
                  : 'RUNNING DUAL-MODEL CASCADE...'}
              </span>
            </>
          ) : (
            <span>INITIATE THREAT SCAN</span>
          )}
        </button>
      </form>

      {/* Immediate Last Scan Banner */}
      {lastResult && (
        <button
          type="button"
          onClick={() => onSelectEvent(lastResult)}
          className="mt-4 w-full rounded-lg border border-slate-700/80 bg-[#080c14] p-3 text-left transition hover:border-sky-500/50 cursor-pointer"
        >
          <div className="flex items-center justify-between">
            <span className="font-mono-tabular text-[10px] uppercase tracking-wider text-slate-400">
              LATEST SCAN RESULT (CLICK TO INSPECT)
            </span>
            <span className="font-mono-tabular text-[11px] font-bold text-sky-400">
              {Math.round(lastResult.confidence * 100)}% CONF
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            {lastResult.primary_target === 'SAFE' || lastResult.primary_target === 'None' ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
            )}
            <div className="truncate font-mono-tabular text-xs font-bold text-white">
              {lastResult.primary_target === 'SAFE'
                ? 'SAFE ALERT (HUMAN VERIFIED)'
                : lastResult.primary_target === 'None'
                ? 'AREA CLEAR (NO TARGETS)'
                : `${lastResult.primary_target} — ${lastResult.action_taken}`}
            </div>
          </div>
        </button>
      )}
    </section>
  );
};
