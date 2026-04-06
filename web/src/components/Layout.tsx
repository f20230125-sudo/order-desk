import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";
import type { Role } from "../lib/api";
import { ROLE_NAME, useRole } from "../lib/role";

type Theme = "system" | "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const t = localStorage.getItem("order-desk:theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("order-desk:theme", theme);
    } catch {
      // not fatal
    }
  }, [theme]);
  const next = () => setTheme((t) => (t === "system" ? "dark" : t === "dark" ? "light" : "system"));
  return [theme, next];
}

export function Layout() {
  const { role, setRole } = useRole();
  const [theme, nextTheme] = useTheme();
  return (
    <>
      <a className="skip" href="#main">
        Skip to the content
      </a>
      <header className="top">
        <div className="top-inner">
          <Link to="/" className="wordmark">
            Order Desk
          </Link>
          <div className="role" role="group" aria-label="Working as">
            <span className="role-label">Working as</span>
            {(["sales", "ops", "finance"] as Role[]).map((r) => (
              <button key={r} type="button" aria-pressed={role === r} onClick={() => setRole(r)}>
                {ROLE_NAME[r]}
              </button>
            ))}
          </div>
          <nav className="top-actions" aria-label="Main">
            <NavLink to="/intake" className="button primary">
              Add from a document <kbd>N</kbd>
            </NavLink>
            <button type="button" className="theme" onClick={nextTheme} aria-label={`Theme: ${theme}. Change theme`}>
              Theme: {theme === "system" ? "auto" : theme}
            </button>
          </nav>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="foot">
        A working demo with made-up companies, orders and people. Built by Uzair Khan.
      </footer>
    </>
  );
}
