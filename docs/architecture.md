# Arquitectura

## Principios

JarvisLocal empieza como monolito modular. Solo el servidor de modelos y, más
adelante, el broker sensible de Windows viven en procesos separados. Seguridad,
integridad, control del usuario y determinismo prevalecen sobre autonomía.

```text
Micrófono → PTT/wake → VAD → STT ─┐
                                  ▼
                         Gestor de conversación
                           ├─ LLM local (proceso)
                           ├─ memoria/RAG
                           └─ planificador
                                  │ ActionRequest tipada
                                  ▼
                         ActionExecutor (frontera)
                                  │
                         PolicyEngine + presupuesto
                                  │ permitir/confirmar/denegar
                                  ▼
                       Broker de herramientas Windows
                  API/FS → DOM → UIA → OCR → VLM → mouse
                                  │
                         verificación + auditoría
                                  │
                       respuesta → TTS → altavoces
```

El orden de automatización es obligatorio: API de aplicación, sistema de
archivos/proceso, DOM, UI Automation, OCR, VLM y finalmente coordenadas.

## Componentes actuales

| Módulo | Responsabilidad | Autoridad |
|---|---|---|
| `cli` | entrada/confirmación local y comandos operativos | interfaz confiable actual |
| `orchestrator` | conversación, tool-calling y respuesta | propone; no ejecuta |
| `models` | contratos Pydantic y metadatos de herramientas | definición |
| `execution` | valida secuencia completa y ejecuta registro | puerta única Python |
| `policy` | recalcula riesgo y valida allowlists/rutas | permite, confirma o deniega |
| `tools` | registro, validación, timeout y handlers | capacidad limitada |
| `projects` | identidad y raíces de proyecto | aislamiento contextual |
| `budgets` | límites acumulados por turno | detención preventiva |
| `cancellation` | token cooperativo thread-safe | interrupción |
| `database` | proyectos, conversación y auditoría | persistencia local |
| `model_providers` | contrato, adaptadores HTTP y ciclo de `llama-server` | inferencia sin autoridad |
| `memory` | trabajo, episodios, decisiones temporales y perfil explícito | persistencia; no infiere autoridad |
| `rag` | extracción, embeddings, FTS5, vectores y citas | recuperación filtrada por proyecto |
| `benchmark` | medición reproducible de modelo, tools y cancelación | observación |

En fases posteriores se crearán paquetes `audio`, `planner`, `browser` y un
proyecto `broker/JarvisLocal.Broker` solo cuando contengan una
implementación real; no se mantienen directorios vacíos ni abstracciones ficticias.

## Flujo de una acción

1. El LLM elige una herramienta publicada mediante JSON Schema e incluye
   `expected_result`.
2. Pydantic rechaza campos extra y tipos inválidos.
3. `ProjectService` exige un `project_id` válido.
4. `PolicyEngine` normaliza rutas y recalcula riesgo desde `ToolSpec`.
5. Se aplican listas blancas, denylist, elevación y efectos externos.
6. Para riesgo 2+, una UI local devuelve un recibo vinculado al `request_id`.
7. El presupuesto consume un paso y la herramienta obtiene token de cancelación.
8. El registro ejecuta con timeout y devuelve un `ToolResult` estructurado.
9. Se registra solicitud, política, confirmación, resultado y verificación.
10. El resultado vuelve al modelo como datos no confiables.

## Herramientas deterministas de Windows

La Fase 4 conserva las operaciones no elevadas en el monolito, detrás de la misma
frontera. `ToolSpec.required_project_permissions` separa lectura, apertura,
ejecución y escritura. Cambiar estos permisos solo es posible desde la CLI local;
no se publica una herramienta para hacerlo.

```text
tool call del LLM
  → esquema Pydantic cerrado
  → proyecto + permisos read/open/execute/write
  → normalización de ruta + raíces + denylist + no UNC/reparse
  → riesgo recalculado + confirmación local si nivel 2
  → handler fijo (API de archivos / ShellExecute / proceso / Git)
  → comprobación posterior + rollback_reference
  → auditoría encadenada + episodio semántico
```

`create_note` y `copy_file` crean con exclusividad; `move_file` usa `MoveFileW`
sin reemplazo, mismo volumen y SHA-256. Los comandos Git son vectores de argumentos
fijos sin shell. El timeout de un handler síncrono cancela el token y espera su
limpieza cooperativa para evitar devolver mientras un thread sigue escribiendo.

`open_file` y `open_folder` solo afirman que Windows aceptó el despacho y la ruta
permanece válida. Confirmar una ventana requeriría UI Automation, fuera de esta
fase. `start_application` exige un `.exe` absoluto en allowlist, sin argumentos.
La escritura queda denegada por defecto hasta habilitación explícita por proyecto.

## Frontera de modelos

`Orchestrator` depende exclusivamente de `ModelProvider`. El contrato ofrece
health check, streaming, cierre/cancelación, respuesta tipada, métricas y tool
calls; no expone ejecución. La fábrica selecciona `llama_cpp` u `ollama` desde
TOML. La política no recibe ni consulta el proveedor, por lo que cambiar modelo,
prompt o backend no cambia permisos efectivos.

```text
Orchestrator → ModelProvider
                  ├─ LlamaCppProvider → HTTP/SSE → llama-server gestionado
                  └─ OllamaProvider   → HTTP/NDJSON → Ollama externo local

tool call → ActionRequest → ActionExecutor → PolicyEngine → ToolRegistry
```

`LlamaServerManager` construye un comando cerrado sin shell: alias, modelo,
loopback, contexto, un solo slot, batch y offload adaptativo. Desactiva Web UI y
no activa `--tools`, MCP ni agent mode. Solo termina el proceso que él mismo creó;
si detecta un servidor saludable preexistente, lo reutiliza y no lo mata.

El historial interno usa el formato canónico OpenAI de mensajes y tool calls. El
adaptador Ollama traduce en su frontera, evitando contaminar conversación o
herramientas con detalles de un backend concreto.

## Memoria y recuperación

`MemoryRepository` separa memoria efímera de sesión, episodios semánticos y
perfil explícito. La memoria documental pertenece a `rag`: una fuente se
identifica por proyecto+ruta+SHA-256 y cada fragmento conserva sección/página,
hash, modificación, modelo y señal de instrucciones sospechosas.

Las decisiones confirmadas tienen una cadena temporal separada por proyecto y
tema. Una sustitución cierra `valid_to`, enlaza `supersedes_id` y guarda motivo y
procedencia. El LLM sólo puede consultar esta cadena con `get_project_decision`;
no puede crearla, corregirla, borrarla ni usar una fuente para elevar autoridad.

```text
raíz autorizada del proyecto
  → extracción TXT/Markdown/PDF textual
  → fragmentos por sección/página + SHA-256
  → Qwen3-Embedding-0.6B en llama-server CPU/loopback
  ├→ document_chunks + vector float32 (SQLite)
  └→ FTS5 unicode61/BM25
        → filtro SQL project_id/fecha/modelo
        → léxico + coseno exacto
        → reciprocal rank fusion
        → evidencia con cita y confianza=no_confiable
```

El índice vectorial es exacto y tiene un límite de 20.000 fragmentos por proyecto.
Esto evita introducir Qdrant antes de demostrar necesidad y evita escaneos sin
límite. `EmbeddingProvider` es independiente de `ModelProvider`; ninguno recibe
autoridad sobre política. Los permisos `read`, `index` y `memory` se verifican
antes de acceder a datos.

## Procesos objetivo

- **Core Python 3.12:** conversación, planificación, memoria, RAG, política y CLI.
- **`llama-server`:** proceso no elevado, loopback, Qwen3-8B GGUF, streaming;
  implementado en Fase 1 con offload adaptable a VRAM disponible.
- **`llama-server` embeddings:** segundo proceso loopback, Qwen3-Embedding-0.6B,
  pooling `last`, CPU por defecto y carga bajo demanda.
- **Broker .NET 8:** named pipe con ACL por usuario; FS/procesos/UIA/captura. No
  acepta comandos libres ni confía en el riesgo enviado por Python.
- **Índice ANN futuro:** Qdrant o extensión SQLite solo si el benchmark supera la
  escala del coseno exacto; no es dependencia actual.
- **VLM:** cargado bajo demanda y nunca simultáneo si excede los 8 GB de VRAM.

## Persistencia

SQLite contiene proyectos, sesiones, mensajes, auditoría, memoria de trabajo,
episodios, decisiones temporales, perfil explícito, fuentes, fragmentos, FTS5 y vectores. Los filtros de
`project_id` se aplican en SQL antes de recuperar o puntuar; cambiar el modelo de
embeddings obliga a reindexar los fragmentos afectados.

Los secretos no pertenecen a SQLite: usarán Credential Manager/DPAPI. Capturas y
audio no se conservarán por defecto. Los servicios no se expondrán a la LAN.

## Hardware objetivo

La configuración se limita deliberadamente a RTX 5060 Laptop de 8 GB y 31.7 GB de
RAM: 8B Q4_K_M con 8K–12K de contexto, Whisper small/medium INT8 en CPU y VLM
4B bajo demanda. No se diseñará suponiendo 24 GB de VRAM.
