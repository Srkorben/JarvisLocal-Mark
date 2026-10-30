# ADR 0005: llama.cpp gestionado y Qwen3-8B inicial

Estado: aceptada — 2026-10-07

El perfil validado usa llama.cpp b11459 CUDA 12.4 y el GGUF oficial
Qwen3-8B-Q4_K_M, contexto 8192, un slot y modo no-thinking. Se eligió por
trazabilidad, español/tool use, Apache-2.0 y ajuste real en 8 GB.

`llama-server` escucha solo en `127.0.0.1`, sin UI, tools integradas, MCP ni agent
mode. JarvisLocal puede iniciar/detectar el servidor y únicamente detiene el
proceso que creó. Streaming SSE permite cancelar cerrando la conexión.

El offload usa `auto` y reserva 1024 MiB mediante fit. Forzar todas las capas bajo
presión de VRAM produjo paginación severa; la adaptación prima estabilidad sobre
una cifra fija de capas. Cualquier cambio de build/modelo exige repetir suite y
benchmark y no modifica la arquitectura del proveedor.
