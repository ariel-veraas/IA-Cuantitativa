# IA Cuantitativa

Asistente local para trabajar con documentos, redactar, calcular y aplicar procedimientos reutilizables. Incluye una aplicación de escritorio que abre su interfaz en el navegador del mismo equipo. Gemini es opcional y está desactivado inicialmente.

## Abrir en Windows

1. Descomprimí `IA-Cuantitativa-Windows.zip` y abrí `IA-Cuantitativa.exe`.
2. El primer inicio descarga y verifica un entorno Python privado. No necesitás instalar Python ni usar una terminal.
3. En la aplicación, elegí el perfil del motor local y pulsá **Preparar y empezar**. Se descargan Ollama y el modelo. La pantalla muestra el progreso y permite pausar y reintentar.
4. Cuando indique que el motor está listo, escribí tu pedido o adjuntá un archivo.

El paquete está dirigido a Windows 10 22H2 o posterior, de 64 bits, arquitectura Intel/AMD. Reservá al menos 12 GB de disco libre; el perfil equilibrado requiere aproximadamente 4,1 GB de descargas iniciales entre motor y modelo. Necesitás Internet para esa preparación. Después, las funciones locales pueden trabajar sin conexión. Si usás una GPU NVIDIA, mantené actualizado su controlador; Ollama exige 551.61 o posterior. [Requisitos oficiales](https://docs.ollama.com/windows).

El perfil equilibrado utiliza Qwen3 4B; el liviano, Qwen3 1.7B. La app detecta si tu equipo tiene una placa de video y te recomienda el perfil liviano si no la tiene: medido en hardware real, el perfil liviano responde en unos 3 segundos con placa de video o sin ella, mientras que el equilibrado pasa de ser casi instantáneo (con placa de video) a unos 8 segundos (sin ella) — y bastante más en pedidos que requieren razonar. El motor conserva un modelo cargado y procesa un pedido por vez. El tamaño del modelo no garantiza la calidad de sus respuestas. Los saludos y los cálculos compatibles se resuelven directamente con código.

Para cerrar el proceso y liberar el motor administrado, usá **Salir de la aplicación**. Cerrar solamente la pestaña no cierra el asistente. Volver a abrir el ejecutable recupera la instancia en ejecución.

## Trabajar

- **Conversar:** preguntas, resúmenes, clasificación y redacción. Adjuntá hasta cuatro documentos por pedido. Las respuestas documentales incluyen fragmentos de fuente para revisar.
- **Documentos:** importar TXT, Markdown, PDF con texto, DOCX, CSV y XLSX; también pegar texto. Los originales no se modifican. Se guarda el texto extraído, no una copia del archivo original.
- **Capacidades:** definir instrucciones y un ejemplo con resultado esperado, probarlo con el modelo y activar la versión revisada. Podés volver a activar una versión anterior que haya pasado su prueba. Estas capacidades son instrucciones controladas, no código ejecutable ni entrenamiento de pesos.
- **Evaluar criterios:** rúbricas con reglas literales y numéricas, interpretación local y asistencia externa opcional; resultados y fuentes exportables.
- **Actividad:** revisar trabajos, duración, uso comunicado por el motor y registro del costo externo. Podés descargar informes desde la conversación.

La recuperación selecciona fragmentos por relevancia (BM25, por palabra completa) y limita su tamaño. Si instalás además un modelo de embeddings en tu motor local (campo opcional en Configuración → Motor externo), la búsqueda también puede encontrar fragmentos relacionados por significado aunque no compartan las mismas palabras, con una sola llamada adicional por pedido. No garantiza encontrar toda la evidencia de un documento largo. Una cita existente no demuestra que la interpretación sea correcta.

Para pedidos que parecen necesitar comparar, justificar o encontrar contradicciones, el asistente activa razonamiento extendido en el modelo local antes de responder; para pedidos simples, sigue respondiendo directo. La respuesta indica cuándo se usó ("con razonamiento extendido"). Si el primer intento local no alcanza y hay más del documento sin usar, reconsidera una vez más con más contexto ("reconsiderado con más contexto") antes de pensar en ayuda externa. Las capacidades propias pueden marcarse como "solo tiene sentido con un documento adjunto": usarlas sin archivo se rechaza antes de llamar al modelo.

Cada respuesta de una capacidad propia puede marcarse como "👍 Buena" o "✎ Corregir" (indicando cuál debería haber sido la respuesta). Desde Capacidades, "Mejorar con ejemplos" junta esas correcciones reales y le pide al modelo local que proponga una versión mejorada de las instrucciones — que igual tiene que pasar su propia prueba antes de poder activarse. No es entrenamiento: es una versión más del mismo mecanismo de versionado, ahora asistido.

En Configuración podés habilitar "Permitir que busque en la web" (con Gemini): solo se usa cuando el pedido parece necesitar información actual y todo lo demás no alcanzó, y lo que encuentra se le devuelve al modelo local para que reconsidere antes de responder, no como respuesta directa. Está apagado por defecto porque cada búsqueda es una llamada paga adicional cuyo costo exacto (Google puede cobrar un cargo extra por búsqueda, además de los tokens) esta app no puede verificar automáticamente.

## Gemini opcional

En **Configuración**, ingresá la clave, elegí un modelo, verificá sus tarifas oficiales y fijá los topes por pedido y mensual. Cada pedido requiere además marcar **Permitir asistencia externa si hace falta**. El programa envía a Google el pedido, las instrucciones y el contexto seleccionado cuando necesita asistencia. Un archivo corto puede quedar incluido completo. No hay anonimización automática ni búsqueda web en esta entrega.

Antes de generar se cuentan tokens y se reserva presupuesto; si una conexión queda en estado incierto, se conserva la reserva y no se repite automáticamente esa llamada. El registro depende de las tarifas configuradas y no reemplaza los límites de facturación de Google ni contabiliza otros programas. La integración autenticada con una cuenta real de Gemini todavía no fue verificada. [Tarifas oficiales](https://ai.google.dev/gemini-api/docs/pricing).

## Integrarlo con otro programa

En **Configuración → Integraciones**, generá una clave (`iqk_...`) para que otro programa tuyo en esta misma computadora — un script, una automatización, un flujo en una herramienta como n8n — le mande pedidos al cerebro y reciba ya la decisión tomada (si lo resolvió solo o si hizo falta escalar), sin depender del token de sesión de la interfaz. El endpoint es `POST /api/integration/ask` con el header `X-IQ-Api-Key`; sigue restringido a esta computadora, no expone nada a la red.

`integrations/asistente_email.py` es un conector de referencia completo: lee correos nuevos por IMAP, le manda cada uno al cerebro, y arma un borrador de respuesta en la carpeta de Borradores del propio buzón — nunca envía nada automáticamente, siempre queda para que una persona lo revise y lo mande ella misma. Copiá `integrations/config.example.json` a `config.json`, completá tus datos y la clave de integración, y corré `python integrations/asistente_email.py --config integrations/config.json`. El mismo patrón (`ask_brain()` + nunca actuar sin revisión humana) sirve de plantilla para conectar WhatsApp, un sistema de tickets o un CRM.

## Datos y respaldo

En Windows, la aplicación, los modelos y los datos viven bajo `%LOCALAPPDATA%\IA-Cuantitativa`. El archivo de trabajo es `data\iq.sqlite3`. La clave de Gemini se guarda separada y cifrada con la protección del usuario de Windows; no se incluye en los respaldos.

**Descargar respaldo**, en Configuración, exporta una copia consistente de la base: conversaciones, texto extraído, capacidades y registros. Para restaurarla, cerrá la aplicación, conservá una copia de los datos actuales y reemplazá `data\iq.sqlite3` por el archivo del respaldo. No existe todavía un asistente de restauración. Los modelos pueden descargarse nuevamente. Eliminar un documento de la lista no borra automáticamente las citas conservadas en resultados anteriores.

## Alcance y comprobaciones

Se completaron 49 pruebas automatizadas de Python, tres del lanzador y ocho recorridos de navegador con un Qwen3 4B real, incluyendo documentos, citas, redacción, capacidades y respaldo. También se comprobó el arranque del paquete con el lanzador compilado para Linux y un entorno Python existente.

**El ejecutable Windows fue compilado, pero no ejecutado en Windows nativo.** No tiene firma de un editor. La preparación automática completa y el rendimiento con la GPU del equipo destino siguen sin verificación. No se declara esta entrega certificada para producción empresarial ni se promete una latencia o ahorro determinado. En este entorno sin GPU, dos consultas documentales anteriores tardaron aproximadamente 28 segundos con carga inicial y 13 segundos con el modelo ya cargado; no representan el rendimiento de una RTX 3060.

Es una aplicación individual que escucha solo en el equipo local. No incluye acceso compartido, roles empresariales, conectores Drive, OCR, agentes autónomos, ejecución de macros ni edición automática de archivos externos. Los lectores tienen límites de tamaño, pero no están aislados en una caja de seguridad para documentos hostiles. XLSX usa valores guardados y no recalcula fórmulas; DOCX omite encabezados y pies. PDF escaneado requiere extracción de texto por otra herramienta.

## Código y construcción

El paquete `IA-Cuantitativa-Codigo.zip` incluye el código, pruebas y un respaldo Git. Para desarrollo: Python 3.11 o superior, `python run.py`; el lector PDF ya está incluido. `requirements.txt` contiene dependencias para las pruebas. Los archivos `.bat` del código fuente son alternativas de desarrollo; no hacen falta para usar el ejecutable.

Para construir Windows, instalá Go y ejecutá `python desktop/build.py`. La compilación incorpora aplicación, lectores, capacidades y licencias en el ejecutable. Las versiones y hashes del entorno y motor están fijados en el código. El contrato y las verificaciones se detallan en `docs/`.
