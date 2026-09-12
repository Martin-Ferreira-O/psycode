# Observaciones de los insumos — SCRUM-30

Revisión del 2026-09-12. Se leyeron los cinco archivos originales del repositorio: HANDOFF.md, API_CONTRACTS.md, docs/README.md, docs/matriz-lenguaje-ideacion-suicida.md y el contenido de las seis hojas de docs/Matriz-lenguaje-ideacion-suicida.xlsx. La lectura del Excel se efectuó sobre sus datos XML; no se efectuó una revisión visual de su formato. El archivo original no fue modificado.

## Diferencia entre Excel y transcripción

En la hoja **Gradiente clínico**, celda **A4**, el Excel no contiene valor. Esa fila corresponde a “Ideación suicida activa inespecífica”; la transcripción Markdown y el contrato inicial indican **2**.

La definición técnica conserva el nivel 2 ya presente en el handoff y contrato, dejando visible su procedencia. No se rellena el Excel ni se presenta el dato como una corrección aprobada por el cliente. La confirmación del insumo pertenece a la revisión clínica previa a producción.

## Interpretación para el equipo

- Las seis hojas son Gradiente clínico, Frases y lenguaje, Características NLP, Lenguaje profesional, Evidencia y fuentes, y Reglas de uso.
- El insumo cita C-SSRS y literatura; la agrupación 0–7 combina categorías de ideación y conducta en su propia organización. No atribuir automáticamente esa numeración a una escala oficial ni convertirla en diagnóstico.
- La hoja de prosodia describe evidencia preliminar/heterogénea y necesidad de validación externa. No demuestra que el tono por sí solo identifique ideación suicida.
- La conversión NULO/BAJO/MEDIO/ALTO es la propuesta operativa del contrato, pendiente de validación clínica, cultural y externa.
- No inventar frecuencias; conservar “No determinado” cuando corresponda. No incluir detalles operativos de métodos ni usar frases aisladas como diagnóstico.

Esta entrega no valida científicamente las referencias bibliográficas del cliente, no diseña un modelo predictivo y no cambia el contenido de los insumos. [Anexo clínico del contrato](../API_CONTRACTS.md#anexo-a--clasificación-del-insumo-clínico).

## Alcance y vacíos de asignación

El handoff excluye captura/transcripción y detección automática, aunque formen parte de la idea general. La API recibe conceptualmente datos ya clasificados mediante una interfaz interna; no se inventa un productor ni una ruta pública de ingesta.

SCRUM-36 necesita endpoints de agregación backend, pero su descripción es frontend y no tiene responsable. El diseño define el módulo y los contratos; la asignación de su implementación sigue pendiente. Los RF-xx se citan tal como aparecen en el handoff; no se inspeccionó el documento externo de requerimientos ni se modificó Jira.
