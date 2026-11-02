import { useRef } from "react";
import { Link } from "react-router";
import { Logo } from "../components/Logo";
import { useMotion, usePageEnter } from "../hooks/useMotion";
import { DURATION, EASE, SplitText, gsap } from "../lib/gsap";

export function NotFound() {
  const pageRef = useRef<HTMLDivElement>(null);
  const codeRef = useRef<HTMLHeadingElement>(null);

  usePageEnter(pageRef);

  useMotion(pageRef, () => {
    const code = codeRef.current;
    if (!code) return;
    const split = SplitText.create(code, { type: "chars", mask: "chars" });
    gsap.from(split.chars, { yPercent: 100, duration: DURATION.slow, ease: EASE.out, stagger: 0.08 });
  });

  return (
    <div className="not-found" ref={pageRef}>
      <Logo />
      <h1 className="not-found__code" ref={codeRef}>
        4<span>0</span>4
      </h1>
      <p className="not-found__text" data-enter>
        Esta página não existe — ou foi cortada na edição.
      </p>
      <Link to="/" className="btn btn--primary" data-enter>
        Voltar ao início
      </Link>
    </div>
  );
}