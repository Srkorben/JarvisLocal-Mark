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
JarvisLocal.lnk
  → Launch-ControlCenter.ps1 (ventana oculta, error visible si falla)
  → python -m jarvis_local.control_center --launch
       ├─ reutiliza instancia saludable
       ├─ o inicia un único proceso pythonw
       └─ abre el navegador predeterminado

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

El token se genera en cada inicio y se guarda en
`data/control_center/endpoint.json`, cuya ACL se restringe a la cuenta actual. La
URL inicial lo canjea por una cookie y redirige inmediatamente; los logs omiten
queries y cookies. El servicio escucha exclusivamente en IPv4 loopback.

## Estados y conflictos

Los estados visibles son disponible, en ejecución, no disponible y con error.
Chat, voz, diagnóstico y mantenimiento usan grupos de exclusión para evitar
servidores/modelos o dispositivos de audio competidores. Un segundo clic sobre un
proceso vivo devuelve `already_running`. La voz aparece no disponible mientras
falten `reference.wav` y `consent.json`, exactamente igual que el backend seguro.

Las acciones de instalación y enrolamiento muestran una confirmación local. Cada
script conserva consola visible; el panel no oculta su salida ni intenta aceptar
prompts en nombre del usuario.

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

El acceso único puede recrearse con `scripts/Consolidate-DesktopShortcuts.ps1`.
Ese script respalda primero cada `.lnk` sustituido, crea y valida el nuevo enlace
y solo entonces retira los nueve accesos redundantes. No elimina scripts,
ejecutables, configuraciones, modelos ni carpetas originales.

Respaldo creado durante la consolidación validada:
`backups/desktop-shortcuts/20261008-121213/` (nueve `.lnk` más
`inventory.json`).

Estado final del Escritorio: un solo acceso directo, `JarvisLocal.lnk`, más
`LM.txt` con instrucciones de uso, voz, diagnóstico y rutas de las herramientas
externas retiradas.

## Limitaciones

- El panel no se instala como servicio de Windows; el acceso lo inicia bajo la
  sesión del usuario y la instancia queda en segundo plano.
- Aplicaciones delegadas como Explorer pueden reutilizar un proceso ya existente,
  por lo que su estado solo puede verificarse como lanzamiento solicitado.
- La conversación por voz permanece bloqueada hasta el enrolamiento real.
- No se ejecutaron nuevamente los tres instaladores durante la aceptación: se
  verificaron catálogo, rutas, confirmación y ejecución mediante el mismo gestor,
  evitando reinstalaciones o descargas innecesarias.
