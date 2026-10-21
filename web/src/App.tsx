import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { RoleProvider } from "./lib/role";
import { Board } from "./pages/Board";
import { NotFound } from "./pages/NotFound";
import { Order } from "./pages/Order";

export default function App() {
  return (
    <RoleProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Board />} />
            <Route path="/orders/:id" element={<Order />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </RoleProvider>
  );
}
