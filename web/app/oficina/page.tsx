import { redirect } from "next/navigation";

// "Oficina administrativa" se reconcibió como "Rutinas" (crea tu propia tarea de
// backoffice y guárdala para repetirla). La ruta vieja redirige, no se borra.
export default function OficinaRedirect() {
  redirect("/rutinas");
}
