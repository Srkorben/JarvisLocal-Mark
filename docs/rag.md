# Memoria local y RAG

## Límites de confianza

Solo se indexa la raíz del proyecto activo, que antes debe estar bajo una raíz
autorizada. Se excluyen componentes configurados como `.git`, `.venv*`,
`*.egg-info`, `.pytest_cache`, `data`, `models`, `runtime`, `node_modules` y
`benchmarks`, además de la denylist global.
No se siguen symlinks ni junctions. No existe exploración automática del disco.

El texto recuperado siempre lleva `trust=untrusted_document_content`. Los patrones
de instrucciones sospechosas agregan `potential_prompt_injection`, pero el
marcado no sustituye la regla principal: ningún documento tiene autoridad. Las
herramientas, permisos y confirmaciones siguen fuera del modelo.

## Tipos de memoria

- **Trabajo:** pares clave/valor ligados a una sesión y proyecto; se eliminan de
  forma explícita y nunca cruzan proyectos.
- **Episódica:** acciones de Jarvis, resultados resumidos, decisiones confirmadas,
  resúmenes explícitos de sesión y pendientes confirmados.
- **Decisiones temporales:** cadenas confirmadas por tema y proyecto, con versión
  vigente/anterior, motivo, intervalo de validez y procedencia. No se extraen
  automáticamente de documentos o conversaciones.
- **Documental:** fuentes, fragmentos, hashes, sección/página, fecha e índice.
- **Perfil:** preferencias explícitas del usuario; visibles, editables y
  eliminables. La API rechaza escrituras inferidas.

No se implementan keylogging, capturas continuas ni observación silenciosa.

## Indexación y consulta

Formatos iniciales: UTF-8 TXT, Markdown por encabezados y PDF con capa de texto.
No hay OCR para PDFs escaneados. El índice es incremental por SHA-256: conserva
documentos sin cambios, reemplaza de forma transaccional los modificados y elimina
fuentes obsoletas. Los embeddings se guardan como vectores `float32`.

```powershell
# Registrar y activar un proyecto autorizado
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --register-project 'Proyecto X' --project-path 'C:\Proyectos\X'
.\.venv\Scripts\python.exe -m jarvis_local.cli --activate-project PROJECT_ID

# Crear/actualizar el índice y consultar evidencia
.\.venv\Scripts\python.exe -m jarvis_local.cli --index-project
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --rag-query '¿Cuál fue la última decisión de arquitectura?' --rag-mode hybrid

# Memoria episódica y perfil explícitos
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --record-decision 'Usar SQLite.' `
  --decision-topic 'Base de datos principal' `
  --decision-reason 'El proyecto es local y de un solo usuario.'
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --decision-history 'Base de datos principal'
# Solicitud explícita: elimina toda la cadena, no reactiva versiones anteriores
.\.venv\Scripts\python.exe -m jarvis_local.cli `
  --forget-decision 'Base de datos principal'
.\.venv\Scripts\python.exe -m jarvis_local.cli --record-pending 'Revisar el índice.'
.\.venv\Scripts\python.exe -m jarvis_local.cli --record-session-summary 'Se validó RAG.'
.\.venv\Scripts\python.exe -m jarvis_local.cli --profile-set 'idioma=es-CO'
.\.venv\Scripts\python.exe -m jarvis_local.cli --profile-list
```

Cada evidencia devuelve ruta absoluta y relativa, sección o página, hash de la
fuente, modificación, puntuaciones y una cita estable del tipo
`docs/architecture.md#Persistencia`. Si no hay evidencia suficiente, la respuesta
lo declara. Una cita prueba procedencia, no que el contenido sea verdadero.

## Escala y rendimiento

SQLite FTS5 y coseno exacto simplifican copias, aislamiento y auditoría. El límite
actual es 20.000 fragmentos semánticos por proyecto. Al superarlo la consulta
falla de forma explícita y obliga a evaluar un índice ANN; Qdrant no es una
dependencia oculta ni obligatoria.

El benchmark se ejecuta con:

```powershell
.\.venv\Scripts\python.exe -m jarvis_local.rag_benchmark
```

Consulta [el resultado validado](../benchmarks/results/rag-qwen3-embedding-0.6b-q8_0.md).

