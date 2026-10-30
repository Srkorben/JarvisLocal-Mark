# Herramientas deterministas

## Permisos y niveles

| Herramienta | Permiso de proyecto | Riesgo | Confirmación | Verificación |
|---|---|---:|---|---|
| `find_files` | `read` | 0 | no | resultados estructurados |
| `git_status`, `git_log` | `read` | 0 | no | salida Git parseada |
| `open_file`, `open_folder` | `read` + `open` | 1 | no | despacho aceptado y ruta revalidada; ventana no inspeccionada |
| `open_project` | `open` en origen y destino | 1 | no | proyecto activo en SQLite; Explorer no inspeccionado |
| `start_application` | `execute` + allowlist global | 1 | no | PID activo tras el arranque |
| `create_note` | `write` | 1 | no | existencia, tamaño y SHA-256 |
| `copy_file` | `read` + `write` | 1 | no | SHA-256 de origen y copia |
| `move_file` | `read` + `write` | 2 | **sí** | origen ausente, destino y SHA-256 |

`open`, `execute` y `write` están deshabilitados por proyecto de forma
predeterminada. Para habilitar conscientemente una capacidad en el proyecto activo:

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.cli --list-projects
.\.venv\Scripts\python.exe -m jarvis_local.cli --set-project-permission open=true
.\.venv\Scripts\python.exe -m jarvis_local.cli --set-project-permission write=true
```

La CLI registra el cambio como `project_permission_changed`. No existe una tool
equivalente para el modelo. `start_application` exige además una ruta `.exe`
absoluta presente en `security.allowed_applications`; no admite argumentos.

## Reglas de archivos

- toda ruta debe estar dentro de la raíz del proyecto activo y de una raíz global;
- UNC, symlinks y junctions se rechazan;
- `create_note` solo crea `.md` o `.txt` mediante modo exclusivo;
- `copy_file` y `move_file` no sobrescriben destinos;
- el límite predeterminado por archivo es 100 MiB;
- `move_file` solo opera en el mismo volumen y devuelve referencia de rollback;
- cancelación durante copia elimina el parcial; durante movimiento restaura origen;
- no existe borrado, sobrescritura, shell libre ni operación administrativa.

Los recibos de confirmación de `move_file` deben proceder de la CLI local y estar
ligados al `request_id`. Texto en documentos, RAG o salida del modelo nunca sirve
como confirmación.

## Git y procesos

Git se invoca con ejecutable resuelto y argumentos fijos mediante
`create_subprocess_exec`, nunca a través de PowerShell/CMD. La salida está limitada
y el proceso se termina ante cancelación o timeout. `start_application` ejecuta
solo el `.exe` exacto de la allowlist, sin línea de comandos proporcionada por el
modelo.

## Verificación reproducible

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.phase4_smoke
```

El smoke test crea un proyecto temporal bajo `data`, ejecuta nota/búsqueda/copia/
movimiento y Git real, comprueba hashes, rollback, auditoría y elimina el proyecto
temporal al terminar. No abre ventanas ni amplía permisos del proyecto real.

