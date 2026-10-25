import { Link } from "react-router";

export interface Crumb {
  label: string;
  to?: string;
}

// Where a page sits under the navigation, the last crumb being the page itself.
export function Breadcrumb({ crumbs }: Readonly<{ crumbs: Crumb[] }>) {
  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      <ol>
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={crumb.label} aria-current={last ? "page" : undefined}>
              {crumb.to && !last ? (
                <Link to={crumb.to}>{crumb.label}</Link>
              ) : (
                crumb.label
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
