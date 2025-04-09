import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { RoleProvider } from "./lib/role";
import { Board } from "./pages/Board";

export default function App() {
  return (
    <RoleProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Board />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </RoleProvider>
  );
}
