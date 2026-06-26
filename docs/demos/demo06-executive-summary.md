# Production Hardening as Configuration — Resumen ejecutivo

**Agente de producción (reembolsos) con endurecimiento real — HITL durable + auto-corrección + protección de secretos — construido en los 6 frameworks y medido de forma pareja.**

---

## Takeaway en una línea

> El **único** mecanismo de seguridad de producción que **ningún** framework Python ofrece de fábrica —ni siquiera LangGraph— es el **enmascarado de secretos hacia el LLM**. Colmena es el único donde *olvidarse de protegerlo no puede filtrar el secreto*. Esa es la ventaja defendible. **No** es "menos líneas de código".

---

## Qué se probó

El mismo agente de reembolsos en los 6 frameworks (Colmena, CrewAI, LangChain, LlamaIndex, LangGraph, Google ADK), con el flujo completo de un agente real de producción:

1. **Decide** el reembolso respetando una política (montos > 100 USD no se auto-aprueban).
2. **Se auto-corrige** (critic-retry) si la decisión viola la política.
3. **Usa un secreto** (API key de pagos) en una herramienta — el secreto **no debe llegar nunca al LLM**.
4. **Pausa para aprobación humana** (HITL) y **sobrevive un reinicio de proceso** (durable).
5. **Enruta** según la respuesta del humano (aprobar / rechazar / escalar).

**Comparación pareja:** mismo modelo, mismo proxy, mismos prompts y escenario compartido; cada competidor usa el patrón idiomático que recomienda su propia documentación. Los 6 **pasan** end-to-end, sin fuga de secreto, con decisión correcta.

---

## El hallazgo central

| Capacidad | Colmena | LangGraph | CrewAI / LangChain / LlamaIndex / ADK |
|---|:--:|:--:|:--:|
| Grafo / branching | nativo | nativo | a mano |
| HITL durable (sobrevive reinicio) | nativo | **nativo** | a mano |
| Auto-corrección (critic-retry) | nativo | nativo | a mano |
| **Enmascarado de secretos** | **nativo** | **a mano** | **a mano** |

- **El enmascarado de secretos es el diferenciador universal.** Es la única fila donde solo Colmena es nativo. En todos los demás, el desarrollador tiene que acordarse de "limpiar" manualmente cada herramienta que toca un secreto. **Lo probamos: la versión que se olvida de limpiar, filtra el secreto al LLM.** En Colmena es un flag (`secure: true`) que el motor garantiza — imposible de olvidar.
- **LangGraph es el par honesto.** Iguala a Colmena en grafo, HITL durable y auto-corrección. La diferencia real vs. el competidor más fuerte **se reduce al enmascarado**.
- **Los 4 frameworks restantes** hacen las cuatro capacidades a mano.

---

## Lo que este demo NO dice (honestidad ante un comprador técnico)

- **No es un win de "menos líneas".** Medido en serio, Colmena no escribe menos código (Colmena 120 + 115 de config declarativa; competidores 93–171; LangGraph es el que **más** tiene, 171). La ventaja es *cualitativa*: en Colmena el endurecimiento es **configuración declarativa que el motor garantiza**; en los demás es **lógica imperativa que mantenés y podés romper**.
- **vs. LangGraph la ventaja es acotada** (esencialmente el enmascarado). Decirlo de frente da credibilidad.

---

## Cómo venderlo

- **Liderar con seguridad, no con líneas de código.** El mensaje es: *"Tus secretos no llegan al LLM por diseño del motor, no porque un desarrollador se haya acordado de limpiarlos."* Es un argumento de **riesgo/cumplimiento**, no de productividad.
- **Mostrar el contrafáctico de fuga** como evidencia (la versión naive filtra; Colmena no puede).
- **Reconocer la paridad con LangGraph** en HITL/grafo/retry — y cerrar con el enmascarado como el único hueco que LangGraph también deja abierto.
- **Para los 4 code-first**, sumar que las cuatro capacidades son código a mano (más superficie de error), respaldado por la matriz.

---

## Evidencia y reproducibilidad

- Detalle técnico: [`demo06-refund-agent.md`](demo06-refund-agent.md) · Réplica: [`demo06-replication.md`](demo06-replication.md)
- Datos crudos: `runs/demo06/summary.{json,csv}` (6 frameworks, todos `all_ok=true`, `secret_leaked=false`)
- Gráficos: `runs/demo06/plots/` (matriz de capacidades, garantía de enmascarado, LOC honesto)
- Correr todo: `bash scripts/run_demo06.sh`
