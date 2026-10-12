# Estado del proyecto

Última actualización: 2026-10-12

## Resumen

Identidad pública actual: **Mark Scout**; nombre habitual: **Mark**. La base
técnica conserva `JarvisLocal` como nombre de repositorio, paquete, datos y
ejecutable hasta una migración separada.

| Fase | Estado | Evidencia |
|---|---|---|
| 0 — Esqueleto seguro | **Completada** | política, auditoría, cancelación y herramientas tipadas |
| 1 — Conversación local por texto | **Completada** | 38 pruebas, diagnóstico, smoke tests y benchmark real |
| 2 — Voz local | **Implementada; aceptación acústica pendiente** | 173 pruebas + 9 subtests; llamada continua semidúplex y PTT desde UI |
| 3 — Memoria de proyectos/RAG | **Completada** | 53 pruebas totales, índice real, 4/4 benchmark RAG |
| 4 — Herramientas deterministas | **Completada** | 10 tools nuevas, smoke real y E2E con LLM |
| 5 — Acceso permanente | **Parcial** | aplicación WPF/WebView2 y acceso `.exe`; faltan bandeja, wake word e inicio de sesión |
| 6 — Automatización estructurada | Pendiente | no iniciado |
| 7 — Visión y tareas multietapa | Pendiente/experimental | no iniciado |
| 8 — Endurecimiento | Continuo | controles base presentes; falta endurecimiento integral |

Incremento posterior a Fase 4: **evaluación de CORE y decisiones temporales,
completado**. No constituye una fase nueva.

Incremento de acceso: **centro de control local completado**. Consolida los nueve
accesos históricos de JarvisLocal en un único `Mark Scout.lnk`. Los accesos de
otros proyectos no forman parte de esta consolidación y no son gestionados por
JarvisLocal.

Incremento de interfaz: **Desktop Alpha de Mark Scout implementada**. `JarvisLocal.exe` aloja el
panel en WPF/WebView2 sin consola, reutiliza el mismo core Python y representa de
forma visual todos los estados de voz. Se validó carga real hasta `EN ESPERA`,
detención completa del árbol de voz y escena `RESPONDIENDO` con ondas expansivas.
Los seis indicadores son módulos seleccionables respaldados por configuración
real de solo lectura. Interfaz ofrece un gobernador Auto/Equilibrado/Eco que baja
a 20 FPS durante inferencia y pausa al ocultarse. No es todavía un motor 3D ni
incorpora avatar en la ventana principal. Godot 4.7.2 sí está instalado e
integrado como cliente experimental de presencia 3D; Unity/Unreal se mantienen
separados hasta completar sus pruebas.

## Centro de control local

- servidor de biblioteca estándar ligado exclusivamente a `127.0.0.1`;
- puerto preferido 8765 con fallback cerrado 8766–8774;
- inicio bajo demanda, health check y bloqueo de segunda instancia;
- catálogo cerrado de diez herramientas, sin comandos/argumentos desde HTTP;
- cookie HttpOnly/SameSite, token aleatorio, CSRF, Host/Origin y CSP;
- procesos con `shell=False`, grupos de exclusión, cooldown y detención del árbol;
- confirmación local para enrolamiento e instalación/mantenimiento;
- estados disponible/en ejecución/no disponible/error;
- icono oscuro personalizado y respaldo recuperable de `.lnk` sustituidos;
- ejecutable WPF de instancia única, WebView2 restringido a loopback y cierre
  coordinado de procesos;
- ADR 0012/0013 y operación en `docs/control-center.md` y `docs/desktop.md`.
- Godot 4.7.2 instalado y smoke autenticado contra presencia loopback;
- Unity Hub 3.22.2 y Unity 6.3 LTS 6000.3.26f1 instalados; el adaptador
  permanece bloqueado por falta de licencia activa (código 198);
- Epic Games Launcher actualizado; Unreal 5.8 requiere autenticación del usuario.

Incremento Ref 2.0: **monitor y panel Núcleo implementados en la rama de UI**.
El endpoint autenticado `/api/system` compone los estados de texto y voz con la
presencia efímera y mide CPU, RAM, GPU y VRAM sin cargar modelos adicionales.
Las lecturas de hardware tienen caché y fallos explícitos; el panel conserva los
controles del catálogo cerrado y la exclusión entre runtimes. Se validó en
Chromium sobre Windows, incluyendo transiciones, Escape y no duplicación. La
validación final dentro de WPF/WebView2 permanece pendiente y esta rama todavía
no está instalada en la carpeta principal.

## Fase 2 implementada

- contratos `STTProvider`, `TTSProvider`, recorder y player sustituibles;
- máquina de estados semidúplex con exclusión de turnos concurrentes;
- WASAPI compartido, selección de dispositivo y resampling explícito;
- llamada semidúplex automática: escucha, detecta el turno, responde y vuelve a escuchar;
- modo alternativo mantener-pulsado-y-hablar, sin atajos globales;
- canal efímero tipado y autenticado UI→runtime para llamada, silencio, PTT y cancelación;
- cancelación, silencio y fin de llamada mediante controles visibles de la UI;
- faster-whisper small multilingüe, CPU INT8, Silero VAD y hotwords;
- transcripción visible, detección de silencio/ambigüedad y Unicode seguro;
- mismo `Orchestrator`, sesión, `project_id`, memoria, política y tools que texto;
- Piper validado como fallback; su voz fue rechazada por el usuario;
- Chatterbox LatAm instalado en proceso/venv separado, CUDA y offline;
- reserva de VRAM en orden voz→LLM y priming CUDA antes de declarar estado listo;
- enrolamiento de voz propia con consentimiento local y SHA-256;
- importación desde UI de audio autorizado de 15–30 s, ocho formatos, respaldo y auditoría;
- transporte JSONL ampliado y acotado para el PCM16 base64 de Chatterbox;
- cancelación durante captura, STT, LLM, playback y worker de clonación;
- auditoría de metadatos/latencia sin almacenar audio ni transcripción.

La aceptación no se cierra todavía: la muestra ya fue grabada y la síntesis es
funcional, pero el usuario debe evaluar semejanza y naturalidad. La lógica de
llamada y sus estados está probada automáticamente; la prueba acústica humana de
varios turnos consecutivos sigue pendiente. No hay wake word, full-duplex,
cancelación de eco, bandeja, UIA, Playwright ni visión.

## Fase 1 implementada

- contrato abstracto `ModelProvider` sin dependencias de un modelo o servidor;
- adaptadores `LlamaCppProvider` y `OllamaProvider` seleccionables por TOML;
- `LlamaServerManager` con comando cerrado, loopback, health polling, timeout de
  arranque y cierre exclusivo del proceso creado por JarvisLocal;
- API OpenAI-compatible de `llama-server` con streaming SSE;
- cancelación real que cierra el stream HTTP, timeouts y errores estructurados;
- ensamblado de tool calls fragmentadas y validación estricta de argumentos JSON;
- historial canónico desacoplado del formato específico de Ollama;
- máximo de iteraciones de herramientas y preservación de auditoría en errores;
- contexto, temperatura, output, thinking, GPU/offload, batch y flash attention
  configurables sin tocar el núcleo;
- offload `auto` con `--fit-target 1024` para adaptarse a los 8 GB de VRAM;
- `llama.cpp` b11459/f498f864f CUDA 12.4 y Qwen3-8B Q4_K_M oficial;
- benchmark JSON/Markdown reproducible y smoke tests de conversación/tool call.

## Seguridad preservada

El proveedor solo genera texto o solicitudes tipadas. No puede editar
`Settings`, allowlists, política ni auditoría. `ActionExecutor` y `PolicyEngine`
siguen siendo la única ruta a capacidades. `llama-server` escucha únicamente en
`127.0.0.1`, no publica UI y no habilita sus tools, MCP o agent mode incorporados.

Herramientas previas de lectura/memoria:

1. `get_current_time`
2. `list_directory`
3. `search_files`
4. `read_text_file`
5. `get_project_context`
6. `search_project_memory`
7. `get_recent_project_activity`
8. `get_user_profile`
9. `get_project_decision`

Fase 4 añade `find_files`, `open_file`, `open_folder`, `open_project`,
`start_application`, `git_status`, `git_log`, `create_note`, `copy_file` y
`move_file`. No existe shell libre, red, borrado, overwrite, GUI visual ni
privilegios. El modelo no puede cambiar permisos.

## Fase 4 implementada

- permisos independientes `open`, `execute` y `write`, falsos por defecto;
- edición de permisos solo mediante CLI local auditada;
- rutas limitadas al proyecto, sin UNC, symlinks ni junctions;
- búsqueda de archivos con exclusión predeterminada de entornos generados;
- apertura de documentos/carpetas mediante asociación Windows, declarando que la
  ventana no puede verificarse todavía;
- aplicaciones únicamente por ruta `.exe` absoluta en allowlist y sin argumentos;
- `git status` y `git log` mediante procesos cancelables y argumentos fijos;
- notas y copias con creación exclusiva, límite de 100 MiB y SHA-256;
- movimientos sin overwrite, mismo volumen, nivel 2, confirmación local y rollback;
- limpieza cooperativa de threads síncronos antes de devolver timeout;
- smoke test reproducible sobre un proyecto temporal y tool call real en español.

## Fase 3 implementada

- registro de proyectos con estado, configuración, raíz y permisos persistentes;
- memoria de trabajo por sesión/proyecto, episodios semánticos, documentos y
  perfil explícito como almacenes distintos;
- decisiones y pendientes rechazados si no están explícitamente confirmados;
- extracción de TXT, Markdown por secciones y PDF con texto por página;
- indexación incremental por SHA-256, actualización y eliminación de obsoletos;
- SQLite FTS5/BM25 y vectores `float32` con coseno exacto y fusión de rankings;
- filtros SQL obligatorios por `project_id`, fechas y modelo de embeddings;
- `EmbeddingProvider` local separado del `ModelProvider` conversacional;
- Qwen3-Embedding-0.6B Q8_0 en un segundo `llama-server` de loopback;
- evidencia con ruta, sección/página, hash, fecha, puntuación y cita verificable;
- texto recuperado marcado como no confiable e indicios de prompt injection;
- límite explícito de 20.000 vectores antes de exigir un índice ANN;
- CLI para proyectos, índice, consulta, decisiones, pendientes, resumen y perfil;
- auditoría de indexación, consultas directas y herramientas de memoria.

## Incremento de memoria temporal

- evaluación documentada de patrones de CORE sin instalarlo ni copiar código;
- esquema SQLite v4 con una decisión vigente por proyecto y tema;
- historial de contradicciones mediante `supersedes_id`, `valid_from` y `valid_to`;
- motivo y procedencia tipada (`explicit_user`, `document` o `tool_result`);
- ninguna fuente documental puede confirmar o persistir una decisión;
- consulta tipada `get_project_decision`, sólo lectura y aislada al proyecto activo;
- corrección por nueva versión confirmada, sin sobrescribir historia;
- olvido explícito de toda la cadena, sin reactivar versiones anteriores;
- tareas persistentes, reglas, MCP, eventos y grafo general permanecen diferidos;
- ADR 0009 y evaluación completa en `docs/core-evaluation.md`.

## Validación ejecutada

```text
python -m pytest -q                         108/108 OK (+3 subtests)
python -m compileall -q src tests           OK
dotnet build JarvisLocal.Desktop Release    OK, 0 warnings / 0 errors
Publish-Desktop.ps1                         OK, win-x64 framework-dependent
python -m jarvis_local.cli --doctor         OK
python -m jarvis_local.cli --verify-audit   OK
python -m jarvis_local.cli --audio-doctor   OK; Chatterbox CUDA/offline 23,88 s
chat real en español con llama-server       OK
tool call real get_current_time             OK
benchmark Qwen3-8B                          OK
índice real 18 documentos / 95 fragmentos    OK, 32 generados eliminados
consulta RAG real con fuentes                OK
benchmark Qwen3-Embedding                    4/4 OK
python -m jarvis_local.phase4_smoke          6/6 operaciones OK
LLM → find_files → política → auditoría      OK
decisión A → corrección B → consulta         OK, vigente/anterior e historial 2
olvido explícito → auditoría                 OK, 2 registros eliminados
hardware WASAPI micrófono/altavoz            OK; entrada fue silencio
Chatterbox CUDA → WASAPI físico              OK; TTS 3,562 s / audio 3,28 s
Piper→Whisper→LLM→tool→TTS                   OK, sin reproducción en benchmark final
worker Chatterbox LatAm CUDA/offline         OK, carga+priming 21,74–23,88 s
voz clonada + Qwen residentes                OK; TTFT 0,515 s; TTS 5,681 s / audio 4,4 s
control_center unit/API security             7/7 OK
control_center smoke HTTP/Windows            9 tools; open/start/stop OK
segunda apertura del centro                  mismo PID/puerto, sin duplicado
Godot smoke autenticado + ciclo catálogo     OK; start/idempotencia/stop
Godot ventana 3D real                        OK; ~168,23 MiB RAM, ~60 MiB VRAM orientativos
importación de voz sintética aislada         OK; normalización, rechazo, respaldo y auditoría
acceso Mark Scout.lnk → aplicación WPF        OK; ventana Mark Scout, sin consola
segunda apertura del `.exe`                 misma instancia/PID
voz desde UI: loading → idle                  OK; arranque integral y cierre limpio
escena speaking + ondas + texto             OK, validación visual
stop desde UI                               OK; sin worker de voz huérfano
```

La suite cubre: cambio de proveedor, proveedor indisponible, respuesta normal,
streaming, tool call fragmentado válido, JSON inválido, nombre inválido,
argumentos inválidos, timeout, cancelación, máximo de iteraciones, loopback,
comando cerrado del servidor, imposibilidad de elevar permisos desde el modelo y
cadena de auditoría válida. La ampliación cubre además aislamiento de memoria,
persistencia de permisos, TXT/Markdown/PDF, actualización y borrado de índice,
recuperación léxica/semántica, denegación por permiso, cancelación de indexación,
instrucciones maliciosas como datos y trazabilidad de citas.

Fase 4 añade casos de rutas UNC, cruce de proyecto, symlink, permiso insuficiente,
origen inexistente, destino ocupado, argumentos extra, cancelación durante copia,
cancelación+rollback durante movimiento, timeout síncrono con limpieza, Git real,
apertura simulada sin afirmar visibilidad y confirmación obligatoria de nivel 2.

El incremento temporal añade contradicción, vigencia, procedencia documental,
confirmación obligatoria, permiso `memory`, aislamiento entre proyectos, consulta
tipada auditada y eliminación explícita. La suite completa y el diagnóstico real
siguen correctos; la cadena append-only de auditoría permanece válida.

Fase 2 añade silencio/ruido sintético, dispositivos ausentes, estados, turnos
repetidos, cancelación en cuatro etapas, Unicode STT inválido, consulta temporal
aislada, RAG con fuente, tool call real, intento de elevar permisos por voz,
consentimiento ligado a muestra, worker aislado y terminación de inferencia.

## Benchmark de voz

| Métrica | Resultado observado |
|---|---:|
| Casos STT no ambiguos | 5/5 |
| WER medio Piper→Whisper | 0,437 |
| Mediana STT | 5,016 s |
| Turno E2E con herramienta | aprobado |
| TTFT desde cierre | 7,704 s |
| Primer audio generado | 10,829 s |
| Total sin playback | 11,735 s |
| RAM Python final | 705,32 MiB |

El conjunto sintético no representa la voz real y evidencia errores en README y
Git/Jarvis. Con la muestra consentida y CUDA, Chatterbox produjo 4,4 s de audio
en 5,681 s con Qwen3-8B residente; el arranque de voz+priming tardó 21,739 s. La
síntesis CPU anterior tardaba 42–54 s por frase. Falta evaluación humana de
semejanza. Informes: `benchmarks/results/audio-phase2.md` y
`benchmarks/results/chatterbox-cuda-rtx5060.md`.

## Benchmark validado

Artefacto: `Qwen3-8B-Q4_K_M.gguf`, 5.027.783.488 bytes, SHA-256
`d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.

| Métrica | Resultado observado |
|---|---:|
| Contexto | 8192 tokens |
| Carga hasta health-ready | 5,563 s |
| VRAM antes / cargado / delta | 1472 / 7153 / 5681 MiB |
| RAM del proceso, working set | 4895,73 MiB |
| TTFT mediano | 0,688 s |
| Generación mediana | 54,85 tokens/s |
| Casos de tool calling | 3/3 |
| Cancelación real | 0,094 s, servidor saludable |

El primer intento con 99 capas forzadas y VRAM ocupada produjo paginación WDDM y
solo 3–5 tokens/s. Se descartó como configuración inválida. El offload adaptativo
es la configuración estable; el rendimiento depende de carga, energía y térmicas.
Informe completo: [benchmarks/results/qwen3-8b-q4_k_m-ctx8192.md](benchmarks/results/qwen3-8b-q4_k_m-ctx8192.md).

## Entorno comprobado

- Python 3.12.10 x64;
- SQLite 3.49.1 con FTS5 disponible;
- Pydantic 2.13.5, HTTPX 0.28.1 y pytest 9.1.1;
- pypdf 6.19.0 para PDFs con capa de texto;
- llama.cpp 0.6.0-dev, build b11459, commit f498f864f, CUDA 12.4;
- NVIDIA RTX 5060 Laptop detectada, 8151 MiB;
- Ollama 0.40 conservado como proveedor opcional de desarrollo.
- .NET 8 y WebView2 Runtime 154.0.4258.62 para `JarvisLocal.exe`.
- PyTorch/torchaudio 2.9.1+cu128 aislados para Chatterbox; RTX 5060 `sm_120`
  comprobada y entorno CPU anterior conservado como fallback.

## Benchmark RAG validado

Artefacto: `Qwen3-Embedding-0.6B-Q8_0.gguf`, 639.150.592 bytes, SHA-256
`06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`.

| Métrica | Resultado observado |
|---|---:|
| Contexto / dimensiones | 2048 / 1024 |
| GPU layers | 0 |
| Indexación de 4 documentos | 6,125 s |
| Latencia mediana de consulta | 1,524 s |
| RAM del proceso, working set | 1207,29 MiB |
| VRAM global antes / cargado / delta | 2912 / 3471 / 559 MiB |
| Fuentes esperadas | 4/4 |
| Cadena de auditoría | válida |

La cifra de VRAM procede de `nvidia-smi` y es global, no atribuible de forma
exclusiva al servidor CPU. El conjunto es de integración/regresión, no una
evaluación universal. Informe: [benchmarks/results/rag-qwen3-embedding-0.6b-q8_0.md](benchmarks/results/rag-qwen3-embedding-0.6b-q8_0.md).

## Cierre del incremento

Fase 4 y el incremento temporal están cerrados. Fase 2 está implementada hasta la
puerta de aceptación: requiere que el usuario escuche y valore su propia voz. No se
ha iniciado wake word, Playwright, UI Automation, broker, OCR ni visión. No se
debe iniciar otra fase hasta cerrar la validación humana de voz.
