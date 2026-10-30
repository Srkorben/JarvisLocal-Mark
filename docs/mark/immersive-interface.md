# Evolución inmersiva de Mark Scout

Estado: primer incremento implementado y prototipo Godot 3D integrado.

## Diagnóstico actual

La aplicación ya dispone de un shell WPF `.exe`, WebView2, una escena procedural
Canvas/CSS, transiciones por estado, panel de herramientas, presencia de voz y un
core Python separado. La UI no contiene autoridad: conversa con el centro local
autenticado y este solo expone operaciones tipadas.

Capacidades implementadas en este incremento:

- identidad pública **Mark Scout**, nombre habitual **Mark**;
- seis módulos seleccionables: Interfaz, Autoridad, Audio, Modelo, Memoria y
  Seguridad;
- datos reales y curados de la configuración, con capacidades y límites visibles;
- calidad visual `Auto`, `Equilibrado` y `Eco`, persistida localmente;
- en `Auto`, inferencia/transcripción/carga reducen el canvas a 20 FPS, 28
  partículas y DPR 1; el resto usa 45 FPS, 72 partículas y DPR máximo 1,35;
- al ocultarse la ventana, el render procedural deja de dibujar;
- la funcionalidad sigue disponible aunque los efectos se reduzcan.

La ventana principal aún no tiene avatar, navegación espacial ni telemetría DXGI.
Existe una escena Godot opcional y autenticada para presencia 3D; la interfaz la
presenta expresamente como experimental.

## Conceptos que aparecían en pantalla

### Voz semidúplex

La expresión oída como «cebo semidúplex» era **voz semidúplex**. Significa que
usuario y asistente se turnan: Mark escucha durante una llamada o al pulsar el
control manual y, mientras reproduce su respuesta, no abre simultáneamente otro
canal de escucha. Reduce eco, activaciones involuntarias y complejidad. Full-duplex
y barge-in quedan pendientes.

La pantalla principal ofrece **Conversación** y **Pulsar para hablar**; el término
técnico y su límite aparecen dentro del módulo Audio.

### Política local

Es el conjunto de reglas ejecutado en este PC que recalcula riesgo, verifica
allowlists, permisos, rutas, presupuesto y confirmaciones. El LLM no puede
modificarlo. La pantalla ahora usa **Control de acciones**; el detalle técnico
permanece en Autoridad y Seguridad.

### WASAPI

La expresión oída como «WhatsAppi» era **WASAPI** (*Windows Audio Session API*),
la interfaz nativa de Windows usada para micrófono y altavoces en modo compartido.
No tiene relación con WhatsApp. El dispositivo real aparece dentro de Audio.

## Alternativas gráficas

| Alternativa | Integración | Calidad | Carga/base | Decisión actual |
|---|---|---|---|---|
| Canvas 2D/CSS actual | directa en WebView2 | muy buena para HUD, ondas y partículas | baja y regulable | **implementada** |
| WebGL/WebGPU local | misma ventana; recursos empaquetados | 3D real, shaders, postprocesado | media; requiere presupuesto estricto | siguiente prototipo razonable |
| Three.js/Babylon.js empaquetado | sobre WebGL/WebGPU | ecosistema 3D amplio | media y nueva dependencia JS | evaluar solo con una escena concreta |
| HelixToolkit/Direct3D en WPF | nativo .NET | 3D técnico | media; dos capas de render | alternativa, no necesaria ahora |
| Godot | cliente opcional integrado | escena 3D nativa y rápida de prototipar | media; proceso adicional | **prototipo funcional** |
| Unity/Unreal | proceso/proyecto adicional | experiencia de juego completa | alta en VRAM, tamaño y mantenimiento | instalación/evaluación autorizada |

WebView2 suele usar aceleración gráfica del sistema, pero Windows decide qué
adaptador emplear. Con una RTX 5060 Laptop de 8 GB no se debe asumir que la UI y
llama.cpp compartirán VRAM de forma favorable. Por ello la evolución recomendada
es mantener el render sustituible, medirlo y degradarlo antes de competir con el
modelo.

## Arquitectura de recursos recomendada

```text
Estado del core (loading / processing / speaking / hidden)
                    │
                    ▼
             VisualQualityGovernor
              ├─ FPS objetivo
              ├─ DPR/resolución
              ├─ partículas/efectos
              └─ pausa cuando no es visible
                    │
                    ▼
       Canvas actual / futuro renderer WebGL

LLM/embeddings mantienen su configuración de GPU y su reserva de VRAM.
La UI nunca decide permisos ni parámetros del modelo.
```

El gobernador actual es determinista y se basa en el estado del agente. Una
versión posterior podrá consumir telemetría nativa de solo lectura (DXGI/PDH,
memoria de GPU, temperatura y batería), con histéresis para evitar cambios
constantes. Esa telemetría no está implementada.

## Función de los seis módulos

- **Interfaz:** único módulo editable hoy; selecciona calidad visual. Expone
  Canvas 2D, detección de motores y el estado experimental de Godot.
- **Autoridad:** muestra riesgo autoaprobable, pasos, rondas y estado privilegiado.
  Es solo lectura para impedir que una página conceda permisos.
- **Audio:** dispositivos, STT, TTS, modos de llamada/PTT, VAD y límites semidúplex reales.
- **Modelo:** proveedor, modelo, contexto, temperatura, thinking y offload reales.
  La edición segura del TOML queda pendiente.
- **Memoria:** recuentos SQLite, embeddings y límites RAG, más separación y
  ausencia de vigilancia.
- **Seguridad:** allowlists, servicios remotos, automatización visual, auditoría y
  pendientes de endurecimiento.

## Integraciones que merecen superficie futura

No se añaden botones vacíos. Las siguientes entradas solo deben aparecer cuando
exista un adaptador probado:

1. **Proyectos y tareas:** proyecto activo, pendientes confirmados y sesiones.
2. **Proveedores/modelos:** salud, carga, VRAM y cambio controlado de proveedor.
3. **Conectores:** APIs o MCP con identidad, permisos, alcance y estado visibles.
4. **Pinokio/aplicaciones locales:** adaptadores de catálogo cerrado; nunca comandos
   libres ni descubrimiento que conceda autoridad automática.
5. **Agentes locales:** registro de capacidades y procedencia, sin heredar permisos
   del agente coordinador.

## Hoja de ruta visual

1. **I0 — completada:** identidad, seis módulos, claridad terminológica y calidad
   visual adaptativa sobre Canvas existente.
2. **I1 — medición:** telemetría CPU/RAM/GPU de solo lectura, benchmark de FPS,
   VRAM y TTFT con interfaz activa/inactiva; presupuesto de render explícito.
3. **I2 — profundidad 3D:** cliente Godot autenticado implementado; integración
   dentro de la ventana y comparación Unity/Unreal pendientes.
4. **I3 — selección de renderer:** comparar Canvas/WebGL/Godot/Unity/Unreal con
   una sola escena, suspendible y con límite de memoria.
5. **I4 — experiencia espacial:** avatar/objetos/escenas cuando exista dirección de
   arte y criterios de interacción medibles.

Puerta de avance: el renderer debe poder apagarse, conservar todos los controles,
no reducir la fiabilidad de voz y mantener una reserva de VRAM suficiente para el
LLM. La apariencia nunca prevalece sobre cancelación, política o trazabilidad.
