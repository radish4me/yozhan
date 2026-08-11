import type { ReactNode } from "react";
import type { AsyncState } from "../useAsync";

interface PanelProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
}

export function Panel({ title, subtitle, children }: PanelProps) {
  return (
    <>
      <h1>{title}</h1>
      {subtitle && <p className="subtitle">{subtitle}</p>}
      {children}
    </>
  );
}

/** Renders loading/error once, so every view doesn't reimplement it. */
export function Async<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  if (state.loading && state.data === null) return <p className="muted">loading…</p>;
  if (state.error) return <p className="error">{state.error}</p>;
  if (state.data === null) return null;
  return <>{children(state.data)}</>;
}
