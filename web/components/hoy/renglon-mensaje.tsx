"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { dinero } from "@/lib/cartera";
import { fechaDM, telefonoMx } from "@/lib/format";
import { SourceBadge } from "@/components/ui";
import { Cabeza, Fila, Marca, TextoMensaje, Tramo } from "@/components/hoy/piezas";
import {
  canalPorDefecto,
  claseDe,
  destinatarioDe,
  esCorreo,
  esCotizacion,
  etiquetaCanal,
  idMensaje,
  nombreDe,
  type Ejecutar,
  type Mensaje,
} from "@/components/hoy/tipos";

/** A quién le llega, legible: el teléfono agrupado o el correo tal cual. */
export function destinoLegible(m: Mensaje): string | null {
  const d = destinatarioDe(m);
  if (!d) return null;
  return m.correo?.para ? d : telefonoMx(d) || d;
}

/** Los datos de un mensaje bajo el nombre del cliente. Un recordatorio trae folio y
 *  atraso; una cotización o una respuesta de correo no tienen factura detrás. */
export function DatosMensaje({ m }: { m: Mensaje }) {
  const conFactura = !esCotizacion(m) && !esCorreo(m);
  return (
    <>
      <span className="font-medium text-ink-2">{claseDe(m)}</span>
      {conFactura && m.folio && <span className="tnum">Factura {m.folio}</span>}
      {conFactura && <Tramo bucket={m.bucket} />}
      {conFactura && m.due_date && <span className="tnum">vence {fechaDM(m.due_date)}</span>}
      {!conFactura && m.title && m.customer && <span>{m.title}</span>}
      {/* Trazabilidad: qué ayudante del dueño lo redactó y de qué fuente sale el dato. */}
      {m.propuesto_por && <span>de {m.propuesto_por}</span>}
      {m.procedencia && (
        <SourceBadge source={m.procedencia.source} presence={m.procedencia.presence} />
      )}
    </>
  );
}

/** Un mensaje que espera decisión: se lee aquí mismo y se aprueba, se edita o se
 *  rechaza sin cambiar de pantalla. También sirve para corregir uno rechazado
 *  (`corregir`): mismas acciones, sin volver a rechazar. */
export function RenglonMensaje({
  m,
  prueba,
  ocupado,
  saliendo,
  ejecutar,
  corregir,
  abiertoDeInicio,
}: {
  m: Mensaje;
  prueba: boolean;
  ocupado: boolean;
  saliendo: boolean;
  ejecutar: Ejecutar;
  corregir?: boolean;
  abiertoDeInicio?: boolean;
}) {
  const id = idMensaje(m);
  const [abierto, setAbierto] = useState(Boolean(abiertoDeInicio));
  // null = se lee; un texto = el dueño lo está editando.
  const [borrador, setBorrador] = useState<string | null>(null);
  const [porRechazar, setPorRechazar] = useState(false);
  const [canalElegido, setCanalElegido] = useState<string | null>(null);

  const conectados = m.channels.filter((c) => c.connected);
  const canal = canalElegido ?? canalPorDefecto(m);
  const destino = destinoLegible(m);
  const quieto = ocupado || saliendo; // no volver a accionar lo que ya se está resolviendo

  const aprobar = () =>
    ejecutar(
      () => api.approve(m.id, canal, borrador ?? undefined),
      // El aviso dice lo que DE VERDAD pasó. En modo de prueba nada sale, haya canal
      // o no. Sin canal conectado el server responde "se enviará cuando conectes…"
      // (queda aprobado, no enviado).
      (res) =>
        prueba
          ? "Aprobado en modo de prueba. No se envió."
          : (res.aviso ?? `Aprobado. Enviando a ${destino ?? etiquetaCanal(m, canal)}.`),
      id,
    );

  const rechazar = () =>
    ejecutar(
      () => api.reject(m.id),
      "Rechazado. No se envía; queda en No salió por si lo corriges.",
      id,
    );

  return (
    <Fila id={id} saliendo={saliendo}>
      <Cabeza
        nombre={nombreDe(m)}
        clienteId={m.customer_id}
        monto={m.amount != null ? dinero(m.amount, m.currency) : null}
      >
        {corregir && <Marca>Lo rechazaste</Marca>}
        <DatosMensaje m={m} />
      </Cabeza>

      <div className="mt-4">
        {borrador === null ? (
          <TextoMensaje texto={m.message} abierto={abierto} onAbrir={setAbierto} />
        ) : (
          <div className="max-w-2xl">
            <textarea
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              rows={Math.min(12, Math.max(4, borrador.split("\n").length + 2))}
              autoFocus
              aria-label={`Mensaje para ${nombreDe(m)}`}
              className="field resize-y leading-relaxed focus:border-accent focus:outline-none"
            />
            <p className="mt-1.5 text-apoyo text-ink-3">
              Se envía tu versión. Tu ayudante aprende de tus cambios.
            </p>
          </div>
        )}
      </div>

      <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-apoyo text-ink-3">
        {conectados.length === 0 ? (
          <>
            <span>Sin canal conectado para este cliente: al aprobar queda listo y sale cuando lo conectes.</span>
            <Link
              href="/configuracion?seccion=conexiones"
              className="font-medium text-accent-ink underline-offset-2 hover:underline"
            >
              Conexiones
            </Link>
          </>
        ) : conectados.length === 1 ? (
          <span>
            Sale por {conectados[0].label}
            {destino ? ` a ${destino}` : ""}
          </span>
        ) : (
          <>
            <span>Sale por</span>
            {conectados.map((c) => (
              <button
                key={c.key}
                type="button"
                aria-pressed={canal === c.key}
                onClick={() => setCanalElegido(c.key)}
                className={`rounded-md px-2 py-0.5 text-apoyo font-medium ${
                  canal === c.key
                    ? "bg-accent-soft text-accent-ink"
                    : "text-ink-2 hover:bg-fill hover:text-ink"
                }`}
              >
                {c.label}
              </button>
            ))}
          </>
        )}
      </p>

      {porRechazar ? (
        <div className="mt-4">
          <p className="text-cuerpo text-ink-2">
            ¿Rechazar este mensaje? No se envía. Queda en No salió por si lo corriges.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={rechazar} disabled={quieto} className="btn btn-danger">
              Sí, rechazar
            </button>
            <button
              type="button"
              onClick={() => setPorRechazar(false)}
              disabled={quieto}
              className="btn btn-quiet"
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" onClick={aprobar} disabled={quieto} className="btn btn-primary">
            {prueba ? "Aprobar (prueba, no se envía)" : "Aprobar y enviar"}
          </button>
          {borrador === null ? (
            <>
              <button
                type="button"
                onClick={() => setBorrador(m.message)}
                disabled={quieto}
                className="btn btn-quiet"
              >
                Editar
              </button>
              {!corregir && (
                <button
                  type="button"
                  onClick={() => setPorRechazar(true)}
                  disabled={quieto}
                  className="btn btn-quiet"
                >
                  Rechazar
                </button>
              )}
            </>
          ) : (
            <button
              type="button"
              onClick={() => setBorrador(null)}
              disabled={quieto}
              className="btn btn-quiet"
            >
              Cancelar cambios
            </button>
          )}
        </div>
      )}
    </Fila>
  );
}
