import type { ReactNode } from "react";

// Every page's header: its title, a line on what the page is for, and its main
// action, if it has one, on the right.
export function PageHeader({
  title,
  lead,
  action,
}: Readonly<{ title: ReactNode; lead: ReactNode; action?: ReactNode }>) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        <p className="lead">{lead}</p>
      </div>
      {action && <div className="page-action">{action}</div>}
    </div>
  );
}
