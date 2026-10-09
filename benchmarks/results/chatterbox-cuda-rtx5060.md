# Benchmark: Chatterbox CUDA + Qwen3-8B

Fecha: 2026-10-09. Prueba local, offline y reproducida con la referencia de voz
consentida. Chatterbox se cargó y primó antes de `llama-server`.

| Métrica | Resultado |
|---|---:|
| GPU / VRAM | RTX 5060 Laptop / 8.151 MiB |
| PyTorch / arquitectura | 2.9.1+cu128 / sm_120 |
| carga + priming TTS | 21,739 s |
| carga posterior del LLM | 12,423 s |
| TTFT del LLM | 0,515 s |
| velocidad del LLM en este perfil | 10,11 tokens/s |
| síntesis | 5,681 s |
| audio producido | 4,4 s |
| VRAM global base / TTS / TTS+LLM | 1.565 / 5.268 / 7.533 MiB |

Una validación física posterior produjo 3,28 s de audio en 3,562 s y lo reprodujo
por WASAPI en 3,594 s, sin error de salida.

La síntesis CPU observada anteriormente fue 42–54 s por frase. En una prueba con
el orden incorrecto (LLM antes de TTS), WDDM paginó memoria y la síntesis tardó
77,509 s. Por eso el orden de reserva de VRAM forma parte de la arquitectura.

Las cifras no son garantías: `nvidia-smi` informa uso global bajo WDDM y la carga
de escritorio, temperatura y perfil de energía afectan el resultado. El JSON
adyacente conserva los valores de la corrida.
