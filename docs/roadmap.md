# Hoja de ruta

Cada fase exige pruebas y documentación antes de ampliar autoridad. Dificultad:
baja, media, alta o experimental.

| Fase | Objetivo y componentes | Herramientas previstas | Dificultad / riesgos | Resultado de salida |
|---|---|---|---|---|
| 0 — Esqueleto seguro | contratos, config, SQLite, proyectos, política, auditoría, cancelación, presupuestos y simulador | Python 3.12, asyncio, Pydantic, SQLite | media; una frontera defectuosa compromete todo | acciones evaluables sin operaciones peligrosas; **completa** |
| 1 — Texto local | servidor de modelo, streaming, historial y tool-calling estricto | llama.cpp/llama-server, Qwen3-8B GGUF Q4_K_M | media; VRAM, schema y cancelación | chat local cancelable y medido; **completa** |
| 2 — Voz PTT | WASAPI, VAD, STT/TTS sustituibles, hotkey y corte de audio | sounddevice, Silero integrado, faster-whisper, Chatterbox/Piper | media-alta; drivers, calidad y latencia | **infraestructura completa; aceptación de voz propia pendiente** |
| 3 — Memoria/RAG | proyectos, indexador, FTS5, vectores, citas y diario semántico | SQLite FTS5, Qwen3-Embedding-0.6B; ANN solo si escala | alta; mezcla de proyectos e inyección | respuestas con evidencia trazable; **completa** |
| 4 — Herramientas deterministas | 10 herramientas de búsqueda, apertura, Git y archivos | APIs Python/Win32, Git, ShellExecute | media; TOCTOU y rollback | operaciones verificadas sin mouse; **completa con escritura deny-by-default** |
| 5 — Acceso permanente | bandeja, inicio opcional, PTT, wake word, indicadores y emergencia | .NET/WinUI o tray local, openWakeWord | media-alta; privacidad del micrófono | disponibilidad visible en segundo plano |
| 6 — Automatización estructurada | broker, pipe, DOM/UIA y verificador para 1–2 apps | .NET 8, named pipes, FlaUI/UIA3, Playwright | alta; foco, DPI, diálogos | flujos conocidos con ≥95 % de éxito |
| 7 — Visión/multietapa | captura, OCR, VLM bajo demanda y bucle observar-actuar | Windows.Graphics.Capture, PaddleOCR, Qwen3-VL-4B | experimental; grounding y VRAM | respaldo visual estrictamente limitado |
| 8 — Endurecimiento | rollback, cifrado, aislamiento, métricas, adversarial/concurrencia | DPAPI/Credential Manager, ACL/AppContainer | alta y continua | uso cotidiano controlado |

## Puerta antes de visión

Fase 7 no será una dependencia seria hasta cumplir simultáneamente:

- 20–30 herramientas deterministas probadas;
- unas 100 órdenes de voz representativas;
- RAG con fuentes verificables;
- ninguna acción sensible fuera del broker;
- al menos 95 % de éxito en flujos seleccionados;
- cancelación probada durante TTS, escritura y movimiento;
- recuperación controlada ante fallos.

## Estado de transición

Las Fases 0, 1, 3 y 4 están cerradas. La Fase 2 tiene pipeline, hardware, tests y
turno E2E validados; el usuario rechazó Piper y se instaló Chatterbox LatAm
aislado. Falta enrolar/evaluar su muestra antes de cerrar la aceptación. Fase 4 quedó validada con suite completa,
smoke test de archivos/Git y tool call real del LLM. Escritura, apertura y
ejecución permanecen denegadas por proyecto hasta habilitación explícita. La
evaluación de CORE sólo añadió decisiones temporales en SQLite; tareas, reglas,
MCP y eventos continúan diferidos. La prioridad inmediata es enrolar y validar la
voz propia para cerrar Fase 2; no se autoriza browser, UIA, broker o visión.

## Clasificación de expectativas

**Estable hoy:** LLM/STT/TTS offline, PTT, wake word, RAG explícito, APIs de
archivos, DOM, UIA, permisos, listas y auditoría.

**Viable pero frágil:** full-duplex, grounding visual, UI personalizada, tareas
largas, recuperación de diálogos inesperados, voz clonada de baja latencia y
coexistencia permanente de modelos grandes en 8 GB.

**No realista prometer:** autonomía ilimitada, memoria perfecta, fiabilidad humana
en cualquier interfaz, paridad constante con los mejores modelos cloud, control de
UAC/pantalla bloqueada o cero acciones equivocadas.
