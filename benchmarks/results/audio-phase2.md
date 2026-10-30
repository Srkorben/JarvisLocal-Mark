# Benchmark de voz — Fase 2

Fecha UTC: 2026-10-08T16:13:42+00:00

## Configuración

- STT: `faster_whisper` / CPU `int8` / 486217556 bytes
- TTS: `piper` / `es-MX` / CPU / 63201294 bytes
- Carga STT/TTS: 1.859 / 3.594 s
- Entrada de calidad: audio Piper sintetizado; no representa el micrófono ni la voz real.

## Reconocimiento reproducible

- Casos no ambiguos: 5/5
- WER medio: 0.437
- Mediana de transcripción: 5.016 s

| Esperado | Transcripción | WER | STT |
|---|---|---:|---:|
| Jarvis, abre el proyecto JarvisLocal. | Farvis, abre el proyecto FarvisLocal. | 0.400 | 4.828 s |
| Busca el archivo README punto eme de. | Buscala www.chivorradme.md | 1.000 | 4.891 s |
| Consulta el estado de Git del proyecto. | Consulta en estado de shit del proyecto. | 0.286 | 5.016 s |
| ¿Cuál es la decisión vigente sobre SQLite? | ¿Cuál es la decisión vigente sobre SQLite? | 0.000 | 5.031 s |
| Busca documentos relacionados con Qwen tres y llama punto ce pe pe. | Busca documentos relacionados con Qwen3 y llama.cpp. | 0.500 | 6.360 s |

## Turno completo

- Resultado: `success`; aprobado: **True**
- Transcripción: Jarvis, consulta la hora local actual utilizando la herramienta apropiada.
- Herramienta auditada: `get_current_time` (1 evento)
- TTFT desde cierre de captura: 7.7040000000015425 s
- Primer audio generado: 10.829000000001543 s
- Transcripción: 4.735000000000582 s
- Duración total: 11.735000000000582 s
- Audio físico: False
- Auditoría válida: True

## Interrupción TTS

- Ejecutada sobre hardware: False
- Resultado: False
- Latencia: None s

## Smoke de voz propia Chatterbox

Ejecutado después del enrolamiento local consentido, sin reproducir ni persistir
el audio generado:

- backend: Chatterbox Multilingual V3 + pack oficial español LatAm;
- dispositivo: CPU, proceso aislado y modo completamente offline;
- texto: `Hola. En que puedo ayudarte?`;
- salida: 56.640 muestras PCM16 mono a 24 kHz (2,36 s), pico 5.467;
- tiempo desde arranque frío: 115,94 s;
- dispositivo WASAPI de salida abierto después con 0,1 s de PCM silencioso: OK.

El primer intento se interrumpió porque el PCM16 base64 superaba el límite
predeterminado de 64 KiB de `asyncio.StreamReader`. El canal JSONL ahora admite
hasta 32 MiB y rechaza audio decodificado mayor de 24 MiB; una prueba de regresión
usa una respuesta de 80.000 bytes. Esta medición valida transporte y síntesis, no
semejanza subjetiva ni latencia conversacional.

## Limitaciones

La calidad automática usa Piper→Whisper y solo sirve como regresión reproducible. La prueba física abre los dispositivos, pero una persona debe validar inteligibilidad, ruido ambiente y comodidad. faster-whisper comprueba la cancelación entre segmentos y al terminar la inferencia; CTranslate2 no garantiza cortar un kernel CPU ya iniciado.
