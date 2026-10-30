# Evaluación de patrones de CORE

Fecha de revisión: 2026-10-08. Esta evaluación usa CORE como referencia de
producto y diseño; no instala CORE, no copia su código y no convierte sus
afirmaciones de benchmark en garantías para JarvisLocal.

## Matriz del repositorio

| Capacidad | Estado en JarvisLocal | Evidencia local | Conclusión |
|---|---|---|---|
| Vigencia, contradicción y procedencia de decisiones | **Implementada en este incremento** | `memory/models.py`, `memory/repository.py`; `test_temporal_decision_*` | Cadena SQLite por proyecto+tema con actual/anterior, `valid_from`, `valid_to`, motivo, fuente y `supersedes_id`. |
| Identidad y relaciones entre proyectos, documentos, decisiones, tareas y sesiones | **Parcial** | `database.py` (FK de proyectos, sesiones, documentos y decisiones); `test_working_memory_is_scoped_*`, `test_temporal_decisions_are_project_isolated_*` | Proyecto, sesión, documento y decisión tienen identidad explícita. No existe aún una entidad persistente de tarea ni un grafo genérico. |
| Diferenciar documentos, decisiones, perfil e inferencias | **Implementada** | `memory/models.py`, `rag/models.py`; `test_decisions_and_pending_tasks_require_confirmation`, `test_profile_accepts_only_explicit_*`, `test_prompt_injection_is_data_*` | Cada almacén tiene contrato propio; una inferencia o documento no se promueve automáticamente a decisión o preferencia. |
| Recuperación temporal, documental, relacional y de estado | **Parcial** | `rag/service.py`, `tools/builtin.py`; `test_hybrid_search_*`, `test_project_decision_tool_is_scoped_and_audited` | Hay híbrida documental, actividad por fecha y estado temporal por tema. Falta un router de intención y consulta relacional general. |
| Tareas persistentes: objetivo, plan, pasos, aprobación, estado, cancelación y recuperación | **Ausente** | `EpisodicKind.PENDING_TASK` y límites en `orchestrator.py`; pruebas de cancelación/presupuesto | Un pendiente no equivale a un agregado de tarea. Diseñarlo será una fase propia; no se añadió autonomía. |
| Reglas reutilizables por proyecto sin autoridad de seguridad | **Ausente/diferida** | `projects` conserva `config_json`; `policy.py` y `execution.py` son la autoridad | La configuración genérica no es un sistema de reglas. Si se añade, sus reglas serán contexto no confiable y nunca podrán ampliar permisos. |
| MCP y eventos con autorización local | **Ausente/diferida** | `model_providers/llama_server.py` deshabilita tools/MCP del servidor; ADR 0005 | La frontera de herramientas podría admitir adaptadores futuros, pero no hay conectores ni webhooks activos. |
| Neo4j/grafo universal e ingestión continua | **Innecesaria actualmente** | ADR 0006, `rag/repository.py`, límites de indexación autorizada | SQLite, FTS5 y relaciones tipadas cubren la escala actual con menos superficie de ataque. No se adopta vigilancia ni ingestión global. |

## Patrones útiles de CORE

CORE separa contenido original, entidades y afirmaciones, enlaza afirmaciones a
su episodio de origen, clasifica tipos de memoria y conserva contradicciones como
una cadena temporal. También diferencia recuperación temporal, de entidades y de
relaciones, y trata una tarea como unidad persistente con plan, estado, sesiones y
actividad.

Para JarvisLocal se adoptó únicamente el patrón que resolvía una carencia actual:
una decisión confirmada sustituye a la vigente del mismo tema, cierra su intervalo
y conserva su procedencia. No se hizo extracción automática de hechos, resolución
de entidades por LLM ni promoción de documentos a decisiones.

Patrones candidatos, pero no implementados ahora:

- router determinista de intención antes de recuperación;
- entidad persistente de tarea con plan aprobado y registro de actividad;
- reglas tipadas por proyecto, siempre subordinadas a política;
- adaptadores MCP tratados como herramientas remotas no confiables y sujetos a
  allowlists, confirmación y auditoría locales.

No se adoptan Neo4j, Docker, sincronización universal, webhooks proactivos ni una
memoria transversal entre proyectos. El aislamiento de JarvisLocal es una frontera
de seguridad, no sólo una etiqueta de búsqueda.

## Semántica temporal implementada

`temporal_decisions` usa una clave normalizada `(project_id, topic)` y permite una
sola fila `current`. Un cambio confirmado se realiza dentro de una transacción:
la fila anterior pasa a `superseded`, recibe `valid_to` y la nueva conserva
`supersedes_id`, `rationale` y una `DecisionSource` tipada.

- **¿Cuál es vigente?** La única fila `current` del proyecto y tema.
- **¿Cuál era anterior?** La primera fila sustituida de la misma cadena.
- **¿Cuándo y por qué cambió?** `valid_from`/`valid_to` y `rationale`.
- **¿Qué lo respalda?** `kind`, `reference`, cita y hash opcionales de la fuente.
- **Corrección:** es una nueva decisión explícitamente confirmada que sustituye a
  la anterior; nunca se sobrescribe el pasado.
- **Eliminación:** `forget_decision_topic` requiere solicitud explícita y borra
  toda la cadena del tema, sin reactivar una versión anterior. La auditoría de la
  CLI conserva que ocurrió el borrado y cuántas filas afectó, no el texto borrado.

SQLite ofrece eliminación lógica al nivel de consulta, pero copias de seguridad,
WAL, snapshots o sectores no reasignados podrían conservar bytes. Un borrado
forense garantizado queda fuera del alcance actual y debe documentarse al añadir
cifrado/retención en Fase 8.

## Seguridad y licencia

Los documentos, resultados MCP futuros y texto recuperado siguen siendo datos sin
autoridad. `get_project_decision` es sólo lectura, se limita al proyecto activo y
atraviesa `ActionExecutor`, permisos y auditoría. No existe una tool para escribir,
borrar o conceder permisos desde el LLM.

El repositorio CORE declara AGPLv3 con términos adicionales Commons Clause. Por
ello esta evaluación usa ideas arquitectónicas públicas, no código, esquemas ni
implementaciones copiadas.

## Decisión de roadmap

Esta fue una mejora incremental de memoria, no una nueva fase. La siguiente
prioridad continúa siendo la experiencia de **voz local semidúplex**. Tareas persistentes,
reglas, MCP y eventos permanecen diferidos y requerirán diseño y autorización
separados.
