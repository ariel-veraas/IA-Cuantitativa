# Validación de la alfa 0.1

Fecha: 19 de septiembre de 2026.

## Ejecutado

- **34 pruebas automatizadas aprobadas** con Python 3.12 en Linux. Comando: `python -m unittest discover -s tests -v`.
- Lectura de TXT, DOCX con tabla y PDF sintético con página sin texto; límites de selección y referencias.
- Reglas literales y numéricas, valores contradictorios, unidades equivocadas, rúbricas inválidas y criterios obligatorios pendientes.
- Rechazo de citas inventadas, identificadores incorrectos, conclusiones sin evidencia y respuestas con formato inválido.
- Flujo HTTP de la aplicación: documento de ejemplo, rúbrica, trabajo, resultado 70–100 y exportación.
- Conexión HTTP real dentro del equipo a un **servidor que simula un modelo**. Comprueba el contrato de llama.cpp y el flujo hasta el resultado, no la calidad de inferencia.
- Gemini con transporte simulado: conteo, reserva, liquidación, timeout, bloqueo por discrepancia y reservas concurrentes. Ninguna llamada a una API paga.
- Persistencia, recuperación de trabajos, checkpoints, cancelación y bloqueo de una segunda instancia sobre los mismos datos.
- Validación de Host/Origin/sesión y rechazo de destinos externos o redirecciones para el adaptador local.
- Sintaxis JavaScript de la aplicación y del script de navegador; validación del paquete de la skill.
- Ejecución del diagnóstico de hardware y comprobación de la ayuda del benchmark. El diagnóstico describe este entorno de desarrollo, no la computadora del usuario.

## Pendiente, expresamente

- **Navegador real y revisión visual.** La instalación de Chromium se intentó, pero sus descargas agotaron el tiempo de espera. La suite `tests/browser.cjs` queda preparada; no se declara aprobada. Las pruebas HTTP no ejecutan JavaScript ni verifican presentación visual.
- Inferencia con pesos reales, latencia, calidad, consumo de RAM/VRAM y compatibilidad con la GPU del usuario.
- Integración autenticada con Gemini y verificación de modelos/tarifas disponibles para la cuenta real.
- Ejecución de lanzadores en Windows, pruebas en macOS y empaquetado como instalador autónomo.
- Archivos reales variados, documentos adversariales y OCR. Esta alfa no está aislada para procesar archivos no confiables.

## Qué demuestran las pruebas

La lógica y los contratos del primer flujo funcionan en las condiciones cubiertas. No demuestran que un modelo chico alcance todavía la calidad de una persona junior, que responda en un tiempo específico o que exista un ahorro determinado frente a una API. Esas hipótesis necesitan mediciones sobre el equipo y los documentos del laboratorio.

El código incluye el benchmark local para obtener las primeras mediciones. La siguiente decisión técnica debe usar esos resultados.
