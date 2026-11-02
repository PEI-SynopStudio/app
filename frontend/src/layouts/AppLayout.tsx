import { useRef, type ComponentType } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { IconGrid, IconLogout, IconPlus, IconSliders, IconText, type IconProps } from "../components/Icons";
import { Logo } from "../components/Logo";
import { currentUser } from "../data/mock";
import { useMotion } from "../hooks/useMotion";
import { DURATION, EASE, Flip, gsap, prefersReducedMotion, useGSAP } from "../lib/gsap";
import "../styles/app.css";

const INDICATOR = '[data-flip-id="nav-indicator"]';

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<IconProps>;
  isActive: (pathname: string) => boolean;
}

const NAV: NavItem[] = [
  {
    to: "/app",
    label: "Projects",
    icon: IconGrid,
    isActive: (p) => p === "/app" || p.startsWith("/app/projects"),
  },
  { to: "/app/new", label: "New Project", icon: IconPlus, isActive: (p) => p.startsWith("/app/new") },
  {
    to: "/app/summarize",
    label: "Summarize",
    icon: IconText,
    isActive: (p) => p.startsWith("/app/summarize"),
  },
  {
    to: "/app/settings",
    label: "Settings",
    icon: IconSliders,
    isActive: (p) => p.startsWith("/app/settings"),
  },
];

function initials(name: string) {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

export function AppLayout() {
  const { pathname } = useLocation();
  const sidebarRef = useRef<HTMLElement>(null);
  const indicatorState = useRef<ReturnType<typeof Flip.getState> | null>(null);

  // Entrada da sidebar (uma vez, ao entrar na área da app).
  useMotion(sidebarRef, () => {
    gsap.from("[data-nav-item]", {
      x: -12,
      autoAlpha: 0,
      duration: DURATION.base,
      stagger: 0.05,
      clearProps: "transform,opacity,visibility",
    });
  });

  // FLIP do indicador: o estado é capturado no clique; depois do render anima a partir dele.
  const { contextSafe } = useGSAP(
    () => {
      const state = indicatorState.current;
      indicatorState.current = null;
      const indicator = sidebarRef.current?.querySelector(INDICATOR);
      if (!state || !indicator || prefersReducedMotion()) return;
      Flip.from(state, { targets: indicator, duration: DURATION.base, ease: EASE.out });
    },
    { scope: sidebarRef, dependencies: [pathname] },
  );

  const captureIndicator = contextSafe(() => {
    const indicator = sidebarRef.current?.querySelector(INDICATOR);
    if (indicator) indicatorState.current = Flip.getState(indicator);
  });

  return (
    <div className="app">
      <aside className="app-sidebar" ref={sidebarRef}>
        <div className="app-sidebar__logo" data-nav-item>
          <Logo to="/app" />
        </div>

        <nav className="app-nav" aria-label="Application">
          {NAV.map(({ to, label, icon: Icon, isActive }) => {
            const active = isActive(pathname);
            return (
              <Link
                key={to}
                to={to}
                className={active ? "app-nav__link is-active" : "app-nav__link"}
                aria-current={active ? "page" : undefined}
                onClick={captureIndicator}
                data-nav-item
              >
                {active && (
                  <span className="app-nav__indicator" data-flip-id="nav-indicator" aria-hidden="true" />
                )}
                <Icon />
                <span className="app-nav__label">{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="app-user" data-nav-item>
          <span className="app-user__avatar" aria-hidden="true">
            {initials(currentUser.name)}
          </span>
          <div className="app-user__info">
            <p className="app-user__name">{currentUser.name}</p>
            <p className="app-user__email">{currentUser.email}</p>
          </div>
          <Link to="/" className="app-user__logout" aria-label="Log out" title="Log out">
            <IconLogout />
          </Link>
        </div>
      </aside>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}