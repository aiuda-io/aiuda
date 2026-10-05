"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/components/ui";
import { toast } from "@/components/toast";
import {
  esDeHoy,
  instante,
  idMensaje,
  idPago,
  idPromesa,
  type Ejecutar,
  type Mensaje,
  type Renglon,
} from "@/components/hoy/tipos";

/** Un rechazado se queda a la vista una semana por si se corrige; después vive en
 *  "Ver todo lo enviado". Lo fallido y lo que espera canal no caducan: piden acción. */
const DIAS_RECHAZADO_A_LA_VISTA = 7;

function reciente(iso: string | null | undefined, dias: number): boolean {
  const d = instante(iso);
  if (!d) return true; // sin fecha no se esconde nada
  return Date.now() - d.getTime() < dias * 86_400_000;
}

/** Todo lo que Hoy lee y las tres listas que pinta.
 *
 *  No hay un endpoint único: se juntan los que ya existen. El número N NO se calcula
 *  aquí: viene en `cartera.espera_tu_ok`, y la lista "Por aprobar" se arma con la
 *  misma regla del server (`pide_decision` en cada mensaje, `vencida` en cada
 *  promesa), así que pinta exactamente N renglones.
 *
 *  `abrir` es el id de un mensaje que llegó por liga (`/?r=<id>`): se incluye aunque
 *  ya no sea de hoy, para que la liga nunca caiga en una pantalla sin él.
 */
export function useHoy(abrir: string | null) {
  const { data, error, loading, refetch, refetchQuiet } = useApi(async () => {
    const [cartera, pendientes, pagos, promesas, enviados, aprobados, rechazados, fallidos, prueba] =
      await Promise.all([
        api.cartera(),
        api.reminders("pending_approval") as Promise<Mensaje[]>,
        api.reconciliation(),
        api.promises("active"),
        api.reminders("sent") as Promise<Mensaje[]>,
        // Aprobados que no han salido: en modo de prueba TODO queda aquí, y sin canal
        // conectado también. Sin esto, al aprobar el mensaje desaparecía de la pantalla.
        api.reminders("approved") as Promise<Mensaje[]>,
        api.reminders("rejected") as Promise<Mensaje[]>,
        // Fallidos: el envío se intentó y no salió. Se enseñan para que no desaparezcan
        // en silencio; si no, parecería que todo salió bien.
        api.reminders("failed") as Promise<Mensaje[]>,
        api.shadowMode().catch(() => ({ modo_sombra: false })),
      ]);
    return {
      cartera,
      pendientes,
      pagos: pagos.pending,
      promesas,
      enviados,
      aprobados,
      rechazados,
      fallidos,
      prueba: prueba.modo_sombra,
    };
  }, []);

  const [ocupado, setOcupado] = useState(false);
  // Renglones que se están resolviendo: colapsan con .row-leaving mientras se vuelve
  // a bajar la lista. Solo tras confirmar el server (no es optimista: es cobranza real).
  const [saliendo, setSaliendo] = useState<Set<string>>(new Set());

  const porAprobar = useMemo<Renglon[]>(() => {
    if (!data) return [];
    return [
      ...data.pendientes
        .filter((m) => m.pide_decision !== false)
        .map((m): Renglon => ({ clase: "mensaje", id: idMensaje(m), mensaje: m })),
      ...data.pagos.map((p): Renglon => ({ clase: "pago", id: idPago(p), pago: p })),
      ...data.promesas
        .filter((p) => p.vencida)
        .map((p): Renglon => ({ clase: "promesa", id: idPromesa(p), promesa: p })),
    ];
  }, [data]);

  // "No salió": primero lo que falló (pide atención), luego lo aprobado que sigue
  // detenido, lo que ya no hace falta y, al final, lo rechazado reciente.
  const noSalio = useMemo<Mensaje[]>(() => {
    if (!data) return [];
    const yaNoHaceFalta = data.pendientes.filter((m) => m.pide_decision === false);
    const rechazados = data.rechazados.filter(
      // Un rechazado de una factura que ya se cerró no tiene nada que corregir.
      (m) =>
        m.id === abrir ||
        (m.factura_abierta !== false && reciente(m.updated_at, DIAS_RECHAZADO_A_LA_VISTA)),
    );
    return [...data.fallidos, ...data.aprobados, ...yaNoHaceFalta, ...rechazados];
  }, [data, abrir]);

  // "Enviado" solo lista lo que salió DE VERDAD (sent_at real), y solo lo de hoy.
  const enviado = useMemo<Mensaje[]>(() => {
    if (!data) return [];
    return data.enviados
      .filter((m) => m.sent_at && (esDeHoy(m.sent_at) || m.id === abrir))
      .sort((a, b) => (b.sent_at ?? "").localeCompare(a.sent_at ?? ""));
  }, [data, abrir]);

  // Lo aprobado con canal listo sale en segundo plano: unos segundos después ya es
  // "Enviado" o "No salió" con su motivo. Se vuelve a preguntar un par de veces para
  // que el renglón no se quede diciendo "en camino" hasta que el dueño recargue.
  const prueba = data?.prueba ?? false;
  const enCamino = !prueba && (data?.aprobados ?? []).some((m) => !m.pendiente);
  const intentos = useRef(0);
  useEffect(() => {
    if (!enCamino) {
      intentos.current = 0;
      return;
    }
    if (intentos.current >= 4) return;
    const t = setTimeout(() => {
      intentos.current += 1;
      refetchQuiet();
    }, 2500);
    return () => clearTimeout(t);
  }, [enCamino, data, refetchQuiet]);

  const ejecutar = useCallback<Ejecutar>(
    async (fn, ok, saleId) => {
      setOcupado(true);
      try {
        const res = await fn();
        toast(typeof ok === "function" ? ok(res) : ok, "success");
        if (saleId) {
          setSaliendo((s) => new Set(s).add(saleId));
          // Colapsa y a los 250 ms refresca en silencio (sin parpadeo de esqueletos).
          // La marca se quita cuando llegó el dato nuevo: si el renglón se fue, ya no
          // está; si no se fue (raro), reaparece, que es lo honesto.
          setTimeout(() => {
            refetchQuiet().finally(() =>
              setSaliendo((s) => {
                const n = new Set(s);
                n.delete(saleId);
                return n;
              }),
            );
          }, 250);
        } else {
          refetchQuiet();
        }
        return true;
      } catch (e) {
        toast((e as Error).message, "error");
        return false;
      } finally {
        setOcupado(false);
      }
    },
    [refetchQuiet],
  );

  return {
    data,
    error,
    loading,
    refetch,
    refetchQuiet,
    prueba,
    porAprobar,
    noSalio,
    enviado,
    ocupado,
    saliendo,
    ejecutar,
  };
}
