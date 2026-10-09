# Aplicación gráfica de escritorio

Estado: **Desktop Alpha implementada y validada en Windows 11**.

## Experiencia principal

`JarvisLocal.exe` es la base técnica de la aplicación **Mark Scout**. Abre una ventana WPF sin consola,
aloja la interfaz local mediante WebView2 y arranca o reutiliza el mismo centro de
control Python. La CLI continúa disponible exclusivamente para diagnóstico,
recuperación y desarrollo.

La escena usa un fondo procedural, cuadrícula en perspectiva, partículas, anillos
y ondas que cambian con la máquina de estados de voz:

`OFFLINE → LOADING → IDLE → RECORDING → TRANSCRIBING → PROCESSING → SPEAKING`

También representa `CANCELLING` y `ERROR`. Durante la respuesta se muestran la
transcripción y el texto generado. Este estado es efímero: no se guarda audio ni
se crea un segundo historial.

## Ejecutar

Desde el Escritorio, abre `Mark Scout.lnk`. El acceso apunta a:

```text
C:\Users\andcb\Documents\AI Local\JarvisLocal\runtime\desktop\JarvisLocal.exe
```

Si la aplicación ya está abierta, un segundo inicio activa la ventana existente.
Dentro de ella, pulsa **Iniciar voz** y espera **En espera**. Mantén
`Ctrl+Alt+M` para hablar y suelta para enviar. `Ctrl+Alt+Pause` cancela el turno.

El panel **Sistemas** conserva las funciones consolidadas de diagnóstico,
enrolamiento, preparación de modelos, configuración y apertura del proyecto.
Las acciones de instalación o enrolamiento siguen requiriendo confirmación local.
En **Enrolar mi voz** se puede grabar una muestra propia o importar un archivo
autorizado de 15–30 segundos. La importación es completamente loopback, valida y
normaliza el audio, conserva un respaldo de la referencia anterior y no reentrena
el modelo.
La entrada **Presencia 3D experimental** abre el cliente Godot opcional conectado
al mismo estado efímero; el panel conserva propiedad directa del proceso para
impedir duplicados y poder detenerlo.

Los seis indicadores laterales son módulos seleccionables: **Interfaz,
Autoridad, Audio, Modelo, Memoria y Seguridad**. Presentan únicamente datos reales
de configuración y estado, con límites explícitos. El único ajuste visual actual
es Auto/Equilibrado/Eco; se conserva en el perfil local del WebView2 y nunca
modifica permisos ni políticas.

## Compilar y publicar

Requiere .NET SDK 8 y Microsoft Edge WebView2 Runtime. El paquete WebView2 se fija
en el proyecto .NET; el runtime ya forma parte de la instalación normal de Windows
11/Edge, pero se comprueba en la máquina objetivo.

```powershell
Set-Location 'C:\Users\andcb\Documents\AI Local\JarvisLocal'
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\Publish-Desktop.ps1
```

La publicación es `win-x64`, dependiente del runtime de .NET 8 instalado. Se
eligieron varios archivos en `runtime\desktop` en lugar de prometer un binario
monolítico: WebView2 necesita sus ensamblados y cargador nativo. Todo ese directorio
es regenerable e ignorado por Git.

## Límites actuales

- La escena es una interfaz procedural acelerada por el navegador embebido; no es
  todavía un motor 3D como Unity o Unreal.
- Las ondas reaccionan al estado de conversación, no a amplitud PCM en tiempo real.
- No hay avatar, wake word, bandeja del sistema ni inicio automático con Windows.
- Integraciones con APIs, Pinokio o agentes futuros deberán entrar como adaptadores
  y herramientas tipadas; la interfaz no expone ejecución arbitraria.
- Cerrar la ventana detiene el centro de control y los procesos que este inició.

## Seguridad

WebView2 solo puede navegar al puerto loopback seleccionado. Ventanas emergentes,
permisos web, DevTools, menús contextuales y navegación externa están desactivados.
El panel conserva token aleatorio, cookie HttpOnly/SameSite, CSRF, CSP y catálogo
cerrado. La telemetría visual de voz acepta exclusivamente estado, transcripción,
respuesta y error acotados; no acepta campos de permisos o política.
