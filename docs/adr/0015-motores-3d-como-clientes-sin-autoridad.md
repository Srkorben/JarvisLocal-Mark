# ADR 0015: motores 3D como clientes sin autoridad

Fecha: 2026-10-08

## Contexto

El usuario autorizó instalar Unity, Unreal Engine y motores pertinentes, y pidió
integrarlos con Mark Scout. El núcleo existente ya tiene conversación, memoria,
política, auditoría y una aplicación WPF/WebView2. Ningún motor gráfico debe crear
un segundo asistente ni convertirse en una ruta para ejecutar acciones.

## Decisión

- El núcleo Python continúa siendo la única fuente de estado y autoridad.
- Los motores 3D se integran inicialmente como **clientes de presentación**.
- El primer cliente real usa Godot 4.7.2 y consulta únicamente presencia efímera
  mediante HTTP loopback con token aleatorio heredado temporalmente por entorno.
- El token no se guarda en el proyecto del motor ni se imprime en logs. Godot
  recibe la ruta fija del endpoint protegido por ACL y valida que sea loopback.
- El catálogo cerrado del centro de control inicia y detiene el cliente Godot.
- Unity y Unreal se evalúan con proyectos equivalentes; ninguno recibirá acceso a
  herramientas, memoria completa, política ni configuración de seguridad.
- El shell WPF/WebView2 sigue siendo la experiencia principal hasta comparar
  consumo, integración, distribución y recuperación en la máquina objetivo.

## Consecuencias

Godot permite validar hoy una escena 3D conectada sin migración del producto. Un
fallo del render no detiene el núcleo. Ejecutar un editor 3D al mismo tiempo que
Qwen3 puede presionar los 8 GB de VRAM; por ello los prototipos no arrancan
automáticamente y deben cerrarse antes de cargas LLM/VLM exigentes.
