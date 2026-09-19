import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CallDetail from "./pages/CallDetail";
import Calls from "./pages/Calls";
import Dashboard from "./pages/Dashboard";
import PatientDetail from "./pages/PatientDetail";
import PatientForm from "./pages/PatientForm";
import Patients from "./pages/Patients";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/patients" element={<Patients />} />
        <Route path="/patients/new" element={<PatientForm />} />
        <Route path="/patients/:id" element={<PatientDetail />} />
        <Route path="/patients/:id/edit" element={<PatientForm />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/calls/:id" element={<CallDetail />} />
      </Route>
    </Routes>
  );
}