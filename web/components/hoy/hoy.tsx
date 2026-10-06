"use client";

/* Hoy: el inicio y la pantalla de trabajo diario.
 *
 * Una lista, no un tablero. Arriba, cuánto hay por cobrar. En medio, "Por aprobar (N)":
 * cada renglón enseña el mensaje y se aprueba, se edita o se rechaza ahí mismo. Luego
 * "No salió", solo si hay algo, y al final "Enviado" con lo que salió hoy.
 *
 * N lo define el server (`espera_tu_ok` de /v1/cartera) y es el mismo número del menú.
 * Cero datos de ejemplo: sin nada que enseñar, la pantalla dice qué paso falta.
 */

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { ErrorState, PageHeader, SearchInput, Skeleton, useApi } from "@/components/ui";
import { useAyudantes } from "@/lib/ayudantes-store";
import { AvisoTopeIA } from "@/components/hoy/aviso-tope-ia";
import { Cifras } from "@/components/hoy/cifras";
import { Enviado } from "@/components/hoy/enviado";
import { NoSalio } from "@/components/hoy/no-salio";
import { AvisoFaltantes, PasosQueFaltan, pasosQueFaltan } from "@/components/hoy/pasos";
import { Seccion } from "@/components/hoy/piezas";
import { RenglonMensaje } from "@/components/hoy/renglon-mensaje";
import { RenglonPago } from "@/components/hoy/renglon-pago";
import { RenglonPromesa } from "@/components/hoy/renglon-promesa";
import { nombreDe, type Renglon } from "@/components/hoy/tipos";
import { useHoy } from "@/components/hoy/use-hoy";

/** Con pocos renglones buscar estorba; con muchos, hace falta. */
const BUSCAR_DESDE = 7;

function nombreDelRenglon(r: Renglon): string {
  if (r.clase === "mensaje") return nombreDe(r.mensaje);
  if (r.clase === "promesa") return r.promesa.customer;
  return r.pago.counterparty ?? r.pago.proposal?.customer ?? "";
}

export function Hoy() {
  // Liga directa a un mensaje: /?r=<id> lo abre y baja hasta él.
  const abrir = useSearchParams().get("r");
  const hoy = useHoy(abrir);
  const { data, porAprobar, noSalio, enviado, prueba, ocupado, saliendo, ejecutar } = hoy;

  const ia = useApi(() => api.provider().catch(() => null), []);
  const { ayudantes, loading: cargandoAyudantes } = useAyudantes();
  const [buscar, setBuscar] = useState("");

  const yaBajo = useRef(false);
  useEffect(() => {
    if (yaBajo.current || !abrir || !data) return;
    yaBajo.current = true;
    document.getElementById(`r-${abrir}`)?.scrollIntoView({ block: "start" });
  }, [abrir, data]);

  if (hoy.error) return <ErrorState message={hoy.error} retry={hoy.refetch} />;

  const fecha = new Date().toLocaleDateString("es-MX", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  if (!data) {
    return (
      <div className="min-w-0">
        <PageHeader title="Hoy" subtitle={fecha} />
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
        <div className="mt-12 space-y-4">
          <Skeleton className="h-6 w-40 rounded" />
          <Skeleton className="h-32 w-full rounded-lg" />
          <Skeleton className="h-32 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  const { cartera } = data;
  const hayCartera = (cartera.open_count_todas ?? cartera.open_count) > 0 || Object.keys(cartera.by_source ?? {}).length > 0;
  const hayCifras = hayCartera || cartera.recovered_this_month > 0;
  // Hasta saber qué hay conectado no se dice que falta algo: decirlo de más espanta.
  const sabemosQueFalta = !ia.loading && !cargandoAyudantes;
  const faltan = sabemosQueFalta
    ? pasosQueFaltan({
        ia: Boolean(ia.data?.connected || ia.data?.env_fallback),
        cartera: hayCartera,
        ayudante: ayudantes.length > 0,
      })
    : [];
  const sinNada = porAprobar.length + noSalio.length + enviado.length === 0;

  const q = buscar.trim().toLowerCase();
  const visibles = q
    ? porAprobar.filter((r) => nombreDelRenglon(r).toLowerCase().includes(q))
    : porAprobar;

  return (
    <div className="min-w-0">
      <PageHeader title="Hoy" subtitle={fecha} />

      <AvisoTopeIA />

      {hayCifras && <Cifras cartera={cartera} />}

      {sinNada && faltan.length > 0 ? (
        <div className={hayCifras ? "mt-12" : ""}>
          <PasosQueFaltan pasos={faltan} />
        </div>
      ) : (
        <>
          {!sinNada && <AvisoFaltantes pasos={faltan} />}

          <Seccion
            titulo="Por aprobar"
            n={cartera.espera_tu_ok}
            nota={
              prueba && porAprobar.length > 0
                ? "Modo de prueba encendido: lo que apruebes no se envía a tus clientes."
                : undefined
            }
            derecha={
              porAprobar.length >= BUSCAR_DESDE ? (
                <SearchInput value={buscar} onChange={setBuscar} placeholder="Buscar cliente" />
              ) : undefined
            }
          >
            {porAprobar.length === 0 ? (
              <p className="text-cuerpo text-ink-2">
                Nada espera tu aprobación. Lo que redacten tus ayudantes aparece aquí.{" "}
                <Link
                  href="/facturas"
                  className="font-medium text-accent-ink underline-offset-2 hover:underline"
                >
                  Ver Cartera
                </Link>
              </p>
            ) : visibles.length === 0 ? (
              <p className="text-cuerpo text-ink-2">Ningún cliente con ese nombre espera aprobación.</p>
            ) : (
              <ul>
                {visibles.map((r, i) =>
                  r.clase === "mensaje" ? (
                    <RenglonMensaje
                      key={r.id}
                      m={r.mensaje}
                      prueba={prueba}
                      ocupado={ocupado}
                      saliendo={saliendo.has(r.id)}
                      ejecutar={ejecutar}
                      abiertoDeInicio={r.mensaje.id === abrir}
                      principal={i === 0}
                    />
                  ) : r.clase === "pago" ? (
                    <RenglonPago
                      key={r.id}
                      p={r.pago}
                      ocupado={ocupado}
                      saliendo={saliendo.has(r.id)}
                      ejecutar={ejecutar}
                      principal={i === 0}
                    />
                  ) : (
                    <RenglonPromesa
                      key={r.id}
                      p={r.promesa}
                      ocupado={ocupado}
                      saliendo={saliendo.has(r.id)}
                      ejecutar={ejecutar}
                      principal={i === 0}
                    />
                  ),
                )}
              </ul>
            )}
          </Seccion>

          <NoSalio
            mensajes={noSalio}
            prueba={prueba}
            ocupado={ocupado}
            saliendo={saliendo}
            ejecutar={ejecutar}
            abrir={abrir}
            principal={porAprobar.length === 0}
          />

          <Enviado mensajes={enviado} abrir={abrir} />
        </>
      )}
    </div>
  );
}
