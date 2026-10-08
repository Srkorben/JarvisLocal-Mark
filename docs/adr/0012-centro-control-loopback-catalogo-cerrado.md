# ADR 0012: centro de control loopback con catálogo cerrado

Estado: aceptada — 2026-10-08

JarvisLocal tenía nueve accesos directos válidos que conservaban parámetros y
dependencias, pero fragmentaban la operación y permitían iniciar instancias
incompatibles. Se requiere un único acceso y una interfaz web local sin añadir un
framework, servicio externo ni superficie de shell arbitrario.

Se implementa `jarvis_local.control_center` con la biblioteca estándar de Python:
`ThreadingHTTPServer` enlazado exclusivamente a `127.0.0.1`, `ProcessManager` y un
catálogo inmutable de nueve `ToolSpec`. La API selecciona identificadores; no
acepta ejecutables, rutas, argumentos, entorno o comandos. Los procesos se crean
con `shell=False`, conservan los scripts originales y usan grupos de exclusión.

El acceso inicia el servidor bajo demanda y reutiliza una instancia saludable.
Un bloqueo de archivo evita carreras; el servidor elige el primer puerto libre de
8765–8774 y escribe su endpoint con ACL de la cuenta. La primera URL intercambia
un token aleatorio por cookie HttpOnly/SameSite; POST exige además Origin, Host y
CSRF. CSP impide recursos externos y framing. Los logs excluyen queries/cookies.

Se descartan un servidor expuesto en LAN, una API de comandos genérica, Docker y
un framework web adicional. El centro no se instala como servicio de Windows y
no sustituye el futuro icono de bandeja de Fase 5. Explorer puede delegar en un
proceso existente, por lo que solo se garantiza la solicitud de apertura.
