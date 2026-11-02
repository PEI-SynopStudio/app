import { useRef, useState, type MouseEvent } from "react";
import { Link } from "react-router";
import type { LegalBlock, LegalDocument } from "../data/legal";
import { usePageEnter } from "../hooks/useMotion";
import { DURATION, EASE, ScrollTrigger, gsap, prefersReducedMotion, useGSAP } from "../lib/gsap";
import { formatDate } from "../lib/utils";
import { Logo } from "./Logo";
import "../styles/legal.css";

const SCROLL_OFFSET = 88; // sticky header + breathing room

function sectionNumber(index: number) {
  return String(index + 1).padStart(2, "0");
}

export function LegalPage({ doc }: { doc: LegalDocument }) {
  const pageRef = useRef<HTMLDivElement>(null);
  const [activeId, setActiveId] = useState(doc.sections[0].id);

  usePageEnter(pageRef);

  // The table of contents follows the reading position. This is state, not decoration: always runs.
  const { contextSafe } = useGSAP(
    () => {
      const last = doc.sections.length - 1;
      doc.sections.forEach((section, index) => {
        ScrollTrigger.create({
          trigger: `#${section.id}`,
          // The last section is short and may never reach 40% of the viewport.
          start: index === last ? "top 70%" : "top 40%",
          end: "bottom 40%",
          onToggle: (self) => {
            if (self.isActive) setActiveId(section.id);
          },
        });
      });
    },
    { scope: pageRef },
  );

  const scrollToSection = contextSafe((event: MouseEvent<HTMLAnchorElement>, id: string) => {
    event.preventDefault();
    gsap.to(window, {
      scrollTo: { y: `#${id}`, offsetY: SCROLL_OFFSET },
      duration: prefersReducedMotion() ? 0 : DURATION.slow,
      ease: EASE.inOut,
    });
  });

  return (
    <div className="legal" ref={pageRef}>
      <header className="legal-header">
        <div className="container legal-header__inner">
          <Logo />
          <nav className="legal-header__nav" aria-label="Main">
            <Link to="/login" className="legal-header__link">
              Log in
            </Link>
            <Link to="/signup" className="btn btn--primary btn--sm">
              Create account
            </Link>
          </nav>
        </div>
      </header>

      <main className="container legal__main">
        <header className="legal__intro" data-enter>
          <p className="eyebrow">Legal</p>
          <h1 className="legal__title">{doc.title}</h1>
          <p className="legal__meta">
            <span>Version {doc.version}</span>
            <span aria-hidden="true">·</span>
            <span>Effective {formatDate(doc.effectiveDate)}</span>
          </p>
          <p className="legal__lead">{doc.lead}</p>
        </header>

        <div className="legal__layout">
          <nav className="legal-toc" aria-labelledby="toc-title" data-enter>
            <p className="legal-toc__title" id="toc-title">
              On this page
            </p>
            <ol className="legal-toc__list">
              {doc.sections.map((section, index) => {
                const isActive = section.id === activeId;
                return (
                  <li key={section.id}>
                    <a
                      href={`#${section.id}`}
                      className={isActive ? "legal-toc__link is-active" : "legal-toc__link"}
                      aria-current={isActive ? "location" : undefined}
                      onClick={(event) => scrollToSection(event, section.id)}
                    >
                      <span className="legal-toc__n">{sectionNumber(index)}</span>
                      {section.title}
                    </a>
                  </li>
                );
              })}
            </ol>
          </nav>

          <article className="legal__body" data-enter>
            {doc.sections.map((section, index) => (
              <section
                key={section.id}
                id={section.id}
                className="legal-section"
                aria-labelledby={`${section.id}-title`}
              >
                <span className="legal-section__n" aria-hidden="true">
                  {sectionNumber(index)}
                </span>
                <h2 className="legal-section__title" id={`${section.id}-title`}>
                  {section.title}
                </h2>
                {section.blocks.map((block, blockIndex) => (
                  <LegalBlockView key={blockIndex} block={block} />
                ))}
              </section>
            ))}
          </article>
        </div>
      </main>

      <footer className="legal-footer container">
        <Logo />
        <nav className="legal-footer__links" aria-label="Legal">
          <Link to="/terms">Terms and Conditions</Link>
          <Link to="/privacy">Privacy Policy</Link>
        </nav>
        <p>© 2026 SynopStudio · PEI Project</p>
      </footer>
    </div>
  );
}

function LegalBlockView({ block }: { block: LegalBlock }) {
  switch (block.type) {
    case "heading":
      return <h3 className="legal-section__subtitle">{block.text}</h3>;
    case "list":
      return (
        <ul className="legal-list">
          {block.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      );
    default:
      return <p>{block.text}</p>;
  }
}