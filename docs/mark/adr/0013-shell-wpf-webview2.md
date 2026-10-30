# ADR 0013: shell WPF con WebView2 para la experiencia de escritorio

- Estado: aceptada
- Fecha: 2026-10-08

## Contexto

El pipeline de voz funcionaba desde PowerShell, pero una consola no es una
experiencia adecuada para un asistente visual persistente. Ya existía un centro
web loopback seguro y probado. Reescribir conversación, memoria, política y tools
dentro de otro framework crearía dos asistentes y dos fronteras de seguridad.

## Decisión

Crear un ejecutable `WinExe` en .NET 8/WPF que aloje el panel existente con
Microsoft Edge WebView2. El shell:

- inicia o reutiliza el servidor Python exclusivamente en `127.0.0.1`;
- no muestra consola y mantiene una sola instancia mediante mutex por usuario;
- restringe WebView2 al origen loopback exacto y deniega permisos/popups;
- detiene el servidor y sus procesos propiedad al cerrar;
- conserva al core Python como única implementación de conversación y autoridad.

El panel publica una escena procedural Canvas/CSS y consume solo presencia efímera
de voz. La comunicación visual no puede modificar políticas, permisos o allowlists.

## Consecuencias

Se obtiene un `.exe` sin ventana de PowerShell, una experiencia gráfica sustituible
y un punto de entrada estable para futuras vistas. Se agrega una dependencia de
compilación en .NET 8 y `Microsoft.Web.WebView2` 1.0.4258.31, además del WebView2
Runtime instalado en Windows.

No se adopta Unity/Unreal en este incremento: elevaría notablemente tamaño,
complejidad y superficie de actualización antes de validar la interacción. El shell
permite cambiar posteriormente solo la capa de render sin alterar el core seguro.

La CLI no se elimina; queda como ruta de diagnóstico y recuperación, no como la
interfaz principal del usuario.
