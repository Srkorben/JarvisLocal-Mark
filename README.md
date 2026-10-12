# Mark Scout

**Mark Scout** (nombre habitual: **Mark**) es un copiloto personal para Windows,
local por defecto,
auditable y cancelable. El proyecto se construye por fases: el modelo propone;
política, presupuesto y ejecutor independientes conservan toda autoridad sobre el
sistema operativo.

La base técnica conserva temporalmente el nombre `JarvisLocal` en rutas, paquete
Python, SQLite y ejecutable para evitar una migración destructiva. Esa distinción
está documentada en el ADR 0014.

## Estado actual

Las **Fases 0, 1, 3 y 4 están implementadas y validadas**. La Fase 2 ya tiene un
pipeline de voz local semidúplex, una muestra propia enrolada y síntesis E2E
validada; falta la aceptación humana de naturalidad para cerrarla. No se ha iniciado wake word, Playwright, UI
Automation, broker C#, OCR ni visión.

Funciona ahora:

- `ModelProvider` sustituible por configuración (`llama_cpp` u `ollama`);
- Qwen3-8B Q4_K_M oficial en `llama-server`, contexto de 8K y modo no-thinking;
- inicio, detección, health check y detención del servidor gestionado;
- streaming, timeout y cancelación real cerrando la conexión HTTP;
- tool calling OpenAI-compatible con validación de JSON y esquemas Pydantic;
- historial textual persistente en SQLite;
- política, permisos y auditoría completamente independientes del proveedor;
- offload GPU adaptativo con reserva de VRAM para evitar paginación WDDM;
- configuración TOML validada, proyectos aislados y presupuestos por turno;
- memoria de trabajo, episódica, documental y perfil explícito separados;
- decisiones temporales confirmadas con vigente/anterior, motivo y procedencia;
- TXT, Markdown y PDF textual indexados incrementalmente por hash;
- SQLite FTS5 + embeddings locales + coseno exacto, filtrados por proyecto;
- citas a ruta/sección/página y señalización de posible prompt injection;
- herramientas deterministas de búsqueda, apertura, proyectos, Git y archivos;
- permisos `open`, `execute` y `write` denegados por defecto;
- creación/copia sin sobrescritura y movimiento sensible confirmado con rollback.
- micrófono/altavoces WASAPI, controles gráficos, estados explícitos y semidúplex;
- `STTProvider` faster-whisper small CPU INT8 con VAD/hotwords;
- `TTSProvider` sustituible, cancelación de audio y auditoría sin guardar PCM;
- Chatterbox LatAm aislado/offline para la voz propia, ligado a consentimiento.
- importación local de referencias de voz autorizadas (15–30 s) desde **Sistemas**,
  con normalización, hash, respaldo recuperable y auditoría sin guardar el audio;
- aplicación WPF/WebView2 `JarvisLocal.exe`, sin consola, con escena procedural,
  ondas por estado de voz y centro de control loopback de catálogo cerrado;
- presencia visual efímera para carga, escucha, transcripción, procesamiento,
  respuesta, cancelación y error, sin duplicar historial ni guardar audio.
- panel **Núcleo** dentro del chat, con estado real de texto/voz, modelo,
  CPU, RAM, GPU y VRAM, y controles que reutilizan el catálogo cerrado;
- seis módulos interactivos con configuración real y límites explícitos;
- gobernador visual Auto/Equilibrado/Eco que reduce FPS, resolución y partículas
  durante inferencia y pausa el render al ocultarse.
- cliente experimental Godot 4.7.2 conectado a la presencia efímera de Mark,
  iniciable desde el catálogo cerrado sin acceso a memoria, política ni tools.

El benchmark reproducible obtuvo 0,688 s de TTFT mediano, 54,85 tokens/s, 3/3
casos de tool calling y cancelación en 94 ms. Son medidas de esta máquina y no una
garantía. El benchmark RAG obtuvo 4/4 fuentes esperadas y 1,524 s de latencia
mediana de consulta con embeddings en CPU. Consulta [PROJECT_STATUS.md](PROJECT_STATUS.md),
el [benchmark del LLM](benchmarks/results/qwen3-8b-q4_k_m-ctx8192.md) y el
[benchmark RAG](benchmarks/results/rag-qwen3-embedding-0.6b-q8_0.md).
La prueba E2E con audio sintético obtuvo 11,735 s sin reproducción y reveló
errores con nombres técnicos; consulta el
[benchmark de voz](benchmarks/results/audio-phase2.md). No se promete latencia
conversacional hasta medir la muestra propia.

## Preparación

Requisitos:

- Windows 11 de 64 bits;
- Python 3.12 de 64 bits;
- NVIDIA RTX 5060 Laptop o hardware compatible para la configuración incluida;
- artefactos locales descritos en [docs/dependencies.md](docs/dependencies.md).

El equipo local ya contiene el binario y el modelo, ambos ignorados por Git. Para
recrear el entorno Python:

```powershell
Set-Location 'C:\Users\andcb\Documents\AI Local\JarvisLocal'
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup.ps1
```

El script crea `.venv`, instala el paquete y dependencias de desarrollo, ejecuta
las pruebas y termina con diagnóstico. Si encuentra un entorno de otra versión de
Python, lo preserva como `.venv.incompatible-<fecha>`.

La voz activa usa deliberadamente otro entorno. Ya está instalada en esta máquina;
para recrearla descarga XTTS-v2 fijado por revisión (~2,09 GB):

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Setup-XTTS.ps1
```

## Uso y verificación

La experiencia principal se abre desde `Mark Scout.lnk`, que ejecuta directamente
`runtime\desktop\JarvisLocal.exe`. No abre CMD ni PowerShell. En **Conversación**,
pulsa **Iniciar llamada** una sola vez: Mark escucha cada intervención, responde y
vuelve a escuchar hasta que pulses **Colgar**. En **Pulsar para hablar**, mantén el
micrófono presionado y suéltalo para enviar.
Consulta [docs/desktop.md](docs/desktop.md).

Para cambiar la referencia de síntesis, abre **Sistemas → Enrolar mi voz → Subir
audio**. Admite WAV, MP3, M4A, FLAC, OGG, OPUS, AAC o WMA de 15–30 segundos y
24 MiB como máximo. Debes confirmar que eres titular de la voz o que cuentas con
autorización del titular. El proceso permanece en `127.0.0.1`; normaliza el audio
a PCM mono de 24 kHz y respalda la referencia anterior. XTTS usa la muestra como
referencia zero-shot: no se reentrenan los pesos del modelo.

El centro también puede iniciarse, consultarse o detenerse desde consola para
diagnóstico o recuperación:

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.control_center --launch
.\.venv\Scripts\python.exe -m jarvis_local.control_center --status
.\.venv\Scripts\python.exe -m jarvis_local.control_center --stop
```

```powershell
# Conversación interactiva; inicia y detiene llama-server automáticamente
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Run-Jarvis.ps1

# Una instrucción
.\.venv\Scripts\python.exe -m jarvis_local.cli --once '¿Qué hora es?'

# Diagnóstico y cadena de auditoría
.\.venv\Scripts\python.exe -m jarvis_local.cli --doctor
.\.venv\Scripts\python.exe -m jarvis_local.cli --verify-audit

# Enrolar conscientemente 15 s de tu propia voz (una sola vez)
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --enroll-own-voice --voice-enroll-seconds 15

# Inventario, diagnóstico y runtime de voz controlado por la interfaz
.\.venv\Scripts\python.exe -m jarvis_local.cli --list-audio-devices
.\.venv\Scripts\python.exe -m jarvis_local.cli --audio-doctor
.\.venv\Scripts\python.exe -m jarvis_local.cli --voice

# Proyecto activo, índice incremental y consulta con fuentes
.\.venv\Scripts\python.exe -m jarvis_local.cli --list-projects
.\.venv\Scripts\python.exe -m jarvis_local.cli --index-project
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --rag-query '¿Qué decisión de arquitectura está documentada?'

# Registrar y consultar una decisión confirmada (escritura sólo desde CLI local)
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --record-decision 'Usar SQLite.' `
  --decision-topic 'Persistencia' `
  --decision-reason 'Despliegue local de un solo usuario.'
.\.venv\Scripts\python.exe -m jarvis_local.cli --decision-history 'Persistencia'

# Evaluar una acción sin efectos
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --simulate-tool list_directory `
  --arguments '{"path":"C:\\Users\\andcb\\Documents\\AI Local\\JarvisLocal"}'

# Ver permisos y habilitar explícitamente una capacidad para el proyecto activo
.\.venv\Scripts\python.exe -m jarvis_local.cli --list-projects
.\.venv\Scripts\python.exe -m jarvis_local.cli --set-project-permission open=true

# Integración real controlada de herramientas de Fase 4
.\.venv\Scripts\python.exe -m jarvis_local.phase4_smoke

# Suite y benchmark
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m jarvis_local.benchmark
.\.venv\Scripts\python.exe -m jarvis_local.rag_benchmark
```

En llamada, **Silenciar** libera la captura hasta reactivarla; **Interrumpir**
detiene el turno actual y **Colgar** cierra la sesión y el micrófono. En modo
manual, mantén pulsado el micrófono y suelta para enviar. `Ctrl+C` solo cierra la
CLI de diagnóstico. La voz transcrita nunca confirma
acciones sensibles. XTTS-v2 está seleccionado y falla cerrado si faltan la
muestra o su manifiesto SHA-256. Consulta [docs/audio.md](docs/audio.md).

La voz clonada usa CUDA en la RTX 5060. Mark carga y prepara XTTS-v2 antes de
`llama-server`, de modo que el offload adaptativo del LLM solo utiliza la VRAM
restante. La primera carga integrada observada fue 110,9 s; después del
precalentamiento, una respuesta de 5,39 s de audio se sintetizó en 2,28 s. Piper
y Chatterbox se conservan como fallbacks, pero no son la selección activa.

## Configuración de modelos

`config\jarvis.toml` selecciona el proveedor sin cambiar el núcleo:

```toml
[llm]
provider = "llama_cpp"
base_url = "http://127.0.0.1:8080/v1"
model = "qwen3-8b-q4_k_m"
context_tokens = 8192

[llama_cpp]
auto_start = true
gpu_layers = "auto"
fit_target_mib = 1024

[embeddings]
provider = "llama_cpp"
base_url = "http://127.0.0.1:8081/v1"
model = "qwen3-embedding-0.6b-q8_0"
gpu_layers = 0
```

Solo se aceptan URLs `http://127.0.0.1`. `llama-server` desactiva su UI y no
habilita tools, MCP ni agent mode. Cambiar el modelo o proveedor no altera
allowlists, niveles de riesgo ni permisos efectivos.

Los secretos nunca deben guardarse en TOML. No añadas como raíz autorizada `C:\`,
el perfil completo, `AppData`, credenciales ni ubicaciones protegidas. El núcleo
no debe ejecutarse como administrador.

Los permisos `open`, `execute` y `write` deben habilitarse por proyecto desde la
CLI local. `move_file` siempre exige además confirmación interactiva. Consulta la
[matriz de herramientas](docs/tools.md) antes de ampliar permisos.

## Estructura

```text
JarvisLocal/
├─ benchmarks/             runner y resultados reproducibles
├─ config/                 configuración declarativa
├─ desktop/                shell WPF/WebView2 de la aplicación gráfica
├─ docs/                   arquitectura, selección, roadmap y ADR
├─ models/                 pesos locales ignorados por Git
├─ runtime/                llama.cpp local ignorado por Git
├─ scripts/                instalación y ejecución
├─ src/jarvis_local/
│  ├─ model_providers/     contrato, Ollama, llama.cpp y gestor del servidor
│  ├─ audio/               WASAPI, STT/TTS, llamada/PTT, estados y enrolamiento
│  ├─ control_center/      UI local, presencia efímera y gestor de procesos
│  ├─ memory/              trabajo, episodios y perfil explícito
│  ├─ rag/                 extracción, embeddings, índice y recuperación híbrida
│  ├─ cli.py               interfaz local confiable
│  ├─ orchestrator.py      conversación y coordinación sin autoridad
│  ├─ execution.py         puerta única de ejecución del núcleo
│  ├─ policy.py            política independiente del LLM
│  ├─ tools/               esquemas, registro y herramientas
│  ├─ projects.py          identidad, permisos y aislamiento por proyecto
│  ├─ database.py          persistencia y cadena de auditoría
│  └─ cancellation.py      cancelación cooperativa
└─ tests/                  pruebas unitarias, integración HTTP y seguridad
```

Consulta [SECURITY.md](SECURITY.md) antes de añadir una capacidad y
[docs/rag.md](docs/rag.md) para operar memoria documental. Revisa
[la evaluación de patrones de CORE](docs/core-evaluation.md),
[docs/tools.md](docs/tools.md) para acciones de Windows y
[docs/roadmap.md](docs/roadmap.md) antes de ampliar el alcance. La auditoría,
operación y recuperación del acceso único están en
[docs/control-center.md](docs/control-center.md). El diagnóstico y la hoja de ruta
visual están en [docs/immersive-interface.md](docs/immersive-interface.md).
El inventario y las pruebas de motores están en
[docs/3d-engines.md](docs/3d-engines.md).
