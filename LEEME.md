# IA Cuantitativa · Alfa 0.1

Una primera aplicación local para revisar documentos contra criterios, resolver las comprobaciones simples con código y reservar la interpretación para un modelo. Está pensada como base del laboratorio de IA para pymes, no como el producto empresarial terminado.

**Ya se puede ejecutar el circuito completo sin descargar modelos:** cargar un documento, elegir una rúbrica, evaluar reglas, consultar fuentes y exportar resultados. Para interpretar criterios hay un adaptador de llama.cpp. Gemini es opcional y viene desactivado.

## Probala primero con el ejemplo

### Windows

1. Descomprimí el paquete. Entrá en la carpeta `ia-cuantitativa`.
2. Necesitás **Python 3.11 o superior**, con el lanzador `py` disponible. Si no lo tenés, instalalo desde [python.org](https://www.python.org/downloads/windows/). Esta alfa todavía no incluye un instalador autónomo.
3. Abrí **`iniciar.bat`**. Se abrirá el navegador en `http://127.0.0.1:8765`.
4. Tocá **Probar con un ejemplo** y después **Iniciar evaluación**.
5. El resultado esperado es **70 puntos y 30 pendientes**, con tres reglas resueltas y un criterio que requiere interpretación. No hay una IA simulando inteligencia detrás del modo de reglas.

Para leer PDF digitales y DOCX, cerrá la app y ejecutá `instalar.bat` una vez. Descarga dos lectores y sus dependencias en un entorno separado. Luego volvé a abrir `iniciar.bat`. TXT, Markdown, texto pegado y el ejemplo no necesitan esos paquetes.

Dejá abierta la terminal mientras usás la aplicación. Para terminar, presioná Ctrl+C en esa terminal. Si el navegador no se abre, ingresá manualmente a la dirección anterior.

### Linux o macOS

Desde la carpeta del proyecto:

```sh
python3 run.py
```

Para habilitar los lectores opcionales:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

La implementación y las pruebas automatizadas se ejecutaron en Linux con Python 3.12. Los lanzadores de Windows y el funcionamiento en macOS requieren comprobación en esos sistemas.

## Qué podés hacer

| Función | Estado en esta alfa |
|---|---|
| TXT, Markdown y texto pegado | Disponibles sin paquetes adicionales |
| PDF con texto y DOCX | Disponibles con lectores opcionales |
| Presencia de una frase | Regla literal; no interpreta negaciones ni significado |
| Comparación numérica | Regla estricta `campo: número unidad`, con un máximo |
| Interpretación | Adaptador para un servidor local llama.cpp |
| Asistencia de Gemini | Adaptador experimental, desactivado por defecto |
| Rúbricas | Editor, importación y exportación JSON, hasta 15 criterios |
| Fuentes | Referencias a páginas o bloques y comprobación de citas |
| Historial | SQLite local, checkpoints, cancelación y reanudación |
| Informes | Exportación Markdown y registro completo JSON |
| Skills | Una skill incluida, versionada y cargada al ejecutar el trabajo |
| Diagnóstico | Informe local de hardware y comando de benchmark |

Los pesos se normalizan a 100. El rango de puntaje muestra qué queda pendiente; no significa probabilidad de que un proveedor cumpla. Un resultado de IA siempre se marca para revisión humana. Que una cita exista no demuestra que la interpretación sea correcta.

El modo de reglas puede encontrar `ISO 27001` dentro de `No contamos con ISO 27001`: comprueba **presencia literal**. Para verificar que existe una certificación, usá un criterio de interpretación y revisá su fuente. La ausencia de una frase se deja pendiente, no se convierte automáticamente en incumplimiento.

## Conectar un modelo local

La aplicación administra el flujo; **llama.cpp administra el modelo y la memoria de inferencia**. Se mantienen separados para no cargar pesos cada vez que llega una consulta.

1. Instalá una compilación de [llama.cpp](https://github.com/ggml-org/llama.cpp) apropiada para tu sistema y GPU.
2. Conseguí un modelo instruct en formato GGUF compatible, con licencia adecuada para tu uso. Un candidato para medir es Qwen3 de 4B parámetros cuantizado; la elección definitiva depende de tu RAM, VRAM y resultados. El paquete no incluye pesos ni garantiza una latencia determinada.
3. Iniciá `llama-server` y dejalo abierto. Ejemplo para CPU, reemplazando la ruta:

```sh
llama-server -m /ruta/al/modelo.gguf --alias local --host 127.0.0.1 --port 8080 -c 4096
```

En Windows usá el ejecutable `llama-server.exe` y una ruta entre comillas. Para GPU, usá una compilación con el backend apropiado y configurá las capas de GPU según la memoria disponible. No supongas que una GPU será más rápida si el modelo no cabe en memoria o hay descarga parcial de capas.

4. En la app, abrí **Configuración**, dejá la dirección `http://127.0.0.1:8080` y el alias `local`, marcá **Habilitar el modelo local** y guardá.
5. Volvé a evaluar el ejemplo usando **Reglas + modelo local**. La conclusión esperada del criterio de urgencias es que no están incluidas sin cargo, con una cita verificable; el modelo puede equivocarse.

El adaptador pide JSON con esquema y desactiva el razonamiento extendido mediante `enable_thinking: false`. Eso requiere una plantilla y un modelo compatibles. Si la respuesta se trunca o no valida, el criterio queda pendiente. El límite de caracteres del contexto no equivale a un límite de tokens: si el servidor informa desbordamiento, reducí `max_context_chars` o ajustá su contexto dentro de la memoria disponible.

Guardar la conexión no descarga, inicia ni comprueba la salud del motor. Las opciones guardadas desde la pantalla tienen prioridad sobre los campos locales de `config.json`.

## Medir en tu computadora

Sin enviar el diagnóstico a ningún servicio:

```sh
python -m iq.diagnostics
python -m iq.benchmark --url http://127.0.0.1:8080 --model local --repetitions 5 --output benchmark-local.json
```

En Windows también podés usar `py -3`; en Linux o macOS, `python3` o el Python del entorno virtual.

El benchmark realiza un saludo y cinco evaluaciones sintéticas. Registra duración total HTTP, consumo de tokens si el servidor lo informa, citas válidas y coincidencia con la respuesta esperada. La primera llamada no garantiza un arranque frío. No mide tiempo hasta el primer token ni el consumo pico de RAM/VRAM. Una sola tarea no permite elegir el mejor modelo: el siguiente paso es armar un conjunto de documentos reales y medir calidad, memoria y latencia.

El benchmark toma la dirección y el alias de sus argumentos o de `config.json`, no de los ajustes guardados en la interfaz. No usa Gemini.

## Gemini: configuración opcional de laboratorio

El ejemplo y los flujos locales funcionan con esta sección completamente apagada. Si querés probar asistencia externa:

1. Copiá `config.example.json` como `config.json`.
2. Verificá la disponibilidad del modelo y sus [tarifas actuales](https://ai.google.dev/gemini-api/docs/pricing). El adaptador de esta versión solo admite `gemini-2.5-flash` y `gemini-2.5-flash-lite`, con razonamiento desactivado. La integración no se probó contra una cuenta real y los modelos pueden cambiar o retirarse.
3. Configurá `cloud_enabled: true`, `gemini_model`, tarifas de entrada y salida por millón de tokens, `monthly_budget_usd`, `per_job_budget_usd` y `pricing_confirmed: true`. Los presupuestos y las tarifas deben ser positivos. No se incluyen precios supuestos.
4. Definí `GEMINI_API_KEY` como variable de entorno antes de iniciar la aplicación. No pongas la clave en archivos de código ni en la rúbrica.
5. Reiniciá la app. En cada trabajo, marcá explícitamente **Permitir Gemini para criterios pendientes**.

Ejemplos para establecer la variable en una terminal nueva, reemplazando el texto de muestra:

```powershell
# Windows PowerShell
$env:GEMINI_API_KEY="TU_CLAVE"
py -3 run.py
```

```sh
# Linux / macOS
export GEMINI_API_KEY='TU_CLAVE'
python3 run.py
```

Se envían a Google las instrucciones de la skill, el criterio y los fragmentos seleccionados. La selección es léxica; no hay todavía un buscador semántico ni anonimización automática. Un documento corto puede entrar completo en la selección. `countTokens` también recibe ese contenido. Esta versión no hace búsquedas web mediante Gemini.

Antes de la llamada generativa se cuentan tokens y se reserva presupuesto en SQLite, con margen de entrada y límite de salida. Se contabiliza el uso devuelto; si una conexión se corta, se conserva la reserva. No se repite automáticamente un intento generativo del mismo criterio y trabajo. Crear una nueva evaluación es un trabajo nuevo y puede generar gasto adicional.

Este control usa las tarifas que configuraste y solo registra llamadas de esta aplicación. **No impone un límite de facturación en la cuenta de Google.** No cubre precios desactualizados, otros clientes ni cambios del proveedor. Si el consumo calculado supera una reserva, la aplicación bloquea nuevas llamadas y requiere revisar el registro; todavía no hay conciliación desde la interfaz.

## Datos, privacidad y límites

- Se guardan texto extraído, referencias, hashes, rúbricas, resultados, configuración de los trabajos y consumo en `data/iq.sqlite3`. No se guarda una copia binaria del archivo original. La clave externa no se guarda en SQLite ni se manda a la interfaz.
- Cerrá la aplicación antes de copiar toda la carpeta `data` para hacer un respaldo. No subas esa carpeta a un repositorio: puede contener información de tus documentos. Podés usar otra carpeta con `--data-dir` o `IQ_DATA_DIR`.
- Se admite una instancia por carpeta de datos y un trabajo a la vez. Hay hasta diez trabajos activos en cola; la pantalla lista los últimos 50 trabajos y 100 documentos. No hay paginación ni borrado desde la interfaz todavía.
- Si se interrumpe una ejecución, los criterios terminados quedan guardados. Al reanudar no se repiten esos pasos. Cancelar no puede retirar una solicitud ya recibida por un proveedor ni deshacer su posible gasto.
- Límites: 8 MB por archivo, 200.000 caracteres extraídos, PDF de hasta 100 páginas, DOCX expandido hasta 40 MB. Estos límites no constituyen un aislamiento de los lectores: usá documentos confiables en este laboratorio.
- No hay OCR. Un PDF escaneado puede carecer de texto, y la disposición de tablas o columnas puede alterar su extracción. DOCX lee cuerpo y tablas, pero no encabezados, pies ni cuadros de texto. Se muestran advertencias cuando se detectan limitaciones.
- El servidor escucha únicamente en `127.0.0.1`. Tiene validación de Host, Origin y token de sesión, pero **no es un servidor de producción ni una plataforma multiusuario**. No lo publiques en Internet ni lo expongas a una red empresarial como está.
- No se ejecutan macros, comandos sugeridos por documentos ni herramientas elegidas libremente por un modelo. Las acciones disponibles las decide código de la aplicación.

## Desarrollar y comprobar

```sh
python -m unittest discover -s tests -v
```

Los lectores opcionales deben estar instalados para ejecutar las pruebas PDF/DOCX; si faltan, esas pruebas se omiten. La prueba del conector local levanta un servidor HTTP simulado. Las de Gemini usan respuestas simuladas y nunca consumen una API paga.

Para la prueba de navegador, instalá Playwright en un entorno de desarrollo, instalá su Chromium, iniciá la app con una carpeta de datos descartable y ejecutá `node tests/browser.cjs`. El navegador no es una dependencia del producto; se usa solamente para QA. Podés cambiar `IQ_TEST_URL` y guardar capturas con `IQ_SCREENSHOT_DIR`.

Consultá `docs/ARQUITECTURA.md` para la estructura y el alcance pendiente, y `docs/VALIDACION.md` para distinguir las pruebas ejecutadas de las que todavía faltan.

## Referencias técnicas

- [Servidor llama.cpp y contrato de chat](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
- [Gemini generateContent](https://ai.google.dev/api/generate-content), [countTokens](https://ai.google.dev/api/tokens) y [configuración de razonamiento](https://ai.google.dev/gemini-api/docs/thinking).
- [Extracción de texto en pypdf y sus límites](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
- [Servidor HTTP de Python y limitaciones para producción](https://docs.python.org/3/library/http.server.html).

Esta entrega es código fuente del laboratorio. Las dependencias, los modelos y sus licencias se administran por separado; no se asigna todavía una licencia pública de distribución al proyecto.
