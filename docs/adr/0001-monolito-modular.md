# ADR 0001: Monolito modular primero

Estado: aceptada — 2026-10-07

JarvisLocal comienza como un paquete Python modular. Distribuir conversación,
memoria y política como servicios añadiría red, autenticación y fallos operativos
sin mejorar aún el aislamiento. Solo se separan procesos por seguridad o recursos:
servidor de modelos, broker .NET y eventualmente Qdrant/VLM.

Consecuencia: las fronteras internas son contratos tipados, no APIs de red. Si un
módulo necesita aislamiento real en el futuro, podrá extraerse sin cambiar el
modelo de acciones.
