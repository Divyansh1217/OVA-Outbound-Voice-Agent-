import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import StatusBadge from "../components/StatusBadge";
import { callService } from "../services/calls";
import type { Call } from "../types";
import { formatDate } from "../utils";

export default function Calls() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");

  useEffect(() => {
    callService
      .list()
      .then((data) => setCalls(data.calls))
      .catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(
    () => (filter === "all" ? calls : calls.filter((c) => c.status === filter)),
    [calls, filter]
  );

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of calls) m.set(c.status, (m.get(c.status) ?? 0) + 1);
    return m;
  }, [calls]);

  if (error) return <div className="error">{error}</div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Calls</h1>
          <p className="page-sub">Every arranged outreach call and its outcome.</p>
        </div>
      </div>

      <div className="card">
        <div className="form-group" style={{ maxWidth: 260, marginBottom: 14 }}>
          <label className="label">Filter by status</label>
          <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All statuses ({calls.length})</option>
            {Array.from(counts.keys())
              .sort()
              .map((s) => (
                <option key={s} value={s}>
                  {s} ({counts.get(s)})
                </option>
              ))}
          </select>
        </div>

        {filtered.length === 0 ? (
          <div className="empty-state">No calls found.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Patient</th>
                <th>Status</th>
                <th>Preferred time</th>
                <th>Outcome</th>
                <th>Appointment</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} className="row-link">
                  <td>
                    <Link to={`/calls/${c.id}`}>{c.patient_name}</Link>
                  </td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>{c.preferred_time}</td>
                  <td>{c.outcome || "—"}</td>
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