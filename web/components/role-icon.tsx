import type { ReactNode } from "react";

// Iconos de rol (línea, 18px viewBox, monocromáticos) para el badge del avatar.
// Mismo estilo que los iconos de la sidebar. El color lo hereda del contenedor
// (currentColor), así el símbolo toma el color de acento del ayudante.
function svg(children: ReactNode) {
  return (
    <svg
      viewBox="0 0 18 18"
      className="h-full w-full"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

export const ROLE_ICONS: Record<string, ReactNode> = {
  coins: svg(<><circle cx="6.8" cy="7" r="3.6" /><path d="M9.4 4.7a3.6 3.6 0 1 1 1.8 6.6" /></>),
  cart: svg(<><path d="M2.6 3.4h1.7l1.3 6.8h6.1l1.3-4.9H5.3" /><circle cx="7.2" cy="14" r="1" /><circle cx="12" cy="14" r="1" /></>),
  scale: svg(<><path d="M9 3v11M5.2 14h7.6" /><path d="M3.4 6.4h11.2M3.4 6.4 5.4 10H1.4zM14.6 6.4 12.6 10h4z" /></>),
  chat: svg(<><path d="M3 4.4h12v7.4H8.2L5 14.2v-2.4H3z" /></>),
  reconcile: svg(<><path d="M3 6.6h9M9.6 4.2 12 6.6 9.6 9" /><path d="M15 11.4H6M8.4 9l-2.4 2.4L8.4 13.8" /></>),
  box: svg(<><path d="M9 2.7 15 5.6v6.8L9 15.3 3 12.4V5.6z" /><path d="M3 5.6 9 8.5l6-2.9M9 8.5v6.8" /></>),
  pen: svg(<><path d="M11.4 3.2 14.8 6.6 6.3 15H3v-3.3z" /><path d="M10 4.6 13.4 8" /></>),
  target: svg(<><circle cx="9" cy="9" r="5.4" /><circle cx="9" cy="9" r="2.2" /></>),
  spark: svg(<><path d="M9 2.8 10.5 7.5 15.2 9 10.5 10.5 9 15.2 7.5 10.5 2.8 9 7.5 7.5z" /></>),
  bolt: svg(<><path d="M9.8 2.4 4.6 9.6h3.8l-1 6 5.6-7.6H9.2z" /></>),
  star: svg(<><path d="M9 2.8 10.9 6.7l4.3.6-3.1 3 .8 4.3L9 12.6 5.1 14.6l.8-4.3-3.1-3 4.3-.6z" /></>),
  leaf: svg(<><path d="M4 14C4 8.5 8 4.4 14 4.4 14 9.9 10 14 4 14z" /><path d="M4 14 9.4 8.6" /></>),
};

/** Símbolo de rol que hereda el color del contenedor (currentColor). */
export function RoleIcon({ symbol, className = "" }: { symbol: string; className?: string }) {
  return <span className={`flex ${className}`}>{ROLE_ICONS[symbol] ?? ROLE_ICONS.spark}</span>;
}
