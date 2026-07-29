import { ACCENT_COLORS, DEFAULT_APPEARANCE, normalizeAppearance, type PartCategory } from "@/lib/look";
import { AVATAR_BASE, AVATAR_PARTS } from "@/components/avatar-parts";
import { RoleIcon } from "@/components/role-icon";

/**
 * Avatar de un ayudante: la mascota de aiuda compuesta por capas (base + boca + ojos + pelo +
 * sombrero + accesorio) sobre un círculo de color, con un símbolo de rol en la esquina. Todos
 * comparten la misma silueta; las partes y el color hacen que cada ayudante se sienta suyo (el
 * usuario las elige; las plantillas las traen por defecto). La cara default = la mascota de
 * siempre, aplanada.
 */
export function Avatar({
  name,
  size = 40,
  color = 0,
  symbol,
  hair,
  eyes,
  mouth,
  hat,
  accessory,
  className = "",
}: {
  /** Solo para accesibilidad (alt). */
  name?: string;
  size?: number;
  /** Índice en ACCENT_COLORS. */
  color?: number;
  /** Clave de símbolo de rol (badge). Si falta, no se dibuja badge. */
  symbol?: string;
  hair?: string;
  eyes?: string;
  mouth?: string;
  hat?: string;
  accessory?: string;
  className?: string;
}) {
  const a = normalizeAppearance({ color, symbol, hair, eyes, mouth, hat, accessory });
  const bg = ACCENT_COLORS[a.color % ACCENT_COLORS.length];
  const showBadge = !!a.symbol && size >= 34;
  const badge = Math.max(14, Math.round(size * 0.42));

  // Una parte "none" es null a propósito (no dibuja nada); solo caemos al default si el id es
  // desconocido (no existe en el registro). Por eso checamos la llave, no `?? fallback`.
  const layer = (cat: PartCategory, id: string) => {
    const parts = AVATAR_PARTS[cat];
    return parts[id in parts ? id : DEFAULT_APPEARANCE[cat]];
  };
  const showAccessory = size >= 24; // a tamaños diminutos, lentes/corbata se difuminan

  return (
    <span
      className={`relative inline-flex shrink-0 ${className}`}
      style={{ width: size, height: size }}
      aria-hidden={name ? undefined : true}
    >
      <span
        className="flex h-full w-full items-center justify-center overflow-hidden rounded-full"
        style={{ background: bg }}
      >
        <svg
          viewBox="0 0 64 64"
          className="h-full w-full"
          role={name ? "img" : undefined}
          aria-label={name ? `Ayudante ${name}` : undefined}
        >
          {/* La mascota se dibuja de borde a borde del viewBox (pelo/sombrero en y~8, el
              moño casi en y~2.6); el recorte circular se la comía arriba. Se escala al 90%
              anclada al centro-inferior (32,64): la cabeza y el sombrero ganan aire dentro
              del círculo y los hombros siguen sangrando al borde de abajo (recorte de
              retrato), sin dejar hueco. */}
          <g transform="translate(32 64) scale(0.9) translate(-32 -64)">
            {AVATAR_BASE}
            {layer("mouth", a.mouth)}
            {layer("eyes", a.eyes)}
            {layer("hair", a.hair)}
            {layer("hat", a.hat)}
            {showAccessory && layer("accessory", a.accessory)}
          </g>
        </svg>
      </span>
      {showBadge && (
        <span
          className="absolute -bottom-0.5 -right-0.5 flex items-center justify-center rounded-full bg-surface ring-1 ring-line"
          style={{ width: badge, height: badge, color: bg }}
        >
          <RoleIcon symbol={a.symbol!} className="h-[62%] w-[62%]" />
        </span>
      )}
    </span>
  );
}
