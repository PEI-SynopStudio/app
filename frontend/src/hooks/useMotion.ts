import type { RefObject } from "react";
import { DESKTOP, DURATION, EASE, MOTION_OK, gsap, staggerEach, useGSAP } from "../lib/gsap";

export interface MotionContext {
  isDesktop: boolean;
}

type MotionSetup = (ctx: MotionContext) => void | (() => void);

/**
 * Animações decorativas: só correm quando o utilizador NÃO pediu movimento reduzido.
 * Com movimento reduzido, o conteúdo fica no estado final definido no CSS.
 *
 * Tudo o que for criado no `setup` (tweens, timelines, ScrollTriggers, SplitText)
 * é revertido automaticamente ao desmontar ou quando as `dependencies` mudam.
 *
 * Callbacks do GSAP criados aqui (onEnter, onComplete, ScrollTrigger.batch, delayedCall…)
 * já correm dentro do contexto certo: NÃO os envolvas em contextSafe — isso cria um ciclo
 * entre contextos e rebenta a stack no revert. contextSafe é só para handlers de eventos
 * do React (onClick, onSubmit…), usando o `useGSAP` do próprio componente.
 */
export function useMotion(
  scope: RefObject<HTMLElement | null>,
  setup: MotionSetup,
  dependencies: unknown[] = [],
) {
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(
        { motionOk: MOTION_OK, isDesktop: DESKTOP },
        (ctx) => {
          const conditions = ctx.conditions;
          if (!conditions?.motionOk) return;
          return setup({ isDesktop: Boolean(conditions.isDesktop) });
        },
        scope,
      );
    },
    { scope, dependencies, revertOnUpdate: true },
  );
}

/** Padrão de entrada único: elementos com `data-enter` sobem 16px e aparecem em cascata. */
export function usePageEnter(scope: RefObject<HTMLElement | null>) {
  useMotion(scope, () => {
    const items = gsap.utils.toArray<HTMLElement>("[data-enter]", scope.current);
    if (items.length === 0) return;
    gsap.from(items, {
      y: 16,
      autoAlpha: 0,
      duration: DURATION.base,
      ease: EASE.out,
      stagger: staggerEach(items.length),
      clearProps: "transform,opacity,visibility",
    });
  });
}