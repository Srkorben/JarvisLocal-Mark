# ADR 0008: herramientas deterministas limitadas antes del broker

Estado: aceptada — 2026-10-08

La Fase 4 incorpora operaciones de lectura, apertura y archivos dentro del núcleo
Python porque sus contratos son pequeños, no requieren elevación y pueden
validarse con APIs nativas. No se introduce shell libre ni se adelanta el broker
.NET/UI Automation.

Cada herramienta continúa atravesando `ActionExecutor`, `PolicyEngine`, permisos
de proyecto, presupuesto, cancelación, verificación y auditoría. Los permisos
`open`, `execute` y `write` son falsos por defecto, incluso en proyectos migrados.
Solo la CLI local confiable puede cambiarlos; el LLM no dispone de esa herramienta.

Las creaciones y copias usan apertura exclusiva y nunca sobrescriben. Los
movimientos usan `MoveFileW` sin reemplazo, se limitan al mismo volumen, verifican
SHA-256 y son nivel 2 con confirmación ligada al `request_id`. Un timeout de un
handler síncrono activa el token y espera su limpieza cooperativa, para no devolver
mientras un thread continúa modificando archivos.

La apertura asociada solo confirma que Windows aceptó el despacho y que la ruta
sigue siendo válida; sin UI Automation no afirma que una ventana esté visible. El
riesgo TOCTOU frente a un atacante local concurrente no se considera resuelto por
completo. Por ello `write=false` permanece por defecto y acciones más amplias o
privilegiadas deberán moverse al broker con handles/ACL apropiados.

