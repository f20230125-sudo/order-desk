import { useEffect } from "react";
import { Link } from "react-router";

export function NotFound() {
  useEffect(() => {
    document.title = "Not found: Order Desk";
  }, []);
  return (
    <div className="page">
      <h1 className="h-page">Nothing at this address</h1>
      <p>Orders are found from the board: search by PO, tracking or serial number.</p>
      <Link className="button" to="/">
        Back to the board
      </Link>
    </div>
  );
}
