// Etiquetas canónicas de las secciones de primer nivel (los destinos directos
// del menú). Fuente única para el Rastro (saber "dónde estás") y para resolver
// el nombre de cada paso del camino. Las páginas de detalle declaran su propia
// etiqueta humana con usePageTrail ("Factura M-107", el nombre del cliente, …).
export const SECTION_LABELS: Record<string, string> = {
  "/": "Resumen",
  "/centro": "Centro de mando",
  "/facturas": "Facturas",
  "/promesas": "Promesas de pago",
  "/conversaciones": "Conversaciones",
  "/clientes": "Clientes",
  "/prospectos": "Prospectos",
  "/productos": "Productos",
  "/citas": "Agenda",
  "/conciliacion": "Conciliación",
  "/ayudantes": "Tu equipo",
  "/rutinas": "Rutinas",
  "/integraciones": "Integraciones",
  "/sat": "SAT · Bóveda fiscal",
  "/importar": "Importar datos",
  "/configuracion": "Configuración",
  "/aparatos": "Tus aparatos",
  "/desarrolladores": "API",
  "/perfil": "Tu perfil",
};

// ¿Es un destino de primer nivel del menú? Entrar a una sección por el menú es
// empezar de nuevo, no continuar el camino: por eso reinicia el rastro.
export function isSection(href: string): boolean {
  return href in SECTION_LABELS;
}
