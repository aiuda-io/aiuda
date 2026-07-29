## Qué cambia

<!-- Una o dos frases. Un cambio, un PR. Si cierra un issue, pon "Cierra #123". -->

## Cómo se probó

<!-- Comandos que corriste y su resultado. Por ejemplo: -->

- [ ] `uv run pytest` verde
- [ ] `uv run ruff check .` limpio
- [ ] `cd web && npx tsc --noEmit` limpio (si tocaste la consola)
- [ ] `cd web && npm run build` (si tocaste la consola)

## Checklist de reglas

- [ ] Cero emojis y sin em dashes en código, UI y textos.
- [ ] Texto de producto en español mexicano.
- [ ] Tests verdes; agregué o actualicé tests si el cambio lo amerita.
- [ ] Sin secretos ni datos internos (claves, tokens, correos o rutas personales).
- [ ] No debilité los safeguards de los agentes (reglas de fábrica, máquina de
      estados de aprobación, fact-check de pagos).
- [ ] Los no-ops o cosas "que se cablean después" están marcadas honestamente en
      la UI y en el commit.
