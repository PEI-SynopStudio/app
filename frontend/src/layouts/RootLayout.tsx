import { useRef } from "react";
import { Outlet, ScrollRestoration, useLocation } from "react-router";
import { useMotion } from "../hooks/useMotion";
import { DURATION, EASE, gsap } from "../lib/gsap";

export function RootLayout() {
  const { pathname } = useLocation();
  const barRef = useRef<HTMLDivElement>(null);

  // Camada secundária: uma linha laranja fina sinaliza cada mudança de página.
  useMotion(
    barRef,
    () => {
      const bar = barRef.current;
      if (!bar) return;
      gsap
        .timeline()
        .fromTo(bar, { scaleX: 0, autoAlpha: 1 }, { scaleX: 1, duration: DURATION.base, ease: EASE.out })
        .to(bar, { autoAlpha: 0, duration: DURATION.quick, ease: EASE.in });
    },
    [pathname],
  );

  return (
    <>
      <div ref={barRef} className="route-bar" aria-hidden="true" />
      <Outlet />
      <ScrollRestoration />
    </>
  );
}