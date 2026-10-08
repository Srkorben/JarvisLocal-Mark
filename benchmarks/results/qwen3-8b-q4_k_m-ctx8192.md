# Benchmark de Fase 1

Fecha UTC: 2026-10-07T21:31:25+00:00

## Configuración

- Modelo: `Qwen3-8B-Q4_K_M.gguf`
- Formato/cuantización: GGUF / Q4_K_M
- Tamaño: 5027783488 bytes
- SHA-256: `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`
- Contexto: 8192 tokens
- Máximo de salida: 1024 tokens
- Offload solicitado: auto (reserva objetivo: 1024 MiB)
- llama.cpp: b11459 / f498f864f

## Rendimiento observado

- Carga hasta health-ready: 5.563 s
- VRAM aproximada antes/cargado/delta: 1472 / 7153 / 5681 MiB
- RAM del proceso (working set): 4895.73 MiB
- TTFT mediano: 0.688 s
- Velocidad mediana: 54.85 tokens/s

## Tool calling

Resultado: **3/3** casos.

- `get_current_time` → `get_current_time`: PASS
- `list_directory` → `list_directory`: PASS
- `search_files` → `search_files`: PASS

## Cancelación real

Resultado: **PASS**; latencia 0.094 s; servidor listo después: True.

## Conversación en español

### Caso 1

**Prompt:** Explica en español, en tres frases claras, por qué una copia de seguridad no sustituye al control de versiones.

**Respuesta:** Una copia de seguridad solo guarda una versión del archivo o proyecto en un momento dado, mientras que el control de versiones mantiene un historial completo de cambios. El control de versiones permite revertir a versiones anteriores o comparar cambios, algo que una copia de seguridad no ofrece. Por lo tanto, una copia de seguridad es una medida complementaria, no una sustituta, del control de versiones.

### Caso 2

**Prompt:** Un estudiante tiene 90 minutos para estudiar dos temas. Propón un plan breve y justifica la distribución del tiempo.

**Respuesta:** **Plan de estudio para 90 minutos:**

- **Tema 1: 45 minutos**
- **Tema 2: 45 minutos**

**Justificación:**

Dado que el estudiante tiene 90 minutos para estudiar dos temas, es más eficiente dividir el tiempo equitativamente entre ambos. Esto asegura que ambos temas reciban la misma atención y se evite la sobrecarga en uno de ellos. Además, estudiar cada tema durante 45 minutos permite una comprensión más profunda, ya que el tiempo suficiente para revisar conceptos clave, practicar ejercicios o tomar notas. Si se asignara más tiempo a un tema, podría resultar en un estudio superficial del otro.

### Caso 3

**Prompt:** Resume esta idea sin añadir datos: JarvisLocal debe priorizar seguridad, trazabilidad y control del usuario sobre autonomía.

**Respuesta:** JarvisLocal debe priorizar seguridad, trazabilidad y control del usuario sobre la autonomía.
