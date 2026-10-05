"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useApi } from "@/components/ui";
import { SettingsField, SettingsSection, settingsInputCls } from "@/components/settings";

import { TagManager } from "@/components/tags";
import { api } from "@/lib/api";
import { toast } from "@/components/toast";
import { SHADOW_EVENT, avisarModoPrueba, useApagarModoPrueba } from "@/components/modo-prueba";

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

/** Modo de prueba: un solo nombre, un solo interruptor. Apagarlo pasa por el mismo
 *  diálogo que la franja (components/modo-prueba.tsx), que pregunta qué hacer con lo
 *  ya aprobado antes de dejarlo salir a clientes de verdad. */
function ModoPrueba() {
  const { data, loading, error, refetch, refetchQuiet } = useApi(() => api.shadowMode(), []);
  const [override, setOverride] = useState<boolean | null>(null);
  const [guardando, setGuardando] = useState(false);
  const { apagar, apagando, dialogo } = useApagarModoPrueba(() => refetchQuiet());
  const activo = override ?? data?.modo_sombra ?? false;
  const retenidos = data?.retenidos ?? 0;

  // Lo apague la franja o este interruptor, los dos se enteran sin recargar.
  useEffect(() => {
    const oir = (e: Event) =>
      setOverride(!!(e as CustomEvent<{ activo: boolean }>).detail?.activo);
    window.addEventListener(SHADOW_EVENT, oir);
    return () => window.removeEventListener(SHADOW_EVENT, oir);
  }, []);

  async function encender() {
    setGuardando(true);
    setOverride(true); // optimista
    try {
      const res = await api.setShadowMode(true);
      avisarModoPrueba(res.modo_sombra);
      toast("Modo de prueba encendido: nada sale a tus clientes.", "info");
      refetchQuiet();
    } catch (e) {
      setOverride(false); // revierte
      toast((e as Error).message, "error");
    } finally {
      setGuardando(false);
    }
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
          onClick={activo ? apagar : encender}
          disabled={loading || guardando || apagando}
          className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 ${
            activo ? "bg-accent" : "bg-field"
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
      {dialogo}
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
