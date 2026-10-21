import { useEffect, useState } from "react";
import { ErrorMessage } from "./components/ErrorMessage";
import { SyncRunsPage } from "./components/syncRuns/SyncRunsPage";
import { getHealth } from "./services/api";

function App() {
  const [status, setStatus] = useState("Connecting...");
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch((err: unknown) => {
        setStatus("Backend unavailable");
        setError(err);
      });
  }, []);

  return (
    <main style={{ padding: "1.5rem 2rem", fontFamily: "Arial" }}>
      <h1>PULSE Dashboard</h1>
      <p>Ecosystem Intelligence Platform</p>
      <p>Backend status: {status}</p>
      {error !== null ? <ErrorMessage error={error} /> : <SyncRunsPage />}
    </main>
  );
}

export default App;
