# Decisión de arquitectura

Para la primera versión de memoria documental se decidió almacenar los vectores
en SQLite como BLOB float32 y ejecutar una búsqueda coseno exacta. Qdrant no será
una dependencia obligatoria mientras el proyecto permanezca por debajo de veinte
mil fragmentos.

