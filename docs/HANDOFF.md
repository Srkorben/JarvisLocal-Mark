# Mark / JarvisLocal: documento de transferencia

## Actualización local: XTTS-v2 (12 de octubre de 2026)

- Chatterbox fue rechazado tras dos referencias por sonido robotizado e interferencias.
- El usuario aportó una referencia autorizada de 20,01 s y aceptó una comparación
  audible de XTTS-v2 como mejora clara.
- `xtts` es ahora un `TTSProvider` seleccionable y el proveedor efectivo local.
- Worker aislado JSONL: modelo, latentes de hablante y priming CUDA se cargan una
  vez; cancelación termina el proceso; no abre puertos.
- Modelo `coqui/XTTS-v2` fijado en
  `6c2b0d75eae4b7047358e3b6bd9325f857d43f77`; entorno `.venv-xtts`.
- Medida real: 110,891 s de arranque y 2,281 s para generar 5,387 s de audio ya caliente.
- Suite posterior: 178 pruebas + 9 subpruebas aprobadas.
- Pendiente: conversación humana multivuelta desde WPF y medir el efecto conjunto
  XTTS+Qwen sobre tokens/s. No confundir clonación zero-shot con entrenamiento.

Última actualización: 11 de octubre de 2026 (sesión 3 de Claude Code).
Este documento permite continuar sin depender de las conversaciones anteriores.

## 0b. Entrega Codex: llamada semidúplex y PTT desde la UI (12 de octubre de 2026)

Esta sección es la más reciente y prevalece sobre las descripciones históricas de
voz y del estado de la instalación que aparecen más abajo. La intervención parte
de `edd15ac` en `claude/ref2-chat-ui`; la implementación quedó en `0bdaebc` y
`master` no se fusionó ni se modificó.

### Resultado

- Se eliminaron los controles globales de teclado para voz y el módulo
  `audio/hotkey.py`. No queda ninguna referencia a las antiguas combinaciones en
  código, configuración, scripts o documentación operativa.
- La misma app ofrece **Conversación** y **Pulsar para hablar**. En conversación,
  una sola acción prepara el runtime, abre WASAPI al quedar listo, detecta inicio
  y fin del habla, procesa el turno y vuelve automáticamente a escuchar hasta
  **Colgar**.
- **Silenciar** aborta la captura temporal sin cerrar la llamada; **Reactivar** la
  abre de nuevo. **Interrumpir** propaga cancelación a captura, STT, LLM,
  herramientas y TTS según la fase activa.
- El modo manual abre el micrófono al presionar y lo cierra al soltar. También
  gestiona `pointercancel`, pérdida de captura, pérdida de foco, ocultación de la
  página y teclado accesible para evitar grabaciones huérfanas.
- Se amplió el canal loopback autenticado y tipado con `start_call`, `end_call`,
  `mute`, `unmute`, `start_recording`, `finish_recording` y `cancel`. No transporta
  texto, confirmaciones ni autoridad.
- La presencia efímera añade `listening`, `voice_detected`, `muted` y `ending`,
  junto con modo/llamada/silencio. Revisiones antiguas siguen sin poder sustituir
  el estado actual.
- El endpointing usa RMS local de baja latencia, confirmación de inicio,
  500 ms de preroll, silencio final configurable y rollover de buffers sin voz.
  Silero VAD continúa como filtro dentro de faster-whisper antes de aceptar la
  transcripción.
- La seguridad previa permanece intacta: mismo `Orchestrator`, política, memoria,
  herramientas, auditoría y configuración de privacidad. Una transcripción no
  confirma acciones sensibles.

### Validación

- Suite Windows: **173 pruebas y 9 subtests aprobados**.
- Pruebas automáticas específicas: llamada con detección voz→silencio→respuesta→
  nueva escucha, silencio/reactivación, PTT, cancelación, ausencia de autoridad en
  el canal, CSRF/autenticación y runtime inactivo.
- Validación real en este PC: `JarvisLocal.exe` inició el centro de control y el
  runtime de voz; la UI recorrió `INICIALIZANDO → ESCUCHANDO → MICRÓFONO
  SILENCIADO → ESCUCHANDO → EN ESPERA`. El modo manual quedó disponible y un
  gesto breve abrió/cerró la captura sin dejarla activa.
- Se comprobó el árbol accesible real de WPF/WebView2. Las acciones se validaron
  además en Chromium contra **el mismo servidor y proceso de voz reales**, no un
  runtime simulado.
- No se declara todavía una conversación acústica humana multivuelta: requiere
  que el propietario hable y evalúe STT, corte de pausa, semejanza y naturalidad.

### Limitaciones deliberadas

- Continúa siendo semidúplex. No hay cancelación de eco ni barge-in acústico
  fiable; mientras Mark habla, se utiliza el botón visible **Interrumpir**.
- El runtime puede permanecer preparado después de colgar para evitar otra carga
  costosa; la captura WASAPI sí se libera. Detener el runtime desde Sistemas o
  cerrar la app libera también modelos y procesos.
- No se añadió wake word, escucha fuera de una llamada, segundo orquestador,
  nuevos permisos ni persistencia de audio/transcripciones.

Archivos centrales: `audio/{base,devices,session}.py`, `cli.py`, `config.py`,
`control_center/{voice_control,presence,server,web,catalog,modules}.py`,
`tests/{test_audio,test_control_center}.py`, ADR 0019 y documentación operativa.
H-01 permanece **corregido** desde `81745d7`; esta entrega no reintroduce
persistencia conversacional cuando `store_conversation_content = false`.

## Objetivo y referencias

**Mark** (proyecto técnico **JarvisLocal**) es un asistente de IA local para Windows 11. Usa Qwen3-8B en `llama-server`, STT faster-whisper, TTS Piper o Chatterbox, un centro de control loopback y una app WPF/WebView2. El objetivo es un asistente de uso diario: interfaz funcional, respuestas rápidas, privacidad efectiva y capacidad progresiva de actuar sobre el escritorio.

- **Ref 1.0, rendimiento** (PR #1, `claude/ref1-latency`). Diagnóstico y corrección de la latencia:
  - Chatterbox CUDA hundía al LLM de ~55 a ~6 tokens/s;
  - la GPU queda reservada para el LLM;
  - Piper en CPU como voz provisional (calidad rechazada);
  - streaming, carga diferida y trazas.
- **Ref 2.0, evolución integral** (PR #2, `claude/ref2-chat-ui`): UI/UX, chat, centro de control, servicios y modelos, memoria, herramientas, control de Windows, automatización y visión. **Es la prioridad actual.**

## 0a. Sesión 3 de Claude Code (11 de octubre de 2026)

| Commit | Rama | Contenido |
|---|---|---|
| `59683fb` | `claude/ref1-latency` | Prueba de catálogo determinista (misma fijación que Codex). **CI del PR #1 sin fallos conocidos** en Linux |
| `5678c03` | `claude/ref2-chat-ui` | Fusión de `claude/ref1-latency` (merge normal, sin reescribir historia) |
| `6b63079` | `claude/ref2-chat-ui` | Chat: Esc cancela la respuesta en curso, botón "Ir al final", `aria-busy` durante el streaming |
| `81745d7` | `claude/ref2-chat-ui` | **Privacidad H-01 corregida** (ver más abajo) |
| `062b3b6` | `claude/ref2-chat-ui` | **Historial recuperable en memoria** del centro de control (ver más abajo) y cabecera del chat reorganizada |

- Se conservó íntegra la entrega de Codex (`90f484c`, `6ce5c29`). Un panel de núcleo equivalente que Claude tenía sin publicar se **descartó** para no duplicar el monitor de Codex; queda solo en la rama local `backup/local-core-panel`, que no se publica.
- **Pruebas (nube, Linux):** 167 pasan, 0 fallan.
- **Chromium (Playwright)**, contra el servidor real del panel con un runtime simulado y el `SystemStatusMonitor` de Codex con hardware simulado:
  - streaming, cancelación (botón y Esc), error y mensaje vacío;
  - Markdown y texto malicioso (0 `<img>`, 0 `<script>`);
  - mensaje repetido, modo ampliado, panel Núcleo (VRAM) e "Ir al final".
- **No probado en Windows ni en WPF en esta sesión.**

### Historial del chat (`062b3b6`)

- **Dónde vive:** el centro de control guarda en memoria los últimos 50 turnos (`ChatTranscript` en `control_center/text_chat.py`): texto del usuario, respuesta final y resultado (terminado, cancelado o error).
- **De dónde sale:** de lo que el servidor ya ve, es decir `/api/chat`, la presencia, las cancelaciones y las detenciones del runtime.
- **Privacidad:** **no se escribe en disco ni en el navegador** y desaparece al cerrar el centro de control, en coherencia con H-01.
- **Endpoints:**
  - `GET /api/chat/history`, con cookie de sesión;
  - `POST /api/chat/history/clear`, con CSRF. Conserva el turno que siga en curso.
- **En la interfaz:** al cargar el panel o la app WPF se restaura la conversación, incluido un turno todavía en curso. Hay un botón "Borrar".
- **Límite:** borrar el historial visible **no** reinicia el contexto del modelo. El runtime conserva su memoria de sesión hasta reiniciar el núcleo.
- **Verificado en Chromium:** tras recargar se recuperan 12 de 12 mensajes, con su Markdown y su resultado. Tras borrar y recargar quedan 0.

### H-01: qué cambió exactamente (`81745d7`)

- **Con `logging.store_conversation_content = false`** (valor por defecto):
  - el orquestador **no escribe** el texto del usuario ni el de Mark en SQLite;
  - el historial vive en memoria del proceso (32 sesiones × 60 mensajes), así que el modelo conserva el contexto mientras el núcleo está abierto y lo pierde al cerrarlo;
  - en la auditoría de herramientas, la intención se guarda como `[contenido no almacenado: N caracteres]`. Se conservan la herramienta, los argumentos, el riesgo, la política y el resultado, y la cadena hash sigue siendo válida.
- **Con `true`:** el comportamiento anterior (mensajes e intención en claro).
- **Conversaciones guardadas antes:** **no se borran**.
- **Pruebas** (`tests/test_privacy.py`): recorren **todas** las tablas de SQLite con los dos valores. La antigua `test_normal_response_is_persisted` dependía del defecto y ahora activa el almacenamiento de forma explícita.
- **Contenido que todavía puede guardarse, no conversacional pero sí sensible:**
  - los **argumentos** de las herramientas en la auditoría, por ejemplo el texto de `create_note` o las rutas;
  - `expected_result`, que redacta el modelo;
  - la intención de `--rag-query` en la CLI.
  - Revisarlos antes de prometer "ningún contenido privado".

## 0. Entrega publicada por Codex

GitHub se tomó como fuente canónica. La rama remota
`claude/ref2-chat-ui` terminaba en `e979b9c`; las modificaciones no confirmadas de
la última sesión de Claude Code no estaban disponibles en el repositorio ni en los
árboles inspeccionados. Por tanto, **Codex reconstruyó** el monitor y la integración
descritos en la delegación; no afirma haber recuperado archivos inexistentes.

Implementación técnica: `90f484c` (`feat(control-center): add live core monitor`).
La rama publicada continúa siendo `claude/ref2-chat-ui`, apilada sobre
`claude/ref1-latency`; el PR #2 conserva esa relación. `master` permanece en
`bd4a876` y no fue fusionado ni modificado.

### Resultado de esta entrega

- `system_status.py`: monitor local de CPU/RAM y GPU/VRAM NVIDIA, caché de dos
  segundos, timeout de 800 ms, fallos explícitos y sin cargar modelos.
- `GET /api/system`: autenticación por cookie, `Cache-Control: no-store` y
  respuesta sin PID, comandos, credenciales ni rutas privadas.
- Panel **Núcleo** dentro del chat: modelo configurado, runtimes de texto/voz,
  métricas y controles reales sobre el `ProcessManager` existente.
- Estados con precedencia segura y rechazo de revisiones antiguas de presencia.
- Bind exclusivo en Windows para evitar que dos copias compartan un puerto.
- Corrección de la prueba de catálogo mediante un ejecutable sintético; conserva
  las once entradas y ya no depende del software instalado en el host de CI.

Validación de la entrega: **159 pruebas y 9 subtests aprobados**, comprobación de
JavaScript con Node aprobada y `git diff --check` aprobado tras la documentación.
En Windows se verificó la lectura real de una RTX 5060 Laptop y en Chromium se
probaron apertura/cierre del panel, Escape, transiciones texto→voz→detenido y
ausencia de procesos duplicados. **No se declara validación en WPF/WebView2**: esa
prueba permanece pendiente en el equipo del propietario después de recuperar la
rama.

El hallazgo de privacidad **H-01** permanece abierto: no se debe añadir historial
persistente hasta que `store_conversation_content = false` impida realmente guardar
contenido en SQLite. No se modificó la instalación principal ni su configuración.

### Recuperación segura con GitHub Desktop

`Fetch origin` solo descarga referencias y commits; no cambia los archivos del
directorio de trabajo. Para no afectar la instalación principal, la opción segura
es clonar `Srkorben/JarvisLocal-Mark` en una carpeta de desarrollo distinta,
seleccionar `claude/ref2-chat-ui`, ejecutar **Fetch origin** y después **Pull
origin**. No hacer Checkout/Pull sobre
`C:\Users\andcb\Documents\AI Local\JarvisLocal` hasta decidir expresamente instalar
la rama y respaldar `config/jarvis.toml` y `data/`.

Próximas prioridades de Ref 2.0: validar el panel en WPF/WebView2, resolver H-01,
probar las herramientas reales permitidas desde el chat y, solo después, diseñar
historial recuperable de sesión. El trabajo temporal de Codex puede eliminarse una
vez verificados los commits remotos porque no contiene artefactos necesarios que
no estén en GitHub.

## 1. Estado real

- `master` (`bd4a876`) **no ha cambiado**. Nada de esto está fusionado ni instalado en el PC del propietario.
- Todo el trabajo vive en dos ramas, apiladas una sobre otra:

| Rama | Contenido | Depende de |
|---|---|---|
| `claude/ref1-latency` | Ref 1.0: latencia, reparto de GPU, runtime de texto y benchmark | `master` (`bd4a876`) |
| `claude/ref2-chat-ui` | Ref 2.0: chat escrito en el centro de control | `claude/ref1-latency` (necesita `--panel-chat`) |

Commits finales:

| Rama | Commit | Descripción |
|---|---|---|
| `claude/ref1-latency` | `59683fb` | Prueba de catálogo determinista (sesión 3) |
| `claude/ref2-chat-ui` | último de la sesión 3 | Monitor Núcleo (Codex), chat accesible y H-01 corregido |
| `master` | `bd4a876` | Sin cambios |

La instalación del propietario (`C:\Users\andcb\Documents\AI Local\JarvisLocal`) está en `master` y sin cambios locales; se comprobó con `git status`. **No hay interfaz local sin publicar.**

- **PR [Srkorben/JarvisLocal-Mark#1](https://github.com/Srkorben/JarvisLocal-Mark/pull/1)**: borrador, `claude/ref1-latency` → `master`. **No fusionar sin aprobación del propietario.**
- **PR [Srkorben/JarvisLocal-Mark#2](https://github.com/Srkorben/JarvisLocal-Mark/pull/2)**: borrador, `claude/ref2-chat-ui` → `claude/ref1-latency`. No fusionar todavía.
- La rama experimental de voz `claude/jarvislocal-mark-ahioni`, con los ajustes de acento, sigue aislada y **no se incorpora**. La condición `accent_source=model` es defectuosa.

## 2. Ref 1.0: qué se completó

**Código**, en la rama `claude/ref1-latency`:
- **Voz progresiva** (`audio/speech_stream.py`): síntesis frase a frase, solapada con la reproducción.
- **Trazas de latencia sin contenido** (`latency.py`), en `data/logs/latency.jsonl`.
- **Esquemas de herramientas filtrados** por permisos (`orchestrator.py`).
- **Presencia no bloqueante** (`control_center/presence.py`).
- **Benchmark local** (`latency_benchmark.py`). El procedimiento está en `docs/latency.md`.
- **GPU reservada para el LLM.**
  - `tts.provider = "piper"`.
  - Chatterbox solo usa CUDA con `voice_clone.allow_gpu = true`; sin esa opción se usa Piper en CPU.
- **Runtime de texto `cli --panel-chat`**: solo carga el LLM, y el TTS solo si se pide voz. `/api/chat` lo arranca salvo que la voz ya esté activa.

**Mediciones en la RTX 5060** (detalle en `docs/latency.md`):

| Medida | GPU libre | Con Chatterbox CUDA | Con Piper CPU |
|---|---|---|---|
| Velocidad del LLM | ~55 tokens/s | 5,6–7 tokens/s | 46–54 tokens/s |
| Primer audio | — | 19,1 s | 7,2 s |
| Turnos largos | — | se cortan a 120 s | se completan |

- Con Piper en CPU, el STT pasa a ser el mayor coste del turno de voz: 5,7 s.
- **La voz Piper `es_MX-ald` fue rechazada por calidad.**

**No validado todavía en producción.** Pendiente:
1. Prueba B: Chatterbox en CPU con la referencia autorizada. Mide la viabilidad de la voz clonada sin quitarle la GPU al LLM.
2. Comparación de neutralidad del acento. Probablemente requiera descargar otro modelo: hay que explicarlo y pedir autorización antes.
3. Ajuste del STT (`beam_size`, modelo).
4. Separar el límite de generación del de reproducción (hoy son 120 s en total).
5. Decisión definitiva del TTS. **No adoptarla sin esas mediciones.**

El propietario quiere que la importación de la voz de unos 20 s se haga **desde la UI/UX**. El backend ya existe: `/api/voice/reference/import` y el botón "Subir audio" del cajón *Sistemas*.

## 3. Ref 2.0: qué se completó

**Chat escrito integrado** en el centro de control (`control_center/web.py`). El shell WPF/WebView2 solo carga esta página, así que el chat aparece también allí.

| Funcionalidad | Implementada | Probada automáticamente | Pendiente |
|---|---|---|---|
| Área de conversación (burbujas Tú/Mark) | ✅ | ✅ navegador¹ | Validación visual en WPF |
| Campo de texto: Enter envía, Mayús+Enter salto | ✅ | ✅ navegador¹ | — |
| Envío al modelo local (`/api/chat`, cookie + CSRF) | ✅ | ✅ unitario + navegador¹ | Prueba con Qwen real en Windows |
| Respuesta progresiva (presencia cada 250 ms) | ✅ | ✅ navegador¹ | Fluidez real con Qwen |
| Indicador de fase (cola, iniciando, pensando, hablando, cancelando) | ✅ | ✅ navegador¹ | — |
| Errores, núcleo detenido, bloqueo de 150 s, desconexión | ✅ | ✅ error del núcleo¹; desconexión solo por código | Desconexión real |
| Cancelación (`POST /api/chat/cancel` → `/api/chat/next` → `cancel_active`) | ✅ | ✅ unitario + navegador¹ | Con Qwen real |
| "Responder también con voz" | ✅ | Solo la lógica del runtime | Audio real en Windows |
| Diseño coherente y vista móvil | ✅ | Capturas¹ | Revisión del propietario |

¹ Prueba en Chromium (Playwright) contra el servidor real del panel, con su autenticación, y un runtime simulado. **No es la app WPF ni el LLM real.**

**Seguridad:**
- Sin cambios en la autenticación: la página usa cookie, las acciones CSRF y el runtime un token de portador.
- Los mensajes se pintan con `textContent`.
- La conversación no se guarda en el navegador.
- La política de herramientas no cambia: el runtime de texto deniega las confirmaciones interactivas.

### Validación real en Windows 11 (sesión 2, con Qwen3-8B)

Montaje experimental, **sin tocar la instalación**:
- carpeta `JarvisLocal-ref1` en la rama `claude/ref2-chat-ui`;
- enlaces `mklink /J` a `.venv`, `models` y `runtime` de la instalación;
- `set PYTHONPATH=...\JarvisLocal-ref1\src`;
- `.venv\Scripts\python.exe -m jarvis_local.control_center --launch`.

La raíz efectiva es `JarvisLocal-ref1`, con base de datos y registros propios en `JarvisLocal-ref1\data`.

| Prueba | Resultado |
|---|---|
| El panel abre con el chat (navegador, puerto 8765) | ✅ |
| Mensaje corto con Qwen real | ✅ Respondió en 2–3 s, incluido el arranque del núcleo de texto |
| Respuesta larga en streaming y Cancelar | ✅ Se detuvo a mitad de frase: "Cancelado · 2.0 s" |
| Markdown | ❌ Se veía en bruto (`**Planificación**`). Corregido en `741ad7f`, **pendiente de revalidar en Windows** |
| Herramientas `get_current_time` y `list_directory` | ⏳ **No probadas en real** |
| App WPF/WebView2 | ⏳ **No probada** |

### Mejoras de la sesión 2 (`741ad7f`)

- **Markdown seguro:** negritas, cursivas, código en línea, listas, títulos, párrafos y bloques de código.
  - Solo usa `createElement`/`textContent`, nunca `innerHTML`.
  - El HTML que llegue en una respuesta se muestra como texto.
  - No interpreta `_x_` ni `__x__`, para no romper nombres como `get_current_time`.
- **Chat ampliable:** botón "Ampliar/Reducir" de hasta 980 px que atenúa el núcleo y recuerda la preferencia. Al cerrar el chat vuelve el diseño original. La columna izquierda de módulos se oculta solo con el chat abierto.
- **Estabilidad:**
  - El turno ignora revisiones de presencia anteriores a su envío, así que un mensaje repetido no se cierra con la respuesta anterior.
  - Las actualizaciones vacías no borran el texto ya generado.
- **Texto de estado:** sin núcleo, el estado ya no exige iniciar la voz.
- **Verificado en Chromium** (Playwright, servidor real del panel y runtime simulado):
  - streaming, cancelación y error;
  - Markdown y texto malicioso: 0 `<img>`, 0 `<script>`, `window.__xss` sin definir;
  - mensaje repetido y modo ampliado.

### Hallazgo de privacidad H-01 (corregido en `81745d7`; ver sección 0a; abajo, la descripción original)

Procede de la auditoría del 9 de octubre (`docs/` en la rama `claude/jarvislocal-mark-ahioni`, commit `5f921b9`).
- **El problema:** `logging.store_conversation_content = false` **no tiene efecto**. Las conversaciones (`database.py`, mensajes) y las intenciones se guardan **en claro** en SQLite.
- **Consecuencias:**
  - Hay que corregirlo antes de considerar fiable cualquier historial persistente.
  - El historial recuperable del chat **no debe construirse** hasta respetar ese indicador. Opción de diseño: historial solo en memoria del runtime, o persistencia únicamente si el usuario la activa.

## 4. Archivos modificados

- **Monitor Núcleo (Codex, `90f484c`)**:
  - `src/jarvis_local/control_center/system_status.py`;
  - `src/jarvis_local/control_center/{launcher,server,web}.py`;
  - `tests/test_system_status.py` y `tests/test_control_center.py`;
  - `README.md`, `PROJECT_STATUS.md`, `docs/control-center.md` y ADR 0018.

- **Ref 1.0**:
  - `src/jarvis_local/`: `latency.py`, `latency_benchmark.py`, `orchestrator.py`, `projects.py`, `tools/registry.py`, `cli.py` y `config.py`.
  - `src/jarvis_local/audio/`: `speech_stream.py`, `session.py`, `lazy.py`, `providers.py` y `__init__.py`.
  - `src/jarvis_local/control_center/`: `presence.py`, `catalog.py`, `launcher.py`, `modules.py` y `server.py`.
  - `config/jarvis.toml`, `docs/latency.md` y `.github/workflows/tests.yml`.
  - Pruebas: `test_latency*.py`, `test_speech_stream.py`, `test_presence_publish.py` y `test_text_runtime.py`.
- **Ref 2.0**:
  - `src/jarvis_local/control_center/`: `web.py`, `server.py`, `text_chat.py` y `presence.py`.
  - `src/jarvis_local/audio/session.py`.
  - `tests/test_control_center.py` y `tests/test_text_runtime.py`.
  - `docs/HANDOFF.md`.

## 5. Pruebas y errores conocidos

- **Linux (nube), sesión 3:** 163 pasan y 0 fallan.
- **Prueba del catálogo:** corregida con una fijación determinista en ambas ramas, sin SKIP ni borrado.
- **CI** (`.github/workflows/tests.yml`): Windows y Linux. Revisar el resultado de los últimos commits en GitHub.
- **Interfaz local del propietario:** la instalación está en `master`, sin cambios locales (comprobado en la sesión 2).
- **Configuración local:** el `config\jarvis.toml` del propietario sigue pidiendo Chatterbox CUDA. Con este código, sin `allow_gpu`, se usará Piper.

## 6. Riesgos de integración

1. **Instalación local.** Integrar las ramas exige actualizar la instalación de Windows. Hacerlo **solo con autorización**, con copia de seguridad de `config\jarvis.toml` y `data\`.
2. **Voz por defecto.** Piper queda como voz si no se decide otra cosa, y su calidad fue rechazada. Antes de integrar, decidir el TTS (prueba B) o avisar al propietario.
3. **Runtimes exclusivos.** El runtime de texto y la voz no pueden coexistir: al iniciar la voz, el panel detiene `chat_runtime`, y un turno de texto en curso se pierde.
4. **Presencia compartida.** Un turno de voz (PTT) durante un chat escrito también se ve en el panel. El chat ignora transcripciones ajenas, pero no las muestra.

## 7. Cómo continuar desde otra sesión

```bash
git fetch origin claude/ref2-chat-ui claude/ref1-latency
git checkout claude/ref2-chat-ui
pip install -e ".[dev]" numpy
python -m pytest -q
```

- **Para ver el chat sin Windows:** levantar `ControlCenterHTTPServer` con un `ProcessManager` falso y un runtime simulado que consuma `/api/chat/next` con el token de portador y publique la presencia completa, como hace `VoicePresenceClient`. Abrir `/?token=…` en un navegador.
- **Atención:** la presencia **reemplaza** todo el estado en cada `POST`; hay que enviar siempre `state`, `transcript`, `response` y `error`.
- **Instrucciones de terminal para el propietario:** bloques `cmd`, un comando por paso, esperando su resultado.

## 7 bis. Defectos y pendientes conocidos del chat

1. Revalidar en Windows el Markdown con Qwen real.
2. Probar en real las herramientas `get_current_time` y `list_directory`, y una que requiera confirmación, como `open_file`. El runtime de texto deniega las confirmaciones: comprobar que el mensaje se entiende.
3. Probar la app WPF con `set JARVISLOCAL_ROOT=%USERPROFILE%\Documents\AI Local\JarvisLocal-ref1` y `runtime\desktop\JarvisLocal.exe` en la misma consola con `PYTHONPATH`.
4. "Responder también con voz" usa Piper, cuya voz fue rechazada.
5. Historial: **implementado en memoria** (`062b3b6`). Pendientes: persistirlo solo si `store_conversation_content = true`, y una opción "Nueva conversación" que reinicie también el contexto del modelo.
6. Una respuesta muy larga se re-renderiza completa en cada actualización (cada 250 ms). Es aceptable hasta unos 16 KB, el límite de presencia.

## 7 ter. Recuperar el entorno de prueba en Windows (sin tocar la instalación)

En `C:\Users\andcb\Documents\AI Local` ya existen:
- `JarvisLocal`: instalación principal, en `master`;
- `JarvisLocal-ref1`: carpeta experimental en `claude/ref2-chat-ui`, con enlaces `mklink /J` a `.venv`, `models` y `runtime` de la instalación. Para quitar un enlace se usa `rmdir`, nunca `del /s`.

Pasos, un comando `cmd` por paso:
1. `git -C "%USERPROFILE%\Documents\AI Local\JarvisLocal-ref1" pull --ff-only`
2. `cd /d "%USERPROFILE%\Documents\AI Local\JarvisLocal-ref1"`
3. `set "PYTHONPATH=%USERPROFILE%\Documents\AI Local\JarvisLocal-ref1\src"`
4. `.venv\Scripts\python.exe -m jarvis_local.control_center --launch` para el navegador. Para la app WPF: `set "JARVISLOCAL_ROOT=%CD%"` y después `runtime\desktop\JarvisLocal.exe`.

La carpeta experimental usa su propio `data\`, así que el chat empieza con la base de datos vacía.

## 7 quater. Decisiones que requieren autorización del propietario

1. **Voz definitiva:** Piper fue rechazada. La prueba B (Chatterbox en CPU con referencia autorizada) está pendiente, igual que la comparación de acento neutro, que requiere descargar un modelo.
2. **Integración en la instalación principal:** fusionar los PR #1 y #2, con copia de seguridad de `config\jarvis.toml` y `data\`.
3. **Historial persistente:** activar o no `store_conversation_content = true`.
4. **Argumentos de herramientas en la auditoría:** decidir si se redactan también cuando el almacenamiento está desactivado.

## 8. Primera tarea concreta de la siguiente sesión

**Validar y pulir el chat y el panel Núcleo en Windows 11 y WPF, sin benchmarks** (sección 7 ter).
1. Guiar al propietario para abrir el panel con la rama `claude/ref2-chat-ui` (carpeta `JarvisLocal-ref1` + `PYTHONPATH`), sin tocar su instalación.
2. Enviar 3 mensajes reales a Qwen: corto, largo y con herramienta. Probar Cancelar y comprobar la app WPF.
3. Corregir lo que aparezca.
4. Después, siguiente entrega de Ref 2.0:
   - "Nueva conversación": reiniciar también el contexto del modelo, que hoy exige reiniciar el núcleo;
   - historial de la sesión recuperable desde el núcleo, no desde el navegador;
   - flujo de importación de la voz de 20 s integrado en la UI.
