import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import BiomarkerTable from "../components/BiomarkerTable";
import StatusBadge from "../components/StatusBadge";
import { callService } from "../services/calls";
import { patientService } from "../services/patients";
import type { Patient } from "../types";
import { formatDate } from "../utils";

const TIME_OPTIONS = ["morning", "afternoon", "evening"];

export default function PatientDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [patient, setPatient] = useState<Patient | null>(null);
  const [error, setError] = useState("");
  const [preferredTime, setPreferredTime] = useState("morning");
  const [arranging, setArranging] = useState(false);

  const load = () => {
    if (!id) return;
    patientService
      .get(id)
      .then(setPatient)
      .catch((e) => setError(e.message));
  };

  useEffect(load, [id]);

  const arrangeCall = async () => {
    if (!id) return;
    setArranging(true);
    setError("");
    try {
      const call = await callService.arrange(id, preferredTime);
      navigate(`/calls/${call.id}`);
    } catch (e) {
      setError((e as Error).message);
      setArranging(false);
    }
  };

  if (error && !patient) return <div className="error">{error}</div>;
  if (!patient) return <div className="loading">Loading patient…</div>;

  const hasReport = patient.biomarkers.length > 0;

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/patients" className="muted">
            ← Patients
          </Link>
          <h1 className="page-title" style={{ marginTop: 6 }}>
            {patient.name}
          </h1>
          <p className="page-sub">{patient.phone}</p>
        </div>
        <Link to={`/patients/${patient.id}/edit`} className="btn btn-ghost">
          Edit patient &amp; report
        </Link>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <h2 className="card-title">Lab report</h2>
        {hasReport ? (
          <BiomarkerTable biomarkers={patient.biomarkers} />
        ) : (
          <p className="muted">
            No report added yet.{" "}
            <Link to={`/patients/${patient.id}/edit`}>Add a report</Link> before
            arranging a call.
          </p>
        )}
      </div>

      <div className="grid-2">
        <div className="card">
          <h2 className="card-title">Arrange a voice call</h2>
          <p className="muted" style={{ marginTop: -6 }}>
            The AI agent will call {patient.name} and discuss the biomarker report,
            then offer to book a doctor consultation.
          </p>
          <div className="form-group" style={{ marginTop: 14 }}>
            <label className="label">Preferred time of day</label>
            <select
              className="select"
              value={preferredTime}
              onChange={(e) => setPreferredTime(e.target.value)}
            >
              {TIME_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {t[0].toUpperCase() + t.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <button
            className="btn btn-primary"
            style={{ marginTop: 14 }}
            disabled={arranging || !hasReport}
            onClick={arrangeCall}
          >
            {arranging ? "Arranging…" : "📞 Arrange call"}
          </button>
          {!hasReport && (
            <p className="muted" style={{ marginTop: 10 }}>
              Add at least one biomarker before arranging a call.
            </p>
          )}
        </div>

        <div className="card">
          <h2 className="card-title">Call history</h2>
          {!patient.calls || patient.calls.length === 0 ? (
            <p className="muted">No calls yet for this patient.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Time</th>
                  <th>Appointment</th>
                </tr>
              </thead>
              <tbody>
                {patient.calls.map((c) => (
                  <tr key={c.id} className="row-link">
                    <td>
                      <Link to={`/calls/${c.id}`}>
                        <StatusBadge status={c.status} />
                      </Link>
                    </td>
                    <td className="muted">{formatDate(c.created_at)}</td>
                    <td>{c.appointment_booked ? "Booked" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}