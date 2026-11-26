import { useRef } from "react";
import { Link } from "react-router";
import { IconArrowRight } from "../../components/Icons";
import { Logo } from "../../components/Logo";
import { useMotion } from "../../hooks/useMotion";
import { DURATION, EASE, ScrollTrigger, SplitText, gsap } from "../../lib/gsap";
import "../../styles/landing.css";
import { HeroCut } from "./HeroCut";
import { SiteHeader } from "./SiteHeader";

const STEPS = [
  {
    n: "01",
    title: "Upload your video",
    text: "Interviews, lectures, podcasts or livestreams. One long file is the starting point.",
  },
  {
    n: "02",
    title: "We find the moments",
    text: "SynopStudio identifies the excerpts with the most potential to stand on their own.",
  },
  {
    n: "03",
    title: "Export vertical clips",
    text: "Short clips, reframed to 9:16 and ready to publish.",
  },
];

export function Landing() {
  const rootRef = useRef<HTMLDivElement>(null);

  useMotion(rootRef, () => {
    const q = gsap.utils.selector(rootRef);

    // Hero — the title rises word by word behind a mask; the rest follows.
    const title = SplitText.create(q("[data-hero-title]"), {
      type: "words",
      mask: "words",
      wordsClass: "split-word",
    });
    gsap
      .timeline({ defaults: { ease: EASE.out } })
      .from(title.words, { yPercent: 110, duration: DURATION.slow, stagger: 0.06 })
      .from(q("[data-hero-fade]"), { y: 16, autoAlpha: 0, duration: DURATION.base, stagger: 0.08 }, "-=0.6");

    // How it works — the steps enter as a group when they reach the screen.
    const steps = q("[data-step]");
    gsap.set(steps, { y: 32, autoAlpha: 0 });
    ScrollTrigger.batch(steps, {
      start: "top 85%",
      once: true,
      onEnter: (batch: Element[]) => {
        gsap.to(batch, { y: 0, autoAlpha: 1, duration: DURATION.base, stagger: 0.1, overwrite: true });
      },
    });

    // Statement — the words "light up" with the scroll.
    const statementEl = q("[data-statement]")[0];
    const statement = SplitText.create(statementEl, { type: "words" });
    gsap.fromTo(
      statement.words,
      { opacity: 0.15 },
      {
        opacity: 1,
        ease: "none",
        stagger: 0.1,
        scrollTrigger: { trigger: statementEl, start: "top 80%", end: "bottom 45%", scrub: 0.6 },
      },
    );

    // Final CTA.
    gsap.from(q("[data-cta] > *"), {
      y: 24,
      autoAlpha: 0,
      duration: DURATION.base,
      stagger: 0.08,
      scrollTrigger: { trigger: q("[data-cta]")[0], start: "top 80%" },
    });
  });

  return (
    <div className="landing" ref={rootRef}>
      <SiteHeader />

      <main>
        <section className="hero container">
          <div className="hero__copy">
            <p className="eyebrow" data-hero-fade>
              Short clips from long videos
            </p>
            <h1 className="hero__title" data-hero-title>
              <span className="hero__line">One long video.</span>
              <span className="hero__line hero__line--accent">Endless short stories.</span>
            </h1>
            <p className="hero__lead" data-hero-fade>
              Upload a long recording and get vertical clips with the moments that truly matter.
            </p>
            <div className="hero__actions" data-hero-fade>
              <Link to="/signup" className="btn btn--primary btn--lg">
                Get started <IconArrowRight />
              </Link>
              <Link to="/login" className="btn btn--ghost btn--lg">
                Log in
              </Link>
            </div>
          </div>
          <HeroCut />
        </section>

        <section className="steps" id="how-it-works" aria-labelledby="steps-title">
          <div className="container">
            <h2 className="section-title" id="steps-title">
              How it works
            </h2>
            <ol className="steps__list">
              {STEPS.map((step) => (
                <li key={step.n} className="step" data-step>
                  <span className="step__n" aria-hidden="true">
                    {step.n}
                  </span>
                  <h3 className="step__title">{step.title}</h3>
                  <p className="step__text">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="statement">
          <div className="container">
            <p className="statement__text" data-statement>
              One recording. Dozens of moments. SynopStudio finds the ones that matter and turns them into
              clips ready to publish.
            </p>
          </div>
        </section>

        <section className="cta surface-dark">
          <div className="container cta__inner" data-cta>
            <h2 className="cta__title">Ready for your first cut?</h2>
            <p className="cta__text">Create an account and upload your first video.</p>
            <div className="cta__actions">
              <Link to="/signup" className="btn btn--accent btn--lg">
                Create account
              </Link>
              <Link to="/login" className="btn btn--ghost btn--lg">
                Log in
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-footer container">
        <Logo />
        <nav className="site-footer__links" aria-label="Legal">
          <Link to="/terms">Terms and Conditions</Link>
          <Link to="/privacy">Privacy Policy</Link>
        </nav>
        <p>© 2026 SynopStudio · PEI Project</p>
      </footer>
    </div>
  );
}