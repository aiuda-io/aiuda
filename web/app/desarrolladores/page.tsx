"use client";

// Documentación consultable del API local. Los endpoints de esta página salen del backend
// REAL (server/aiuda_server/api/*.py, verificados contra /openapi.json): si algo no existe,
// no se lista. Buscador + grupos plegables + curl copiable con la URL de esta instalación.
import { useMemo, useState, useSyncExternalStore } from "react";
import { PageHeader, SearchInput } from "@/components/ui";

type Metodo = "GET" | "POST" | "PUT" | "DELETE";

type Endpoint = {
  m: Metodo;
  path: string;
  desc: string;
  /** Cuerpo JSON de ejemplo (solo si el endpoint lo pide de verdad). */
  body?: string;
  /** Campos multipart (subida de archivos). */
  form?: string[];
  /** Bandera extra del curl (ej. guardar la descarga en un archivo). */
  flags?: string;
};

type Grupo = { key: string; title: string; hint: string; items: Endpoint[] };

// El mismo contrato que usa la consola (lib/api.ts): en el build empaquetado el API vive en
// el MISMO origen que esta página (http://127.0.0.1:4747); en desarrollo, tras /api.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const BASE_LOCAL = "http://127.0.0.1:4747";

const GRUPOS: Grupo[] = [
  {
    key: "cartera",
    title: "Cartera y facturas",
    hint: "Lo que te deben, los pagos y la conciliación.",
    items: [
      { m: "GET", path: "/v1/cartera", desc: "Resumen de la cartera: aging, recuperado del mes y pendientes." },
      { m: "GET", path: "/v1/invoices", desc: "Facturas con bucket y días de atraso. Filtra con ?status=open." },
      { m: "GET", path: "/v1/invoices/{invoice_id}", desc: "Detalle de una factura con su presencia en cada fuente." },
      {
        m: "POST",
        path: "/v1/invoices",
        desc: "Alta directa de factura en aiuda, opcionalmente inyectada a tu maestro.",
        body: '{"customer_id":"abc123","folio":"A-101","amount":1500,"due_date":"2026-08-15"}',
      },
      { m: "POST", path: "/v1/invoices/{invoice_id}/pay", desc: "Registra el pago de la factura y la cierra." },
      { m: "POST", path: "/v1/invoices/{invoice_id}/remind", desc: "Pide un recordatorio redactado para esa factura ahora." },
      { m: "GET", path: "/v1/invoices/{invoice_id}/cfdi.xml", desc: "Descarga el XML del CFDI de la factura.", flags: '-o cfdi.xml' },
      { m: "GET", path: "/v1/invoices/{invoice_id}/cfdi.pdf", desc: "Descarga el PDF del CFDI de la factura.", flags: '-o cfdi.pdf' },
      { m: "GET", path: "/v1/promises", desc: "Promesas de pago de tus clientes. Filtra con ?status=." },
      { m: "POST", path: "/v1/promises/{promise_id}/fulfill", desc: "Marca la promesa como cumplida." },
      {
        m: "POST",
        path: "/v1/payments",
        desc: "Registra un pago a mano; entra a la bandeja de conciliación.",
        body: '{"amount":1500,"reference":"SPEI 0012","counterparty":"Ferretería Ruiz"}',
      },
      { m: "GET", path: "/v1/reconciliation", desc: "Bandeja de conciliación: pagos detectados con su evidencia." },
      { m: "GET", path: "/v1/reconciliation/resueltos", desc: "Historial: pagos ya conciliados o rechazados." },
      {
        m: "POST",
        path: "/v1/reconciliation/{payment_id}/confirm",
        desc: "Aplica el pago a las facturas que le indiques.",
        body: '{"invoice_ids":["inv123"]}',
      },
      { m: "POST", path: "/v1/reconciliation/{payment_id}/ignore", desc: "Rechaza el pago: no corresponde a ninguna factura." },
      { m: "GET", path: "/v1/reconciliation/config", desc: "Tolerancia de monto con la que se cruzan pagos y facturas." },
      {
        m: "PUT",
        path: "/v1/reconciliation/config",
        desc: "Ajusta esa tolerancia (porcentaje y monto absoluto).",
        body: '{"tolerancia_pct":1,"tolerancia_abs":50}',
      },
      {
        m: "POST",
        path: "/v1/cobro/link",
        desc: "Genera un link de pago con la pasarela que tengas conectada.",
        body: '{"monto":1500,"concepto":"Factura A-101","referencia":"A-101"}',
      },
      {
        m: "GET",
        path: "/v1/export/{entidad}.xlsx",
        desc: "Exporta a Excel: facturas, clientes, prospectos, productos, citas, promesas o conciliacion.",
        flags: "-o facturas.xlsx",
      },
    ],
  },
  {
    key: "recordatorios",
    title: "Recordatorios",
    hint: "Lo que el ayudante propone y tú apruebas antes de que salga.",
    items: [
      { m: "GET", path: "/v1/reminders", desc: "Recordatorios por estado. Filtra con ?status=pending." },
      { m: "POST", path: "/v1/reminders/{reminder_id}/approve", desc: "Aprueba y envía el recordatorio. Fuerza canal con ?channel=." },
      { m: "POST", path: "/v1/reminders/{reminder_id}/reject", desc: "Rechaza el borrador; el rechazo alimenta el aprendizaje." },
      { m: "POST", path: "/v1/reminders/{reminder_id}/send", desc: "Reintenta el envío de uno ya aprobado que no salió." },
      { m: "POST", path: "/v1/daily/run", desc: "Dispara la corrida de cobranza ahora, sin esperar al scheduler." },
      { m: "GET", path: "/v1/learning/summary", desc: "Qué está aprendiendo el ayudante de tus correcciones." },
      { m: "GET", path: "/v1/settings/ventana-envio", desc: "La franja horaria en la que sí se envía a clientes." },
      {
        m: "PUT",
        path: "/v1/settings/ventana-envio",
        desc: "Fija esa franja (vacío = sin restricción).",
        body: '{"ventana":"09:00-20:00"}',
      },
      { m: "GET", path: "/v1/settings/modo-sombra", desc: "Si el modo sombra está encendido (redacta y aprueba, no envía)." },
      { m: "PUT", path: "/v1/settings/modo-sombra", desc: "Prende o apaga el modo sombra.", body: '{"activo":true}' },
    ],
  },
  {
    key: "clientes",
    title: "Clientes",
    hint: "Tu directorio, sus etiquetas y la prospección.",
    items: [
      { m: "GET", path: "/v1/customers", desc: "Clientes con saldo abierto. Filtra con ?kind=prospecto." },
      {
        m: "POST",
        path: "/v1/customers",
        desc: "Alta directa de cliente o prospecto en aiuda.",
        body: '{"name":"Ferretería Ruiz","phone":"+528112345678"}',
      },
      { m: "GET", path: "/v1/customers/{customer_id}", desc: "Ficha del cliente: datos, facturas y su hilo de conversación." },
      {
        m: "PUT",
        path: "/v1/customers/{customer_id}",
        desc: "Edita el cliente y encola la actualización hacia sus sistemas.",
        body: '{"email":"pagos@ferreteriaruiz.mx"}',
      },
      {
        m: "POST",
        path: "/v1/customers/{customer_id}/messages",
        desc: "Escribe al cliente desde su ficha (crea la conversación si no existe).",
        body: '{"body":"Buen día, le comparto su estado de cuenta."}',
      },
      {
        m: "POST",
        path: "/v1/customers/{customer_id}/attachments",
        desc: "Adjunta un archivo y se lo manda por WhatsApp.",
        form: ["file=@estado-de-cuenta.pdf"],
      },
      { m: "POST", path: "/v1/customers/{customer_id}/optout", desc: "Marca o quita la baja de mensajes del cliente.", body: '{"activo":true}' },
      { m: "PUT", path: "/v1/customers/{customer_id}/tags", desc: "Reemplaza las etiquetas del cliente.", body: '{"tags":["vip"]}' },
      { m: "GET", path: "/v1/tags", desc: "Las etiquetas del negocio con cuántos clientes tiene cada una." },
      { m: "POST", path: "/v1/tags", desc: "Crea una etiqueta.", body: '{"name":"vip","color":"azul"}' },
      { m: "PUT", path: "/v1/tags/{tag_id}", desc: "Renombra o recolorea una etiqueta.", body: '{"name":"vip","color":"verde"}' },
      { m: "DELETE", path: "/v1/tags/{tag_id}", desc: "Borra la etiqueta y la quita de sus clientes." },
      { m: "GET", path: "/v1/search", desc: "Búsqueda global de clientes, facturas y conversaciones. Usa ?q=." },
      { m: "GET", path: "/v1/prospeccion/fuente", desc: "Estado honesto de la fuente de prospección (DENUE del INEGI)." },
      {
        m: "POST",
        path: "/v1/prospeccion/buscar",
        desc: "Busca negocios por giro alrededor de un punto.",
        body: '{"condicion":"ferretería","lat":25.6866,"lng":-100.3161,"radio_m":2000}',
      },
      {
        m: "POST",
        path: "/v1/prospeccion/importar",
        desc: "Carga los negocios elegidos a tu cartera como prospectos.",
        body: '{"negocios":[{"id":"denue-1","nombre":"Ferretería Ruiz","telefono":"8112345678"}]}',
      },
    ],
  },
  {
    key: "conversaciones",
    title: "Conversaciones",
    hint: "La bandeja unificada de WhatsApp y correo.",
    items: [
      { m: "GET", path: "/v1/conversations", desc: "La bandeja: hilos identificados y por identificar." },
      { m: "GET", path: "/v1/conversations/{conversation_id}", desc: "El hilo completo con sus mensajes y su estado de entrega." },
      {
        m: "POST",
        path: "/v1/conversations/{conversation_id}/messages",
        desc: "Escribe tú en el hilo (queda como mensaje humano).",
        body: '{"body":"Ya vi su pago, gracias."}',
      },
      {
        m: "POST",
        path: "/v1/conversations/{conversation_id}/messages/{message_id}/resend",
        desc: "Reintenta un saliente tuyo que quedó sin enviarse.",
      },
      {
        m: "POST",
        path: "/v1/conversations/{conversation_id}/takeover",
        desc: "Tomas el hilo tú: el ayudante deja de responder ahí.",
        body: '{"takeover":true}',
      },
      { m: "POST", path: "/v1/conversations/{conversation_id}/dismiss", desc: "Saca el hilo de la bandeja por identificar (ruido)." },
      { m: "POST", path: "/v1/conversations/{conversation_id}/undismiss", desc: "Deshace el descarte y lo regresa a la bandeja." },
      {
        m: "POST",
        path: "/v1/conversations/{conversation_id}/registrar-cliente",
        desc: "Liga el hilo a un cliente existente o da de alta uno nuevo.",
        body: '{"name":"Ferretería Ruiz"}',
      },
    ],
  },
  {
    key: "catalogo",
    title: "Catálogo y agenda",
    hint: "Lo que vendes, tus cotizaciones y tus citas.",
    items: [
      { m: "GET", path: "/v1/products", desc: "Tu catálogo con precios y existencias." },
      {
        m: "POST",
        path: "/v1/products",
        desc: "Alta directa de producto (dedupe por SKU).",
        body: '{"name":"Tornillo 1/4","sku":"T-14","price":12.5}',
      },
      {
        m: "POST",
        path: "/v1/quotes",
        desc: "Genera una cotización con precios reales; queda en Aprobaciones.",
        body: '{"customer_id":"abc123","items":[{"product_id":"p1","cantidad":10}]}',
      },
      { m: "GET", path: "/v1/appointments", desc: "Las citas de tu agenda." },
      {
        m: "POST",
        path: "/v1/appointments",
        desc: "Alta directa de cita (hora de pared, sin zona).",
        body: '{"title":"Visita a Ferretería Ruiz","starts_at":"2026-08-01T10:00"}',
      },
    ],
  },
  {
    key: "ayudantes",
    title: "Ayudantes",
    hint: "Tus ayudantes, sus aiuditas y su chat.",
    items: [
      { m: "GET", path: "/v1/aiuditas/catalog", desc: "El catálogo de aiuditas con sus perillas y sus fuentes." },
      { m: "GET", path: "/v1/ayudantes", desc: "Tus ayudantes con las aiuditas que tienen activas." },
      { m: "POST", path: "/v1/ayudantes", desc: "Crea un ayudante (opcionalmente con sus aiuditas).", body: '{"name":"tavo"}' },
      { m: "GET", path: "/v1/ayudantes/{ayudante_id}", desc: "Detalle de un ayudante." },
      { m: "PUT", path: "/v1/ayudantes/{ayudante_id}", desc: "Edita nombre, apariencia o instrucciones.", body: '{"name":"tavo"}' },
      { m: "DELETE", path: "/v1/ayudantes/{ayudante_id}", desc: "Elimina el ayudante." },
      {
        m: "PUT",
        path: "/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}",
        desc: "Activa una aiudita y guarda su config validada.",
        body: '{"config":{"autonomia":"siempre_pedir"}}',
      },
      { m: "DELETE", path: "/v1/ayudantes/{ayudante_id}/aiuditas/{aiudita_id}", desc: "Le quita esa aiudita al ayudante." },
      { m: "POST", path: "/v1/ayudantes/{ayudante_id}/correr", desc: "Corre al ayudante ahora con sus perillas y reglas." },
      {
        m: "POST",
        path: "/v1/ayudantes/{ayudante_id}/chat",
        desc: "Hablar con tu ayudante (sus herramientas son de solo lectura).",
        body: '{"message":"¿cómo va la cobranza?"}',
      },
      { m: "GET", path: "/v1/ayudantes/{ayudante_id}/prompt", desc: "El system prompt real con el que corre, tal cual." },
      { m: "GET", path: "/v1/agents", desc: "El equipo de cobranza que trae aiuda y su actividad." },
      { m: "POST", path: "/v1/agents/{slug}/activate", desc: "Activa a ese agente del equipo." },
      { m: "POST", path: "/v1/agents/{slug}/deactivate", desc: "Lo desactiva." },
      { m: "POST", path: "/v1/agents/{slug}/chat", desc: "Chat con ese agente.", body: '{"message":"resume la cartera"}' },
      { m: "GET", path: "/v1/agents/{slug}/config", desc: "Sus reglas, contexto del negocio y buckets automáticos." },
      {
        m: "PUT",
        path: "/v1/agents/{slug}/config",
        desc: "Guarda esas reglas (las usa el agente tal cual).",
        body: '{"user_rules":"Nunca escribas los domingos."}',
      },
      { m: "GET", path: "/v1/agents/{slug}/systems", desc: "A qué sistemas llega ese agente y a cuáles le falta." },
    ],
  },
  {
    key: "integraciones",
    title: "Integraciones",
    hint: "Tus fuentes, las conexiones a la medida y el write-back.",
    items: [
      { m: "GET", path: "/v1/integrations", desc: "El grafo de fuentes: cuáles están conectadas y qué proveen." },
      { m: "GET", path: "/v1/integrations/{key}", desc: "Detalle de una fuente y los campos que pide para conectarse." },
      { m: "GET", path: "/v1/integrations/{key}/config", desc: "Su config guardada (los secretos van enmascarados)." },
      {
        m: "PUT",
        path: "/v1/integrations/{key}/config",
        desc: "Guarda la config; el secreto se cifra en tu computadora.",
        body: '{"values":{"url":"https://mi-odoo.mx","db":"prod","user":"api"}}',
      },
      { m: "DELETE", path: "/v1/integrations/{key}/config", desc: "Desconecta la fuente y borra su credencial." },
      { m: "PUT", path: "/v1/integrations/{key}/capabilities", desc: "Elige qué capacidades sí jalas de esa fuente.", body: '{"disabled":["cfdi"]}' },
      { m: "POST", path: "/v1/integrations/{key}/test", desc: "Prueba en vivo la conexión con tus credenciales." },
      { m: "POST", path: "/v1/integration-requests", desc: "Pide una fuente que todavía no existe.", body: '{"system":"Contpaqi","reason":"Ahí vive mi cartera"}' },
      { m: "POST", path: "/v1/sync", desc: "Sincroniza las fuentes conectadas respetando de dónde lee cada capacidad." },
      { m: "GET", path: "/v1/custom-connectors", desc: "Tus conexiones a la medida (las que creaste por API)." },
      {
        m: "POST",
        path: "/v1/custom-connectors",
        desc: "Crea una conexión a la medida contra tu propia API.",
        body: '{"name":"Mi ERP","cap":"cuentas_por_cobrar","base_url":"https://api.mierp.mx","list_path":"/facturas"}',
      },
      {
        m: "PUT",
        path: "/v1/custom-connectors/{cid}",
        desc: "Edita la conexión (la clave solo se reemplaza si mandas una nueva).",
        body: '{"name":"Mi ERP","cap":"cuentas_por_cobrar","base_url":"https://api.mierp.mx"}',
      },
      { m: "DELETE", path: "/v1/custom-connectors/{cid}", desc: "Borra la conexión a la medida." },
      {
        m: "POST",
        path: "/v1/custom-connectors/test",
        desc: "Prueba una declaración sin guardarla: trae registros y los mapea.",
        body: '{"base_url":"https://api.mierp.mx","list_path":"/facturas"}',
      },
      { m: "POST", path: "/v1/custom-connectors/{cid}/test", desc: "Re-prueba una conexión guardada con su clave cifrada." },
      { m: "GET", path: "/v1/custom-connectors/fields", desc: "Qué campos hay que mapear según la necesidad." },
      { m: "GET", path: "/v1/custom-connectors/{cid}/receta", desc: "La receta de la conexión, sin secretos, para compartirla." },
      { m: "POST", path: "/v1/custom-connectors/importar", desc: "Crea una conexión desde una receta.", body: '{"receta":{"name":"Mi ERP","cap":"cuentas_por_cobrar"}}' },
      { m: "GET", path: "/v1/writeback", desc: "Las inyecciones hacia tus fuentes y cómo les fue." },
      { m: "POST", path: "/v1/writeback/{entry_id}/retry", desc: "Reintenta una inyección que falló." },
      { m: "GET", path: "/v1/inyectar/destinos", desc: "A qué maestros puedes empujar un registro que vive en aiuda." },
      {
        m: "POST",
        path: "/v1/inyectar",
        desc: "Empuja un registro de aiuda al maestro que elijas.",
        body: '{"entidad":"customer","id":"abc123","target":"odoo"}',
      },
      { m: "GET", path: "/v1/objects/{tipo}/source", desc: "Qué fuente es dueña de ese tipo de registro (clientes, facturas, productos, citas)." },
      { m: "POST", path: "/v1/import", desc: "Importador universal: detecta qué trae el archivo y lo carga.", form: ["file=@cartera.xlsx"] },
      { m: "POST", path: "/v1/import/analyze", desc: "Paso 1: propone tipo y mapeo sin importar nada.", form: ["file=@cartera.xlsx"] },
      {
        m: "POST",
        path: "/v1/import/commit",
        desc: "Paso 2: importa con el mapeo que confirmaste.",
        form: ["file=@cartera.xlsx", "entity=facturas"],
      },
      { m: "POST", path: "/v1/integrations/whatsapp/qr", desc: "El QR para emparejar tu WhatsApp (o avisa si ya está)." },
      { m: "GET", path: "/v1/integrations/whatsapp/status", desc: "Si el canal de WhatsApp está emparejado y vivo." },
      { m: "DELETE", path: "/v1/integrations/whatsapp/session", desc: "Cierra la sesión de WhatsApp y borra su emparejamiento." },
      { m: "POST", path: "/v1/integrations/whatsapp-cloud/activate", desc: "Deja la Cloud API oficial como la vía del canal WhatsApp." },
    ],
  },
  {
    key: "oficina",
    title: "Oficina administrativa",
    hint: "El agente de cómputo (CUA) que opera portales por ti: SAT, banca, tribunal.",
    items: [
      { m: "GET", path: "/v1/cua/estado", desc: "Estado honesto: si esta computadora puede correr el navegador del asistente." },
      { m: "GET", path: "/v1/cua/capacidades", desc: "Los portales disponibles y si ya tienen acceso conectado." },
      { m: "GET", path: "/v1/cua/misiones", desc: "Los encargos despachados, del más reciente al más viejo." },
      {
        m: "POST",
        path: "/v1/cua/misiones",
        desc: "Despacha un encargo a un portal (capacidad: cfdi, confirmacion_pago, expedientes).",
        body: '{"capacidad":"cfdi","instruccion":"Baja los CFDI recibidos de este mes"}',
      },
      { m: "GET", path: "/v1/cua/misiones/{mission_id}", desc: "El encargo con su bitácora y su evidencia." },
      { m: "GET", path: "/v1/cua/rutinas", desc: "Las rutinas guardadas (encargo listo para repetir)." },
      { m: "POST", path: "/v1/cua/rutinas", desc: "Guarda un encargo como rutina.", body: '{"nombre":"CFDI del mes","capacidad":"cfdi"}' },
      { m: "DELETE", path: "/v1/cua/rutinas/{rutina_id}", desc: "Borra la rutina." },
      { m: "GET", path: "/v1/cua/portales", desc: "Los portales que registraste por URL." },
      { m: "POST", path: "/v1/cua/portales", desc: "Registra un portal por URL.", body: '{"nombre":"Mi banco","url":"https://banco.mx/empresas"}' },
      { m: "DELETE", path: "/v1/cua/portales/{portal_id}", desc: "Quita ese portal." },
      { m: "PUT", path: "/v1/cua/portales/builtin/{capacidad}", desc: "Fija la dirección de un portal de fábrica.", body: '{"url":"https://banco.mx/empresas"}' },
      { m: "POST", path: "/v1/cua/sesion", desc: "Abre la ventana para que tú entres al portal (handoff).", body: '{"capacidad":"confirmacion_pago"}' },
      { m: "GET", path: "/v1/cua/sesion/{session_id}", desc: "Cómo va ese handoff." },
      { m: "POST", path: "/v1/cua/sesion/{session_id}/confirmar", desc: "Ya entraste: guarda la sesión autenticada, cifrada." },
      { m: "POST", path: "/v1/cua/sesion/{session_id}/cancelar", desc: "Cierra la ventana sin guardar nada." },
      { m: "POST", path: "/v1/cua/sesion/olvidar", desc: "Borra el acceso guardado de un portal.", body: '{"capacidad":"confirmacion_pago"}' },
    ],
  },
  {
    key: "sistema",
    title: "Sistema",
    hint: "Workspace, IA, consumo, bitácora y primer arranque.",
    items: [
      { m: "GET", path: "/health", desc: "Latido del servidor. Es el único endpoint sin token." },
      { m: "GET", path: "/v1/workspace", desc: "Identidad del workspace local (nombre del negocio y tu rol)." },
      { m: "GET", path: "/v1/onboarding/state", desc: "Qué hitos del arranque ya cumpliste." },
      { m: "GET", path: "/v1/usage", desc: "Consumo de IA del mes y lo que el ayudante hizo por ti." },
      { m: "GET", path: "/v1/audit", desc: "Bitácora del negocio: quién hizo qué y cuándo." },
      { m: "GET", path: "/v1/provider", desc: "Qué IA tienes conectada y en qué modo." },
      {
        m: "PUT",
        path: "/v1/provider",
        desc: "Conecta tu IA (el secreto se cifra en tu computadora).",
        body: '{"name":"claude","mode":"api_key","secret":"sk-ant-..."}',
      },
      { m: "DELETE", path: "/v1/provider", desc: "Desconecta la IA y borra su credencial." },
      { m: "POST", path: "/v1/provider/test", desc: "Prueba real: llamada mínima con la credencial efectiva." },
      { m: "POST", path: "/v1/provider/openai/connect", desc: "Conecta OpenAI pegando tu auth.json de Codex." },
      { m: "POST", path: "/v1/provider/openai/device/start", desc: "Arranca Iniciar sesión con ChatGPT (device code)." },
      {
        m: "POST",
        path: "/v1/provider/openai/device/poll",
        desc: "Sondea ese device code hasta que autorices.",
        body: '{"device_code":"...","user_code":"..."}',
      },
      { m: "GET", path: "/v1/setup/estado", desc: "Qué encontró aiuda en esta computadora y qué falta." },
      { m: "GET", path: "/v1/setup/maquina", desc: "Qué computadora es esta y qué IA local le cabe." },
      { m: "POST", path: "/v1/setup/modelo/descargar", desc: "Baja un modelo local con ollama, en segundo plano.", body: '{"modelo":"qwen2.5:7b"}' },
      { m: "GET", path: "/v1/setup/modelo/progreso", desc: "Cómo va esa descarga. Usa ?modelo=." },
      { m: "POST", path: "/v1/setup/red/buscar", desc: "Busca una IA compartida en tu red local." },
      { m: "PUT", path: "/v1/setup/negocio", desc: "Guarda el nombre del negocio (y tu WhatsApp).", body: '{"nombre":"Mi negocio"}' },
      { m: "POST", path: "/v1/setup/terminar", desc: "Cierra el asistente de primer arranque." },
    ],
  },
  {
    key: "webhooks",
    title: "Webhooks entrantes",
    hint: "Los llama tu canal, no tú. Se listan para que sepas qué escucha aiuda.",
    items: [
      { m: "POST", path: "/v1/webhooks/wacli", desc: "Mensajes entrantes de WhatsApp por wacli (tu número)." },
      { m: "POST", path: "/v1/webhooks/evolution", desc: "Mensajes entrantes de WhatsApp por Evolution." },
      { m: "GET", path: "/v1/webhooks/whatsapp-cloud", desc: "Verificación del webhook que hace Meta al registrarlo." },
      { m: "POST", path: "/v1/webhooks/whatsapp-cloud", desc: "Mensajes entrantes del canal oficial de WhatsApp." },
      { m: "POST", path: "/v1/webhooks/twilio-voz", desc: "Estado de una llamada de recordatorio (firma validada)." },
    ],
  },
];

const TOTAL = GRUPOS.reduce((n, g) => n + g.items.length, 0);

const METODO_CLS: Record<Metodo, string> = {
  GET: "bg-accent-soft text-accent-ink",
  POST: "bg-ok-soft text-ok",
  PUT: "bg-warn-soft text-warn",
  DELETE: "bg-danger-soft text-danger",
};

/** El curl exacto para ese endpoint, con la URL de ESTA instalación y el token de sesión. */
function curlDe(base: string, e: Endpoint): string {
  const url = `"${base}${e.path}${e.path === "/health" ? "" : "?token=$AIUDA_TOKEN"}"`;
  const lineas = [e.m === "GET" ? `curl ${url}` : `curl -X ${e.m} ${url}`];
  if (e.body) {
    lineas.push(`  -H "Content-Type: application/json"`);
    lineas.push(`  -d '${e.body}'`);
  }
  if (e.form) for (const campo of e.form) lineas.push(`  -F "${campo}"`);
  if (e.flags) lineas.push(`  ${e.flags}`);
  return lineas.join(" \\\n");
}

/** Busca sin que estorben acentos ni mayúsculas ("prospeccion" encuentra "prospección"). */
const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");

function Copiar({ texto }: { texto: string }) {
  const [estado, setEstado] = useState<"listo" | "ok" | "falla">("listo");

  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
      setEstado("ok");
    } catch {
      setEstado("falla");
    }
    setTimeout(() => setEstado("listo"), 1600);
  }

  return (
    <button
      type="button"
      onClick={copiar}
      title={texto}
      className={`shrink-0 rounded-md border px-2 py-1 text-sello font-medium transition-colors ${
        estado === "ok"
          ? "border-ok bg-ok-soft text-ok"
          : estado === "falla"
            ? "border-danger bg-danger-soft text-danger"
            : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink"
      }`}
    >
      {estado === "ok" ? "Copiado" : estado === "falla" ? "No se pudo" : "Copiar curl"}
    </button>
  );
}

function EndpointRow({ e, base }: { e: Endpoint; base: string }) {
  return (
    <div className="flex items-start gap-3 border-b border-line/60 px-4 py-2.5 last:border-b-0">
      <span
        className={`mt-px w-[52px] shrink-0 rounded px-1 py-0.5 text-center text-sello font-semibold tracking-[0.04em] ${METODO_CLS[e.m]}`}
      >
        {e.m}
      </span>
      <div className="min-w-0 flex-1">
        <code className="block break-all font-mono text-cuerpo text-ink">{e.path}</code>
        <p className="mt-0.5 text-apoyo leading-snug text-ink-3">{e.desc}</p>
      </div>
      <Copiar texto={curlDe(base, e)} />
    </div>
  );
}

// El origen real del navegador, con el default honesto de `aiuda start` para el HTML
// prerenderizado (el export estático se genera sin navegador). No cambia nunca: la
// suscripción es un no-op.
const sinCambios = () => () => {};
const origenDelNavegador = () => window.location.origin;
const origenPrerender = () => BASE_LOCAL;

export default function DesarrolladoresPage() {
  const origen = useSyncExternalStore(sinCambios, origenDelNavegador, origenPrerender);
  const base = API_URL.startsWith("http") ? API_URL : `${origen}${API_URL}`;

  const [q, setQ] = useState("");
  const [abiertos, setAbiertos] = useState<string[]>([GRUPOS[0].key]);

  const filtrados = useMemo(() => {
    const term = norm(q.trim());
    if (!term) return GRUPOS;
    return GRUPOS.map((g) => ({
      ...g,
      items: g.items.filter(
        (e) =>
          norm(e.path).includes(term) ||
          norm(e.desc).includes(term) ||
          norm(e.m).includes(term) ||
          norm(g.title).includes(term),
      ),
    })).filter((g) => g.items.length > 0);
  }, [q]);

  const buscando = q.trim().length > 0;
  const encontrados = filtrados.reduce((n, g) => n + g.items.length, 0);

  return (
    <div className="min-w-0">
      <PageHeader
        title="API"
        subtitle="Todo lo que ves en esta consola existe primero como API, y corre en esta computadora. Construye encima."
        right={
          <span className="tnum text-cuerpo text-ink-3">
            <span className="font-medium text-ink">{TOTAL}</span> endpoints
          </span>
        }
      />

      <section className="rounded-lg border border-line bg-surface">
        <h2 className="border-b border-line px-5 py-3 text-rotulo font-semibold uppercase tracking-[0.06em] text-ink-3">
          Cómo consultarlo desde tu terminal
        </h2>
        <div className="grid grid-cols-1 gap-1 border-b border-line/60 px-5 py-4 md:grid-cols-[190px_1fr] md:gap-6">
          <p className="text-cuerpo font-medium text-ink">Dirección</p>
          <code className="self-center break-all font-mono text-cuerpo text-ink-2">{base}</code>
        </div>
        <div className="grid grid-cols-1 gap-1 border-b border-line/60 px-5 py-4 md:grid-cols-[190px_1fr] md:gap-6">
          <p className="text-cuerpo font-medium text-ink">Cómo te identificas</p>
          <div className="text-cuerpo leading-relaxed text-ink-2">
            <p>
              No hay cuentas ni API keys: cada arranque de{" "}
              <code className="font-mono text-cuerpo text-ink">aiuda start</code> genera un token
              de sesión y lo imprime en la terminal, dentro de la liga de la consola
              (<code className="font-mono text-cuerpo text-ink">?token=…</code>). Ese mismo token
              va en los ejemplos de abajo.
            </p>
            <pre className="mt-2 overflow-x-auto rounded-md bg-panel px-3 py-2 font-mono text-cuerpo leading-relaxed text-ink-2">
              {"export AIUDA_TOKEN=\"el-token-de-tu-arranque\""}
            </pre>
            <p className="mt-2 text-cuerpo text-ink-3">
              Si arrancas con <code className="font-mono text-cuerpo">aiuda start --no-token</code>,
              el parámetro sobra. El servidor escucha solo en 127.0.0.1: nada de esto sale de tu
              computadora.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-1 border-b border-line/60 px-5 py-4 md:grid-cols-[190px_1fr] md:gap-6">
          <p className="text-cuerpo font-medium text-ink">Primer request</p>
          <pre className="overflow-x-auto self-center font-mono text-cuerpo leading-relaxed text-ink-2">
            {curlDe(base, { m: "GET", path: "/v1/cartera", desc: "" })}
          </pre>
        </div>
        <div className="grid grid-cols-1 gap-1 px-5 py-4 md:grid-cols-[190px_1fr] md:gap-6">
          <p className="text-cuerpo font-medium text-ink">Referencia completa</p>
          <p className="self-center text-cuerpo leading-relaxed text-ink-2">
            El esquema OpenAPI que sirve el propio servidor, con los cuerpos y respuestas de cada
            endpoint:{" "}
            <a
              href={`${base}/docs`}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent-ink hover:underline"
            >
              /docs
            </a>{" "}
            (y el JSON en{" "}
            <a
              href={`${base}/openapi.json`}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent-ink hover:underline"
            >
              /openapi.json
            </a>
            ).
          </p>
        </div>
      </section>

      <div className="mt-6 mb-3 flex flex-wrap items-center justify-between gap-3">
        <SearchInput
          value={q}
          onChange={setQ}
          placeholder="Busca por ruta o por lo que hace"
        />
        <span className="tnum text-apoyo text-ink-3">
          {buscando
            ? `${encontrados} de ${TOTAL} endpoints`
            : "Abre un tema para ver sus endpoints"}
        </span>
      </div>

      <div className="space-y-2.5">
        {filtrados.map((g) => {
          const abierto = buscando || abiertos.includes(g.key);
          return (
            <section key={g.key} className="overflow-hidden rounded-lg border border-line bg-surface">
              <button
                type="button"
                onClick={() =>
                  setAbiertos((prev) =>
                    prev.includes(g.key) ? prev.filter((k) => k !== g.key) : [...prev, g.key],
                  )
                }
                aria-expanded={abierto}
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-panel/40"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-seccion font-semibold text-ink">{g.title}</p>
                  <p className="text-apoyo text-ink-3">{g.hint}</p>
                </div>
                <span className="tnum shrink-0 text-apoyo text-ink-3">
                  {g.items.length} endpoint{g.items.length === 1 ? "" : "s"}
                </span>
                <svg
                  viewBox="0 0 12 12"
                  className={`h-3 w-3 shrink-0 text-ink-3 transition-transform ${abierto ? "rotate-90" : ""}`}
                  fill="none"
                >
                  <path
                    d="M4.5 3 8 6l-3.5 3"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              {abierto && (
                <div className="border-t border-line">
                  {g.items.map((e) => (
                    <EndpointRow key={`${e.m} ${e.path}`} e={e} base={base} />
                  ))}
                </div>
              )}
            </section>
          );
        })}

        {buscando && filtrados.length === 0 && (
          <div className="rounded-lg border border-line bg-surface px-6 py-10 text-center">
            <p className="text-cuerpo font-medium text-ink">Nada con &ldquo;{q}&rdquo;</p>
            <p className="mt-1 text-cuerpo text-ink-3">
              Prueba con una ruta (invoices, cua) o con lo que quieres lograr (pago, recordatorio).
            </p>
          </div>
        )}
      </div>

      <p className="mt-4 text-cuerpo leading-relaxed text-ink-3">
        Las rutas con <code className="font-mono text-apoyo">{"{llaves}"}</code> esperan un id:
        sustitúyelo antes de correr el comando. aiuda es abierto (Apache-2.0): los mismos
        conectores que usa esta consola los puedes usar tú.
      </p>
    </div>
  );
}
