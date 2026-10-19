
import { useEffect, useState } from "react";
import { getHealth } from "./services/api";

function App() {
  const [status, setStatus] = useState("Connecting...");

  useEffect(() => {
    getHealth()
      .then((data) => setStatus(data.status))
      .catch(() => setStatus("Backend unavailable"));
  }, []);

  return (
    <main style={{ padding: "2rem", fontFamily: "Arial" }}>
      <h1>PULSE Dashboard</h1>
      <p>Ecosystem Intelligence Platform</p>
      <h2>Backend status: {status}</h2>
    </main>
  );
}

export default App;
