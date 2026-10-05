"use client";

// Los dos documentos del SAT que aiuda baja por el dueño: opinión de cumplimiento y
// constancia de situación fiscal. Siguen un guion fijo (no usan su IA) y entran con la
// e.firma que ya guardó. Antes de la primera vez por RFC se pide su permiso; el
// servidor se niega a entrar sin él.
import Link from "next/link";
import { useState } from "react";
import { api, apiUrl, type CuaDeterministas, type RutinaSat } from "@/lib/api";
import { PrimaryButton, PrimaryLink, SecondaryButton, SinEstrenar } from "@/components/ui";
import { toast } from "@/components/toast";
import { fecha, fechaHora } from "@/lib/format";
import { Marca } from "@/components/portales/comunes";

export function DocumentosSat({
  sat,
  disponible,
  onCambio,
}: {
  sat: CuaDeterministas;
  /** ¿Esta instalación trae el navegador? Sin él no hay botones de bajar. */
  disponible: boolean;
  onCambio: () => void;
}) {
  const [ocupado, setOcupado] = useState("");
  // Hoy en hora local, como AAAA-MM-DD, para comparar con la vigencia de la e.firma.
  const ahora = new Date();
  const hoy = `${ahora.getFullYear()}-${String(ahora.getMonth() + 1).padStart(2, "0")}-${String(
    ahora.getDate(),
  ).padStart(2, "0")}`;

  const aceptar = async (rfc: string) => {
    setOcupado(`permiso:${rfc}`);
    try {
      await api.cuaAceptarConsentimiento(rfc);
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setOcupado("");
    }
  };

  const bajar = async (rfc: string, r: RutinaSat) => {
    setOcupado(`${r.capacidad}:${rfc}`);
    try {
      await api.cuaEncolar(r.capacidad, undefined, rfc);
      toast(`Bajando ${r.nombre} de ${rfc}. Tarda cerca de un minuto.`, "info");
      onCambio();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setOcupado("");
    }
  };

  return (
    <section>
      <h2 className="text-seccion font-semibold text-ink">Documentos del SAT</h2>
      <p className="mt-1 max-w-2xl text-cuerpo text-ink-2">
        aiuda entra al portal del SAT con tu e.firma y te baja el PDF. Solo consulta y descarga: no
        presenta, no firma ni acepta nada. Funciona aunque no tengas ninguna IA conectada.
      </p>

      {sat.empresas.length === 0 ? (
        // Sin navegador no tiene caso pedir la e.firma: no habría con qué usarla.
        disponible && (
        <div className="mt-6 rounded-xl bg-panel px-6 py-8 text-center">
          <p className="text-seccion font-semibold text-ink">Falta tu e.firma</p>
          <p className="mx-auto mt-2 max-w-md text-cuerpo text-ink-2">
            Para entrar al SAT por ti, aiuda necesita la e.firma de tu negocio. Se guarda cifrada en
            esta computadora.
          </p>
          <div className="mt-5">
            <PrimaryLink href="/sat">Cargar mi e.firma</PrimaryLink>
          </div>
        </div>
        )
      ) : (
        <div className="mt-6 space-y-8">
          {sat.empresas.map((e) => {
            // La vigencia viene como día (AAAA-MM-DD): vencida desde el día siguiente.
            const vencida = !!e.vigente_hasta && e.vigente_hasta.slice(0, 10) < hoy;
            const faltaPermiso = !e.consentimiento_en;
            return (
              <article key={e.rfc}>
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-line-strong pb-2">
                  <h3 className="tnum text-cuerpo font-semibold text-ink">{e.rfc}</h3>
                  <p className="min-w-0 truncate text-apoyo text-ink-3">
                    {e.nombre ? `${e.nombre} · ` : ""}
                    {vencida ? (
                      <span className="font-medium text-danger">e.firma vencida el {fecha(e.vigente_hasta)}</span>
                    ) : (
                      <>e.firma vigente hasta el {fecha(e.vigente_hasta)}</>
                    )}
                  </p>
                </div>

                {vencida && (
                  <p className="mt-3 rounded-lg bg-danger-soft px-4 py-3 text-cuerpo text-danger">
                    Con una e.firma vencida el SAT no deja entrar. Renuévala en el SAT y{" "}
                    <Link href="/sat" className="font-medium underline underline-offset-2">
                      carga la nueva
                    </Link>
                    .
                  </p>
                )}

                {disponible && !vencida && faltaPermiso && (
                  <div className="mt-3 rounded-xl bg-accent-soft px-5 py-4">
                    <p className="text-cuerpo font-semibold text-ink">Antes de la primera vez, tu permiso</p>
                    <p className="mt-1 max-w-2xl text-cuerpo text-ink-2">{sat.consentimiento_texto}</p>
                    <div className="mt-4 flex flex-wrap items-center gap-3">
                      <PrimaryButton onClick={() => aceptar(e.rfc)} disabled={ocupado === `permiso:${e.rfc}`}>
                        {ocupado === `permiso:${e.rfc}` ? "Guardando…" : "Acepto"}
                      </PrimaryButton>
                      <span className="text-apoyo text-ink-3">Se pide una sola vez para este RFC.</span>
                    </div>
                  </div>
                )}

                <ul>
                  {e.rutinas.map((r) => (
                    <Documento
                      key={r.capacidad}
                      r={r}
                      mandando={ocupado === `${r.capacidad}:${e.rfc}`}
                      puedeBajar={disponible && !vencida && !faltaPermiso}
                      onBajar={() => bajar(e.rfc, r)}
                    />
                  ))}
                </ul>
              </article>
            );
          })}
          <p className="max-w-2xl text-apoyo text-ink-3">
            Cada vez que bajas la opinión de cumplimiento, el SAT le pone un folio nuevo.
          </p>
        </div>
      )}
    </section>
  );
}

function Documento({
  r,
  mandando,
  puedeBajar,
  onBajar,
}: {
  r: RutinaSat;
  mandando: boolean;
  puedeBajar: boolean;
  onBajar: () => void;
}) {
  const doc = r.ultimo_documento;
  const intento = r.ultima_corrida;
  // Una falla solo se enseña si es más reciente que el último documento bueno.
  const fallo =
    intento?.status === "failed" && (!doc || !doc.fecha || intento.fecha > doc.fecha) ? intento : null;
  const positivo = /positiv/i.test(doc?.sentido ?? "");

  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line py-4 last:border-0">
      <div className="min-w-0 flex-1 basis-72">
        <p className="flex flex-wrap items-center gap-2 text-cuerpo font-medium text-ink">
          {r.nombre}
          {!r.estrenada && <SinEstrenar />}
        </p>
        {r.en_curso ? (
          <p className="mt-1 flex items-center gap-2 text-apoyo font-medium text-accent-ink">
            <span className="breathe h-1.5 w-1.5 rounded-full bg-accent" />
            Adentro del portal del SAT. Tarda cerca de un minuto.
          </p>
        ) : doc ? (
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-apoyo text-ink-3">
            {doc.sentido && (
              <Marca color={positivo ? "var(--color-ok)" : "var(--color-warn)"}>{doc.sentido}</Marca>
            )}
            <span className="tnum">Bajado el {fechaHora(doc.fecha)}</span>
            {doc.folio && <span className="tnum">Folio {doc.folio}</span>}
          </p>
        ) : (
          <p className="mt-1 text-apoyo text-ink-3">Aún no lo has bajado.</p>
        )}
        {fallo && !r.en_curso && (
          <p className="mt-2 text-apoyo text-danger">
            No pudo el {fechaHora(fallo.fecha)}: {fallo.error}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {doc && (
          <a
            href={apiUrl(`/v1/documentos/${doc.id}.pdf`)}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-quiet btn-sm"
          >
            Ver PDF
          </a>
        )}
        {puedeBajar && (
          <SecondaryButton size="sm" onClick={onBajar} disabled={mandando || r.en_curso}>
            {r.en_curso || mandando ? "Bajando…" : doc ? "Bajar de nuevo" : "Bajar ahora"}
          </SecondaryButton>
        )}
      </div>
    </li>
  );
}
