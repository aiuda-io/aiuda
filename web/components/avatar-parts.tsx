import type { ReactNode } from "react";
import type { PartCategory } from "@/lib/look";

// Piezas de la mascota de aiuda, por capas, en una sola viewBox 0 0 64 64 (el <svg> lo pone
// Avatar una vez). Silueta rellena (base blanca donde se posan ojos/boca) + detalles en línea
// con caps redondos, igual idiom que role-icon.tsx. La mascota es neutra (blanca + tinta); el
// color de acento vive en el círculo de fondo, no en el personaje. Sin <defs>, sin ids, sin
// random → sin colisiones de SSR/hidratación.
//
// PARITY: landing/index.html replica estas piezas como strings (PARTS/BASE). Si cambias una
// forma o agregas una variante, espeja allá y mantén PART_KEYS (lib/look.ts) en lockstep.

const SKIN = "#F3F0E8"; // off-white cálido, contrasta sobre los 8 acentos
const GLOSS = "#FFFFFF"; // brillo (guiño al glossy original)
const INK = "#23272C"; // ojos/boca/línea
const HAIR = "#3B4149"; // pelo (slate oscuro, nunca acento)
const HAT = "#586069"; // sombreros (slate medio, se distingue del pelo)

// Geometría de referencia: cabeza ellipse(32,27,18,19); ojos en x25/x39, y27; boca (32,35);
// cuerpo desde y≈48 recortado por el círculo del wrapper.
export const AVATAR_BASE: ReactNode = (
  <>
    <path d="M9 64C9 52 18 47.5 32 47.5C46 47.5 55 52 55 64Z" fill={SKIN} />
    <circle cx="14" cy="29" r="3.6" fill={SKIN} />
    <circle cx="50" cy="29" r="3.6" fill={SKIN} />
    <ellipse cx="32" cy="27" rx="18" ry="19" fill={SKIN} />
    <ellipse cx="23.5" cy="18" rx="4.2" ry="6" fill={GLOSS} opacity="0.55" transform="rotate(-22 23.5 18)" />
  </>
);

export const AVATAR_PARTS: Record<PartCategory, Record<string, ReactNode>> = {
  eyes: {
    dot: (
      <>
        <circle cx="25" cy="27" r="3" fill={INK} />
        <circle cx="39" cy="27" r="3" fill={INK} />
        <circle cx="26.1" cy="25.9" r="0.85" fill="#fff" />
        <circle cx="40.1" cy="25.9" r="0.85" fill="#fff" />
      </>
    ),
    "round-soft": (
      <>
        <circle cx="25" cy="27" r="3.1" fill="none" stroke={INK} strokeWidth="1.6" />
        <circle cx="39" cy="27" r="3.1" fill="none" stroke={INK} strokeWidth="1.6" />
      </>
    ),
    line: (
      <path d="M21.8 27h6.4M35.8 27h6.4" stroke={INK} strokeWidth="1.9" strokeLinecap="round" fill="none" />
    ),
    wide: (
      <>
        <ellipse cx="25" cy="27" rx="3" ry="3.7" fill={INK} />
        <ellipse cx="39" cy="27" rx="3" ry="3.7" fill={INK} />
        <circle cx="26.1" cy="25.6" r="0.9" fill="#fff" />
        <circle cx="40.1" cy="25.6" r="0.9" fill="#fff" />
      </>
    ),
    pixel: (
      <>
        <rect x="22.8" y="24.8" width="4.4" height="4.4" rx="1.1" fill={INK} />
        <rect x="36.8" y="24.8" width="4.4" height="4.4" rx="1.1" fill={INK} />
      </>
    ),
  },

  mouth: {
    "smile-soft": (
      <path d="M28 34.5Q32 38 36 34.5" fill="none" stroke={INK} strokeWidth="1.8" strokeLinecap="round" />
    ),
    flat: <path d="M29 35.6h6" stroke={INK} strokeWidth="1.8" strokeLinecap="round" fill="none" />,
    "line-smile": (
      <path d="M26.5 34.4Q32 38.6 37.5 34.4" fill="none" stroke={INK} strokeWidth="1.8" strokeLinecap="round" />
    ),
    "o-talk": <ellipse cx="32" cy="35.6" rx="2" ry="2.5" fill={INK} />,
    none: null,
  },

  hair: {
    none: null,
    short: (
      <path
        d="M14.4 27C14.4 13 22 8 32 8C42 8 49.6 13 49.6 27C49.6 19.5 43 16.4 32 16.4C21 16.4 14.4 19.5 14.4 27Z"
        fill={HAIR}
      />
    ),
    "side-part": (
      <path
        d="M14.4 27C14.4 13 22 8 32 8C42 8 49.6 13 49.6 25.5C49.6 19 44 16 35 16.8C31 19.8 24 20.6 18.5 19.6C16.4 21.6 15 24.5 14.4 27Z"
        fill={HAIR}
      />
    ),
    bob: (
      <path
        d="M13 27C13 12 21 8 32 8C43 8 51 12 51 27C51 34 49.2 39.5 47.2 41.5C47.2 30 47 20.5 44 18.4C40.2 16.2 36 16.6 32 16.6C28 16.6 23.8 16.2 20 18.4C17 20.5 16.8 30 16.8 41.5C14.8 39.5 13 34 13 27Z"
        fill={HAIR}
      />
    ),
    bun: (
      <>
        <circle cx="32" cy="6.6" r="4" fill={HAIR} />
        <path
          d="M14.4 27C14.4 13 22 8 32 8C42 8 49.6 13 49.6 27C49.6 19.5 43 16.4 32 16.4C21 16.4 14.4 19.5 14.4 27Z"
          fill={HAIR}
        />
      </>
    ),
    textured: (
      <path
        d="M14.4 26.5C13.6 19 15 14 18 12C18 14 19.4 14.6 21 13C21.6 15 23.4 15.4 25.4 13.6C26 15.6 28 16 30 14.2C31 16 33.4 16 35.2 14.2C36.4 16 38.6 15.8 40 13.8C41 15.6 43 15.6 44.4 13.4C47 15 49 18.6 49.6 26.5C49.6 19.5 43 16.4 32 16.4C21 16.4 14.4 19 14.4 26.5Z"
        fill={HAIR}
      />
    ),
  },

  hat: {
    none: null,
    cap: (
      <>
        <path d="M15.5 20.5C16.5 11.5 23 7 32 7C41 7 47.5 11.5 48.5 20.5C40 17.5 24 17.5 15.5 20.5Z" fill={HAT} />
        <path d="M15.5 20.5C9 20.8 5.5 22.4 5 23.6C11 24.6 17.5 23.6 22 21.4C19.5 20.6 17.5 20.4 15.5 20.5Z" fill={HAT} />
      </>
    ),
    beanie: (
      <>
        <path d="M14.5 21.5C14.5 11.5 22 7 32 7C42 7 49.5 11.5 49.5 21.5C36 18 28 18 14.5 21.5Z" fill={HAT} />
        <rect x="13.5" y="19.5" width="37" height="4.2" rx="2.1" fill="#6B727B" />
      </>
    ),
    "hard-hat": (
      <>
        <path d="M16.5 19.5C16.5 11.5 23.5 8.5 32 8.5C40.5 8.5 47.5 11.5 47.5 19.5C36 16.5 28 16.5 16.5 19.5Z" fill="#C2862F" />
        <rect x="12" y="18" width="40" height="3.2" rx="1.6" fill="#C2862F" />
        <path d="M30 9.2h4v8h-4z" fill="#A9741F" />
      </>
    ),
    headset: (
      <>
        <path d="M16 25C16 13.5 23 9.5 32 9.5C41 9.5 48 13.5 48 25" fill="none" stroke={INK} strokeWidth="2.4" strokeLinecap="round" />
        <rect x="12.5" y="23.5" width="5.2" height="8.4" rx="2.6" fill={INK} />
        <rect x="46.3" y="23.5" width="5.2" height="8.4" rx="2.6" fill={INK} />
        <path d="M15 31.5C15 37.5 21.5 39.5 26 38.5" fill="none" stroke={INK} strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="26.5" cy="38.4" r="1.5" fill={INK} />
      </>
    ),
  },

  accessory: {
    none: null,
    glasses: (
      <>
        <rect x="20.3" y="23.4" width="9.4" height="7.2" rx="2.6" fill="none" stroke={INK} strokeWidth="1.6" />
        <rect x="34.3" y="23.4" width="9.4" height="7.2" rx="2.6" fill="none" stroke={INK} strokeWidth="1.6" />
        <path d="M29.7 26.5h4.6" stroke={INK} strokeWidth="1.6" strokeLinecap="round" fill="none" />
        <path d="M20.3 25.6 16.5 24.6M43.7 25.6 47.5 24.6" stroke={INK} strokeWidth="1.6" strokeLinecap="round" fill="none" />
      </>
    ),
    "glasses-round": (
      <>
        <circle cx="25" cy="27" r="4.6" fill="none" stroke={INK} strokeWidth="1.4" />
        <circle cx="39" cy="27" r="4.6" fill="none" stroke={INK} strokeWidth="1.4" />
        <path d="M29.6 27h4.8" stroke={INK} strokeWidth="1.4" strokeLinecap="round" fill="none" />
        <path d="M20.4 26.4 16.6 25.4M43.6 26.4 47.4 25.4" stroke={INK} strokeWidth="1.4" strokeLinecap="round" fill="none" />
      </>
    ),
    tie: (
      <>
        <path d="M27.5 48 32 52.5 36.5 48" fill="none" stroke={INK} strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M32 52.5 29.8 56 32 62 34.2 56Z" fill="#3A4A6B" />
      </>
    ),
    lanyard: (
      <>
        <path d="M27 48 31.2 56M37 48 32.8 56" stroke={INK} strokeWidth="1.5" strokeLinecap="round" fill="none" />
        <rect x="28.8" y="55" width="6.4" height="8.5" rx="1.2" fill="#fff" stroke={INK} strokeWidth="1.4" />
        <path d="M30.4 58h3.2" stroke={INK} strokeWidth="1.2" strokeLinecap="round" fill="none" />
      </>
    ),
  },
};
