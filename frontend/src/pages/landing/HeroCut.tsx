import { useRef } from "react";
import { Waveform } from "../../components/Waveform";
import { useMotion } from "../../hooks/useMotion";
import { COLORS, DURATION, EASE, gsap } from "../../lib/gsap";
import type { WaveRange } from "../../lib/utils";

const BARS = 48;
const SCAN = 1.6; // segundos que a cabeça de leitura demora a percorrer o vídeo

const PICKS: WaveRange[] = [
  { id: "a", from: 6, to: 11 },
  { id: "b", from: 21, to: 26 },
  { id: "c", from: 35, to: 40 },
];

const CLIPS = [
  { id: "a", title: "The Question That Changed Everything", time: "0:42" },
  { id: "b", title: "The Error No One Sees", time: "0:35" },
  { id: "c", title: "Final Advice", time: "0:28" },
];

export function HeroCut() {
  const rootRef = useRef<HTMLDivElement>(null);

  useMotion(rootRef, () => {
    const q = gsap.utils.selector(rootRef);

    const tl = gsap.timeline({
      defaults: { ease: EASE.out },
      // Pausa o loop ambiente quando o hero sai do ecrã (performance).
      scrollTrigger: {
        trigger: rootRef.current,
        start: "top bottom",
        end: "bottom top",
        toggleActions: "play pause resume pause",
      },
    });

    // 1. Setup — o vídeo longo "carrega".
    tl.from(q("[data-cut-frame]"), { y: 24, autoAlpha: 0, duration: DURATION.base })
      .from(q(".wave__bar"), { scaleY: 0, duration: DURATION.base, stagger: { amount: 0.4 } }, "-=0.25")
      // 2. Ação — a cabeça de leitura percorre o vídeo (linear: é um indicador de progresso)…
      .addLabel("scan")
      .fromTo(
        q("[data-cut-scan]"),
        { xPercent: 0, autoAlpha: 1 },
        { xPercent: 100, duration: SCAN, ease: "none" },
        "scan",
      );

    // …e cada momento escolhido acende quando ela passa por cima.
    PICKS.forEach((range) => {
      tl.from(
        q(`.wave__bar[data-range="${range.id}"]`),
        { backgroundColor: COLORS.ink, duration: 0.25, stagger: 0.03, ease: "none" },
        `scan+=${(range.from / BARS) * SCAN}`,
      );
    });

    // 3. Resolução — o resto recua (staging) e os clipes saem do vídeo.
    tl.to(q("[data-cut-scan]"), { autoAlpha: 0, duration: DURATION.quick }, `scan+=${SCAN}`)
      .from(q(".wave__bar:not(.is-pick)"), { opacity: 1, duration: DURATION.base }, "<")
      .from(q("[data-cut-clip]"), { y: 24, autoAlpha: 0, duration: DURATION.base, stagger: 0.08 }, "<0.1")
      .from(
        q("[data-cut-fill]"),
        { scaleX: 0, duration: DURATION.slow, ease: EASE.inOut, stagger: 0.08 },
        "<0.2",
      )
      // 4. Ambiente — os momentos escolhidos continuam a "respirar".
      .to(q(".wave__bar.is-pick"), {
        scaleY: () => gsap.utils.random(0.45, 1),
        duration: 1.1,
        ease: "sine.inOut",
        repeat: -1,
        yoyo: true,
        repeatRefresh: true,
        stagger: { each: 0.04, from: "random" },
      });
  });

  return (
    <div className="cut" ref={rootRef} aria-hidden="true">
      <div className="cut__frame" data-cut-frame>
        <div className="cut__bar">
          <span className="cut__dot" />
          <span className="cut__file">full_interview.mp4</span>
          <span className="cut__time">1:12:48</span>
        </div>

        <div className="cut__track">
          <div className="cut__wave">
            <Waveform bars={BARS} ranges={PICKS} seed={2} />
            <div className="cut__scan" data-cut-scan>
              <span className="cut__playhead" />
            </div>
          </div>
        </div>

        <div className="cut__clips">
          {CLIPS.map((clip) => (
            <div key={clip.id} className="cut__clip" data-cut-clip>
              <span className="cut__clip-progress">
                <span className="cut__clip-fill" data-cut-fill />
              </span>
              <span className="cut__clip-title">{clip.title}</span>
              <span className="cut__clip-time">{clip.time}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}