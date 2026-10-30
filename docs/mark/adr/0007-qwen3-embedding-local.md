# ADR 0007: proveedor de embeddings local y Qwen3-Embedding-0.6B

Estado: aceptada — 2026-10-07

RAG depende de `EmbeddingProvider`, no de llama.cpp ni de un modelo concreto. El
proveedor inicial usa un segundo `llama-server` en `127.0.0.1:8081`, con UI
deshabilitada, pooling `last`, un slot y cancelación cerrando la petición HTTP.
No recibe `PolicyEngine` ni autoridad de herramientas.

Se seleccionó el GGUF oficial `Qwen3-Embedding-0.6B-Q8_0.gguf`: 1024 dimensiones,
639.150.592 bytes, Apache-2.0 y SHA-256
`06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.
La configuración inicial usa contexto 2048 y cero capas GPU para preservar VRAM
para Qwen3-8B. Una instrucción de consulta separa queries de documentos.

El benchmark reproducible recuperó la fuente esperada en 4/4 casos, incluida una
paráfrasis en español y contenido con indicios de prompt injection. Cambiar el
modelo exige reindexar porque cada fragmento conserva el identificador del modelo.

