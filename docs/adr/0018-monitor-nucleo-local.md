# ADR 0018 — Monitor local del núcleo con caché y estado compuesto

Fecha: 2026-10-10
Estado: aceptada

## Contexto

El centro de control ya administraba los runtimes de texto y voz, pero la UI no
tenía una vista segura y uniforme del estado del núcleo ni del consumo de recursos.
Consultar `nvidia-smi` en cada refresco sería costoso y exponer listas de procesos
o rutas internas introduciría datos innecesarios en la superficie HTTP.

También se comprobó que `HTTPServer` podía reutilizar un puerto en Windows. Dos
árboles de trabajo distintos podían aparentar que poseían el mismo endpoint, lo
que volvía no determinista qué versión recibía una petición.

## Decisión

- Componer el estado operativo a partir de `ProcessManager` y la presencia efímera
  existente; no se abre ningún modelo para medirlo.
- Obtener CPU y RAM con contadores nativos del sistema y consultar la GPU NVIDIA
  mediante `nvidia-smi`, con timeout de 800 ms.
- Almacenar únicamente las lecturas de hardware durante dos segundos. Los estados
  de runtimes y presencia se recalculan en cada solicitud.
- Exponer `GET /api/system` mediante la autenticación por cookie existente,
  cabeceras `no-store` y un esquema que no contiene PID, comandos, credenciales ni
  rutas privadas.
- Aplicar la precedencia `error > cancelling > processing > initializing >
  available > off`, para impedir que «Listo» o «Disponible» oculten una carga en
  curso.
- En Windows, exigir propiedad exclusiva del puerto mediante
  `SO_EXCLUSIVEADDRUSE`; el fallback cerrado 8766–8774 sigue disponible.

## Consecuencias

El panel puede mostrar datos reales con bajo coste y estados explícitos de
indisponibilidad. La GPU no NVIDIA o la ausencia de `nvidia-smi` no rompen el
servidor. La telemetría es local y deliberadamente limitada. La validación final
en WPF/WebView2 sigue siendo necesaria antes de instalar esta rama en el árbol
principal del propietario.
