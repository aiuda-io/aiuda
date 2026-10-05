"use client";

import { useState } from "react";
import Link from "next/link";
import { mxn } from "@/lib/api";
import { Marca, Seccion, TextoMensaje } from "@/components/hoy/piezas";
import { destinoLegible } from "@/components/hoy/renglon-mensaje";
import {
  claseDe,
  diaYHora,
  etiquetaCanal,
  haceRato,
  idMensaje,
  nombreDe,
  type Mensaje,
} from "@/components/hoy/tipos";

/** Un mensaje que ya salió: quién, cuánto, por dónde y cuándo, con su texto a un clic.
 *  `conFecha` pone la fecha completa (historial); sin él dice "hace 2 h" (lo de hoy). */
export function RenglonEnviado({
  m,
  abiertoDeInicio,
  conFecha,
}: {
  m: Mensaje;
  abiertoDeInicio?: boolean;
  conFecha?: boolean;
}) {
  const [ver, setVer] = useState(Boolean(abiertoDeInicio));
  const [abierto, setAbierto] = useState(true);
  const destino = destinoLegible(m);
  return (
    <li id={idMensaje(m)} className="scroll-mt-24 border-t border-line py-4 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          {m.customer_id ? (
            <Link
              href={`/clientes/detalle?id=${m.customer_id}`}
              className="text-cuerpo font-semibold text-ink underline-offset-2 hover:text-accent-ink hover:underline"
            >
              {nombreDe(m)}
            </Link>
          ) : (
            <span className="text-cuerpo font-semibold text-ink">{nombreDe(m)}</span>
          )}
          <span className="ml-2 text-apoyo text-ink-3">
            {claseDe(m)}
            {m.folio ? ` · Factura ${m.folio}` : ""}
          </span>
        </div>
        {m.amount != null && (
          <span className="tnum text-cuerpo font-medium text-ink">{mxn(m.amount)}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-apoyo text-ink-3">
        <Marca color="ok">
          Enviado {conFecha ? diaYHora(m.sent_at) : haceRato(m.sent_at)}
        </Marca>
        <span>
          por {etiquetaCanal(m, m.channel)}
          {destino ? ` a ${destino}` : ""}
        </span>
        <button
          type="button"
          onClick={() => setVer((v) => !v)}
          aria-expanded={ver}
          className="font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          {ver ? "Ocultar mensaje" : "Ver mensaje"}
        </button>
      </div>
      {ver && (
        <div className="mt-3">
          <TextoMensaje texto={m.message} abierto={abierto} onAbrir={setAbierto} />
        </div>
      )}
    </li>
  );
}

/** Lo que salió hoy de verdad. El historial completo vive en /actividad. */
export function Enviado({ mensajes, abrir }: { mensajes: Mensaje[]; abrir: string | null }) {
  return (
    <Seccion
      titulo="Enviado"
      n={mensajes.length > 0 ? mensajes.length : undefined}
      derecha={
        <Link
          href="/actividad"
          className="text-cuerpo font-medium text-accent-ink underline-offset-2 hover:underline"
        >
          Ver todo lo enviado
        </Link>
      }
    >
      {mensajes.length === 0 ? (
        <p className="text-cuerpo text-ink-3">Hoy todavía no sale ningún mensaje.</p>
      ) : (
        <ul>
          {mensajes.map((m) => (
            <RenglonEnviado key={m.id} m={m} abiertoDeInicio={m.id === abrir} />
          ))}
        </ul>
      )}
    </Seccion>
  );
}
