// Formateo canónico es-MX de FECHAS y horas: una sola fuente. Antes vivía
// disperso (~10 variantes inline, algunas con ISO crudo). Centralizar aquí evita
// que dos pantallas muestren la misma fecha distinto. (mxn() vive en lib/api.)

const MX = "es-MX";

// "2 oct": día sin cero y mes corto, separados por un espacio. El navegador, según
// su versión, arma "02-oct" o "02 oct." para es-MX; aquí se compone a mano para
// que una fecha se lea igual en toda la consola.
function diaMes(d: Date): string {
  const mes = d.toLocaleDateString(MX, { month: "short" }).replace(".", "");
  return `${d.getDate()} ${mes}`;
}

function hora(d: Date): string {
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

/** Un instante que manda el servidor, como fecha de verdad. LA única lectura de
 *  fechas de la consola: todo lo demás de este archivo pasa por aquí.
 *
 *  Tres casos:
 *   - Fecha sola ("2026-05-18") o periodo ("2026-06"): medianoche LOCAL. Leída como
 *     UTC, en México retrocede un día y mostraría "17 may".
 *   - Fecha con hora y SIN zona ("2026-10-05T16:11:08"): es UTC. El servidor guarda
 *     en UTC y SQLite no conserva la zona. Leída como local queda seis horas
 *     adelantada: "hace un momento" para algo de hace seis horas.
 *   - Fecha con zona ("…Z", "…+00:00", "…-06:00"): se respeta tal cual.
 *
 *  La única hora que NO es un instante es la de una cita (la que el dueño tecleó,
 *  hora de su reloj): esa se lee con `deReloj`. */
export function instante(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  let s = iso.trim();
  if (/^\d{4}-\d{2}$/.test(s)) s = `${s}-01T00:00:00`;
  else if (/^\d{4}-\d{2}-\d{2}$/.test(s)) s = `${s}T00:00:00`;
  else if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(s)) {
    s = `${s.replace(" ", "T")}Z`;
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Una hora de reloj, sin zona a propósito: la de una cita. "A las 10" es a las 10
 *  de quien la agendó, esté donde esté el servidor. */
export function deReloj(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso.trim().replace(/(Z|[+-]\d{2}:?\d{2})$/i, ""));
  return Number.isNaN(d.getTime()) ? null : d;
}

const parse = instante;

/** ¿El instante cae en el día de hoy de quien mira? */
export function esDeHoy(iso: string | null | undefined): boolean {
  const d = instante(iso);
  return d !== null && d.toDateString() === new Date().toDateString();
}

/** 18 may 2026: fecha con año. El formato por defecto de la consola. */
export function fecha(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${diaMes(d)} ${d.getFullYear()}` : "·";
}

/** 18 may: día y mes, sin año (listas densas donde el año se sobreentiende). */
export function fechaDM(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? diaMes(d) : "·";
}

/** 18 may, 14:30: fecha y hora (mensajes, actividad), en la zona de quien mira. */
export function fechaHora(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? `${diaMes(d)}, ${hora(d)}` : "·";
}

/** lun 5 oct, 16:00: cuándo es una cita. Es hora de reloj (la que tecleó el dueño),
 *  así que se lee con `deReloj`, no con `instante`. Reloj de 24 horas, como el resto
 *  de la consola: sin "p.m." y sin cero a la izquierda en el día. */
export function fechaCita(iso: string | null | undefined): string {
  const d = deReloj(iso);
  if (!d) return "Sin fecha";
  const dia = d.toLocaleDateString(MX, { weekday: "short" }).replace(".", "");
  return `${dia} ${diaMes(d)}, ${hora(d)}`;
}

// "Otros datos" de un cliente: lo que no cupo en nombre, teléfono y correo. La llave
// viene de donde vino el dato (una columna de su Excel, un campo de su sistema), y
// muchas veces es de máquina: "municipio", "dias_credito", "codigo_postal".
const DATO_ES: Record<string, string> = {
  municipio: "Municipio", localidad: "Localidad", ciudad: "Ciudad", colonia: "Colonia",
  estado: "Estado", entidad: "Estado", entidad_federativa: "Estado", pais: "País", country: "País",
  calle: "Calle", direccion: "Dirección", domicilio: "Domicilio", address: "Dirección",
  numero_exterior: "Número exterior", num_exterior: "Número exterior", num_ext: "Número exterior",
  numero_interior: "Número interior", num_interior: "Número interior", num_int: "Número interior",
  cp: "Código postal", c_p: "Código postal", codigo_postal: "Código postal", zip: "Código postal",
  referencia: "Referencia", zona: "Zona", ruta: "Ruta", latitud: "Latitud", longitud: "Longitud",
  rfc: "RFC", curp: "CURP", razon_social: "Razón social", nombre_comercial: "Nombre comercial",
  regimen: "Régimen fiscal", regimen_fiscal: "Régimen fiscal", uso_cfdi: "Uso de CFDI",
  giro: "Giro", actividad: "Actividad", sector: "Sector", categoria: "Categoría", tipo: "Tipo",
  tamano: "Tamaño", empleados: "Empleados", personal_ocupado: "Personal ocupado",
  contacto: "Contacto", contact: "Contacto", puesto: "Puesto", vendedor: "Vendedor",
  telefono2: "Otro teléfono", telefono_2: "Otro teléfono", telefono_fijo: "Teléfono fijo",
  tel: "Teléfono", telefono: "Teléfono", celular: "Celular", whatsapp: "WhatsApp",
  correo2: "Otro correo", correo_2: "Otro correo", email2: "Otro correo", email_2: "Otro correo",
  sitio_web: "Sitio web", pagina_web: "Sitio web", web: "Sitio web", website: "Sitio web",
  facebook: "Facebook", instagram: "Instagram",
  dias_credito: "Días de crédito", credito_dias: "Días de crédito", plazo: "Días de crédito",
  plazo_dias: "Días de crédito", limite_credito: "Límite de crédito",
  forma_pago: "Forma de pago", metodo_pago: "Método de pago",
  condiciones_pago: "Condiciones de pago", lista_precios: "Lista de precios",
  descuento: "Descuento", moneda: "Moneda", banco: "Banco", cuenta: "Cuenta", clabe: "CLABE",
  notas: "Notas", nota: "Nota", notes: "Notas", comentarios: "Comentarios",
  observaciones: "Observaciones", origen: "Origen", fuente: "Origen",
  fecha_alta: "Fecha de alta", cumpleanos: "Cumpleaños", id_externo: "Folio en tu sistema",
};

/** El nombre con el que se le enseña al dueño una llave de "Otros datos".
 *
 *   - Si es una llave conocida ("municipio", "dias_credito"), su nombre en español.
 *   - Si la escribió una persona (trae espacios, mayúsculas o acentos: "Días de
 *     crédito", "Lista VIP"), se respeta tal cual: es su encabezado.
 *   - Si es de máquina y no la conocemos ("fecha_ultima_compra", "tipoCliente"),
 *     se separa en palabras y se le pone mayúscula inicial. No se inventa un acento
 *     ni un significado. */
export function etiquetaDato(llave: string): string {
  const cruda = String(llave ?? "").trim();
  if (!cruda) return "Dato";
  const norma = cruda
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[\s.\-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (DATO_ES[norma]) return DATO_ES[norma];
  // La escribió una persona: no es de máquina.
  if (/\s/.test(cruda) || /[\u0080-\uffff]/.test(cruda) || /^[A-Z][a-z]/.test(cruda)) return cruda;
  if (/^[A-Z0-9]{2,6}$/.test(cruda)) return cruda; // siglas: "RFC", "CP"
  const palabras = norma.split("_").filter(Boolean).join(" ");
  return palabras ? palabras.charAt(0).toUpperCase() + palabras.slice(1) : cruda;
}

// Metros con LADA de 2 dígitos: se agrupan "XX XXXX XXXX"; el resto (LADA de 3)
// como "XXX XXX XXXX". Cubre la gran mayoría de números MX sin una tabla enorme.
const LADA_2 = new Set(["55", "56", "33", "81"]);

/** 8112772622 → "81 1277 2622". Teléfono MX legible a partir de un crudo sucio
 *  (mezcla de +5218…, (55)0433-2181, 10 dígitos). Normaliza dígitos y quita el
 *  país (521+10 o 52+10). Si NO parsea a un MX de 10 dígitos, devuelve el crudo
 *  tal cual: honesto, no inventa. `pais: true` antepone un "+52" discreto. */
export function telefonoMx(raw: string | null | undefined, opts?: { pais?: boolean }): string {
  if (!raw) return "";
  const crudo = String(raw).trim();
  let d = crudo.replace(/\D/g, "");
  if (d.length === 13 && d.startsWith("521")) d = d.slice(3); // móvil con "1": 521 + 10
  else if (d.length === 12 && d.startsWith("52")) d = d.slice(2); // 52 + 10
  // Estados Unidos y Canadá (1 + diez dígitos): un cliente de fuera se lee igual de
  // claro, y con su "+1" para que nadie lo confunda con un número de México.
  if (d.length === 11 && d.startsWith("1")) return `+1 ${d.slice(1, 4)} ${d.slice(4, 7)} ${d.slice(7)}`;
  if (d.length !== 10) return crudo; // ni MX de 10 dígitos ni +1: crudo, sin mentir
  const grupos = LADA_2.has(d.slice(0, 2))
    ? `${d.slice(0, 2)} ${d.slice(2, 6)} ${d.slice(6)}` // 81 1277 2622
    : `${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6)}`; // 999 123 4567
  return opts?.pais ? `+52 ${grupos}` : grupos;
}

// Unidades de medida que llegan en inglés desde algunas fuentes (Odoo, tiendas):
// se muestran en español. Fallback al crudo si no está mapeada (no se inventa).
const UOM_ES: Record<string, string> = {
  units: "pzas", unit: "pza", uom: "pzas",
  pieces: "pzas", piece: "pza", each: "pza", pcs: "pzas", pc: "pza",
  hours: "horas", hour: "hora", hrs: "horas", hr: "hora",
  days: "días", day: "día",
  dozens: "docenas", dozen: "docena",
  boxes: "cajas", box: "caja",
  liters: "L", litres: "L", liter: "L", litre: "L",
  meters: "m", metres: "m", meter: "m", metre: "m",
  kg: "kg", kgs: "kg", g: "g", gr: "g",
};

/** "Units" → "pzas". Unidad de medida en español; fallback al crudo. */
export function unidad(u: string | null | undefined): string {
  if (!u) return "";
  const key = u.trim().toLowerCase();
  return UOM_ES[key] ?? u.trim();
}

/** "Hoy, 10:11" si fue hoy; si no, "05 oct, 10:11". Para bitácoras. */
export function hoyOFecha(iso: string | null | undefined): string {
  const d = instante(iso);
  if (!d) return "";
  if (d.toDateString() !== new Date().toDateString()) return fechaHora(iso);
  return `Hoy, ${hora(d)}`;
}

/** hace 4 min, hace 1 h, hace 2 d: tiempo relativo corto (bandejas). */
export function haceTiempo(iso: string | null | undefined): string {
  const d = parse(iso);
  // Timestamps basura (datetime.min del backend, epoch 0 de contactos de sistema
  // como 0@status) parsean a fechas válidas pero absurdas: "hace 739799 d". No es
  // tiempo real; se trata como desconocido.
  if (!d || d.getFullYear() < 2015) return "·";
  const secs = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (secs < 60) return "hace un momento";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `hace ${mins} min`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `hace ${hrs} h`;
  return `hace ${Math.floor(hrs / 24)} d`;
}
