# Benchmarks

El benchmark de Fase 1 inicia el `llama-server` configurado, mide carga, VRAM/RAM,
TTFT y velocidad, ejecuta tres prompts en español, tres casos de tool calling y
una cancelación durante generación con comprobación posterior de salud.

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.benchmark
```

Los resultados JSON y Markdown incluyen el hash del modelo y quedan en `results/`.
El resultado validado actual es
[`results/qwen3-8b-q4_k_m-ctx8192.md`](results/qwen3-8b-q4_k_m-ctx8192.md).
Las pruebas son pequeñas y reproducibles; no pretenden sustituir una evaluación
extensa ni comparar modelos con metodologías diferentes.

El benchmark de Fase 3 crea una base temporal, indexa cuatro documentos de
`fixtures/rag`, ejecuta recuperación léxica, semántica e híbrida y comprueba la
fuente, el texto esperado y la señal de prompt injection. También registra hash y
tamaño del GGUF, latencias, RAM, una aproximación global de VRAM, tamaño SQLite y
validez de auditoría.

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.rag_benchmark
```

Resultado validado:
[`results/rag-qwen3-embedding-0.6b-q8_0.md`](results/rag-qwen3-embedding-0.6b-q8_0.md).
Las cuatro preguntas evitan depender del LLM generativo: evalúan recuperación y
trazabilidad de forma determinista. No miden calidad universal ni escalabilidad.
