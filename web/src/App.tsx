import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { RoleProvider } from "./lib/role";
import { Board } from "./pages/Board";
import { NotFound } from "./pages/NotFound";

// The order and intake pages carry the PDF reader (pdf.js); the board, the first screen, does not need it.
const Order = lazy(() => import("./pages/Order").then((m) => ({ default: m.Order })));
const Intake = lazy(() => import("./pages/Intake").then((m) => ({ default: m.Intake })));

function Loading() {
  return (
    <div className="page">
      <p className="quiet">Loading.</p>
    </div>
  );
}

export default function App() {
  return (
    <RoleProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Board />} />
            <Route
              path="/orders/:id"
              element={
                <Suspense fallback={<Loading />}>
                  <Order />
                </Suspense>
              }
            />
            <Route
              path="/intake"
              element={
                <Suspense fallback={<Loading />}>
                  <Intake />
                </Suspense>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </RoleProvider>
  );
}
