// Campos de credenciales por integración. Compartido por el drawer rápido y la
// vista completa de cada integración. Una sola fuente de verdad.

export type FieldDef = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
  type?: "text" | "select";
  options?: { value: string; label: string }[];
  hint?: string;
};

// Presets de servidor por proveedor de correo: elegir Gmail/Outlook rellena los hosts
// (el dueño solo pone correo + contraseña de aplicación). IMAP genérico los deja a mano.
export const EMAIL_PRESETS: Record<string, Record<string, string>> = {
  google: { imap_host: "imap.gmail.com", imap_port: "993", smtp_host: "smtp.gmail.com", smtp_port: "465" },
  microsoft: { imap_host: "outlook.office365.com", imap_port: "993", smtp_host: "smtp.office365.com", smtp_port: "587" },
  imap: {},
};

export const INTEGRATION_FIELDS: Record<string, FieldDef[]> = {
  whatsapp: [
    { key: "instance", label: "Instancia", placeholder: "mi-negocio" },
    { key: "base_url", label: "URL de Evolution API", placeholder: "https://evo.midominio.com" },
    { key: "token", label: "Token de la instancia", secret: true },
  ],
  whatsapp_cloud: [
    {
      key: "access_token",
      label: "Token de acceso (permanente)",
      secret: true,
      hint: "Genéralo en Meta for Developers con un usuario de sistema; el temporal caduca en 24 horas.",
    },
    { key: "phone_number_id", label: "ID del número de teléfono", placeholder: "1122334455" },
    { key: "waba_id", label: "ID de la cuenta de WhatsApp Business", placeholder: "opcional" },
    {
      key: "template_cobranza",
      label: "Plantilla aprobada para recordatorios",
      placeholder: "recordatorio_pago",
      hint: "Fuera de la ventana de 24 horas, Meta solo permite plantillas aprobadas: sin plantilla, esos envíos fallan (honesto).",
    },
    { key: "template_idioma", label: "Idioma de la plantilla", placeholder: "es_MX" },
  ],
  slack: [
    { key: "bot_token", label: "Bot token (xoxb-…)", secret: true },
    {
      key: "channel",
      label: "Canal de avisos",
      placeholder: "#cobranza",
      hint: "A dónde salen los avisos (resumen diario, corte de IA). Invita al bot al canal: /invite @aiuda.",
    },
  ],
  twilio_voz: [
    { key: "account_sid", label: "Account SID", placeholder: "AC…" },
    { key: "auth_token", label: "Auth Token", secret: true },
    {
      key: "from_number",
      label: "Número de origen (Twilio)",
      placeholder: "+5215512345678",
      hint: "El número que compraste en Twilio, en formato E.164 (+52…). Desde ahí salen las llamadas. Twilio cobra por minuto.",
    },
  ],
  email: [
    {
      key: "provider",
      label: "Proveedor",
      type: "select",
      options: [
        { value: "imap", label: "IMAP (genérico)" },
        { value: "google", label: "Gmail (Google)" },
        { value: "microsoft", label: "Outlook (Microsoft)" },
      ],
      hint: "Gmail y Outlook rellenan los servidores solos; con IMAP genérico los pones tú. Entrar con OAuth (botón de Google/Microsoft) está por cablear: hoy la vía completa es la contraseña de aplicación.",
    },
    { key: "email", label: "Correo", placeholder: "cobranza@minegocio.com" },
    { key: "imap_host", label: "Servidor IMAP (entrada)", placeholder: "imap.gmail.com" },
    { key: "imap_port", label: "Puerto IMAP", placeholder: "993" },
    {
      key: "smtp_host",
      label: "Servidor SMTP (salida)",
      placeholder: "smtp.gmail.com",
      hint: "Sin SMTP se puede leer el buzón, pero no responder ni enviar.",
    },
    { key: "smtp_port", label: "Puerto SMTP", placeholder: "465" },
    { key: "password", label: "Contraseña de aplicación", secret: true },
  ],
  odoo: [
    { key: "url", label: "URL de Odoo", placeholder: "https://miempresa.odoo.com" },
    { key: "db", label: "Base de datos", placeholder: "miempresa" },
    { key: "username", label: "Usuario", placeholder: "admin@miempresa.com" },
    { key: "api_key", label: "API key o contraseña", secret: true },
  ],
  shopify: [
    { key: "store_domain", label: "Dominio de la tienda", placeholder: "mitienda.myshopify.com" },
    { key: "access_token", label: "Access token", secret: true },
  ],
  woocommerce: [
    { key: "base_url", label: "URL de la tienda", placeholder: "https://mitienda.mx" },
    { key: "consumer_key", label: "Consumer key" },
    { key: "consumer_secret", label: "Consumer secret", secret: true },
  ],
  google_sheets: [
    {
      key: "api_key",
      label: "API key de Google",
      secret: true,
      hint: "Créala en Google Cloud Console (APIs y servicios → Credenciales) con la Google Sheets API habilitada.",
    },
    {
      key: "spreadsheet_id",
      label: "ID de la hoja",
      placeholder: "1AbC…xyz",
      hint: "Es la parte del enlace entre /d/ y /edit. La hoja debe estar compartida como 'Cualquier persona con el enlace · Lector'.",
    },
    { key: "sheet_range", label: "Rango", placeholder: "Facturas!A:F", hint: "La primera fila del rango son los encabezados; aiuda mapea las columnas por su nombre." },
    {
      key: "tipo",
      label: "Tipo de datos",
      type: "select",
      options: [
        { value: "facturas", label: "Facturas por cobrar" },
        { value: "clientes", label: "Clientes" },
        { value: "productos", label: "Productos" },
      ],
    },
  ],
  mercadolibre: [
    {
      key: "client_id",
      label: "Client ID (App ID)",
      placeholder: "1234567890123456",
      hint: "De tu aplicación en developers.mercadolibre.com.mx (Mis aplicaciones).",
    },
    { key: "client_secret", label: "Client Secret", secret: true },
    {
      key: "access_token",
      label: "Access token",
      secret: true,
      hint: "El token OAuth de tu app; aiuda lo refresca solo cuando caduca.",
    },
    {
      key: "refresh_token",
      label: "Refresh token",
      secret: true,
      hint: "Deja que aiuda renueve el acceso sin volver a autorizar la app.",
    },
    {
      key: "seller_id",
      label: "ID de vendedor",
      placeholder: "opcional",
      hint: "Si lo dejas vacío, aiuda lo detecta con /users/me.",
    },
  ],
  belvo: [
    {
      key: "belvo_link_id",
      label: "Link ID",
      hint: "El link de Belvo del banco del negocio; sin él aiuda ve las conexiones pero no las cuentas.",
    },
    { key: "secret_id", label: "Secret ID" },
    { key: "secret_password", label: "Secret password", secret: true },
  ],
  stripe: [{ key: "api_key", label: "Secret key (sk_…)", secret: true }],
  mercadopago: [
    {
      key: "access_token",
      label: "Access token (APP_USR-…)",
      secret: true,
      hint: "De tu aplicación en el panel de desarrolladores de Mercado Pago (Credenciales de producción).",
    },
  ],
  clip: [
    {
      key: "api_key",
      label: "API key de Clip",
      secret: true,
      hint: "Genérala en el portal de Clip (Desarrolladores → API keys).",
    },
  ],
  conekta: [
    {
      key: "api_key",
      label: "Private key (key_…)",
      secret: true,
      hint: "La llave privada de tu cuenta Conekta. Acepta tarjeta, OXXO Pay y SPEI.",
    },
  ],
  facturama: [
    { key: "user", label: "Usuario" },
    { key: "password", label: "Contraseña", secret: true },
  ],
  facturapi: [{ key: "api_key", label: "API key (sk_…)", secret: true }],
  googlecalendar: [
    { key: "token", label: "Token o service account", secret: true },
    { key: "calendar_id", label: "Calendar ID", placeholder: "primary" },
  ],
  hubspot: [{ key: "token", label: "Private app token", secret: true }],
  denue: [{ key: "token", label: "Token de INEGI" }],
  image_gen: [
    {
      key: "provider",
      label: "Proveedor",
      type: "select",
      options: [
        { value: "fal", label: "fal.ai (Flux · open-weights, más barato)" },
        { value: "openai", label: "OpenAI (gpt-image-1)" },
        { value: "custom", label: "Propio / self-host (compatible con OpenAI)" },
      ],
      hint: "fal.ai corre modelos open-weights (Flux) a fracciones de centavo por imagen. 'Propio' apunta a tu ComfyUI/Stable Diffusion tras un gateway compatible con la Images API de OpenAI.",
    },
    { key: "api_key", label: "API key", secret: true },
    {
      key: "base_url",
      label: "Endpoint (solo self-host)",
      placeholder: "https://mi-servidor/v1",
      hint: "Solo para la vía 'Propio': la URL base de tu endpoint compatible. fal y OpenAI la traen por defecto.",
    },
    {
      key: "model",
      label: "Modelo",
      placeholder: "fal-ai/flux/schnell",
      hint: "Opcional. Por defecto Flux schnell (fal) o gpt-image-1 (OpenAI).",
    },
  ],
};

export function fieldsFor(key: string): FieldDef[] {
  return INTEGRATION_FIELDS[key] ?? [{ key: "token", label: "Token o credencial", secret: true }];
}
