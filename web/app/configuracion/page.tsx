"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageHeader, useApi } from "@/components/ui";
import { SettingsField, SettingsPage, SettingsSection, settingsInputCls } from "@/components/settings";
import { TagManager } from "@/components/tags";
import { api } from "@/lib/api";
import { toast } from "@/components/toast";
import { SHADOW_EVENT } from "@/components/shadow-banner";

// Aviso chico para una sección de configuración que no cargó: sin esto el control
// pintaba su valor default (posiblemente FALSO) como si fuera el real.
function SettingLoadError({ retry }: { retry: () => void }) {
  return (
    <p className="text-cuerpo text-ink-3">
      No se pudo cargar este ajuste.{" "}
      <button onClick={retry} className="font-medium text-accent-ink hover:underline">
        Reintentar
      </button>
    </p>
  );
}

function ModoSombra() {
  const { data, loading, error, refetch } = useApi(() => api.shadowMode(), []);
  const [override, setOverride] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const active = override ?? data?.modo_sombra ?? false;

  async function toggle() {
    const next = !active;
    setSaving(true);
    setOverride(next); // optimista
    try {
      const res = await api.setShadowMode(next);
      setOverride(res.modo_sombra);
      window.dispatchEvent(new CustomEvent(SHADOW_EVENT, { detail: { activo: res.modo_sombra } }));
      toast(
        res.modo_sombra
          ? "Modo sombra activado: nada sale a clientes reales."
          : "Modo sombra desactivado: los envíos vuelven a salir.",
        "info",
      );
    } catch (e) {
      setOverride(!next); // revierte
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  if (error) return <SettingLoadError retry={refetch} />;

  return (
    <div className="flex items-center gap-4">
      <button
        type="button"
        role="switch"
        aria-checked={active}
        aria-label="Modo sombra"
        onClick={toggle}
        disabled={loading || saving}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60 ${
          active ? "bg-accent" : "bg-line-strong"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-surface shadow transition-transform ${
            active ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
      <span className="text-cuerpo font-medium text-ink">
        {active ? "Activado: nada sale a clientes reales" : "Desactivado: los envíos salen normal"}
      </span>
    </div>
  );
}

/** Contexto del negocio: texto libre que el motor inyecta al system prompt de todos
 *  tus ayudantes (giro, politicas de pago, datos para deposito). Real: se guarda a
 *  nivel tenant y el redactor lo usa. Se guarda al salir del campo. */
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

  if (error) {
    return (
      <SettingsField
        label="Contexto del negocio"
        hint="Lo que tus ayudantes deben saber: giro, políticas de pago, datos bancarios para depósito."
      >
        <SettingLoadError retry={refetch} />
      </SettingsField>
    );
  }

  return (
    <SettingsField
      label="Contexto del negocio"
      hint="Lo que tus ayudantes deben saber: giro, políticas de pago, datos bancarios para depósito. Entra al system prompt de todos, bajo las reglas de fábrica."
    >
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
        placeholder="Ej. Aceptamos transferencia y depósito OXXO. Cuenta CLABE 0123…"
      />
      <p className="mt-1 text-apoyo text-ink-3" aria-live="polite">
        {estado === "guardando" ? "Guardando…" : estado === "ok" ? "Guardado" : ""}
      </p>
    </SettingsField>
  );
}

/** No-molestar: la franja (hora de México) en la que SÍ salen los envíos
 *  automatizados. Fuera de ella, el recordatorio aprobado espera a la siguiente
 *  corrida dentro de horario (no se pierde). Vacío = sin restricción. */
function VentanaEnvio() {
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
      <SettingsField label="Horario de envío" hint="Formato HH:MM-HH:MM en hora de México.">
        <SettingLoadError retry={refetch} />
      </SettingsField>
    );
  }

  return (
    <SettingsField
      label="Horario de envío"
      hint="Formato HH:MM-HH:MM en hora de México (ej. 09:00-20:00). Vacío = sin restricción. Si configuraste horario en la capacidad de cobranza de un ayudante, ese manda."
    >
      <input
        className={settingsInputCls}
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

/** Modo técnico: enseña lo que solo le sirve a quien programa (hoy, la API).
 *
 *  La regla del producto: el desarrollador instala, el usuario no técnico implementa.
 *  Que la API exista y esté documentada es bueno; que viva en el menú de alguien que
 *  nunca va a escribir un curl, no. Quien la busca la prende. Es preferencia de ESTA
 *  consola (localStorage), no config del negocio: no se la impone a los demás. */
function ModoTecnico() {
  const [activo, setActivo] = useState(false);
  useEffect(() => setActivo(localStorage.getItem("aiuda-modo-tecnico") === "1"), []);
  const alternar = () => {
    const nuevo = !activo;
    setActivo(nuevo);
    localStorage.setItem("aiuda-modo-tecnico", nuevo ? "1" : "0");
    window.dispatchEvent(new Event("modo-tecnico-cambio"));
    toast(nuevo ? "Modo técnico activado: aparece la API en el menú." : "Modo técnico desactivado.", "info");
  };
  return (
    <div className="flex items-center gap-4">
      <button
        type="button"
        role="switch"
        aria-checked={activo}
        aria-label="Modo técnico"
        onClick={alternar}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
          activo ? "bg-accent" : "bg-line-strong"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-surface shadow transition-transform ${
            activo ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
      <span className="text-cuerpo font-medium text-ink">
        {activo ? "Activado: la API aparece en el menú" : "Desactivado"}
      </span>
    </div>
  );
}


export default function ConfiguracionPage() {
  const { data: session } = useApi(() => api.workspace(), []);
  return (
    <SettingsPage>
      <PageHeader
        title="Configuración"
        subtitle="Cómo se presenta tu ayudante y qué puede hacer sin preguntarte."
      />

      <div className="mt-2">
        <SettingsSection
          title="Modo sombra"
          desc={
            <>
              Tu ayudante redacta y deja todo en Aprobaciones, pero{" "}
              <strong className="font-semibold text-ink">no envía nada</strong> a clientes reales.
              Úsalo la primera semana para validar redacción, horarios y volumen con datos reales,
              sin riesgo.
            </>
          }
        >
          <ModoSombra />
        </SettingsSection>

        <SettingsSection
          title="Modo técnico"
          desc="Enseña en el menú lo que solo le sirve a quien programa: hoy, la API de tu aiuda. Todo lo que ves en esta consola existe primero como API y corre en esta computadora; si no la necesitas, no tiene por qué estorbarte."
        >
          <ModoTecnico />
        </SettingsSection>

        <SettingsSection
          title="No molestar"
          desc="Los envíos automatizados (recordatorios, seguimientos) solo salen dentro de esta franja. Lo que caiga fuera espera a la siguiente corrida dentro de horario; no se pierde. Los clientes que escriben BAJA quedan excluidos siempre (se ve en su ficha)."
        >
          <VentanaEnvio />
        </SettingsSection>

        <SettingsSection
          title="Negocio"
          desc="El nombre y el contexto con los que tu ayudante se presenta y responde."
        >
          <div className="space-y-5">
            <SettingsField label="Nombre del negocio" hint="Así se presenta tu ayudante ante tus clientes.">
              <input className={settingsInputCls} value={session?.business_name ?? ""} readOnly />
            </SettingsField>
            <ContextoNegocio />
          </div>
        </SettingsSection>

        <SettingsSection
          title="Autonomía de tus ayudantes"
          desc="Cuándo puede enviar cada ayudante sin tu aprobación, su tono y sus reglas se configuran por capacidad, en el ayudante mismo. Ahí es real y lo usa el motor."
        >
          <Link
            href="/ayudantes"
            className="inline-flex rounded-md border border-line bg-surface px-3 py-1.5 text-cuerpo font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
          >
            Ir a tus ayudantes
          </Link>
        </SettingsSection>

        <SettingsSection
          title="Etiquetas"
          desc="Cómo agrupas a tus clientes. Tus ayudantes las respetan al filtrar y priorizar."
        >
          <TagManager />
        </SettingsSection>
      </div>
    </SettingsPage>
  );
}
