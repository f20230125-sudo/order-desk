import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes, useParams } from "react-router";

// Skeleton for the deploy check (C0): proves the API, a deep link and the built assets all work on Vercel.
// The real screens replace this once the design direction is approved.

function Health() {
  const [status, setStatus] = useState("checking the database");
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setStatus(d.ok ? `database answered at ${d.db_time} (Postgres ${d.postgres})` : "database error"))
      .catch(() => setStatus("could not reach the API"));
  }, []);
  return <p data-testid="health">{status}</p>;
}

function OrderStub() {
  const { id } = useParams();
  return <p data-testid="order-stub">Order {id}</p>;
}

export default function App() {
  return (
    <BrowserRouter>
      <main>
        <h1>Order Desk</h1>
        <Health />
        <Routes>
          <Route path="/" element={null} />
          <Route path="/orders/:id" element={<OrderStub />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
