// Apariencia de un ayudante: color de acento + cara por capas (pelo, ojos, boca, sombrero,
// accesorio) + símbolo de rol en la esquina. Todos los ayudantes comparten la misma silueta de
// mascota; las partes y el color hacen que cada uno se sienta suyo. Este módulo es data pura
// (sin JSX): los SVG de las partes viven en components/avatar-parts.tsx y el del badge en
// components/role-icon.tsx.

/** Paleta sobria de tonos medios: la mascota blanca contrasta bien sobre cualquiera. */
export const ACCENT_COLORS = [
  "#2C6E8F", // teal
  "#5A4A9C", // violeta
  "#4A7A45", // verde
  "#A66A3A", // ámbar
  "#3A5E8F", // azul
  "#9C4A6A", // vino
  "#5B6B7A", // pizarra
  "#A85A4A", // terracota
];

/** Símbolos disponibles para el badge (los 8 de rol + algunos neutrales). */
export const SYMBOL_KEYS = [
  "coins", "cart", "scale", "chat", "reconcile", "box", "pen", "target",
  "spark", "bolt", "star", "leaf",
] as const;

/** Categorías de la cara, en el orden en que se muestran las filas del picker. */
export const PART_META = [
  { cat: "hair", label: "Pelo" },
  { cat: "eyes", label: "Ojos" },
  { cat: "mouth", label: "Boca" },
  { cat: "hat", label: "Sombrero" },
  { cat: "accessory", label: "Accesorio" },
] as const;

export type PartCategory = (typeof PART_META)[number]["cat"];

/** Variantes por categoría ("none" = sin esa parte). Deben coincidir 1:1 con AVATAR_PARTS. */
export const PART_KEYS: Record<PartCategory, readonly string[]> = {
  hair: ["none", "short", "side-part", "bob", "bun", "textured"],
  eyes: ["dot", "round-soft", "line", "wide", "pixel"],
  mouth: ["smile-soft", "flat", "line-smile", "o-talk", "none"],
  hat: ["none", "cap", "beanie", "hard-hat", "headset"],
  accessory: ["none", "glasses", "glasses-round", "tie", "lanyard"],
};

/** Apariencia plana (serializable; updateAyudante hace shallow-merge sobre estos campos). */
export type Appearance = {
  /** Índice en ACCENT_COLORS. */
  color: number;
  hair: string;
  eyes: string;
  mouth: string;
  hat: string;
  accessory: string;
  /** Badge de rol opcional (capa de esquina, no parte de la cara). */
  symbol?: string;
};

/** Cara default = la mascota de siempre, aplanada (ojos punto + sonrisa, sin pelo/sombrero/accesorio). */
export const DEFAULT_APPEARANCE: Appearance = {
  color: 0,
  hair: "none",
  eyes: "dot",
  mouth: "smile-soft",
  hat: "none",
  accessory: "none",
};

/**
 * Completa una apariencia parcial con la cara default. Total e idempotente: records viejos
 * `{color, symbol}` salen como Appearance completa, conservando el symbol. Tolera ids
 * desconocidos (el compositor cae a default por capa).
 */
export function normalizeAppearance(p?: Partial<Appearance> | null): Appearance {
  return {
    color: typeof p?.color === "number" ? p.color : DEFAULT_APPEARANCE.color,
    hair: p?.hair ?? DEFAULT_APPEARANCE.hair,
    eyes: p?.eyes ?? DEFAULT_APPEARANCE.eyes,
    mouth: p?.mouth ?? DEFAULT_APPEARANCE.mouth,
    hat: p?.hat ?? DEFAULT_APPEARANCE.hat,
    accessory: p?.accessory ?? DEFAULT_APPEARANCE.accessory,
    symbol: p?.symbol,
  };
}

/** Cara completa determinista por perfil (slug) — plantillas y agentes del backend. */
const PERFIL_LOOK: Record<string, Appearance> = {
  // Cobranza — analista con lentes
  mariana: { color: 0, hair: "bob", eyes: "round-soft", mouth: "smile-soft", hat: "none", accessory: "glasses", symbol: "coins" },
  // Ventas — afable, sonrisa
  carlos: { color: 3, hair: "short", eyes: "dot", mouth: "line-smile", hat: "none", accessory: "none", symbol: "cart" },
  // Legal y fiscal — formal, lentes redondos
  lupita: { color: 1, hair: "bun", eyes: "round-soft", mouth: "flat", hat: "none", accessory: "glasses-round", symbol: "scale" },
  // Recepción — headset
  valeria: { color: 4, hair: "bob", eyes: "dot", mouth: "smile-soft", hat: "headset", accessory: "none", symbol: "chat" },
  // Conciliación — neutro, lentes
  diego: { color: 2, hair: "short", eyes: "dot", mouth: "flat", hat: "none", accessory: "glasses", symbol: "reconcile" },
  // Compras — casco de obra
  roberto: { color: 5, hair: "none", eyes: "dot", mouth: "flat", hat: "hard-hat", accessory: "lanyard", symbol: "box" },
  // Contenido — creativo, pelo con textura
  memo: { color: 7, hair: "textured", eyes: "line", mouth: "o-talk", hat: "none", accessory: "none", symbol: "pen" },
  // Prospección — lentes, sonrisa
  sofia: { color: 6, hair: "bun", eyes: "dot", mouth: "smile-soft", hat: "none", accessory: "glasses", symbol: "target" },
};

// Alias por slug de ROL: el catálogo capability-first usa "cobranza", "ventas"… (no
// nombres de persona). Mismas caras curadas, para que las plantillas se vean iguales.
for (const [persona, rol] of [
  ["mariana", "cobranza"], ["carlos", "ventas"], ["lupita", "legal"],
  ["valeria", "recepcion"], ["diego", "conciliacion"], ["roberto", "compras"],
  ["memo", "contenido"], ["sofia", "prospeccion"],
] as const) {
  PERFIL_LOOK[rol] = PERFIL_LOOK[persona];
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

function pick(keys: readonly string[], slug: string, salt: string): string {
  return keys[hash(`${slug}:${salt}`) % keys.length];
}

/**
 * Apariencia de un agente/plantilla por su slug (determinista y estable entre sesiones). Los 8
 * roles conocidos traen una cara curada; los demás varían pelo/ojos/boca/lentes por hash, pero
 * sin sombrero (los sombreros se reservan a los presets de rol para no verse disfraz).
 */
export function appearanceForSlug(slug: string): Appearance {
  return (
    PERFIL_LOOK[slug] ?? {
      color: hash(slug) % ACCENT_COLORS.length,
      hair: pick(PART_KEYS.hair, slug, "hair"),
      eyes: pick(PART_KEYS.eyes, slug, "eyes"),
      mouth: pick(PART_KEYS.mouth, slug, "mouth"),
      hat: "none",
      accessory: pick(["none", "glasses", "glasses-round"], slug, "acc"),
      symbol: "spark",
    }
  );
}

/** Apariencia por defecto al crear un ayudante: toma el perfil de su primera aiudita. */
export function lookForAiuditas(ids: string[], fallbackColor = 0): Appearance {
  if (ids.length > 0) return appearanceForSlug(ids[0].split(".")[0]);
  return normalizeAppearance({ color: fallbackColor % ACCENT_COLORS.length, symbol: "spark" });
}
