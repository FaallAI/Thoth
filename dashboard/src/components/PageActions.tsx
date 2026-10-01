import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Page-owned actions share the shell heading and remain inline in isolated views. */
export function PageActions({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setTarget(document.getElementById("dashboard-page-actions"));
  }, []);
  return target ? createPortal(children, target) : <div className="pen-page-actions">{children}</div>;
}
