import { useRef, type ReactNode } from "react";
import { Logo } from "../components/Logo";
import { Waveform } from "../components/Waveform";
import { useMotion, usePageEnter } from "../hooks/useMotion";
import { gsap } from "../lib/gsap";
import "../styles/auth.css";

const ASIDE_RANGES = [
  { id: "a", from: 8, to: 13 },
  { id: "b", from: 24, to: 29 },
];

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  footer: ReactNode;
  children: ReactNode;
}

export function AuthLayout({ title, subtitle, footer, children }: AuthLayoutProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLElement>(null);

  usePageEnter(rootRef);

  // Camada ambiente: os "melhores momentos" respiram devagar (só em desktop, onde o painel existe).
  useMotion(asideRef, ({ isDesktop }) => {
    if (!isDesktop) return;
    gsap.to(".wave__bar.is-pick", {
      scaleY: () => gsap.utils.random(0.45, 1),
      duration: 1.2,
      ease: "sine.inOut",
      repeat: -1,
      yoyo: true,
      repeatRefresh: true,
      stagger: { each: 0.06, from: "random" },
    });
  });

  return (
    <div className="auth" ref={rootRef}>
      <aside className="auth__aside surface-dark" ref={asideRef}>
        <Logo />
        <div className="auth__wave">
          <Waveform bars={40} ranges={ASIDE_RANGES} seed={3} />
        </div>
        <p className="auth__quote">From the long video to the right clip.</p>
      </aside>

      <main className="auth__main">
        <div className="auth__panel">
          <div className="auth__mobile-logo">
            <Logo />
          </div>
          <header data-enter>
            <h1 className="auth__title">{title}</h1>
            <p className="auth__subtitle">{subtitle}</p>
          </header>
          <div data-enter>{children}</div>
          <p className="auth__footer" data-enter>
            {footer}
          </p>
        </div>
      </main>
    </div>
  );
}