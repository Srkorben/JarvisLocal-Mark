# ADR 0006: RAG híbrido en SQLite antes de incorporar un motor vectorial

Estado: aceptada — 2026-10-07

La primera implementación mantiene documentos, fragmentos, metadatos, FTS5 y
vectores `float32` en la misma base SQLite. La recuperación léxica usa BM25; la
semántica calcula coseno exacto y la combinación usa reciprocal rank fusion.
Todas las consultas filtran por `project_id` antes de puntuar.

No se hace obligatorio Qdrant ni `sqlite-vec`. Para una sola máquina y los
proyectos iniciales, un segundo servicio añade ciclo de vida, puertos, copias y
riesgo de filtros mal aplicados sin una ventaja demostrada. `sqlite-vec` aún no
es necesario para el volumen de aceptación.

La búsqueda exacta se detiene por encima de 20.000 vectores; no degrada
silenciosamente a un escaneo ilimitado. Al acercarse a ese límite se repetirá un
benchmark y se decidirá entre una extensión SQLite madura y Qdrant local. Migrar
el índice no cambia SQLite como fuente de metadatos ni la frontera de proyectos.

