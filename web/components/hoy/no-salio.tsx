"use client";

import { useState } from "react";
import Link from "next/link";
import { api, mxn } from "@/lib/api";
import { Cabeza, Fila, Marca, Seccion, TextoMensaje } from "@/components/hoy/piezas";
import { DatosMensaje, RenglonMensaje, destinoLegible } from "@/components/hoy/renglon-mensaje";
import {
  canalPorDefecto,
  etiquetaCanal,
  idMensaje,
  nombreDe,
  type Ejecutar,
  type Mensaje,
} from "@/components/hoy/tipos";

const ligaCls = "font-medium text-accent-ink underline-offset-2 hover:underline";

/** Por qué no se pudo enviar, en una oración completa. Un motivo que ya es una
 *  oración (los de WhatsApp dicen qué hacer) va solo; a los cortos se les agrega el
 *  consejo de siempre. */
function motivoDelFallo(m: Mensaje): string {
  const a = destinoLegible(m) ?? "el destinatario";
  const motivo = (m.motivo_fallo ?? "").trim();
  if (!motivo) return `No se pudo enviar a ${a}. Revisa la conexión y vuelve a intentar.`;
  if (motivo.endsWith(".")) return `No se pudo enviar a ${a}. ${motivo}`;
  return `No se pudo enviar a ${a}: ${motivo}. Revisa la conexión y vuelve a intentar.`;
}

/** Lo que se aprobó o se redactó y no llegó al cliente, con su motivo y lo que se
 *  puede hacer. Existe para que nada desaparezca en silencio: sin esta sección un
 *  envío fallido se vería igual que uno que salió bien. */
export function NoSalio({
  mensajes,
  prueba,
  ocupado,
  saliendo,
  ejecutar,
  abrir,
}: {
  mensajes: Mensaje[];
  prueba: boolean;
  ocupado: boolean;
  saliendo: Set<string>;
  ejecutar: Ejecutar;
  abrir: string | null;
}) {
  if (mensajes.length === 0) return null;
  return (
    <Seccion titulo="No salió" n={mensajes.length}>
      <ul>
        {mensajes.map((m) =>
          // Un rechazado que se puede corregir es un mensaje con sus acciones de siempre.
          m.status === "rejected" && !m.retirado && m.factura_abierta !== false ? (
            <RenglonMensaje
              key={m.id}
              m={m}
              prueba={prueba}
              ocupado={ocupado}
              saliendo={saliendo.has(idMensaje(m))}
              ejecutar={ejecutar}
              corregir
              abiertoDeInicio={m.id === abrir}
            />
          ) : (
            <Detenido
              key={m.id}
              m={m}
              prueba={prueba}
              ocupado={ocupado}
              saliendo={saliendo.has(idMensaje(m))}
              ejecutar={ejecutar}
              abiertoDeInicio={m.id === abrir}
            />
          ),
        )}
      </ul>
    </Seccion>
  );
}

function Detenido({
  m,
  prueba,
  ocupado,
  saliendo,
  ejecutar,
  abiertoDeInicio,
}: {
  m: Mensaje;
  prueba: boolean;
  ocupado: boolean;
  saliendo: boolean;
  ejecutar: Ejecutar;
  abiertoDeInicio: boolean;
}) {
  const id = idMensaje(m);
  const [verTexto, setVerTexto] = useState(abiertoDeInicio);
  const [abierto, setAbierto] = useState(abiertoDeInicio);
  const quieto = ocupado || saliendo;
  const a = destinoLegible(m) ?? "el destinatario";
  const canal = canalPorDefecto(m);

  let marca: React.ReactNode;
  let motivo: string;
  let accion: React.ReactNode = null;
  let liga: React.ReactNode = null;

  if (m.factura_abierta === false && m.status !== "rejected") {
    // La factura se pagó o se canceló después de redactarlo (o de aprobarlo): cobrarla
    // sería un error, así que aquí no se ofrece enviarlo. Un borrador se puede descartar.
    marca = <Marca>Ya no hace falta</Marca>;
    motivo = "La factura ya no está abierta, así que este recordatorio no se debe enviar.";
    if (m.status === "pending_approval") {
      accion = (
        <button
          type="button"
          disabled={quieto}
          onClick={() => ejecutar(() => api.reject(m.id), "Descartado.", id)}
          className="btn btn-secondary"
        >
          Descartar
        </button>
      );
    }
  } else if (m.status === "failed") {
    marca = <Marca color="danger">Falló el envío</Marca>;
    motivo = motivoDelFallo(m);
    accion = (
      <button
        type="button"
        disabled={quieto}
        onClick={() =>
          ejecutar(
            () => api.approve(m.id, canal),
            (res) => res.aviso ?? `Reintentando el envío a ${a}.`,
            id,
          )
        }
        className="btn btn-primary"
      >
        Reintentar envío
      </button>
    );
    liga = (
      <Link href="/configuracion?seccion=conexiones" className="btn btn-quiet">
        Revisar conexiones
      </Link>
    );
  } else if (m.status === "approved" && prueba) {
    marca = <Marca color="warn">Modo de prueba</Marca>;
    motivo = `Lo aprobaste en modo de prueba, así que no se envió a ${a}. Apaga el modo de prueba para poder enviarlo.`;
    liga = (
      <Link href="/configuracion" className="btn btn-quiet">
        Ir a Ajustes
      </Link>
    );
  } else if (m.status === "approved") {
    const esperaCanal = Boolean(m.pendiente);
    marca = esperaCanal ? (
      <Marca color="warn">Esperando canal</Marca>
    ) : (
      <Marca color="accent">Aprobado, sin enviar</Marca>
    );
    motivo = m.pendiente ?? `Está aprobado y todavía no sale a ${a}.`;
    accion = (
      <button
        type="button"
        disabled={quieto}
        onClick={() =>
          ejecutar(
            () => api.sendReminder(m.id),
            // El server no dice aquí si hay canal: si ya estaba esperando uno, lo
            // honesto es decir que se volvió a intentar, no que ya va en camino.
            esperaCanal
              ? "Se volvió a intentar. Si el canal sigue sin conectar, se queda aquí esperando."
              : `Enviando a ${destinoLegible(m) ?? etiquetaCanal(m, canal)}.`,
            id,
          )
        }
        className="btn btn-primary"
      >
        Enviar ahora
      </button>
    );
    if (esperaCanal) {
      liga = (
        <Link href="/configuracion?seccion=conexiones" className="btn btn-quiet">
          Conectar canal
        </Link>
      );
    }
  } else {
    // Rechazado: por aiuda (la factura dejó de cobrarse) o por el dueño, de una
    // factura que después se cerró. Solo llega aquí por liga directa.
    marca = <Marca>{m.retirado ? "Retirado" : "Lo rechazaste"}</Marca>;
    motivo = m.retirado
      ? `aiuda lo retiró y no se envía. ${m.retirado}`
      : "Lo rechazaste y la factura ya no está abierta: no hay nada que corregir.";
  }

  return (
    <Fila id={id} saliendo={saliendo}>
      <Cabeza
        nombre={nombreDe(m)}
        clienteId={m.customer_id}
        monto={m.amount != null ? mxn(m.amount) : null}
      >
        {marca}
        <DatosMensaje m={m} />
      </Cabeza>
      <p className="mt-3 max-w-2xl text-cuerpo leading-relaxed text-ink-2">{motivo}</p>
      {verTexto && (
        <div className="mt-3">
          <TextoMensaje texto={m.message} abierto={abierto} onAbrir={setAbierto} />
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {accion}
        {liga}
        <button
          type="button"
          onClick={() => setVerTexto((v) => !v)}
          aria-expanded={verTexto}
          className={`px-2 text-apoyo ${ligaCls}`}
        >
          {verTexto ? "Ocultar mensaje" : "Ver mensaje"}
        </button>
      </div>
    </Fila>
  );
}
