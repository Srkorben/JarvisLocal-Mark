# ADR 0003: Ollama provisional, llama.cpp objetivo

Estado: sustituida por ADR 0004 y 0005 — 2026-10-07

Se reutiliza Ollama instalado para probar conversación y tool-calling sin descargar
otro modelo grande. La arquitectura objetivo sigue siendo `llama-server` porque
permite controlar artefacto GGUF, cuantización, contexto, offload, parámetros y
cancelación de streaming.

El adaptador de Ollama permanece opcional para desarrollo. `llama-server` y el
modelo objetivo ya fueron instalados y validados en Fase 1. Ninguno de los dos
proveedores puede configurarse fuera de `127.0.0.1`.
