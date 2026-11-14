import { ThreatCategory, ActuatorType } from '../types/sentinel';

class NotificationService {
  private audioCtx: AudioContext | null = null;
  private isMuted: boolean = false;
  private lastNotificationTime: Record<string, number> = {};
  private titleTimer: number | null = null;
  private defaultTitle = 'Wildlife Deterrent System | ECE 3332: Microcontroller Project Lab | Group 8';

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('focus', () => {
        this.clearTitleAlert();
      });
    }
  }

  public getPermissionState(): NotificationPermission {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      return 'denied';
    }
    return Notification.permission;
  }

  public async requestPermission(): Promise<NotificationPermission> {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      return 'denied';
    }
    if (Notification.permission === 'granted') {
      return 'granted';
    }
    try {
      const perm = await Notification.requestPermission();
      return perm;
    } catch {
      return 'denied';
    }
  }

  public setMuted(muted: boolean) {
    this.isMuted = muted;
  }

  public getMuted(): boolean {
    return this.isMuted;
  }

  private getAudioContext(): AudioContext | null {
    if (typeof window === 'undefined') return null;
    if (!this.audioCtx) {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        this.audioCtx = new AudioCtx();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume().catch(() => {});
    }
    return this.audioCtx;
  }

  /**
   * 100% Offline Web Audio API tactical chime synthesizer.
   * Distinct acoustic signatures for Threat vs. Human/SAFE detection.
   */
  public playAlertChime(target: ThreatCategory) {
    if (this.isMuted || target === 'None') return;
    const ctx = this.getAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;

    if (target === 'SAFE') {
      // Calm two-tone ascending verification chime for Human (SAFE)
      this.scheduleTone(ctx, 587.33, now, 0.09, 'sine', 0.12);       // D5
      this.scheduleTone(ctx, 880.0, now + 0.11, 0.16, 'sine', 0.12); // A5
    } else if (target === 'LARGE MAMMAL') {
      // High-priority 3-pulse tactical alert
      this.scheduleTone(ctx, 880, now, 0.08, 'sawtooth', 0.18);
      this.scheduleTone(ctx, 1174.66, now + 0.1, 0.08, 'sawtooth', 0.18);
      this.scheduleTone(ctx, 1396.91, now + 0.2, 0.16, 'sawtooth', 0.2);
    } else if (target === 'SMALL MAMMAL') {
      // Medium-priority dual pulse
      this.scheduleTone(ctx, 783.99, now, 0.09, 'triangle', 0.18);
      this.scheduleTone(ctx, 1046.5, now + 0.11, 0.14, 'triangle', 0.18);
    } else if (target === 'BIRD') {
      // Crisp high-frequency ping
      this.scheduleTone(ctx, 1046.5, now, 0.07, 'sine', 0.15);
      this.scheduleTone(ctx, 1318.51, now + 0.09, 0.12, 'sine', 0.15);
    }
  }

  private scheduleTone(
    ctx: AudioContext,
    freq: number,
    startTime: number,
    duration: number,
    type: OscillatorType,
    peakGain: number
  ) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, startTime);

    gain.gain.setValueAtTime(0.0001, startTime);
    gain.gain.exponentialRampToValueAtTime(peakGain, startTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(startTime);
    osc.stop(startTime + duration + 0.02);
  }

  /**
   * Triggers background OS Notification + Audio Chime + Window Title Badge
   * even when the user has minimized the browser or switched to another window.
   */
  public notifyDetection(
    target: ThreatCategory,
    confidence: number,
    actuators: ActuatorType[],
    soundDurationMs: number,
    force = false
  ) {
    if (target === 'None') return;

    const now = Date.now();
    const lastTime = this.lastNotificationTime[target] || 0;
    // Cooldown of 6 seconds per class during continuous live camera streaming unless forced
    if (!force && now - lastTime < 6000) {
      return;
    }
    this.lastNotificationTime[target] = now;

    this.playAlertChime(target);

    const confPct = `${Math.round(confidence * 100)}%`;
    const isSafe = target === 'SAFE';

    const title = isSafe
      ? `SAFE ALERT // Human Verified (${confPct})`
      : `THREAT DETECTED // ${target} (${confPct})`;

    const body = isSafe
      ? `Human presence confirmed. 0 deterrents engaged.`
      : `Deployed: ${actuators.join(' + ')} | Sound Duration: ${(soundDurationMs / 1000).toFixed(1)}s`;

    // Flash document title when window is unfocused or minimized
    if (typeof document !== 'undefined' && document.hidden) {
      this.flashDocumentTitle(isSafe ? `[SAFE: HUMAN ${confPct}]` : `[ALERT: ${target} ${confPct}]`);
    }

    // Native OS Desktop Notification (works when browser window is minimized or covered)
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
      try {
        const n = new Notification(title, {
          body,
          tag: `sentinel-${target}`,
          requireInteraction: false,
        });
        n.onclick = () => {
          window.focus();
          n.close();
        };
      } catch {
        // Ignore if notification fails in restricted context
      }
    }
  }

  private flashDocumentTitle(badgeText: string) {
    this.clearTitleAlert();
    let toggle = false;
    this.titleTimer = window.setInterval(() => {
      document.title = toggle ? this.defaultTitle : `${badgeText} — SENTINEL`;
      toggle = !toggle;
    }, 900);
  }

  public clearTitleAlert() {
    if (this.titleTimer !== null) {
      clearInterval(this.titleTimer);
      this.titleTimer = null;
    }
    if (typeof document !== 'undefined') {
      document.title = this.defaultTitle;
    }
  }
}

export const notificationService = new NotificationService();
