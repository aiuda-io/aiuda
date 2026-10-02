/** El oficio visible de un slug de runtime.
 *
 *  El dueño NUNCA creó a nadie con estos nombres: son los motores internos que redactan
 *  (cobranza, ventas, recepción, conciliación). Donde hay un ayudante suyo detrás se
 *  muestra SU nombre, y esto queda solo como respaldo para el trabajo que no tiene
 *  ayudante asignado: conciliaciones y promesas, que no las redacta nadie.
 *
 *  Aquí vivía `web/lib/asistentes.ts`, un catálogo de 334 líneas con ocho personas
 *  ficticias, sus capacidades y su navegación. Era un segundo sistema de agentes
 *  paralelo al real, y estaba desincronizado del backend.
 */
const OFICIO: Record<string, string> = {
  mariana: "Cobranza",
  carlos: "Ventas",
  valeria: "Recepción",
  diego: "Conciliación",
};

export function oficioDe(slug: string | null | undefined): string {
  return OFICIO[slug ?? ""] ?? "Tu ayudante";
}
