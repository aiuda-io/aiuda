// Candado de scroll de la página, compartido por Drawer y Modal. Lleva la cuenta de
// capas abiertas: con un Modal encima de un Drawer, cerrar una capa no le suelta el
// scroll a la otra, y al cerrar la última la página vuelve a moverse.
let capas = 0;

export function lockScroll(): () => void {
  if (capas++ === 0) document.body.style.overflow = "hidden";
  let suelto = false;
  return () => {
    if (suelto) return;
    suelto = true;
    if (--capas === 0) document.body.style.overflow = "";
  };
}
