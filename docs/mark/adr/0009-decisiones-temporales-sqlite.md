# ADR 0009 — Decisiones temporales tipadas en SQLite

## Estado

Aceptada — 2026-10-08.

## Contexto

La memoria episódica guardaba decisiones confirmadas como eventos independientes.
No podía determinar de forma fiable cuál seguía vigente, qué había sustituido,
cuándo cambió ni qué fuente respaldaba el cambio. CORE demuestra el valor del
patrón de contradicciones encadenadas, pero su grafo general, ingestión automática
y dependencias no son apropiados para el alcance local actual.

## Decisión

Añadir `temporal_decisions` a SQLite, con una única decisión vigente por
`project_id + topic_key`, intervalos de validez, relación `supersedes_id`, motivo y
procedencia tipada. Sólo una confirmación local explícita puede crear o sustituir
una decisión. El modelo dispone únicamente de una herramienta de consulta.

Una corrección agrega una nueva versión y preserva historia. Una solicitud
explícita de olvido elimina la cadena completa del tema para que ninguna versión
anterior reaparezca como vigente. La auditoría registra la operación sin copiar el
contenido eliminado.

## Consecuencias

- consultas actuales e históricas son deterministas y aisladas por proyecto;
- no se necesita Neo4j ni resolución automática de entidades;
- una fuente documental conserva procedencia, pero no concede autoridad;
- el tema debe elegirse explícitamente; la detección semántica de contradicciones
  queda fuera de alcance;
- el borrado no garantiza erradicación forense en WAL, backups o snapshots;
- la próxima prioridad sigue siendo voz push-to-talk.
