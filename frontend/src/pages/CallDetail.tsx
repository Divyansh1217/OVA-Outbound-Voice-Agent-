import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import BiomarkerTable from "../components/BiomarkerTable";
import StatusBadge from "../components/StatusBadge";
import { callService } from "../services/calls";
import { subscribeToCall } from "../services/stream";
import type { Call, Evaluation, StreamEvent, TranscriptTurn } from "../types";
import { formatDate, formatDuration } from "../utils";

const TERMINAL = new Set(["completed", "error", "no_answer", "busy", "declined"]);

interface ResultPayload {
  status?: string;
  outcome?: string;
  duration_seconds?: number;
  appointment_booked?: boolean;
  appointment_details?: Record<string, string>;
  patient_agreed_not_booked?: boolean;
  sentiment?: string;
  key_topics?: string[];
  summary?: string;
  transcript?: TranscriptTurn[];
  evaluations?: Evaluation[];
}

export default function CallDetail() {
  const { id } = useParams();
  const [call, setCall] = useState<Call | null>(null);
  const [error, setError] = useState("");

  const [liveStatus, setLiveStatus] = useState("");
  const [liveTranscript, setLiveTranscript] = useState<TranscriptTurn[]>([]);
  const [liveEval, setLiveEval] = useState<Evaluation[]>([]);
  const [liveMeta, setLiveMeta] = useState<Partial<Call>>({});

  const transcriptRef = useRef<HTMLDivElement>(null);
  const lastMsg = useRef<{ role: string; content: string } | null>(null);

  const load = () => {
    if (!id) return;
    callService
      .get(id)
      .then((c) => {
        setCall(c);
        setLiveStatus(c.status);
        setLiveTranscript(c.transcript);
        setLiveEval(c.evaluations);
        lastMsg.current =
          c.transcript.length > 0
            ? c.transcript[c.transcript.length - 1]
            : null;
      })
      .catch((e) => setError(e.message));
  };

  useEffect(load, [id]);

  useEffect(() => {
    if (!id) return;
    const unsubscribe = subscribeToCall(id, (event: StreamEvent) => {
      if (event.type === "snapshot") {
        setLiveStatus(event.status);
        if (event.transcript?.length) setLiveTranscript(event.transcript);
        setLiveEval(event.evaluations ?? []);
      } else if (event.type === "conversation") {
        setLiveTranscript((prev) => {
          const last = prev[prev.length - 1];
          if (
            last &&
            last.role === event.role &&
            last.content === event.content
          ) {
            return prev;
          }
          return [...prev, { role: event.role, content: event.content }];
        });
      } else if (event.type === "status") {
        setLiveStatus(event.status);
      } else if (event.type === "result") {
        const r = event.result as ResultPayload;
        setLiveStatus(event.status);
        setLiveMeta((prev) => ({
          ...prev,
          status: event.status,
          outcome: r.outcome,
          duration_seconds: r.duration_seconds,
          appointment_booked: r.appointment_booked,
          appointment_details: r.appointment_details,
          patient_agreed_not_booked: r.patient_agreed_not_booked,
          sentiment: r.sentiment,
          key_topics: r.key_topics,
          summary: r.summary,
        }));
        if (r.transcript && r.transcript.length) {
          setLiveTranscript(r.transcript);
        }
        if (r.evaluations) setLiveEval(r.evaluations);
        load();
      }
    });
    return unsubscribe;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [liveTranscript]);

  useEffect(() => {
    if (!call || TERMINAL.has(call.status)) return;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [call?.status, id]);

  if (error && !call) return <div className="error">{error}</div>;
  if (!call) return <div className="loading">Loading call…</div>;

  const meta = { ...call, ...liveMeta };
  const status = liveStatus || call.status;
  const isLive = !TERMINAL.has(status);
  const appointment =
    (meta.appointment_details as Record<string, string> | undefined) ?? {};

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/calls" className="muted">
            ← Calls
          </Link>
          <h1 className="page-title" style={{ marginTop: 6 }}>
            {call.patient_name || call.patient?.name}
          </h1>
          <p className="page-sub">
            {call.patient_phone || call.patient?.phone} · {formatDate(call.created_at)}
            {call.room_name ? ` · ${call.room_name}` : ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {isLive && <span className="muted">● live</span>}
          <StatusBadge status={status} />
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2 className="card-title">Transcript</h2>
          <div className="transcript" ref={transcriptRef}>
            {liveTranscript.length === 0 ? (
              <div className="empty-state">
                {isLive
                  ? "Waiting for the call to start…"
                  : "No transcript recorded."}
              </div>
            ) : (
              liveTranscript.map((t, i) => (
                <div key={i} className={`msg ${t.role}`}>
                  <div className="msg-head">
                    {t.role === "assistant" ? "HealthLine Agent" : "Patient"}
                  </div>
                  {t.content}
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h2 className="card-title">Call summary</h2>
            <dl className="kv">
              <dt>Preferred time</dt>
              <dd>{meta.preferred_time}</dd>
              <dt>Duration</dt>
              <dd>{formatDuration(meta.duration_seconds ?? 0)}</dd>
              <dt>Outcome</dt>
              <dd>{meta.outcome || "—"}</dd>
              <dt>Sentiment</dt>
              <dd>{meta.sentiment || "—"}</dd>
            </dl>
            {meta.summary && (
              <p style={{ marginTop: 12 }}>{meta.summary}</p>
            )}
            {meta.key_topics && meta.key_topics.length > 0 && (
              <div className="key-topics">
                {meta.key_topics.map((t) => (
                  <span key={t} className="topic-chip">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="card">
            <h2 className="card-title">Appointment</h2>
            {meta.appointment_booked ? (
              <dl className="kv">
                <dt>Appointment ID</dt>
                <dd>{appointment.appointment_id || "—"}</dd>
                <dt>Doctor</dt>
                <dd>{appointment.doctor || "—"}</dd>
                <dt>Date</dt>
                <dd>{appointment.scheduled_date || "—"}</dd>
                <dt>Time</dt>
                <dd>{appointment.scheduled_time || "—"}</dd>
                <dt>Location</dt>
                <dd>{appointment.location || "—"}</dd>
                {appointment.notes && (
                  <>
                    <dt>Notes</dt>
                    <dd>{appointment.notes}</dd>
                  </>
                )}
              </dl>
            ) : meta.patient_agreed_not_booked ? (
              <p className="error" style={{ padding: 0, textAlign: "left" }}>
                Patient agreed to book, but no appointment was confirmed — needs review.
              </p>
            ) : (
              <p className="muted">No appointment was booked during this call.</p>
            )}
          </div>

          <div className="card">
            <h2 className="card-title">Evaluation</h2>
            {liveEval.length === 0 ? (
              <p className="muted">Scoring runs after the call completes.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Score</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {liveEval.map((e, i) => (
                    <tr key={i}>
                      <td>{e.metric_name}</td>
                      <td className="eval-score">{(e.score * 100).toFixed(0)}%</td>
                      <td>
                        <span className={`badge ${e.passed ? "badge-ok" : "badge-danger"}`}>
                          {e.passed ? "Pass" : "Fail"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <h2 className="card-title">Patient report</h2>
            <BiomarkerTable biomarkers={call.patient?.biomarkers ?? call.biomarkers ?? []} />
          </div>
        </div>
      </div>
    </>
  );
}