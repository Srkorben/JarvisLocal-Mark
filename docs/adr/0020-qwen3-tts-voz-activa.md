# ADR 0020: Qwen3-TTS Base como voz activa

Estado: aceptada — 2026-10-12.

El usuario rechazó Piper, Chatterbox y XTTS-v2 por timbre robotizado o
interferencias en la ruta integrada. Una comparación audible con la misma
referencia autorizada aprobó `Qwen/Qwen3-TTS-12Hz-0.6B-Base` 0.6B. Se adopta
Qwen3-TTS como proveedor activo sin cambiar el contrato `TTSProvider`.

El modelo vive en `.venv-qwen3-tts`, se fija en la revisión
`5d83992436eae1d760afd27aff78a71d676296fc` y se ejecuta en un worker JSONL
local, sin puertos ni descargas durante la sesión. La referencia, su
transcripción explícita y el manifiesto SHA-256 se validan antes de cargarlo.
Cancelar termina el worker. Piper, Chatterbox y XTTS permanecen como fallbacks,
no como selecciones activas.

La decisión favorece semejanza y claridad sobre velocidad. En esta RTX 5060
Laptop, sin FlashAttention 2, una prueba integrada reciente necesitó 23,656
segundos de síntesis para 7,812 segundos de audio. Esto no cumple aún el objetivo
de conversación fluida. El backend oficial queda como implementación correcta y
reproducible; cualquier acelerador futuro deberá demostrar equivalencia acústica,
cancelación, modo offline y compatibilidad con la reserva de VRAM del LLM antes
de sustituirlo.

Las respuestas se sintetizan como una unidad prosódica y la semilla se fija en
42. Después de reproducir una toma robótica con los defaults oficiales, se
adopta el perfil conservador aprobado auditivamente: temperatura `0.65`, top-k
`30` y top-p `0.9` tanto para talker como subtalker. La salida PCM de 24 kHz pasa
sin remuestreo propio a WASAPI compartido con
conversión nativa de Windows. Esta ruta evita que la aplicación introduzca una
transformación distinta de la usada al aprobar los previews. La calidad final
continúa requiriendo comprobación humana multivuelta: las métricas de señal no
sustituyen esa aceptación.

Qwen3-TTS ocupa aproximadamente 3,3 GiB de VRAM. La autorización para usar CUDA
sigue siendo configuración local explícita y no concede al modelo ninguna
autoridad sobre herramientas o políticas. La primera carga debe mostrarse como
`Inicializando`, nunca como disponibilidad inmediata.
