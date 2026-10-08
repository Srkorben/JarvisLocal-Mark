# Dependencias y artefactos

Comprobado el 2026-10-07. Los modelos de fases futuras no se han descargado.

## Python

| Componente | Versión/rango | Uso | Licencia/nota |
|---|---:|---|---|
| Python | 3.12.10 x64 | núcleo | CPython oficial |
| SQLite | 3.49.1 | persistencia y FTS5 | incluido con Python |
| Pydantic | 2.13.5 (`>=2.13.4,<3`) | validación y JSON Schema | MIT |
| HTTPX | 0.28.1 (`>=0.28.1,<1`) | HTTP async y streaming cancelable | BSD-3-Clause |
| pypdf | 6.19.0 (`>=6.19.0,<7`) | extracción de PDF con texto | BSD-3-Clause |
| pytest | 9.1.1 (`>=9.1.1,<10`) | pruebas de desarrollo | MIT, Python 3.12 |

No se añadió un framework de agentes: el bucle, los contratos y la frontera de
autoridad permanecen explícitos y auditables.

Fase 4 no añadió paquetes: archivos/procesos usan la biblioteca estándar y APIs
Win32; Git es un ejecutable local detectado e invocado mediante argumentos fijos.

## llama.cpp

- versión: `0.6.0-dev`, build `11459`, commit `f498f864f`;
- artefacto Windows x64 CUDA 12.4 oficial de
  [releases de llama.cpp](https://github.com/ggml-org/llama.cpp/releases);
- ruta local: `runtime\llama.cpp-b11459-cuda12.4` (ignorada por Git);
- SHA-256 del ZIP binario:
  `FFA28270EE78E5E4F2113DEE51C3AEAD3EAD400987B67B11C76887469C82F588`;
- SHA-256 del ZIP CUDA runtime:
  `8C79A9B226DE4B3CACFD1F83D24F962D0773BE79F1E7B75C6AF4DED7E32AE1D6`;
- licencia: MIT;
- GPU detectada: RTX 5060 Laptop, compute capability 12.0, 8151 MiB.

La [documentación oficial del servidor](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
describe `/health`, streaming y la API OpenAI-compatible. JarvisLocal fija host
`127.0.0.1`, desactiva UI, no habilita herramientas internas y usa un comando
cerrado. El build queda fijado para reproducibilidad; actualizarlo requiere volver
a ejecutar suite, smoke tests y benchmark.

## Modelo seleccionado

- repositorio oficial: [Qwen/Qwen3-8B-GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF);
- revisión verificada: `86e51c53be47cd9d82e0acb3ca6b4faedb51171d`;
- archivo: `Qwen3-8B-Q4_K_M.gguf`;
- formato/cuantización: GGUF / Q4_K_M;
- tamaño: 5.027.783.488 bytes;
- SHA-256: `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`;
- licencia: Apache-2.0;
- ruta local: `models\Qwen3-8B-Q4_K_M.gguf` (ignorada por Git);
- configuración: 8192 tokens, no-thinking, un slot, GPU auto, reserva 1024 MiB.

Solo se descargó esta variante grande. La selección y alternativas están en
[model-selection.md](model-selection.md), y las medidas reales en
[el benchmark](../benchmarks/results/qwen3-8b-q4_k_m-ctx8192.md).

## Proveedor alternativo

Ollama 0.40 permanece instalado y soportado como backend de desarrollo. No es
dependencia arquitectónica ni se inicia desde JarvisLocal. Sus modelos existentes
no se descargaron de nuevo y no forman parte del benchmark de aceptación.

## Modelo de embeddings

- repositorio oficial: [Qwen/Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF);
- revisión verificada: `370f27d7550e0def9b39c1f16d3fbaa13aa67728`;
- archivo único descargado: `Qwen3-Embedding-0.6B-Q8_0.gguf`;
- formato/cuantización: GGUF / Q8_0;
- tamaño: 639.150.592 bytes;
- SHA-256: `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`;
- licencia: Apache-2.0;
- dimensiones: 1024; el modelo publicado admite contexto de hasta 32K;
- configuración JarvisLocal: contexto 2048, pooling `last`, CPU (`gpu_layers=0`);
- ruta local: `models\Qwen3-Embedding-0.6B-Q8_0.gguf` (ignorada por Git).

Se descargó una sola cuantización. El servidor OpenAI-compatible usa
`/v1/embeddings` en `127.0.0.1:8081`; el mismo build fijado de llama.cpp sirve el
modelo. La selección está registrada en ADR 0007 y el resultado real en
[el benchmark RAG](../benchmarks/results/rag-qwen3-embedding-0.6b-q8_0.md).

## Índice vectorial

Qdrant se evaluó, pero no es dependencia de esta fase: SQLite FTS5 más coseno
exacto cubre la escala inicial con menos procesos y una frontera transaccional
simple. `sqlite-vec` tampoco se incorporó todavía. ADR 0006 fija el límite de
20.000 vectores y la condición para reevaluar un índice ANN.

## Fases posteriores

Whisper small/medium INT8, Piper español, Silero VAD, openWakeWord y un VLM se
evaluarán solo al entrar en su fase. Qdrant se reevaluará únicamente si la escala
lo justifica. No se descargarán múltiples variantes grandes «por si acaso».
