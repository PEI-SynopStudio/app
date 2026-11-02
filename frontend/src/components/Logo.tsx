import { Link } from "react-router";

export function Logo({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="logo">
      <span className="logo__mark" aria-hidden="true" />
      <span className="logo__text">
        Synop<span>Studio</span>
      </span>
    </Link>
  );
}