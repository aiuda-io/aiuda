// Formateo canónico es-MX de FECHAS y horas: una sola fuente. Antes vivía
// disperso (~10 variantes inline, algunas con ISO crudo). Centralizar aquí evita
// que dos pantallas muestren la misma fecha distinto. (mxn() vive en lib/api.)

const MX = "es-MX";

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // Fechas SIN hora se interpretan como medianoche LOCAL, no UTC: si no,
  // `new Date("2026-05-18")` es UTC y en huso México (-6) retrocede un dia
  // (mostraria "17 may"). Las cadenas con hora/zona se respetan tal cual.
  let s = iso;
  if (/^\d{4}-\d{2}$/.test(s)) s = `${s}-01T00:00:00`; // periodo "2026-06"
  else if (/^\d{4}-\d{2}-\d{2}$/.test(s)) s = `${s}T00:00:00`; // fecha sola
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 18 may 2026 — fecha con año. El formato por defecto de la consola. */
export function fecha(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? d.toLocaleDateString(MX, { day: "2-digit", month: "short", year: "numeric" }) : "·";
}

/** 18 may — día y mes, sin año (listas densas donde el año se sobreentiende). */
export function fechaDM(iso: string | null | undefined): string {
  const d = parse(iso);
  return d ? d.toLocaleDateString(MX, { day: "2-digit", month: "short" }) : "·";
}

/** 18 may, 14:30 — fecha y hora (mensajes, actividad). */
export function fechaHora(iso: string | null | undefined): string {
  const d = parse(iso);
  return d
    ? d.toLocaleString(MX, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "·";
}

/** junio 2026 — mes y año (periodos como "Plan y uso"). Sin arg = mes actual. */
export function periodo(iso?: string | null): string {
  const d = iso === undefined ? new Date() : parse(iso);
  return d ? d.toLocaleDateString(MX, { month: "long", year: "numeric" }) : "·";
}

/** 14,851 — número con separador de miles. */
export function num(value: number): string {
  return Number(value).toLocaleString(MX);
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
  if (d.length !== 10) return crudo; // no es MX de 10 dígitos: crudo, sin mentir
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

/** hace 4 min · hace 1 h · hace 2 d — tiempo relativo corto (bandejas). */
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
