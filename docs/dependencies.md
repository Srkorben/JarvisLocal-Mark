# Dependencias y artefactos

Comprobado el 2026-10-08.

## Python

| Componente | Versión/rango | Uso | Licencia/nota |
|---|---:|---|---|
| Python | 3.12.10 x64 | núcleo | CPython oficial |
| SQLite | 3.49.1 | persistencia y FTS5 | incluido con Python |
| Pydantic | 2.13.5 (`>=2.13.4,<3`) | validación y JSON Schema | MIT |
| HTTPX | 0.28.1 (`>=0.28.1,<1`) | HTTP async y streaming cancelable | BSD-3-Clause |
| pypdf | 6.19.0 (`>=6.19.0,<7`) | extracción de PDF con texto | BSD-3-Clause |
| pytest | 9.1.1 (`>=9.1.1,<10`) | pruebas de desarrollo | MIT, Python 3.12 |
| sounddevice | 0.5.6 | PortAudio/WASAPI compartido | MIT |
| faster-whisper | 1.2.1 | STT local CPU INT8 | MIT |
| piper-tts | 1.8.0 | TTS de respaldo | GPL-3.0-or-later; voces por separado |

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

## Audio local

### STT

- `Systran/faster-whisper-small`, revisión
  `536b0662742c02347bc0e980a01041f333bce120`;
- tamaño local total: 486.217.556 bytes;
- `model.bin` SHA-256:
  `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`;
- CPU INT8, español y Silero VAD incluido por faster-whisper.

### Piper de respaldo

- OHF-Voice `piper1-gpl`, motor 1.8.0, GPL-3.0-or-later;
- `es_MX-ald-medium.onnx`, 63.201.294 bytes, SHA-256
  `019b3803293c93e34a206dd2e53a3889209a514e786fd7144f7b70196c579b63`;
- configuración SHA-256
  `5a71498158e04afc8099bfd019c7e87c68eb9d042505a2b1a87e5c1ac2b1a61d`;
- el usuario rechazó su timbre: queda como fallback técnico y fixture.

### Chatterbox para voz propia

- entorno separado `.venv-chatterbox`, no dependencia del core;
- código commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2`, MIT;
- dependencia PerTh fijada en commit
  `ff1c8ac55a976971245cdd53c18d6131ca00d993`;
- base HF revisión `5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`;
- pack LatAm revisión `27e595bf2fe7be0533ca299d9afafcde08b7cca7`, MIT;
- `ve.pt` 5.698.626 bytes, SHA-256
  `4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1`;
- `s3gen.pt` 1.057.165.844 bytes, SHA-256
  `9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3`;
- tokenizer 69.989 bytes, SHA-256
  `69632f47220a788a52ce2661d096453c5655e9bf25289d89a8d832c46ee07dbf`;
- `t3_es_mx_latam.safetensors` 2.143.990.280 bytes, SHA-256
  `c66c4517f11c2b35a56e28615c0689deb864cbc411e329552223bbd0a6a063f8`;
- `spacy_ontonotes` fijado con SHA-256 oficial
  `b216e7f92de7ae285aeab8feba2faa8ea8216e5995ff6fb3d391cc8356db1bfe`;
- PyTorch 2.6.0 CPU y NumPy 1.26.4 aislados;
- worker cargado offline; semejanza pendiente de la muestra del usuario.

### Normalización de referencias importadas

- WAV PCM se normaliza con biblioteca estándar + NumPy del entorno de audio;
- FFmpeg Essentials 8.1.1 local procesa MP3, M4A, FLAC, OGG, OPUS, AAC y WMA;
- FFmpeg se invoca con argumentos fijos, sin shell, red ni plugins del navegador;
- si FFmpeg no existe, WAV continúa disponible y los demás formatos fallan cerrado.

Fuentes primarias: [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Piper OHF](https://github.com/OHF-Voice/piper1-gpl),
[Chatterbox](https://github.com/resemble-ai/chatterbox) y
[modelo LatAm](https://huggingface.co/ResembleAI/Chatterbox-Multilingual-es-mx-latam).

## Aplicación de escritorio

- .NET SDK/runtime 8 para compilar y ejecutar el shell WPF `win-x64`;
- `Microsoft.Web.WebView2` 1.0.4258.31, licencia Microsoft;
- Microsoft Edge WebView2 Runtime instalado localmente (154.0.4258.62 durante la
  validación de esta máquina);
- Godot 4.7.2 está instalado por WinGet para el prototipo de presencia 3D;
- Unity Hub 3.22.2, Unity Editor 6000.3.26f1 y Epic Games Launcher 20.3.3 están
  instalados; Unreal Editor no está instalado;
- los editores Unity/Unreal no son dependencias de ejecución del núcleo.

La escena principal usa Canvas 2D del WebView2 ya presente. Godot es opcional y
se ejecuta como cliente; si no está instalado, conversación, políticas y tools
siguen funcionando. Cualquier renderer futuro deberá degradarse sin afectar el
número de tokens/s ni la seguridad.

La publicación es dependiente del runtime y se genera en `runtime/desktop`, que
queda fuera de Git. El frontend no carga fuentes, scripts ni recursos remotos.

## Fases posteriores

openWakeWord y un VLM se evaluarán solo al entrar en sus fases. Qdrant se
reevaluará únicamente si la escala lo justifica. No se descargarán múltiples
variantes grandes «por si acaso».
