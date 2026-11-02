import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { CustomEase } from "gsap/CustomEase";
import { Flip } from "gsap/Flip";
import { ScrollToPlugin } from "gsap/ScrollToPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

// Registo único de todos os plugins usados na app (antes de qualquer useGSAP).
gsap.registerPlugin(useGSAP, CustomEase, Flip, ScrollToPlugin, ScrollTrigger, SplitText);


CustomEase.create("synop-out", "0.16, 1, 0.3, 1");
CustomEase.create("synop-in", "0.7, 0, 0.84, 0");
CustomEase.create("synop-in-out", "0.65, 0, 0.35, 1");

export const EASE = {
  out: "synop-out", // entradas
  in: "synop-in", // saídas
  inOut: "synop-in-out", // movimento dentro do ecrã
} as const;

export const DURATION = {
  quick: 0.2,
  base: 0.5,
  slow: 0.9,
} as const;

export const COLORS = {
  ink: "#111111",
  white: "#ffffff",
  accent: "#e54823",
} as const;

export const MOTION_OK = "(prefers-reduced-motion: no-preference)";
export const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
export const DESKTOP = "(min-width: 960px)";

gsap.defaults({ duration: DURATION.base, ease: EASE.out });

// As fontes web alteram as métricas do texto: recalcula os ScrollTriggers quando carregarem.
document.fonts.ready.then(() => ScrollTrigger.refresh());

export function prefersReducedMotion(): boolean {
  return window.matchMedia(REDUCED_MOTION).matches;
}

/** Atraso entre itens que mantém o stagger total dentro do orçamento (~400ms). */
export function staggerEach(count: number, budget = 0.4): number {
  return gsap.utils.clamp(0.02, 0.08, budget / Math.max(count - 1, 1));
}

/** Feedback de erro: 2–3 oscilações horizontais firmes, sem overshoot (~400ms). */
export function shake(target: Element | null) {
  if (!target || prefersReducedMotion()) return;
  gsap.to(target, {
    keyframes: { x: [0, -10, 10, -6, 6, 0], easeEach: "power1.inOut" },
    duration: 0.4,
    ease: "none",
    overwrite: true,
  });
}

export { gsap, useGSAP, CustomEase, Flip, ScrollToPlugin, ScrollTrigger, SplitText };