# Integración de OpenJarvis en Mark

Mark es la aplicación (`runtime\desktop\JarvisLocal.exe`), la identidad, la voz y
la autoridad. OpenJarvis (`open-jarvis/OpenJarvis`, base registrada en
`OPENJARVIS_UPSTREAM`) aporta el motor de inferencia y sus capacidades, visibles
dentro de la misma ventana en **Capacidades de Mark**.

## Arquitectura

| Capa | Qué hace | Dónde |
| --- | --- | --- |
| Ventana | WPF + WebView2; solo navega al centro de control en `127.0.0.1`; niega todo permiso web salvo el micrófono para el panel de capacidades (`127.0.0.1`, puerto propio desde 8790) | `desktop/JarvisLocal.Desktop/` |
| Centro de control | Chat, modo llamada, Núcleo, módulos, Sistemas; catálogo cerrado de procesos | `src/jarvis_local/control_center/` |
| Cerebro de Mark | Orquestador, política, presupuestos y auditoría de Mark; el modelo se consulta por el proveedor `openjarvis` (Ollama, `qwen3:8b`) | `src/jarvis_local/model_providers/openjarvis_engine.py` |
| Capacidades | `jarvis serve` en `127.0.0.1` (puerto propio desde 8790), sin clave ni login, incrustado en la ventana; hogar propio en `data\openjarvis` | `src/jarvis_local/openjarvis_bridge.py` |
| Voz | Qwen3-TTS aislado; OpenJarvis la usa como backend `mark_voice` con la misma muestra y consentimiento | `src/openjarvis/speech/mark_voice/` |

## Navegación: la pantalla de Mark es la puerta de entrada

La pantalla de inicio de Mark (círculo azul, ondas, indicador de conexión,
Iniciar llamada) se conserva. Debajo del encabezado hay pestañas; cada una abre
una página real de la interfaz de OpenJarvis dentro de la misma ventana, con el
tema azul de Mark y sin la barra lateral propia de OpenJarvis (`?shell=mark`):

| Pestaña | Página de OpenJarvis |
| --- | --- |
| Inicio | Pantalla de Mark |
| Conversación | Chat de Mark (texto y voz, con su política y herramientas) |
| Agentes y automatizaciones | `/agents`: agentes gestionados, plantillas, programación |
| Investigación | `/` con Deep Research activado |
| Correo | `/data-sources?focus=email`: Gmail, Gmail IMAP, IMAP, Outlook |
| Calendario y tareas | `/data-sources?focus=calendar`: Google Calendar, Google Tasks, Google Contacts (y Apple en macOS) |
| Documentos y fuentes | `/data-sources`: todos los conectores y la carga de archivos |
| Memoria | `/data-sources?tab=memory` |
| Canales | `/data-sources?tab=messaging` |
| Herramientas | `/settings?section=tools` |
| Modelos | `/settings?section=models` |
| Configuración | `/settings` |
| Estado | `/dashboard` |
| Registros | `/logs` |

OpenJarvis arranca con Mark y el encabezado muestra su estado (apagado,
iniciando, listo o con error). Así las pestañas responden al instante y las
automatizaciones programadas corren mientras Mark esté abierto.

## Iniciar llamada

- **Regresión corregida:** con el panel de OpenJarvis abierto, "Iniciar llamada" y el chat fallaban con "entra en conflicto con OpenJarvis", porque compartían el grupo exclusivo `maintenance`. Ahora OpenJarvis convive con la voz y el chat, y solo choca con las tareas que reinstalan dependencias.
- **Motivo visible:** si la llamada no está disponible, debajo del botón aparece exactamente qué falta (entorno de voz, modelo, muestra, transcripción o consentimiento).
- **Diagnóstico sin cambios:** `python -m jarvis_local.control_center --voice-check` informa, sin modificar nada, el motor de voz, la muestra configurada y lo que falte. El instalador lo ejecuta y además comprueba que `.venv-qwen3-tts` carga el *worker* de voz.

## Botón de encendido y servicios

- **Encender Mark** carga el modelo local (núcleo de conversación) y OpenJarvis; **Apagar** detiene la voz, el núcleo y OpenJarvis. El botón muestra el estado: apagado, encendiendo o encendido.
- **OpenJarvis tiene su propio puerto, desde el 8790.** El rango 8765–8774 es del centro de control de Mark; si ambos usaban el 8765, OpenJarvis no podía abrir su puerto y el panel mostraba la página de Mark, bloqueada (icono de prohibido). Si el 8790 está ocupado, se usa el siguiente libre.
- **Instancias huérfanas.** Al arrancar, Mark cierra los servidores de OpenJarvis que hayan quedado vivos de una sesión anterior. En Windows, el árbol de procesos se cierra con `taskkill /T /F` cuando hace falta.
- **Ollama primero.** Antes de iniciar OpenJarvis, Mark asegura que Ollama responda (lo inicia oculto si está instalado), porque `jarvis serve` se cierra si no hay motor.
- **Errores con causa.** La salida de cada proceso oculto queda en `data\logs\tools\<herramienta>.log`. Si OpenJarvis se cierra, el panel muestra el motivo (por ejemplo "Ollama no responde…" o "se cerró al iniciar (código 1): …"), junto a un botón **Reintentar**. Si la interfaz no termina de cargar en 30 s, también se avisa.

## Seguridad: la política de Mark manda

En cada arranque, Mark regenera `data\openjarvis\capabilities.json` a partir de
`[security]` en `config/jarvis.toml` y fija en `data\openjarvis\config.toml` la
política de capacidades (`default_deny`), `allowed_dirs`, el servidor en loopback
y la analítica apagada. El resto de ese archivo (conectores, agentes, skills) es
del usuario y se conserva.

| Capacidad de OpenJarvis | Agentes (`_default`) | Se habilita cuando |
| --- | --- | --- |
| `file:read` | Permitida, solo dentro de `allowed_roots` | Siempre (las rutas las acota `allowed_dirs`) |
| `memory:read`, `memory:write`, `schedule:create` | Permitidas | Siempre |
| `file:write` | Denegada | Nunca desde OpenJarvis (en Mark, escribir pide confirmación) |
| `code:execute`, `tool:invoke` | Denegadas | `privileged_tools_enabled = true` |
| `network:fetch` | Denegada | `allowed_domains` no vacío y `max_outbound_bytes > 0` |
| `channel:send`, `system:admin` | Denegadas | Nunca para agentes |

OpenJarvis evalúa cada capacidad por nombre de herramienta, no por dominio. Por
eso, si Mark autoriza algún dominio, la red de los agentes se abre completa
(con la protección SSRF de OpenJarvis). La identidad `server:api` (tu propia
administración de agentes en la interfaz) conserva `system:admin`.

Verificado con OpenJarvis y Ollama reales (`qwen3:0.6b`): un agente leyó un
archivo dentro de las raíces; leer `/etc/hostname` se negó por `allowed_dirs`;
`file_write` y `shell_exec` se negaron por capacidad.

## Matriz de capacidades

| Capacidad | Estado en Mark (Windows) |
| --- | --- |
| Motor Ollama, selección de modelo | Verificado con Ollama real (chat de Mark con herramienta auditada; chat del panel) |
| Otros motores locales (llama.cpp, LM Studio) | Disponibles en OpenJarvis; no verificados |
| vLLM, SGLang, MLX, Apple FM, Exo, Nexa, Uzu | No aplican o no son nativos en Windows |
| Motores en la nube (cloud, LiteLLM, NIM) | Requieren claves y red; desactivados por la política por defecto |
| Agentes `simple`, `orchestrator`, `native_react` | Verificados (`orchestrator` ejecutó `calculator`) |
| Deep Research | No verificado; sobre documentos locales no necesita red, la búsqueda web necesita `network:fetch` |
| Agentes de código (OpenHands, mini-SWE, `claude_code`, `opencode`) | Bloqueados: necesitan `code:execute` |
| Memoria y conocimiento (SQLite, BM25, grafo) | Disponibles con el componente Rust; cubiertos por la suite de pruebas |
| Skills | Catálogo y uso disponibles; instalar desde Internet necesita red |
| Automatizaciones y agentes programados | Permitidos (`schedule:create`) con la misma política |
| Conectores Gmail, Calendar, Drive, Notion, Slack, Outlook, Dropbox, IMAP, RSS, etc. | Requieren credenciales y red; no verificados |
| Conectores Apple (iMessage, Notes, Contacts, Health, Music, Calendar) | Solo macOS |
| Canales (31: Telegram, Discord, Slack, WhatsApp…) | Bloqueados: `channel:send` denegado |
| Voz: STT faster-whisper | Instalado (extra `desktop`); no verificado con micrófono real |
| Voz: TTS `mark_voice` | Probado con un worker simulado; Qwen3-TTS real no se probó aquí |
| Micrófono en el panel | Permitido solo para el servidor de OpenJarvis en loopback (nunca para el centro de control); requiere republicar `JarvisLocal.exe` |
| Dashboard, logs, telemetría, energía (NVIDIA) | Interfaz verificada; energía NVIDIA no medida aquí |
| Interfaz completa dentro de Mark | Verificada en Chromium: con Ollama real (chat) y con Ollama simulado (las 14 pestañas); WebView2 no probado |
| Conector Markdown/Obsidian | Verificado: conectar, sincronizar y recuperar el contenido desde `knowledge.db` |
| Correo y calendario (estado) | Verificado: la API lista Gmail, IMAP, Outlook, Calendar, Tasks y Contacts con su estado y tipo de autenticación; conectar requiere tus credenciales |

## VRAM (RTX 5060, 8 GB)

- **Mismo contexto en ambos chats.** El panel usa `JARVIS_NUM_CTX` igual al contexto de Mark (8.192). OpenJarvis pediría 16.384, lo que obligaría a Ollama a recargar el modelo al alternar entre chats y reservaría más KV.
- **La voz se carga antes que el modelo.** Con voz en CUDA, Mark descarga los modelos residentes de Ollama antes de cargar Qwen3-TTS (verificado con Ollama real). Ollama los vuelve a cargar en la siguiente petición, ajustando las capas a la VRAM libre.
- **Ollama no se reconfigura.** Mark no cambia la configuración de tu Ollama. Si Mark lo inicia, lo hace oculto y con tu configuración.

## Instalar y actualizar

`Crear-Acceso-Directo-Mark.bat` localiza o clona el repositorio y ejecuta
`scripts\Install-Mark.ps1`, que:

1. Cierra solo los procesos de Mark.
2. Instala con `uv`, incluido el componente Rust si están las MSVC Build Tools (pide permiso para instalarlas).
3. Compila la interfaz cuando cambia.
4. Asegura Ollama con `qwen3:8b`.
5. Republica `JarvisLocal.exe` cuando cambia su código (.NET 8 SDK, con permiso).
6. Crea el acceso directo **Mark**.

El script deja un registro en `data\logs` y nunca toca `data\`, `models\` ni los entornos de voz.

Para traer versiones nuevas de OpenJarvis: `python scripts/update_openjarvis.py`.
Aplica con fusión de tres vías solo lo que cambió en OpenJarvis desde la base registrada.

## Pendiente de verificar en el PC

- El instalador en Windows (PowerShell 5.1, `winget`, Build Tools, .NET SDK).
- `JarvisLocal.exe` republicado con el permiso de micrófono (compila para `win-x64` sin avisos).
- Qwen3-TTS real en CUDA junto a `qwen3:8b`.
- Los conectores que requieren credenciales.
