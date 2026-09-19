# Verificación de la entrega integrada

Fecha: 19 de septiembre de 2026.

## Resultados observados

- 49 pruebas Python aprobadas: `python -m unittest discover -s tests -v`. Cubren reglas, extracción, contratos, citas, presupuestos concurrentes, recuperación, aislamiento de instancia, rutas HTTP, capacidades versionadas y protección de claves.
- Tres pruebas Go aprobadas: `go -C desktop test ./...`. Cubren extracción, rechazo de traversal y rechazo de URL externa para recuperar una instancia.
- Ocho recorridos completos aprobados con Chromium 153, Playwright y Ollama 0.34.2 ejecutando Qwen3 4B real: saludo sin inferencia; pregunta sobre archivo con cita; exportación; redacción sin archivos; crear/probar/activar capacidad; documentos y actividad; respaldo; vista móvil sin desbordamiento. Sin errores JavaScript ni diálogos inesperados. Capturas desktop/móvil revisadas.
- Lanzador compilado para Linux probado de extremo a extremo con el Python privado existente: extracción del payload, importaciones en modo aislado, inicio, sesión, conversación, persistencia y cierre del proceso.
- Descarga real del ZIP Python para Windows (34.324.622 bytes): SHA-256 esperado verificado y `python.exe` presente en la raíz. No se ejecutó ese binario.
- Ejecutable Windows AMD64 generado por compilación cruzada con Go 1.27.1. Formato PE32+ GUI comprobado; no equivale a una ejecución nativa.
- Las llamadas Gemini y fallos de transporte se verificaron con transportes simulados. No se consumió una API paga.

Los guiones `tests/product_browser.cjs` y `tests/run_product_browser.py` documentan el entorno de navegador/modelo usado. El segundo es un arnés del entorno de desarrollo, con rutas a sus descargas; no es un instalador para el usuario.

## Inferencia real y latencia

En Linux, aproximadamente 15,6 GiB RAM, nueve CPU lógicas y sin GPU, una consulta documental tardó 27,52 s incluyendo 14,13 s de carga; la siguiente, 12,995 s con el modelo residente. En el recorrido final de navegador, una respuesta documental breve se registró en aproximadamente 15,8 s. Son observaciones de pocos ejemplos, no una distribución estadística ni un benchmark de la computadora destino.

Las primeras pruebas detectaron que Qwen alteraba el texto de citas y el validador rechazaba la respuesta. Se cambió el contrato conversacional para pedir IDs y anexar las citas desde la fuente original. Las pruebas finales pasaron con ese contrato. Esto verifica integridad de referencias, no corrección semántica universal.

## Sin verificación en este entorno

- Inicio nativo del EXE en Windows, descarga e instalación automática completas en Windows y compatibilidad con la GPU destino. La máquina de pruebas disponible es Linux; el EXE no tiene firma de editor.
- Integración autenticada contra una cuenta real de Gemini y sus condiciones de facturación.
- Calidad comparable a una persona junior en una distribución real de tareas empresariales, ahorro porcentual, latencia garantizada o pico de VRAM.
- Uso compartido empresarial, OCR, conectores y ejecución de acciones externas: no implementados y no presentados como aprobados.

La entrega contiene una aplicación integrada y un ejecutable construido. Las verificaciones disponibles no permiten certificar un producto final de producción para Windows ni cerrar las hipótesis de rendimiento empresarial.
