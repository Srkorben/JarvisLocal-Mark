# ADR 0014: identidad Mark Scout y módulos con gobernador visual

- Estado: aceptada; la restricción de motores fue superada por ADR 0015
- Fecha: 2026-10-08

## Contexto

El usuario adoptó la identidad pública Mark Scout / Mark y solicitó una evolución
hacia una experiencia similar a videojuego, manteniendo la aplicación existente.
En ese momento no autorizaba motores 3D; esa condición cambió posteriormente. La
RTX 5060 Laptop solo tiene 8 GB de VRAM y el LLM continúa siendo la prioridad.

## Decisión

- Cambiar identidad visible, nombre del asistente y hotkey PTT a Mark / `Ctrl+Alt+M`.
- Conservar por ahora nombres técnicos `JarvisLocal`, paquete `jarvis_local`, rutas,
  SQLite, ejecutable y namespaces; migrarlos requerirá una fase separada.
- Convertir los seis indicadores en módulos de información respaldados por una API
  autenticada y de solo lectura que expone exclusivamente configuración curada.
- Permitir editar solo calidad visual, una preferencia local sin autoridad.
- Añadir modos Auto/Equilibrado/Eco y pausa al ocultarse. Auto reduce carga durante
  loading, transcripción y procesamiento.
- Mantener Canvas 2D/WebView2; no añadir Unity, Unreal, Godot ni otra aplicación.

## Consecuencias

El usuario ve una identidad coherente y puede explorar subsistemas reales sin que
la UI conceda permisos. Los nombres técnicos antiguos siguen visibles solo en
rutas, código y documentación de migración. El gobernador es preventivo por estado,
no telemetría real de GPU; DXGI/PDH queda pendiente. Una escena WebGL futura debe
ser opcional, empaquetada localmente y demostrar mediante benchmark que no afecta
materialmente a la inferencia.
