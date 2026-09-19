# Arquitectura implementada

## Aplicación individual local

El lanzador Go incluye el código y los lectores dentro de un ZIP embebido. En Windows prepara un Python 3.13.15 privado, descargado de python.org y verificado por SHA-256, y arranca `run.py` en modo aislado. La interfaz abre en el navegador y el servidor se vincula únicamente a `127.0.0.1`, con puerto dinámico, comprobación de Host/Origin y token de sesión. No implementa identidad multiusuario ni sirve como host empresarial compartido.

SQLite persiste documentos extraídos, fragmentos, conversaciones, trabajos, capacidades versionadas y movimientos de presupuesto. Un bloqueo de instancia impide dos workers sobre la misma carpeta. Hay un worker y hasta diez trabajos activos en cola. Los checkpoints permiten conservar pasos terminados; un intento externo incierto no se repite automáticamente.

## Decisiones y herramientas

El router combina una capacidad elegida por la persona con selección por palabras y rutas deterministas. Saludos, agradecimientos, cálculos compatibles y comparación textual se resuelven por código. Un modelo pequeño interpreta, redacta y devuelve una respuesta JSON. No se confía en una autocalificación numérica de confianza: el estado `needs_help`, los errores de contrato y las reglas de validación determinan la abstención o asistencia externa permitida. Esto no constituye un detector infalible de errores.

La conversación selecciona hasta cuatro documentos, fragmentos por coincidencia léxica y una ventana acotada de historial. Pide `answer`, `needs_help` y referencias `segment_id`; el programa agrega el texto original. Las evaluaciones por rúbrica exigen además citas coincidentes y calculan puntajes con código. Ninguna salida del modelo ejecuta comandos.

El presupuesto local de selección se expresa en caracteres: no equivale al número exacto de tokens. Los idiomas, tablas o instrucciones extensas pueden reducir el contexto efectivo. No se implementaron embeddings ni compresión semántica aprendida. Una fuente seleccionada puede ser real y no sostener semánticamente la conclusión.

## Motor y memoria

El administrador descarga una versión fija de Ollama (0.34.2), verifica el SHA-256 publicado por GitHub, extrae rutas seguras y descarga Qwen3 mediante la API nativa. En Windows AMD64 la preparación se controla desde la interfaz. En otros sistemas el código de desarrollo necesita un Ollama existente.

El motor privado utiliza el puerto 11435, un directorio propio, nube de Ollama deshabilitada, un modelo cargado y una solicitud paralela. El perfil elige Qwen3 4B o 1.7B; contexto por defecto 4096 tokens, razonamiento extendido desactivado y permanencia de 30 minutos. Una preparación realiza calentamiento. Esto evita recargar pesos por cada consulta; no elimina los costos de inferencia ni garantiza que todo el modelo entre en VRAM.

El adaptador Ollama usa `/api/chat` con esquema JSON. El adaptador llama.cpp mantiene compatibilidad con `/v1/chat/completions`. La UI permite configurar un motor local existente sin usar el administrador.

## Capacidades

La capacidad de evaluación del repositorio tiene manifiesto, instrucciones y versión. Cada trabajo conserva su configuración. Las capacidades creadas desde la aplicación se versionan en SQLite con instrucciones, ejemplo y frase esperada. Una prueba local debe terminar correctamente y contener esa frase antes de habilitar la activación manual. Se conserva el historial y es posible reactivar una versión previamente probada. Esta comprobación detecta regresiones sencillas; no es una evaluación amplia de calidad.

No hay entrenamiento, modificación automática de permisos, instalación de plugins arbitrarios ni ejecución de código de capacidades. La evolución de una capacidad queda bajo control de la persona.

## Asistencia externa y gasto

Gemini requiere habilitación global, clave, tarifas verificadas, presupuestos y autorización en el pedido. El adaptador usa `countTokens` y `generateContent`, JSON estructurado y razonamiento desactivado para los modelos permitidos. El contexto seleccionado se envía también al conteo.

Las reservas usan enteros en microdólares y transacciones SQLite. Se liquidan con el uso comunicado; ante incertidumbre quedan retenidas. Una discrepancia bloquea llamadas posteriores. No hay conciliación de facturas ni límite impuesto a la cuenta de Google. El contenido no se anonimiza automáticamente y no se habilita búsqueda web.

En Windows la clave está protegida con DPAPI; fuera de Windows se guarda en un archivo privado con permisos 0600. Nunca se entrega a la interfaz ni al respaldo SQLite.

## Extracción y límites

TXT/Markdown, DOCX, CSV y XLSX usan lectores acotados; PDF usa pypdf incluido con licencia. Se rechazan archivos demasiado grandes y ZIP con rutas inseguras. No se ejecutan fórmulas ni macros. No hay OCR ni aislamiento del lector en un proceso de seguridad. Los originales no se almacenan ni modifican.

El backup utiliza la API de copia consistente de SQLite. La restauración se realiza con la aplicación cerrada; no tiene interfaz. El borrado de documentos no elimina automáticamente su contenido histórico en resultados. Las capacidades empresariales compartidas, conectores y políticas administradas no forman parte del alcance implementado.
