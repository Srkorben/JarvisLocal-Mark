# Seguridad de JarvisLocal

## Frontera de confianza

El LLM, los documentos, RAG, páginas web, correo, OCR y texto de pantalla se
consideran **contenido no confiable**. Ninguno puede conceder permisos, confirmar
acciones o modificar política. El modelo solo propone `ActionRequest` tipadas.

El flujo obligatorio es:

```text
LLM → esquema → ActionExecutor → PolicyEngine → confirmación local → herramienta
                                                   │
                                                   └→ auditoría
```

`ActionExecutor` es la única puerta de ejecución del núcleo Python. Las futuras
acciones sensibles de Windows atravesarán además un broker .NET independiente.
No existe una herramienta para ejecutar PowerShell, CMD o código arbitrario.

## Niveles

| Nivel | Clase | Política |
|---:|---|---|
| 0 | lectura/observación | automática solo dentro de recursos autorizados |
| 1 | reversible | automática si política y presupuesto lo permiten; siempre auditada |
| 2 | sensible | confirmación explícita desde UI local confiable |
| 3 | privilegiado | deshabilitado por defecto; UAC manual, nunca eludido |

El riesgo lo recalcula `PolicyEngine` a partir de herramienta, rutas,
reversibilidad, efectos externos y elevación. Un nivel declarado por el LLM no se
acepta como autoridad.

## Controles activos en Fases 0, 1, 2, 3 y 4

- servicios de modelo restringidos a `http://127.0.0.1`;
- listas blancas independientes de herramientas, rutas, aplicaciones y dominios;
- denylist de `.ssh`, `.gnupg`, `.aws`, `.azure`, `AppData`, `Windows` y
  `ProgramData`;
- aislamiento de cada acción al proyecto explícito;
- permisos por proyecto (`read`, `index`, `memory`, `open`, `execute`, `write`)
  comprobados fuera del LLM; los tres últimos son falsos por defecto;
- filtros `project_id` aplicados antes de búsquedas FTS o vectoriales;
- índice limitado a raíces autorizadas, sin symlinks y con exclusiones propias;
- resultados RAG etiquetados como contenido no confiable y con citas/hash;
- patrones de prompt injection señalados sin convertirlos en instrucciones;
- argumentos cerrados (`extra=forbid`) y `expected_result` obligatorio;
- límite de pasos, duración, archivos modificados y bytes salientes;
- timeout y token de cancelación por acción;
- handlers síncronos cancelados esperan limpieza cooperativa antes de devolver;
- rutas UNC, symlinks y junctions rechazados;
- creación/copia exclusivas sin overwrite; movimiento mismo volumen con
  confirmación nivel 2, SHA-256 y referencia de rollback;
- aplicaciones por ruta `.exe` absoluta en allowlist, sin argumentos del modelo;
- Git mediante ejecutable/argumentos fijos y sin shell;
- modo simulación sin efectos;
- confirmaciones vinculadas al `request_id` y solo desde la CLI local;
- auditoría sin contenido de conversaciones ni salida de herramientas por defecto;
- triggers que impiden `UPDATE` y `DELETE` de eventos;
- hashes encadenados que detectan cambios externos y no se recalculan al arrancar.
- PTT explícito y visible; no hay wake word, escucha permanente ni keylogging;
- audio de turnos no persistido y transcripción omitida de auditoría por defecto;
- transcripción ambigua/silenciosa no llega al LLM ni a herramientas;
- voz hablada nunca crea un `ConfirmationReceipt` ni concede permisos;
- Chatterbox aislado sin puerto, en modo offline y CPU por defecto;
- clonación bloqueada sin muestra propia y consentimiento local ligado por SHA-256;
- cancelación de Chatterbox termina su proceso en vez de fingir corte cooperativo.

La cadena hash detecta alteraciones, pero aún no tiene un ancla firmada fuera de
SQLite. Un atacante con control total de la cuenta podría reemplazar toda la base.
El endurecimiento de Fase 8 contemplará firma/anclaje, DPAPI y retención.

La detección de frases sospechosas es una ayuda diagnóstica, no una barrera de
seguridad completa. La barrera real es estructural: los documentos solo llegan
como resultado de herramienta; no pueden editar `Settings`, política, allowlists
ni recibos de confirmación. El perfil rechaza inferencias y solo acepta entradas
explícitas desde una interfaz local confiable.

La implementación Python reduce TOCTOU mediante normalización, rechazo de reparse
points, creación exclusiva y verificación posterior, pero no promete resistir a
un atacante local que cambie la jerarquía de directorios en la ventana exacta de
uso. Por ello escritura permanece denegada por defecto. Operaciones más amplias,
credenciales, borrado, overwrite o privilegios esperarán al broker aislado.

## Decisiones temporales

Las decisiones persistentes requieren confirmación explícita desde una superficie
local confiable. Documentos, RAG, tool results y texto generado sólo pueden aportar
procedencia; no pueden crear decisiones ni conceder autoridad. La herramienta
`get_project_decision` es de lectura, se filtra por el proyecto activo y no acepta
un `project_id` elegido por el modelo.

Corregir crea una versión nueva y cierra la anterior. Olvidar un tema es una
operación CLI explícita que elimina toda su cadena y no reactiva versiones viejas;
la auditoría conserva metadatos mínimos de la operación, no el contenido borrado.
La eliminación de filas no garantiza borrado forense de WAL, backups, snapshots o
medios físicos, limitación que debe tratar el endurecimiento de Fase 8.

## Reglas para nuevas herramientas

Cada herramienta debe tener modelo Pydantic, riesgo base, reversibilidad, timeout,
cancelación, resultado estructurado y prueba. Las rutas deben normalizarse antes de
evaluarse. Las acciones sensibles requieren vista previa exacta y confirmación
local. Borrado debe usar Papelera; sobrescritura debe crear respaldo cuando sea
razonable. Los secretos usarán Credential Manager o DPAPI, nunca TOML o SQLite en
texto plano.

No se aceptará una herramienta de «ejecutar cualquier comando». PowerShell solo
podrá aparecer detrás de plantillas cerradas y parámetros validados, si una API
estructurada no existe.

## Voz clonada

La voz sintética es salida expresiva, no identidad ni autenticación. El
enrolamiento exige una acción CLI local, la frase exacta `MI VOZ` y almacena una
muestra dentro de `data/voices/user`, ignorada por Git. El manifiesto solo autoriza
TTS local de JarvisLocal. Si la muestra cambia, el hash deja de coincidir y el
worker no arranca. No existe una herramienta del LLM para enrolar, sustituir o
exportar una voz.

Los pesos y el tokenizador se descargan en setup; al ejecutar, el worker establece
modo offline y deshabilita telemetría de Hugging Face. El modelo incorpora su
marca de agua PerTh. Esto no elimina el riesgo de suplantación si otro software
obtiene la muestra, por lo que el directorio debe considerarse sensible y quedar
fuera de sincronización cloud.

## Detención

`Ctrl+C` detiene la CLI y cada herramienta cooperativa consulta el token antes y
después de actuar. `Ctrl+Alt+Pause` cancela el turno de voz global incluso sin foco:
detiene reproducción, stream HTTP y worker de clonación. Copia borra parciales y
movimiento revierte si se cancela durante la operación. El botón de bandeja sigue
siendo trabajo de Fase 5.

Consulta el análisis completo en [docs/threat-model.md](docs/threat-model.md).
