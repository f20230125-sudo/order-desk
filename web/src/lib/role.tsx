import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Role } from "./api";

// Who you are working as. No login in the demo: the choice is kept in this browser only.
const KEY = "order-desk:role";

function stored(): Role {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "sales" || v === "ops" || v === "finance") return v;
  } catch {
    // storage blocked (private window): fall back to ops, the desk this tool is for
  }
  return "ops";
}

const RoleContext = createContext<{ role: Role; setRole: (r: Role) => void }>({ role: "ops", setRole: () => {} });

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>(stored);
  useEffect(() => {
    try {
      localStorage.setItem(KEY, role);
    } catch {
      // not fatal
    }
  }, [role]);
  return <RoleContext.Provider value={{ role, setRole }}>{children}</RoleContext.Provider>;
}

export const useRole = () => useContext(RoleContext);

export const ROLE_NAME: Record<Role, string> = { sales: "Sales", ops: "Ops", finance: "Finance" };
