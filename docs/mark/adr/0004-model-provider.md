# ADR 0004: Proveedor de modelos como puerto sin autoridad

Estado: aceptada — 2026-10-07

`Orchestrator` depende de un `ModelProvider` abstracto con health, streaming,
cancelación, métricas y respuestas tipadas. Ollama y llama.cpp adaptan sus formatos
en el borde; el historial interno conserva un formato canónico.

El proveedor no recibe `PolicyEngine` ni puede modificar configuración, permisos
o auditoría. Sus tool calls siempre cruzan `ActionRequest` y `ActionExecutor`.
Cambiar backend o modelo por TOML no amplía autoridad.

Consecuencia: existe algo de código de adaptación, pero el núcleo es sustituible,
testeable con un proveedor falso y resistente a cambios del servidor de inferencia.
