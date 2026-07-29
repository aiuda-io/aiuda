import { redirect } from "next/navigation";

// "Recados" pasó a "Oficina administrativa" y luego a "Rutinas". La ruta vieja
// redirige directo al destino actual, no se borra.
export default function RecadosRedirect() {
  redirect("/rutinas");
}
