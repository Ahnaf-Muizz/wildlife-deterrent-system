export type ThreatCategory = 'LARGE MAMMAL' | 'SMALL MAMMAL' | 'BIRD' | 'SAFE' | 'None';
export type ActuatorType = 'SOUND' | 'WATER' | 'LIGHT';
export type MediaType = 'image' | 'video' | 'live_snapshot';

export interface DetectionBox {
  class_id: number;
  class_name: string;
  subtype: string;
  display_label: string;
  confidence: number;
  bbox: [number, number, number, number];
  bbox_norm: [number, number, number, number];
}

export interface VideoTimelineMarker {
  time_sec: number;
  frame: number;
  target: ThreatCategory;
  confidence: number;
  actuators: ActuatorType[];
  count: number;
}

export interface DeterrentEventRecord {
  id: number;
  filename: string;
  result_url: string;
  thumbnail_url: string;
  media_type: MediaType;
  timestamp: string;
  iso_timestamp: string;
  primary_target: ThreatCategory;
  action_taken: string;
  actuators: ActuatorType[];
  sound_duration_ms: number;
  confidence: number;
  resolution: string;
  file_size_kb: number;
  video_duration_sec: number;
  detections: DetectionBox[];
  timeline: VideoTimelineMarker[];
}

export interface DashboardMetrics {
  total_scans: number;
  large_mammals: number;
  small_mammals: number;
  birds: number;
  safe_humans: number;
  clear_scans: number;
  safe_total: number;
}

export interface PaginationInfo {
  page: number;
  per_page: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface DeterrentTelemetry {
  esp32_online: boolean;
  esp32_ip: string;
  is_active: boolean;
  last_target: string;
  active_actuators: ActuatorType[];
  duration_ms: number;
  remaining_ms: number;
}

export interface ModelStatusInfo {
  primary: string;
  secondary: string;
  device: string;
  offline_mode: boolean;
}

export interface DashboardResponse {
  metrics: DashboardMetrics;
  events: DeterrentEventRecord[];
  pagination: PaginationInfo;
  telemetry: DeterrentTelemetry;
  models: ModelStatusInfo;
}

export interface LiveDetectResponse {
  detections: DetectionBox[];
  primary_target: ThreatCategory;
  action_taken: string;
  actuators: ActuatorType[];
  sound_duration_ms: number;
  max_confidence: number;
  inference_ms: number;
  triggered_now: boolean;
  saved_event: DeterrentEventRecord | null;
  telemetry: DeterrentTelemetry;
}
