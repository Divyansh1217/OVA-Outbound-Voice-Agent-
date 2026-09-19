export interface Biomarker {
  name: string;
  value: string;
  unit: string;
  reference_range: string;
  status: string;
}

export interface Patient {
  id: string;
  name: string;
  phone: string;
  notes: string;
  created_at: string;
  updated_at: string;
  biomarker_count?: number;
  biomarkers: Biomarker[];
  last_call_status?: string;
  calls?: CallSummary[];
}

export interface CallSummary {
  id: string;
  patient_id: string;
  status: string;
  preferred_time: string;
  room_name: string;
  created_at: string;
  outcome: string;
  appointment_booked: boolean;
  patient_name?: string;
  patient_phone?: string;
}

export interface TranscriptTurn {
  role: string;
  content: string;
  timestamp?: string;
}

export interface Evaluation {
  metric_name: string;
  score: number;
  reason: string;
  passed: boolean;
}

export interface Call extends CallSummary {
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  appointment_details: Record<string, unknown>;
  patient_agreed_not_booked: boolean;
  sentiment: string;
  key_topics: string[];
  summary: string;
  transcript: TranscriptTurn[];
  evaluations: Evaluation[];
  biomarkers: Biomarker[];
  patient: {
    id: string;
    name: string;
    phone: string;
    biomarkers: Biomarker[];
  };
}

export interface DashboardStats {
  patients: number;
  calls: number;
  in_progress: number;
  completed: number;
  appointments_booked: number;
  today: number;
}

export type StreamEvent =
  | {
      type: "snapshot";
      status: string;
      call: Partial<Call>;
      transcript: TranscriptTurn[];
      evaluations: Evaluation[];
    }
  | { type: "conversation"; role: string; content: string }
  | { type: "result"; result: Record<string, unknown>; status: string }
  | { type: "status"; status: string; message?: string };

export const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  dispatched: "Dispatched",
  accepted: "Accepted",
  in_progress: "In Progress",
  completed: "Completed",
  no_answer: "No Answer",
  busy: "Busy",
  declined: "Declined",
  error: "Error",
};