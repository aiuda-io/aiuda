"use client";

import Link from "next/link";
import { BUCKET_META } from "@/lib/api";
import { WaText } from "@/components/wa-text";
import { esLargo } from "@/components/hoy/tipos";

/** El tramo de antigüedad dicho sin raya: "Vencida 1 a 15 d". */
export function etiquetaTramo(bucket: string): string {
  return (BUCKET_META[bucket]?.label ?? bucket).replace("–", " a ");
}

/** Marca de estado: un punto y la palabra. El color va solo en el punto. */
export function Marca({
  color,
  children,
}: {
  color?: "ok" | "warn" | "danger" | "accent";
  children: React.ReactNode;
}) {
  return (
    <span
      className="mark"
      style={color ? ({ "--mark": `var(--color-${color})` } as React.CSSProperties) : undefined}
    >
      {children}
    </span>
  );
}

/** Marca de antigüedad de una factura, con el color de su tramo. */
export function Tramo({ bucket }: { bucket: string }) {
  const barra = BUCKET_META[bucket]?.bar ?? "bg-ink-3";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-rotulo font-medium text-ink-2">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${barra}`} />
      {etiquetaTramo(bucket)}
    </span>
  );
}

/** Encabezado de una sección de Hoy: título con su número y, a la derecha, lo que quepa. */
export function Seccion({
  titulo,
  n,
  nota,
  derecha,
  children,
}: {
  titulo: string;
  n?: number;
  nota?: string;
  derecha?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-12">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 className="text-seccion font-semibold text-ink">
          {titulo}
          {typeof n === "number" && <span className="tnum font-normal text-ink-3"> ({n})</span>}
        </h2>
        {derecha}
      </div>
      {nota && <p className="mt-1 max-w-xl text-cuerpo text-ink-2">{nota}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Primera línea de un renglón: de quién es y cuánto. El nombre lleva a su ficha. */
export function Cabeza({
  nombre,
  clienteId,
  monto,
  children,
}: {
  nombre: string;
  clienteId?: string | null;
  monto?: string | null;
  /** La línea de datos de abajo (qué es, folio, atraso, quién lo redactó). */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-x-4">
      <div className="min-w-0">
        {clienteId ? (
          <Link
            href={`/clientes/detalle?id=${clienteId}`}
            className="text-seccion font-semibold text-ink underline-offset-2 hover:text-accent-ink hover:underline"
          >
            {nombre}
          </Link>
        ) : (
          <p className="text-seccion font-semibold text-ink">{nombre}</p>
        )}
        {children && (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-apoyo text-ink-3">
            {children}
          </div>
        )}
      </div>
      {monto && <p className="tnum shrink-0 text-seccion font-semibold text-ink">{monto}</p>}
    </div>
  );
}

/** El mensaje tal como lo va a leer el cliente. Si es largo enseña los primeros
 *  renglones y se abre en el mismo lugar: leer no cuesta cambiar de pantalla. */
export function TextoMensaje({
  texto,
  abierto,
  onAbrir,
}: {
  texto: string;
  abierto: boolean;
  onAbrir: (abierto: boolean) => void;
}) {
  const largo = esLargo(texto);
  return (
    <div className="max-w-2xl rounded-[14px] bg-panel px-4 py-3">
      <WaText
        className={`break-words text-cuerpo leading-relaxed text-ink ${
          largo && !abierto ? "line-clamp-4" : ""
        }`}
      >
        {texto}
      </WaText>
      {largo && (
        <button
          type="button"
          onClick={() => onAbrir(!abierto)}
          aria-expanded={abierto}
          className="mt-2 text-apoyo font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          {abierto ? "Ver menos" : "Ver completo"}
        </button>
      )}
    </div>
  );
}

/** Un renglón de cualquiera de las listas: raya fina arriba, sin caja. */
export function Fila({
  id,
  saliendo,
  children,
}: {
  id: string;
  saliendo?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li
      id={id}
      className={`scroll-mt-24 border-t border-line py-6 first:border-t-0 first:pt-2 ${
        saliendo ? "row-leaving" : ""
      }`}
    >
      {children}
    </li>
  );
}
