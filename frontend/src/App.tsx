import { useEffect, useState } from "react";
import { ErrorMessage } from "./components/ErrorMessage";
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
    <main style={{ padding: "2rem", fontFamily: "Arial" }}>
      <h1>PULSE Dashboard</h1>
      <p>Ecosystem Intelligence Platform</p>
      <h2>Backend status: {status}</h2>
      {error !== null && <ErrorMessage error={error} />}
    </main>
  );
}

export default App;
