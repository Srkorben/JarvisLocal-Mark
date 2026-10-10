# Centro de control web local

Estado: implementado y validado el 2026-10-08.

## Alcance auditado

Se inspeccionaron `C:\Users\andcb\Desktop` y el Escritorio público. Se encontraron
doce accesos directos. Nueve fueron creados para JarvisLocal y se consolidan; los
tres restantes no pertenecen a este proyecto y se conservan sin modificaciones.

| Acceso JarvisLocal sustituido | Destino original | Dependencia principal |
|---|---|---|
| Abrir proyecto | `explorer.exe` + raíz del repositorio | carpeta JarvisLocal |
| Chat de texto | PowerShell + `Run-Jarvis.ps1` | `.venv`, TOML, llama.cpp/Qwen3 |
| Configuración | `notepad.exe` + `config/jarvis.toml` | TOML local |
| Conversación por voz | PowerShell + `Run-Jarvis-Voice.ps1` | STT, Chatterbox, muestra consentida |
| Diagnóstico | PowerShell + `Diagnose-Jarvis.ps1` | `.venv`, modelos y SQLite |
| Enrolar mi voz | PowerShell + `Enroll-OwnVoice.ps1` | micrófono, `.venv` |
| Instalar o reparar | PowerShell + `Setup.ps1` | Python 3.12 y red para instalación |
| Preparar clonación | PowerShell + `Setup-VoiceClone.ps1` | red, ~3,21 GB, entorno aislado |
| Preparar audio | PowerShell + `Setup-AudioModels.ps1` | red y espacio para modelos |

Inicialmente fuera de alcance: `Codex Admin YOLO.lnk`, `Codex Admin YOLO - Cuenta
2.lnk` y `MarkItDown - Convertir a Markdown.lnk`. Una solicitud posterior exigió
limpiar todo el ruido del Escritorio; esos tres enlaces se trasladaron al respaldo
`backups/desktop-shortcuts/removed-desktop-noise-20261008-122147/`. Sus destinos,
scripts, ejecutables y carpetas originales no se borraron ni modificaron.

## Arquitectura

```text
Mark Scout.lnk
  → runtime/desktop/JarvisLocal.exe (WPF/WinExe, instancia única)
  → pythonw -m jarvis_local.control_center --launch --no-browser
       ├─ reutiliza instancia saludable
       ├─ o inicia un único proceso pythonw
       └─ presenta el panel dentro de WebView2

127.0.0.1:8765 (fallback 8766–8774)
  → autenticación local + cookie HttpOnly/SameSite
  → CSP + CSRF + validación Host/Origin
  → catálogo cerrado de 9 ToolSpec
  → ProcessManager
       ├─ evita duplicados y grupos incompatibles
       ├─ exige confirmación en mantenimiento/enrolamiento
       ├─ inicia el ejecutable y argumentos originales sin shell
       └─ solo detiene procesos que él mismo inició
```

El navegador no envía comandos. Solo puede seleccionar un identificador incluido
en el catálogo Python. El cuerpo HTTP acepta únicamente el booleano `confirmed`;
no existe un endpoint de shell, rutas, argumentos, variables de entorno ni código.

La conversación de voz es una excepción de presentación, no de autoridad: se
inicia directamente con `.venv\Scripts\python.exe`, `shell=False` y sin ventana de
consola. Su presencia se publica en memoria al mismo servidor para animar la escena;
el endpoint interno rechaza cualquier campo diferente de estado, transcripción,
respuesta y error.

El token se genera en cada inicio y se guarda en
`data/control_center/endpoint.json`, cuya ACL se restringe a la cuenta actual. La
URL inicial lo canjea por una cookie y redirige inmediatamente; los logs omiten
queries y cookies. El servicio escucha exclusivamente en IPv4 loopback.

## Panel Núcleo y monitor local

El chat incluye un panel desplegable **Núcleo**. No es una simulación: utiliza el
mismo `ProcessManager` que administra texto y voz, y por ello sus botones conservan
el catálogo cerrado, los grupos de exclusión y la detención del árbol de procesos.
Muestra el proveedor y modelo configurados, el estado de ambos runtimes y métricas
de CPU, RAM, GPU y VRAM.

`GET /api/system` exige la cookie local ya establecida, responde con `no-store` y
no incluye PID, comandos, rutas privadas ni credenciales. CPU y RAM se leen con
contadores nativos; la GPU NVIDIA se consulta con `nvidia-smi` bajo un timeout de
800 ms. Las métricas de hardware se conservan dos segundos para evitar sondeos
costosos. Si una fuente no existe o excede el timeout, la UI muestra
«No disponible» y el motivo técnico seguro; nunca inventa valores.

La precedencia visual es `error`, `cancelando`, `procesando`, `inicializando`,
`disponible` y `apagado`. Una revisión antigua de presencia no puede sobrescribir
una nueva. En Windows el servidor reclama el puerto de forma exclusiva, por lo
que otra copia debe usar el siguiente puerto del rango cerrado en vez de compartir
silenciosamente el mismo socket.

## Estados y conflictos

Los estados visibles son disponible, en ejecución, no disponible y con error.
Chat, voz, diagnóstico y mantenimiento usan grupos de exclusión para evitar
servidores/modelos o dispositivos de audio competidores. Un segundo clic sobre un
proceso vivo devuelve `already_running`. La voz aparece no disponible mientras
falten `reference.wav` y `consent.json`, exactamente igual que el backend seguro.

Las acciones de instalación y enrolamiento muestran una confirmación local. Cada
script conserva consola visible; el panel no oculta su salida ni intenta aceptar
prompts en nombre del usuario.

La tarjeta **Enrolar mi voz** ofrece además **Subir audio**. El archivo viaja solo
al servidor loopback autenticado y se admite como referencia si dura 15–30 s,
pertenece a una allowlist de formatos y el usuario confirma propiedad o permiso
del titular. La API no acepta rutas ni comandos, limita el cuerpo a 34 MiB
codificados (24 MiB de audio), normaliza a PCM16/24 kHz, respalda la referencia
anterior y registra únicamente metadatos. La conversación de voz debe estar
detenida durante el cambio.

## Operación

```powershell
# Iniciar o reutilizar sin abrir navegador
.\.venv\Scripts\python.exe -m jarvis_local.control_center --launch --no-browser

# Estado y detención exclusiva del panel
.\.venv\Scripts\python.exe -m jarvis_local.control_center --status
.\.venv\Scripts\python.exe -m jarvis_local.control_center --stop

# Smoke HTTP real controlado
.\.venv\Scripts\python.exe -m jarvis_local.control_center_smoke
```

La versión original del acceso puede recrearse con
`scripts/Consolidate-DesktopShortcuts.ps1`; la Desktop Alpha actualiza su destino
al `.exe` publicado. Antes de cambiarlo se conserva una copia recuperable. Ningún
script, ejecutable, configuración, modelo o carpeta original se elimina.

Respaldo creado durante la consolidación validada:
`backups/desktop-shortcuts/20261008-121213/` (nueve `.lnk` más
`inventory.json`).

Respaldo del acceso anterior a Desktop Alpha:
`backups/desktop-shortcuts/desktop-alpha-20261008-185620/JarvisLocal.lnk`.

Estado del proyecto en el Escritorio: un solo acceso directo público,
`Mark Scout.lnk`, más `LM.txt` con instrucciones de uso, voz y diagnóstico. Otros
accesos que puedan existir pertenecen a proyectos distintos y no son administrados
por este centro.

## Limitaciones

- La aplicación no se instala como servicio de Windows; el acceso la inicia bajo la
  sesión del usuario y cerrar la ventana detiene sus procesos propiedad.
- Aplicaciones delegadas como Explorer pueden reutilizar un proceso ya existente,
  por lo que su estado solo puede verificarse como lanzamiento solicitado.
- La clonación de voz permanece bloqueada hasta el enrolamiento real; en esta
  máquina la muestra y el consentimiento ya existen.
- No se ejecutaron nuevamente los tres instaladores durante la aceptación: se
  verificaron catálogo, rutas, confirmación y ejecución mediante el mismo gestor,
  evitando reinstalaciones o descargas innecesarias.
