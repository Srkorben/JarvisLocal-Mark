# ADR 0002: El LLM nunca ejecuta directamente

Estado: aceptada — 2026-10-07

Toda capacidad se describe con `ToolSpec` y recibe un `ActionRequest`. El
`ActionExecutor` valida proyecto, política, confirmación, presupuesto, cancelación
y auditoría. El riesgo se calcula fuera del LLM.

No se ofrecerá shell arbitrario. El futuro broker .NET volverá a validar la acción
y tendrá una lista de operaciones cerrada. Esto duplica ciertas validaciones de
forma deliberada para no convertir el proceso Python en autoridad única.
