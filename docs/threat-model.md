# Modelo de amenazas

## Activos

Documentos y proyectos, historial, identidad del usuario, credenciales, integridad
de archivos, control de aplicaciones y trazabilidad de decisiones.

## Entradas no confiables

- salida del LLM;
- documentos, RAG y metadatos;
- páginas, correo y APIs remotas;
- OCR, VLM y texto de interfaces;
- nombres de archivo, rutas simbólicas y argumentos propuestos;
- resultados de herramientas que incorporen contenido externo.

## Amenazas y controles

| Amenaza | Control actual | Pendiente |
|---|---|---|
| tool call inventada o mal formada | Pydantic cerrado + allowlist | fuzzing de esquemas |
| path traversal/cruce de proyecto | resolución canónica + `commonpath` | pruebas de junction/reparse point |
| lectura de secretos | denylist + extensiones/tamaño | clasificación de secretos |
| prompt injection | datos sin autoridad + política fuera del prompt + prueba RAG maliciosa | corpus adversarial amplio y web |
| cruce de memoria entre proyectos | filtros SQL `project_id` + permisos + pruebas léxica/semántica | fuzzing y migraciones multiusuario |
| bucle de agente | pasos y tiempo máximos | presupuestos por plan/subtarea |
| acción sensible sin usuario | confirmación local ligada a request | UI de bandeja firmada |
| elevación | nivel 3 deshabilitado | broker separado y UAC manual |
| exfiltración | dominios vacíos y 0 bytes salientes | medidor en broker/navegador |
| alteración del audit log | triggers + hash encadenado | ancla/firma externa y retención |
| cancelación tardía | checks cooperativos + cierre del stream HTTP probado | controles locales Interrumpir/Colgar |
| symlink/junction | rechazo de reparse points + ruta canónica | handles relativos en broker |
| TOCTOU concurrente | create exclusivo, no-overwrite, hash y rollback | handles de directorio en broker |
| proceso/comando inyectado | `.exe` allowlist sin args; Git argv fijo sin shell | firma/editor de allowlist |
| proceso comprometido | mínimo privilegio, loopback | ACL de pipe/AppContainer |

## Propiedades que no se prometen

La cuenta local que controla todos los archivos puede reemplazar código y base de
datos. La cadena de hash detecta edición de eventos, pero no resiste por sí sola a
un atacante que sustituya el historial completo. Tampoco se garantiza cancelación
instantánea de código síncrono de terceros, control seguro de UAC/pantalla bloqueada
ni interpretación fiable de cualquier interfaz visual.

## Pruebas mínimas antes de herramientas con escritura

- rutas inexistentes, UNC, junctions y cambios entre validación/uso;
- cancelación antes, durante y después de E/S;
- rollback verificado;
- límite de archivos modificados medido por resultado real;
- confirmación rechazada, expirada y reutilizada;
- caída del broker y respuesta parcial;
- manipulación del audit log;
- inyección en nombre/contenido de archivo.
