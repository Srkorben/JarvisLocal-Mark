# Integración de OpenJarvis en Mark

Mark es la aplicación (`runtime\desktop\JarvisLocal.exe`), la identidad, la voz y
la autoridad. OpenJarvis (`open-jarvis/OpenJarvis`, base registrada en
`OPENJARVIS_UPSTREAM`) aporta el motor de inferencia y sus capacidades, visibles
dentro de la misma ventana en **Capacidades de Mark**.

## Arquitectura

| Capa | Qué hace | Dónde |
| --- | --- | --- |
| Ventana | WPF + WebView2; solo navega al centro de control en `127.0.0.1`; niega todo permiso web salvo el micrófono para el panel de capacidades (`127.0.0.1:8765`) | `desktop/JarvisLocal.Desktop/` |
| Centro de control | Chat, modo llamada, Núcleo, módulos, Sistemas; catálogo cerrado de procesos | `src/jarvis_local/control_center/` |
| Cerebro de Mark | Orquestador, política, presupuestos y auditoría de Mark; el modelo se consulta por el proveedor `openjarvis` (Ollama, `qwen3:8b`) | `src/jarvis_local/model_providers/openjarvis_engine.py` |
| Capacidades | `jarvis serve` en `127.0.0.1:8765`, sin clave ni login, incrustado en la ventana; hogar propio en `data\openjarvis` | `src/jarvis_local/openjarvis_bridge.py` |
| Voz | Qwen3-TTS aislado; OpenJarvis la usa como backend `mark_voice` con la misma muestra y consentimiento | `src/openjarvis/speech/mark_voice/` |

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
| Micrófono en el panel | Permitido solo para `127.0.0.1:8765`; requiere republicar `JarvisLocal.exe` |
| Dashboard, logs, telemetría, energía (NVIDIA) | Interfaz verificada; energía NVIDIA no medida aquí |
| Interfaz completa dentro de Mark | Verificada en Chromium con Ollama real; WebView2 no probado |

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
