import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { callService } from "../services/calls";
import type { Call, DashboardStats } from "../types";
import { formatDate } from "../utils";

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recent, setRecent] = useState<Call[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    callService
      .list()
      .then((data) => {
        setStats(data.stats);
        setRecent(data.calls.slice(0, 8));
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!stats) return <div className="loading">Loading dashboard…</div>;

  const cards = [
    { label: "Patients", value: stats.patients },
    { label: "Total calls", value: stats.calls },
    { label: "In progress", value: stats.in_progress },
    { label: "Completed", value: stats.completed },
    { label: "Appointments booked", value: stats.appointments_booked },
    { label: "Calls today", value: stats.today },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-sub">Overview of outreach calls arranged by doctors.</p>
        </div>
        <Link to="/patients/new" className="btn btn-primary">
          + New Patient
        </Link>
      </div>

      <div className="stat-grid">
        {cards.map((c) => (
          <div className="stat-card" key={c.label}>
            <div className="stat-value">{c.value}</div>
            <div className="stat-label">{c.label}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <h2 className="card-title">Recent calls</h2>
        {recent.length === 0 ? (
          <p className="muted">
            No calls yet. Add a patient, attach their report, then arrange a call.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Patient</th>
                <th>Status</th>
                <th>Preferred time</th>
                <th>Appointment</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((c) => (
                <tr key={c.id} className="row-link">
                  <td>
                    <Link to={`/calls/${c.id}`}>{c.patient_name}</Link>
                  </td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>{c.preferred_time}</td>
                  <td>{c.appointment_booked ? "Booked" : "—"}</td>
                  <td className="muted">{formatDate(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}