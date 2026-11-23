import { useRef, type MouseEvent } from "react";
import { Link } from "react-router";
import { Logo } from "../../components/Logo";
import { useMotion } from "../../hooks/useMotion";
import { DURATION, EASE, ScrollTrigger, gsap, prefersReducedMotion, useGSAP } from "../../lib/gsap";

export function SiteHeader() {
  const headerRef = useRef<HTMLElement>(null);

  // Without motion: only marks the "scrolled" state (shows the bottom line).
  const { contextSafe } = useGSAP(
    () => {
      const header = headerRef.current;
      if (!header) return;
      ScrollTrigger.create({
        start: 8,
        end: "max",
        toggleClass: { targets: header, className: "is-scrolled" },
      });
    },
    { scope: headerRef },
  );

  // With motion: hides when scrolling down, comes back when scrolling up.
  useMotion(headerRef, () => {
    const header = headerRef.current;
    if (!header) return;
    const reveal = gsap
      .from(header, { yPercent: -100, paused: true, duration: 0.3, ease: EASE.out })
      .progress(1);
    ScrollTrigger.create({
      start: "top top",
      end: "max",
      onUpdate: (self) => {
        if (self.direction === -1 || self.scroll() < 120) reveal.play();
        else reveal.reverse();
      },
    });
  });

  const scrollToSteps = contextSafe((event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    gsap.to(window, {
      scrollTo: { y: "#how-it-works", offsetY: 72 },
      duration: prefersReducedMotion() ? 0 : DURATION.slow,
      ease: EASE.inOut,
    });
  });

  return (
    <header className="site-header" ref={headerRef}>
      <div className="container site-header__inner">
        <Logo />
        <nav className="site-header__nav" aria-label="Main">
          <a
            href="#how-it-works"
            className="site-header__link site-header__link--secondary"
            onClick={scrollToSteps}
          >
            How it works
          </a>
          <Link to="/login" className="site-header__link">
            Log in
          </Link>
          <Link to="/signup" className="btn btn--primary btn--sm">
            Create account
          </Link>
        </nav>
      </div>
    </header>
  );
}