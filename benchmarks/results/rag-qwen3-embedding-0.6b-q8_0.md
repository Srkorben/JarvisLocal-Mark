# Benchmark RAG local

Fecha UTC: 2026-10-08T01:50:29+00:00

## Configuración

- Embeddings: `qwen3-embedding-0.6b-q8_0` / `Qwen3-Embedding-0.6B-Q8_0.gguf`
- Tamaño/SHA-256: 639150592 bytes / `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`
- Dimensiones: 1024
- Contexto: 2048 tokens
- GPU layers: 0
- Documentos/fragmentos: 4 / 4

## Rendimiento

- Indexación: 6.125 s
- Latencia mediana por consulta: 1.524 s
- RAM proceso embeddings: 1207.29 MiB
- VRAM antes/cargado/delta: 2912 / 3471 / 559 MiB
- Base SQLite: 167936 bytes

## Evaluación

Resultado: **4/4**.

- PASS — ¿Qué se decidió para el almacenamiento vectorial? → `architecture.md#Decisión de arquitectura` (1.547 s)
- PASS — ¿Cuál es la fecha límite del prototipo lunar? → `planning.txt` (1.531 s)
- PASS — ¿Qué automóvil de demostración funciona sin servicios externos? → `vehicle.md#Demostrador de movilidad` (1.469 s)
- PASS — ¿Dónde aparece el código documental ORION? → `untrusted.md#Contenido externo` (1.516 s)

Cadena de auditoría válida: True.

Este conjunto es deliberadamente pequeño; valida integración y regresiones, no calidad universal de recuperación.