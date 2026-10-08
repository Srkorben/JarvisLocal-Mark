# Selección del modelo de Fase 1

Decisión tomada el 2026-10-07 para RTX 5060 Laptop de 8 GB. Se priorizó español,
seguimiento de instrucciones, tool calling estructurado, artefacto trazable,
latencia y margen de VRAM. La evaluación documental precedió a cualquier descarga;
solo se descargó el ganador.

## Candidatos

| Candidato | Ventaja | Riesgo para esta fase | Decisión |
|---|---|---|---|
| Qwen3-8B Q4_K_M | GGUF oficial, Apache-2.0, llama.cpp documentado, multilingüe y orientado a agentes | generación anterior a Qwen3.5 | **seleccionado** |
| Qwen3.5-9B | familia más reciente y muy capaz en instrucciones/herramientas | mayor presión en 8 GB; distribución oficial evaluada es multimodal/safetensors y no se fijó un GGUF oficial equivalente | pospuesto |
| Qwen3.5-4B | más margen y latencia menor | menor capacidad para planificación y selección fina de argumentos | posible perfil ligero futuro |
| Gemma 4 E4B | modelo moderno, multilingüe y function calling nativo | arquitectura y plantillas recientes, términos Gemma y sin aceptación previa en el build fijado | reevaluar, no descargar |

Fuentes primarias: [Qwen3 y capacidades](https://github.com/QwenLM/Qwen3),
[GGUF oficial de Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B-GGUF),
[Qwen3.5-9B oficial](https://huggingface.co/Qwen/Qwen3.5-9B) y
[Gemma 4](https://ai.google.dev/gemma/docs/core.md). La documentación de Gemma
recuerda además que el modelo produce la llamada pero la aplicación debe validarla
y ejecutarla con salvaguardas; es el mismo principio usado por JarvisLocal.

## Razón de la elección

Qwen3-8B era la combinación con menor incertidumbre operacional: peso oficial
Q4_K_M de 5,03 GB, licencia permisiva, soporte directo en llama.cpp y suficiente
margen para contexto de 8K en la GPU objetivo. Qwen3 admite modo thinking/no-thinking
y su familia declara capacidades multilingües y agentic/tool use. El artefacto se
fijó por revisión y SHA-256, evitando depender de una cuantización comunitaria.

El modelo no se convierte en dependencia del núcleo: `ModelProvider` permite
cambiarlo por configuración. Esta decisión solo fija el perfil validado inicial.

## Resultado empírico

En el conjunto pequeño reproducible:

- conversación en español: tres respuestas coherentes y obediencia al formato;
- tool calling: 3/3 herramientas correctas con argumentos JSON válidos;
- TTFT mediano: 0,688 s;
- velocidad mediana: 54,85 tokens/s;
- carga: 5,563 s;
- consumo incremental aproximado: 5681 MiB de VRAM;
- cancelación: 0,094 s, servidor saludable después.

Tres casos no demuestran fiabilidad general. Antes de herramientas sensibles se
requiere un corpus mayor con falsos positivos, ambigüedad, español coloquial,
argumentos de ruta y ataques de prompt injection.

## Offload

Forzar 99 capas con VRAM previamente ocupada provocó paginación WDDM y 3–5
tokens/s. Se usa `gpu_layers = "auto"` con `--fit on --fit-target 1024`: en un
estado normal cargó el modelo casi por completo y alcanzó el rendimiento anterior;
con presión de VRAM puede reducir offload en vez de degradar catastróficamente.
