"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader, PrimaryButton } from "@/components/ui";
import { SettingsField, SettingsPage, SettingsSection, settingsInputCls } from "@/components/settings";
import { toast } from "@/components/toast";
import { api, type Profile } from "@/lib/api";

export default function PerfilPage() {
  const [loaded, setLoaded] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Saved state (from API)
  const [saved, setSaved] = useState<Profile>({
    business_name: "",
    owner_name: "",
    email: "",
    phone: "",
    rfc: "",
  });

  // Draft state (editable)
  const [draft, setDraft] = useState<Profile>({
    business_name: "",
    owner_name: "",
    email: "",
    phone: "",
    rfc: "",
  });

  const [saving, setSaving] = useState(false);
  const [savedFeedback, setSavedFeedback] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.profile();
      setSaved(data);
      setDraft(data);
      setFetchError(null);
    } catch (e) {
      setFetchError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const isDirty =
    draft.business_name !== saved.business_name ||
    draft.owner_name !== saved.owner_name ||
    draft.email !== saved.email ||
    draft.phone !== saved.phone ||
    draft.rfc !== saved.rfc;

  async function handleSave() {
    setSaving(true);
    try {
      const updated = await api.saveProfile(draft);
      setSaved(updated);
      setDraft(updated);
      setSavedFeedback(true);
      setTimeout(() => setSavedFeedback(false), 2500);
    } catch (e) {
      toast(`No se pudo guardar: ${(e as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) {
    return (
      <SettingsPage>
        <PageHeader title="Tu perfil" />
        <div className="mt-2 skeleton h-48 w-full rounded-lg" />
      </SettingsPage>
    );
  }

  if (fetchError) {
    return (
      <SettingsPage>
        <PageHeader title="Tu perfil" />
        <div className="mt-2 rounded-lg border border-line bg-surface px-6 py-12 text-center">
          <p className="text-[13.5px] font-medium text-danger">Sin conexión con el API</p>
          <p className="mt-1 text-[12.5px] text-ink-3">{fetchError}</p>
        </div>
      </SettingsPage>
    );
  }

  return (
    <SettingsPage>
      <PageHeader title="Tu perfil" />

      <div className="mt-2">
        {/* Negocio */}
        <SettingsSection
          title="Negocio"
          desc="Los datos de tu negocio con los que trabajan tus aiudantes y que aparecen en tus documentos."
        >
          <div className="space-y-5">
            <SettingsField label="Nombre del negocio" hint="Cómo aparece en tus documentos y con tus clientes.">
              <input
                className={settingsInputCls}
                value={draft.business_name}
                onChange={(e) => setDraft((d) => ({ ...d, business_name: e.target.value }))}
                placeholder="Nombre del negocio"
              />
            </SettingsField>
            <SettingsField label="RFC" hint="Para efectos fiscales.">
              <input
                className={settingsInputCls}
                value={draft.rfc}
                onChange={(e) => setDraft((d) => ({ ...d, rfc: e.target.value.toUpperCase() }))}
                placeholder="XAXX010101000"
              />
            </SettingsField>
          </div>
        </SettingsSection>

        {/* Tú */}
        <SettingsSection
          title="Tú"
          desc="Cómo te contactamos y quién responde por el negocio."
        >
          <div className="space-y-5">
            <SettingsField label="Nombre" hint="Tu nombre como responsable del negocio.">
              <input
                className={settingsInputCls}
                value={draft.owner_name}
                onChange={(e) => setDraft((d) => ({ ...d, owner_name: e.target.value }))}
                placeholder="Nombre completo"
              />
            </SettingsField>
            <SettingsField label="Correo" hint="Para notificaciones importantes de la plataforma.">
              <input
                className={settingsInputCls}
                type="email"
                value={draft.email}
                onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                placeholder="tu@correo.com"
              />
            </SettingsField>
            <SettingsField label="WhatsApp" hint="Número donde recibes aprobaciones y el resumen diario.">
              <input
                className={settingsInputCls}
                type="tel"
                value={draft.phone}
                onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))}
                placeholder="+52 1 229 123 4567"
              />
            </SettingsField>
          </div>
        </SettingsSection>

        {/* Acciones */}
        <div className="flex items-center justify-end gap-3 border-t border-line py-6">
          {savedFeedback && <span className="text-[12px] text-ok">Guardado</span>}
          <PrimaryButton onClick={handleSave} disabled={!isDirty || saving}>
            {saving ? "Guardando…" : "Guardar"}
          </PrimaryButton>
        </div>

      </div>
    </SettingsPage>
  );
}
