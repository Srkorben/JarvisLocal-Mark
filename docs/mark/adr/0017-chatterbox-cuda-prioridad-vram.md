# ADR 0017: prioridad de VRAM para Chatterbox en conversación por voz

Fecha: 2026-10-09  
Estado: aceptada

## Contexto

Chatterbox Multilingual LatAm en CPU tardó 42–54 segundos por frase en turnos
reales. La RTX 5060 Laptop es Blackwell (`sm_120`) y el PyTorch 2.6 CPU fijado por
el paquete upstream no podía usarla. Chatterbox y Qwen3-8B tampoco caben con
offload completo simultáneo en 8 GB de VRAM.

## Decisión

- Conservar el entorno CPU sin modificar y crear `.venv-chatterbox-cuda`.
- Usar PyTorch/torchaudio 2.9.1+cu128, cuyo wheel se comprobó con `sm_120`.
- Mantener Chatterbox y PerTh en commits fijados, instalados sin permitir que el
  metadato upstream reemplace el wheel CUDA.
- Cargar y hacer una inferencia de calentamiento de Chatterbox antes de iniciar
  `llama-server`; después, el offload adaptativo de llama.cpp usa la VRAM libre.
- Mantener STT en CPU INT8. GPU, CPU o proveedor no alteran política ni permisos.

## Evidencia

Con voz primero y ambos modelos residentes: 21,739 s de carga+priming de voz,
12,423 s de carga LLM, TTFT 0,515 s, 10,11 tokens/s y 5,681 s de síntesis para
4,4 s de audio. VRAM global: 1.565 → 5.268 → 7.533 MiB. La misma voz en CPU había
tardado 42–54 s por frase. Cargar el LLM primero causó paginación WDDM y 77,509 s
de síntesis en una prueba, por lo que ese orden queda prohibido en la CLI de voz.

## Consecuencias

El arranque de voz tarda unos 22–35 s y el LLM dispone de menos capas GPU durante
esa sesión. El chat de texto conserva su perfil rápido original. El rendimiento
varía con aplicaciones gráficas, temperatura y energía; si falta VRAM, Mark debe
fallar de forma visible, no matar aplicaciones del usuario ni cambiar permisos.
