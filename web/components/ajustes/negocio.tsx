"use client";

import Link from "next/link";
import { useState } from "react";
import { PrimaryButton, SecondaryButton, useApi } from "@/components/ui";
import { SettingsField, SettingsSection, settingsInputCls } from "@/components/settings";
import { Modal } from "@/components/modal";
import { TagManager } from "@/components/tags";
import { api } from "@/lib/api";
import { ajustesApi } from "@/lib/ajustes-api";
import { toast } from "@/components/toast";
import { SHADOW_EVENT } from "@/components/shadow-banner";

// Aviso chico para un ajuste que no cargó: sin esto el control pintaba su valor
// de fábrica (posiblemente FALSO) como si fuera el real.
function SettingLoadError({ retry }: { retry: () => void }) {
  return (
    <p className="text-cuerpo text-ink-2">
      No se pudo cargar este ajuste.{" "}
      <button onClick={retry} className="font-medium text-accent-ink hover:underline">
        Reintentar
      </button>
    </p>
  );
}

/** Modo de prueba: un solo nombre, un solo interruptor.
 *
 *  Apagarlo no es inocuo: lo que el dueño aprobó mientras estaba encendido se
 *  quedó esperando, y al apagarlo saldría a clientes de verdad. Si hay algo así,
 *  se le pregunta antes: mandarlo ya, o no mandarlo. */
function ModoPrueba() {
  const { data, loading, error, refetch, refetchQuiet } = useApi(() => ajustesApi.modoPrueba(), []);
  const [override, setOverride] = useState<boolean | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [preguntar, setPreguntar] = useState(false);
  const activo = override ?? data?.modo_sombra ?? false;
  const retenidos = data?.retenidos ?? 0;

  async function cambiar(siguiente: boolean, quehacer?: "enviar" | "no_enviar") {
    setGuardando(true);
    setOverride(siguiente); // optimista
    try {
      const res = await ajustesApi.cambiarModoPrueba(siguiente, quehacer);
      setOverride(res.modo_sombra);
      window.dispatchEvent(
        new CustomEvent(SHADOW_EVENT, { detail: { activo: res.modo_sombra } }),
      );
      const n = res.retenidos;
      const cuantos = n === 1 ? "1 mensaje" : `${n} mensajes`;
      toast(
        res.modo_sombra
          ? "Modo de prueba encendido: nada sale a tus clientes."
          : res.retenidos_accion === "enviando"
            ? `Modo de prueba apagado. Se ${n === 1 ? "está mandando" : "están mandando"} ${cuantos}.`
            : res.retenidos_accion === "no_enviados"
              ? `Modo de prueba apagado. ${cuantos} ${n === 1 ? "quedó" : "quedaron"} sin mandar, en Hoy.`
              : "Modo de prueba apagado: lo que apruebes ya se envía.",
        "info",
      );
      setPreguntar(false);
      refetchQuiet();
    } catch (e) {
      setOverride(!siguiente); // revierte
      toast((e as Error).message, "error");
    } finally {
      setGuardando(false);
    }
  }

  function alternar() {
    if (activo && retenidos > 0) setPreguntar(true);
    else cambiar(!activo);
  }

  if (error) return <SettingLoadError retry={refetch} />;

  const cuantos = retenidos === 1 ? "1 mensaje aprobado" : `${retenidos} mensajes aprobados`;

  return (
    <div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          role="switch"
          aria-checked={activo}
          aria-label="Modo de prueba"
          onClick={alternar}
          disabled={loading || guardando}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 ${
            activo ? "bg-accent" : "bg-line-strong"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-surface shadow transition-transform ${
              activo ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
        <span className="text-cuerpo font-medium text-ink">
          {activo ? "Encendido: nada sale a tus clientes" : "Apagado: lo que apruebas sí se envía"}
        </span>
      </div>
      {activo && retenidos > 0 && (
        <p className="mt-3 text-cuerpo text-ink-2">
          Tienes {cuantos} que no {retenidos === 1 ? "ha salido" : "han salido"}. Al apagarlo te
          preguntamos qué hacer con {retenidos === 1 ? "él" : "ellos"}.
        </p>
      )}

      <Modal
        open={preguntar}
        onClose={() => !guardando && setPreguntar(false)}
        title={`Tienes ${cuantos} sin mandar`}
        size="sm"
      >
        <p className="text-cuerpo leading-relaxed text-ink-2">
          {retenidos === 1 ? "Lo aprobaste" : "Los aprobaste"} en modo de prueba y por eso no{" "}
          {retenidos === 1 ? "salió" : "salieron"}. Si apagas el modo de prueba,{" "}
          {retenidos === 1 ? "puede irse a un cliente" : "pueden irse a clientes"} de verdad. Tú
          decides.
        </p>
        <p className="mt-3 text-cuerpo leading-relaxed text-ink-2">
          Si no {retenidos === 1 ? "lo mandas" : "los mandas"}, {retenidos === 1 ? "queda" : "quedan"}{" "}
          en Hoy, en No salió, y puedes reintentar {retenidos === 1 ? "ese" : "el que quieras"}.
        </p>
        <div className="mt-6 flex flex-col gap-2">
          <PrimaryButton onClick={() => cambiar(false, "enviar")} disabled={guardando}>
            {retenidos === 1 ? "Apagar y mandarlo ahora" : `Apagar y mandar los ${retenidos} ahora`}
          </PrimaryButton>
          <SecondaryButton onClick={() => cambiar(false, "no_enviar")} disabled={guardando}>
            {retenidos === 1 ? "Apagar sin mandarlo" : "Apagar sin mandarlos"}
          </SecondaryButton>
          <button
            className="btn btn-quiet"
            onClick={() => setPreguntar(false)}
            disabled={guardando}
          >
            Dejarlo encendido
          </button>
        </div>
      </Modal>
    </div>
  );
}

/** Lo que tus ayudantes deben saber del negocio (giro, políticas de pago, datos para
 *  depósito). Se guarda al salir del campo y lo usan todos al redactar. */
function ContextoNegocio() {
  const { data, loading, error, refetch } = useApi(api.businessContext, []);
  const [value, setValue] = useState<string | null>(null);
  const [estado, setEstado] = useState<"idle" | "guardando" | "ok">("idle");
  const actual = value ?? data?.business_context ?? "";

  async function guardar() {
    const limpio = actual.trim();
    if (loading || limpio === (data?.business_context ?? "").trim()) return;
    setEstado("guardando");
    try {
      await api.saveBusinessContext(limpio);
      setEstado("ok");
    } catch (e) {
      setEstado("idle");
      toast((e as Error).message, "error");
    }
  }

  const ayuda =
    "Tu giro, tus políticas de pago, tus datos bancarios para depósito. Todos tus ayudantes lo toman en cuenta al redactar.";

  if (error) {
    return (
      <SettingsField label="Lo que tus ayudantes deben saber" hint={ayuda}>
        <SettingLoadError retry={refetch} />
      </SettingsField>
    );
  }

  return (
    <SettingsField label="Lo que tus ayudantes deben saber" hint={ayuda}>
      <textarea
        className={settingsInputCls}
        rows={3}
        value={actual}
        disabled={loading}
        onChange={(e) => {
          setValue(e.target.value);
          if (estado !== "idle") setEstado("idle");
        }}
        onBlur={guardar}
        placeholder="Ej. Aceptamos transferencia y depósito en OXXO. Cuenta CLABE 0123…"
      />
      <p className="mt-1 text-apoyo text-ink-3" aria-live="polite">
        {estado === "guardando" ? "Guardando…" : estado === "ok" ? "Guardado" : ""}
      </p>
    </SettingsField>
  );
}

/** La franja (hora de México) en la que SÍ salen los envíos. Fuera de ella, lo
 *  aprobado espera a la siguiente revisión dentro de horario. Vacío = a toda hora. */
function HorarioEnvio() {
  const { data, loading, error, refetch } = useApi(() => api.ventanaEnvio(), []);
  const [value, setValue] = useState<string | null>(null);
  const [estado, setEstado] = useState<"idle" | "guardando" | "ok">("idle");
  const actual = value ?? data?.ventana ?? "";

  async function guardar() {
    const limpio = actual.trim();
    if (loading || limpio === (data?.ventana ?? "").trim()) return;
    setEstado("guardando");
    try {
      const res = await api.setVentanaEnvio(limpio);
      setValue(res.ventana);
      setEstado("ok");
    } catch (e) {
      setEstado("idle");
      toast((e as Error).message, "error");
    }
  }

  if (error) {
    return (
      <SettingsField label="Horario de envío" hint="De qué hora a qué hora, en hora de México.">
        <SettingLoadError retry={refetch} />
      </SettingsField>
    );
  }

  return (
    <SettingsField
      label="Horario de envío"
      hint="De qué hora a qué hora, en hora de México. Por ejemplo 09:00-20:00. Vacío: a cualquier hora. Si un ayudante tiene su propio horario de cobranza, ese manda."
    >
      <input
        className={`${settingsInputCls} max-w-[14rem]`}
        value={actual}
        disabled={loading}
        placeholder="09:00-20:00"
        onChange={(e) => {
          setValue(e.target.value);
          if (estado !== "idle") setEstado("idle");
        }}
        onBlur={guardar}
      />
      <p className="mt-1 text-apoyo text-ink-3" aria-live="polite">
        {estado === "guardando" ? "Guardando…" : estado === "ok" ? "Guardado" : ""}
      </p>
    </SettingsField>
  );
}

export function AjustesNegocio() {
  const { data: negocio } = useApi(() => api.workspace(), []);
  return (
    <div>
      <SettingsSection
        title="Modo de prueba"
        desc={
          <>
            Tus ayudantes redactan y tú apruebas, pero{" "}
            <strong className="font-semibold text-ink">nada sale a tus clientes</strong>. Sirve
            para revisar con calma cómo escriben antes de mandar de verdad.
          </>
        }
      >
        <ModoPrueba />
      </SettingsSection>

      <SettingsSection
        title="No molestar"
        desc="Los recordatorios y seguimientos solo salen dentro de este horario. Lo que caiga fuera espera a la siguiente hora permitida; no se pierde. A quien te pidió no recibir mensajes no se le escribe nunca."
      >
        <HorarioEnvio />
      </SettingsSection>

      <SettingsSection
        title="Tu negocio"
        desc="El nombre con el que tus ayudantes se presentan y lo que saben de ti."
      >
        <div className="space-y-6">
          <SettingsField label="Nombre del negocio" hint="Así se presentan tus ayudantes con tus clientes.">
            {/* Texto y no un campo: hoy el nombre no se cambia desde aquí, y un campo
                que no deja escribir se lee como roto. */}
            <p className="text-seccion font-semibold text-ink">{negocio?.business_name ?? ""}</p>
          </SettingsField>
          <ContextoNegocio />
        </div>
      </SettingsSection>

      <SettingsSection
        title="Qué hace cada ayudante sin preguntarte"
        desc="Cuándo puede enviar solo, su tono y sus reglas se deciden en cada ayudante."
      >
        <Link href="/ayudantes" className="btn btn-secondary">
          Ir a Ayudantes
        </Link>
      </SettingsSection>

      <SettingsSection
        title="Etiquetas"
        desc="Cómo agrupas a tus clientes. Tus ayudantes las respetan al filtrar y priorizar."
      >
        <TagManager />
      </SettingsSection>
    </div>
  );
}
