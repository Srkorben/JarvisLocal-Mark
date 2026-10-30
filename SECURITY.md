# Seguridad de Mark Scout / JarvisLocal

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
- llamada o PTT activados explícitamente desde la UI; no hay wake word,
  escucha fuera de una sesión ni keylogging;
- audio de turnos no persistido y transcripción omitida de auditoría por defecto;
- transcripción ambigua/silenciosa no llega al LLM ni a herramientas;
- voz hablada nunca crea un `ConfirmationReceipt` ni concede permisos;
- Chatterbox aislado sin puerto y en modo offline; CUDA solo acelera inferencia
  local y no modifica autoridad, permisos ni confirmaciones;
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
enrolamiento por micrófono exige una acción CLI local y la frase exacta `MI VOZ`.
La interfaz también permite importar una muestra únicamente después de confirmar
propiedad o permiso del titular. En ambos casos queda dentro de
`data/voices/user`, ignorada por Git, y ligada por SHA-256 a un manifiesto de TTS
local. Si cambia, el worker no arranca. No existe una herramienta del LLM para
enrolar, sustituir o exportar una voz.

La importación acepta solo extensiones cerradas, rechaza rutas, limita tamaño y
duración, normaliza a PCM16/24 kHz y usa FFmpeg con comando fijo cuando hace falta.
Se bloquea mientras la conversación de voz está activa. Un reemplazo conserva un
respaldo local recuperable; auditoría no almacena PCM ni el nombre original. La
confirmación de uso de una voz nunca autoriza acciones del agente.

Los pesos y el tokenizador se descargan en setup; al ejecutar, el worker establece
modo offline y deshabilita telemetría de Hugging Face. El modelo incorpora su
marca de agua PerTh. Esto no elimina el riesgo de suplantación si otro software
obtiene la muestra, por lo que el directorio debe considerarse sensible y quedar
fuera de sincronización cloud.

## Detención

`Ctrl+C` detiene la CLI de diagnóstico y cada herramienta cooperativa consulta el token antes y
después de actuar. Los controles locales **Interrumpir** y **Colgar** cancelan el turno:
detienen reproducción, stream HTTP y worker de clonación. Copia borra parciales y
movimiento revierte si se cancela durante la operación. El botón de bandeja sigue
siendo trabajo de Fase 5.

Consulta el análisis completo en [docs/threat-model.md](docs/threat-model.md).

## Centro de control web

El centro de control escucha solo en `127.0.0.1` y escoge entre los puertos
8765–8774. No se enlaza a `0.0.0.0`, IPv6 global ni LAN. Usa un token aleatorio por
proceso, cookie HttpOnly/SameSite, comprobaciones Host/Origin, CSRF, CSP, límite de
cuerpo y `no-store`. El archivo de endpoint recibe ACL de la cuenta local. Queries,
cookies y tokens se omiten de logs.

La API no es un shell: las acciones ejecutables únicamente aceptan un identificador
presente en el catálogo compilado y el booleano `confirmed`. La ruta separada de
importación acepta un nombre base, Base64 acotado y dos booleanos tipados; nunca
acepta una ruta local o un comando. Ejecutable, argumentos y working directory
proceden de `ToolSpec` revisados y se lanzan con `shell=False`. Una página, modelo,
documento o petición HTTP no puede añadir herramientas. Mantenimiento y
enrolamiento exigen confirmación en la interfaz; grupos de exclusión impiden que
modelos, audio o instaladores incompatibles compitan entre sí.

La aplicación WPF no amplía esta autoridad. WebView2 solo permite navegar al
puerto loopback exacto; deniega permisos web, ventanas emergentes y navegación
externa, y desactiva DevTools y menús contextuales. La voz oculta no escribe
stdout/stderr a archivos. El canal de presencia es efímero, autenticado y acepta
solo estado, transcripción, respuesta y error acotados; campos de política,
permisos o herramientas son rechazados.

La API de módulos es autenticada y de solo lectura. Construye una vista curada de
la configuración y recuentos SQLite; no devuelve tokens, contraseñas, contenido de
conversaciones ni rutas de modelos. Solo Interfaz permite cambiar calidad visual,
una preferencia de `localStorage` sin efecto sobre permisos. Autoridad y Seguridad
no pueden editarse desde WebView2.

Los clientes 3D reciben únicamente la presencia efímera necesaria para renderizar.
El token de sesión se hereda por entorno al proceso, no se persiste en el proyecto
gráfico y no concede acceso a acciones del catálogo. Un documento, escena o asset
3D continúa siendo datos no confiables y jamás puede elevar permisos.
