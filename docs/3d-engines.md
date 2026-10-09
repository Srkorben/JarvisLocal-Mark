# Motores 3D e integración con Mark Scout

Fecha de inventario: 2026-10-09.

## Estado ejecutado

| Tecnología | Instalación | Prueba | Integración con Mark |
|---|---|---|---|
| Godot Engine 4.7.2 | instalada por WinGet, paquete oficial MIT | arranque headless y escena cargada | cliente de presencia 3D autenticado, disponible en **Sistemas** |
| Unity Hub 3.22.2 | instalado por WinGet, paquete oficial | Hub detectado | editor/proyecto en preparación |
| Unity 6.3 LTS | instalada en `C:\Program Files\Unity\Hub\Editor\6000.3.26f1` (7,85 GB) | binario/revisión verificados; batch bloqueado por licencia (código 198) | adaptador preparado, no validado ni publicado en el catálogo |
| Epic Games Launcher 20.3.3 | actualizado; instalación existente en `D:\Epic Games` | ejecutable detectado | gestor preparado |
| Unreal Engine 5.8 | no instalado | no ejecutada | bloqueado por autenticación/aceptación de cuenta Epic |

El instalador oficial comprobado de Unity corresponde a la revisión
`de8167e7440c`: `UnitySetup64-6000.3.26f1.exe`, 4.206.721.368 bytes y MD5
`50A903B85D8B597197923D65C2E8C3BB`, coincidente con la API oficial de releases.
El instalador temporal se eliminó después de verificar la instalación; puede
recuperarse desde la misma fuente oficial.

No se incorporaron Three.js ni Babylon.js: WebView2/Canvas ya cubre el render
ligero y Godot permite validar la frontera de motor real. Añadir otro framework
antes de medir los tres caminos duplicaría superficie y mantenimiento.

## Integración Godot funcional

El proyecto está en `integrations/godot/mark-presence`. El catálogo cerrado posee
directamente el proceso Godot y le pasa la ruta fija de `endpoint.json`, protegida
por ACL. La escena valida bind/puerto, consulta `/api/voice/presence` con Bearer
sobre `127.0.0.1`, representa estado, transcripción/respuesta efímera y error, y
no recibe permisos ni tools. `scripts/Run-Godot-Presence.ps1` queda como runner de
smoke manual y limpia del entorno el token al terminar.

Prueba reproducible:

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.control_center --launch --no-browser
.\scripts\Run-Godot-Presence.ps1 -SmokeTest
```

El resultado esperado contiene:

```text
MARK_PRESENCE_SMOKE {"authenticated_loopback":true,"ok":true,...}
```

Prueba gráfica real: la ventana `Mark Scout Presence 3D (DEBUG)` abrió, respondió
y se cerró de forma controlada. Tras tres segundos utilizó 168,23 MiB de working
set y 150,46 MiB privados; `nvidia-smi` observó un delta aproximado de 60 MiB de
VRAM (6985→7045 MiB, con otras cargas ya presentes). Es una medida orientativa,
no un presupuesto garantizado.

La prueba de ciclo de vida desde el catálogo confirmó `started`, rechazó una
segunda instancia con `already_running` y terminó el PID directo con `stopped`;
no quedaron procesos Godot huérfanos tras corregir el primer prototipo.

## Regla de recursos

Con 8 GB de VRAM ningún editor 3D debe quedar residente durante inferencia normal.
Los motores son opt-in, pertenecen al grupo exclusivo `visual_runtime` y el shell
principal conserva Auto/Equilibrado/Eco. Antes de elegir motor principal se medirá
VRAM en reposo, VRAM de escena, tiempo de arranque y efecto sobre tokens/s.

## Pendientes concretos

1. Activar una licencia válida desde Unity Hub y ejecutar/compilar el adaptador
   `integrations/unity/MarkPresence`; no se publica antes de esa validación.
2. Iniciar sesión en Epic Games Launcher, aceptar los términos aplicables e
   instalar UE 5.8; esa intervención no puede automatizar credenciales ni EULA.
3. Crear el mismo benchmark visual en Unity/Unreal y comparar con Godot.
4. Incorporar telemetría real DXGI/NVML al gobernador antes de render 3D continuo.
