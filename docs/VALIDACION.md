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

## Addendum: auditoría independiente y cambios de esta sesión

Fecha: 19 de septiembre de 2026 (misma fecha del sistema; sesión posterior a la entrega descripta arriba). Lo que sigue fue hecho por un agente Claude Code, **no** por Codex/ChatGPT, ejecutando directamente en Windows nativo (no en la máquina Linux descripta arriba). Se documenta separado del resto de este archivo para no mezclarlo con lo que Codex declaró haber probado.

**Verificado ejecutando, en este Windows, sin GPU y sin Ollama instalado:**
- Hash SHA-256 del ZIP de código entregado (`73f3b684bdddee9c22592b8be790764a28f81b72e05360225455273cefa6d953`) coincide exactamente con el declarado.
- Historial de `historial.bundle` contiene el commit `d680016` declarado, con el mensaje y autor esperados.
- Las 49 pruebas Python originales pasan tal cual, incluyendo las 2 que quedan silenciosamente salteadas si no se instalan `pypdf`/`python-docx` vía pip (el runtime empaquetado sí las trae vendorizadas; `tests/` no agrega `vendor/` al `sys.path`, a diferencia de `run.py`).
- El servidor real (`python run.py`) arranca, sirve la interfaz y responde correctamente por HTTP y en un navegador real: saludo y calculadora sin inferencia (0 s), demo de rúbrica con reglas, subida de documentos, activación de capacidades con su compuerta de prueba, defensa CSRF/Host.
- `python-3.13.15-amd64.zip` (el runtime privado que descarga el lanzador Go) existe en python.org, pesa exactamente los 34.324.622 bytes declarados, su SHA-256 coincide con la constante embebida en el binario, y contiene `python.exe` en la raíz junto con `_sqlite3.pyd`/`_ssl.pyd` y la biblioteca estándar completa.
- El `.exe` de `IA-Cuantitativa-Windows.zip` es un PE32+ AMD64 real (no solo "se compiló"); las cadenas de texto embebidas (URL de python.org, HTML/JS de arranque) coinciden literalmente con `desktop/main.go`.

**No verificado en esta sesión** (pendiente de una decisión explícita del usuario antes de gastar tiempo/disco/ancho de banda en eso): arranque del `.exe` compilado en sí mismo, descarga real de Ollama + Qwen3 (~4,1 GB) y una respuesta de razonamiento generada por un modelo real en vez de un transporte simulado.

**Cambios de código de esta sesión** (motivados por una brecha real entre el producto entregado y el objetivo original del usuario: una IA local que *razone* de forma adaptativa y no solo por coincidencia de palabras clave):
- Razonamiento adaptativo real en el motor local (`domain.estimate_complexity`, `providers.LocalProvider.generate/evaluate`, nuevos `reasoning_max_output_tokens`): antes `think`/`enable_thinking` era `False` siempre y en todos los casos; ahora se activa heurísticamente según el pedido (o el criterio, en evaluación por rúbrica), con presupuesto de salida acotado.
- Recuperación por BM25 con coincidencia de palabra completa en `documents.py`, reemplazando el conteo de subcadenas anterior (que podía contar "cat" dentro de "categoria" como una coincidencia).
- Reordenamiento semántico opcional por embeddings (`LocalProvider.embed`, `Config.embedding_model`), con una sola llamada por lotes cuando está configurado; sin configurar, cero llamadas adicionales.
- Contrato mínimo de capacidades (`requires_documents`), verificado en cada uso real antes de llamar al modelo.
- Enrutamiento por palabras clave ampliado (más sinónimos para resumir/clasificar/redactar), documentado explícitamente como heurística y no como comprensión de lenguaje natural, para no repetir la confusión que señaló el usuario.
- 14 pruebas automatizadas nuevas (63 en total) cubriendo cada punto anterior, incluyendo dos pruebas de integración HTTP de punta a punta con un modelo simulado que confirman que un pedido complejo activa `enable_thinking:true` con el presupuesto de razonamiento, y que uno simple lo mantiene en `false` con el presupuesto normal — sin romper ninguna de las 49 pruebas previas.
- Interfaz actualizada para mostrar cuándo se usó razonamiento extendido, declarar el contrato de una capacidad y configurar un modelo de embeddings opcional; verificado interactuando con la interfaz real en un navegador (no solo leyendo el código).

## Addendum 2: verificación nativa en Windows con GPU real (misma sesión, más tarde)

El equipo donde corrió esta sesión resultó tener una **NVIDIA GeForce RTX 3060 de 12 GB** — la misma GPU de prueba mencionada por el usuario — y acceso a Internet, así que se completaron las verificaciones que antes quedaban pendientes de autorización:

- **Go 1.27.1 instalado** (zip oficial de go.dev, SHA-256 verificado) y usado para correr **las 3 pruebas Go declaradas: las tres pasan** (`TestUnzipRejectsTraversal`, `TestUnzipPreservesFiles`, `TestExistingRejectsExternalAddress`). Antes de esto nadie en esta auditoría las había ejecutado.
- **El ejecutable se reconstruyó** con `python desktop/build.py` sobre el código ya modificado; se confirmó que el `payload.zip` embebido contiene los cambios (`estimate_complexity`, el nuevo `LocalProvider.embed`) leyendo el zip generado antes de embeberlo.
- **El .exe se ejecutó nativo en Windows por primera vez**: descargó su propio Python privado (mismo ZIP y hash ya verificados antes), extrajo su payload, arrancó el servidor embebido en un puerto dinámico y sirvió la interfaz real. Saludo y calculadora respondieron en 0,0s, igual que en el servidor de desarrollo.
- **Ollama 0.34.2 + Qwen3 4B reales** se descargaron a través del flujo propio de la aplicación (botón "Preparar y empezar" vía API), verificando el SHA-256 publicado, sin intervención manual. El modelo cargó completo en la GPU (3,18 GB de 12 GB VRAM).
- **Rendimiento medido, no estimado**: una pregunta documental simple con el modelo recién cargado tardó 19,66 s (arranque en frío); la misma clase de pregunta con el modelo ya caliente, **1,02 s**. Una pregunta comparativa que activó razonamiento extendido tardó 12,69–18,64 s.
- **Hallazgo real, no teórico, de "inflación de tokens de razonamiento"**: el primer intento de una pregunta compleja con razonamiento activado falló (`done_reason` no fue `stop` dentro del presupuesto de 1600 tokens); el reintento inmediato con el mismo pedido completó correctamente en 12,69 s con una respuesta correcta y citada. No se investigó más a fondo si fue variabilidad del primer arranque del modo `think` o un caso límite genuino del presupuesto — queda como hallazgo abierto de bajo impacto (el sistema no se rompe: falla con un mensaje claro y es reintentable).
- Para evitar una segunda descarga de 4,1 GB, el motor y el modelo ya descargados se copiaron al directorio de datos del propio `.exe` (`%LOCALAPPDATA%\IA-Cuantitativa\data\engine`); al reabrirlo, preparó el motor sin volver a descargar nada y respondió correctamente.

Con esto, de las brechas de verificación originales solo queda pendiente: integración autenticada con una cuenta real de Gemini (no se realizó ninguna llamada paga) y un benchmark con una distribución más amplia de tareas reales del usuario.

## Addendum 3: reencuadre de producto — cerebro recursivo, no solo ejecución más rápida

Tras ver el Addendum 2, el usuario aclaró que el objetivo no era rendimiento en su GPU: el producto es para pymes que **no tienen placa de video** y no pueden mantener un ingeniero dedicado. Pidió explícitamente: (a) un perfil por defecto que no dependa de GPU, (b) que el sistema decida activamente entre resolver localmente o escalar — con contexto eficiente al escalar —, (c) capacidades que se mejoren con ejemplos reales de uso, y autorizó construir lo que hiciera falta.

**Medido en este mismo equipo, real, no estimado:**

| Perfil | Con GPU (RTX 3060) | Sin GPU (forzado a CPU) |
|---|---:|---:|
| Qwen3 4B (equilibrado), pregunta simple | 1,02 s | 8,43 s |
| Qwen3 1,7B (liviano), pregunta simple | 3,06 s | 3,08 s |
| Qwen3 1,7B (liviano), pregunta con razonamiento | — | 35,03 s |

El hallazgo clave: el perfil liviano es esencialmente **independiente de la GPU** para pedidos simples (~3 s con o sin placa de video), mientras que el equilibrado depende fuertemente de ella. `iq/diagnostics.py` ahora detecta la ausencia de GPU y la interfaz recomienda el perfil liviano en ese caso (sin forzarlo).

**Construido y verificado esta sesión, con Qwen3 4B real corriendo en este equipo:**

- **Reconsideración local acotada** (`iq/conversation.py`): si el primer intento local falla o dice `needs_help` y hay más contenido del documento sin usar, se reintenta una vez, gratis, con más contexto y razonamiento forzado. Si no hay más para ofrecer, no se repite la llamada. Probado con transporte simulado (2 pruebas nuevas) confirmando que sí se envían más fragmentos la segunda vez, y que no se repite cuando no hay más disponible.
- **Contexto comprimido antes de escalar** (`iq/distill.py`): una llamada local gratuita resume qué falta y elige como máximo 6 fragmentos antes de pagarle a Gemini, en vez de reenviar todo. Verificado con Qwen3 4B real: dado un documento con un párrafo relevante entre dos irrelevantes, identificó correctamente el único fragmento necesario.
- **Búsqueda web real vía Gemini** (`iq/providers.py: GeminiProvider.search`): opt-in, apagada por defecto, con advertencia explícita de que el cargo de búsqueda de Google no está verificado por esta app. El resultado de la búsqueda se le devuelve al modelo local para que reconsidere, nunca responde solo. No se hizo ninguna llamada paga real (sin cuenta autorizada); verificado con transporte simulado (2 pruebas).
- **Capacidades que se mejoran con ejemplos reales** (`iq/capabilities.py`): cada respuesta puede marcarse "Buena" o "Corregir"; "Mejorar con ejemplos" junta las correcciones y le pide al modelo local una nueva versión de las instrucciones, que debe repasar la misma compuerta de prueba antes de activarse. **Verificado de punta a punta con Qwen3 4B real**: una capacidad de prueba con una instrucción deliberadamente incompleta, corregida dos veces por el mismo motivo, produjo una versión nueva que aplicaba la corrección, pasó su prueba, y quedó activable — no se activó sola.
- **Hallazgo real durante esa verificación, no hipotético**: la primera versión del prompt de mejora hacía que Qwen3 4B, con razonamiento activado, gastara el presupuesto completo de tokens (probado hasta 4000, el máximo validado) enteramente en "pensar" sin nunca llegar a responder (`done_reason: length`, contenido vacío) — reproducido dos veces de forma consistente, no fue un evento aislado. Desactivar el razonamiento evitaba el corte pero la "mejora" no corregía nada en los hechos. Pedirle explícitamente pensar poco (3–4 líneas) antes de responder resolvió ambos problemas a la vez, confirmado con una llamada real posterior.

**Pruebas automatizadas: 80 de 80 en verde**, más las 3 de Go. El .exe se recompiló varias veces durante esta fase y siempre se relanzó nativo en este Windows, reutilizando el motor y los modelos ya descargados.

## Addendum 4: validado con el modelo que realmente importa (Qwen3 1,7B, el recomendado sin GPU)

Todo lo del Addendum 3 se había probado con Qwen3 4B. Como el perfil que la app recomienda para una pyme sin placa de video es el liviano (1,7B), se repitió la validación con ese modelo específicamente — y aparecieron dos problemas reales que el 4B no mostraba, ambos corregidos y reconfirmados con una llamada real después del arreglo:

- **Las capacidades propias fallaban su propia prueba con 1,7B.** Con razonamiento apagado (la heurística no lo activaba para un ejemplo corto), el modelo ignoraba una instrucción literal ("Terminá el mensaje con Gracias.") y escribía un párrafo genérico. Corrección: probar una capacidad ahora siempre activa razonamiento, sin importar qué diga la heurística de complejidad — es una acción deliberada e infrecuente, no una respuesta de chat bajo presión de latencia.
- **Con documentos vacíos, 1,7B abstenía aunque no hicieran falta.** Una capacidad sin documentos adjuntos (por ejemplo, un cierre de mensaje fijo) hacía que el modelo interpretara `document_fragments` vacío como "falta evidencia" y marcara `needs_help` aunque ya hubiera escrito la respuesta correcta. Corrección: se aclaró explícitamente en el prompt de sistema que un `document_fragments` vacío no implica que falte información, y que `needs_help` debe reflejar si el pedido pudo cumplirse, no si hubo documentos de por medio.

Con ambas correcciones, se repitieron con Qwen3 1,7B real y a través de la aplicación completa (no llamadas sueltas a Ollama): la capacidad de prueba, una pregunta documental con cita, una redacción sin documentos, y una pregunta comparativa con razonamiento — las cuatro dieron resultados correctos.

También en esta fase: la prueba de PDF ya no depende de tener `pypdf` instalado por `pip` — los tests ahora usan la misma copia vendorizada que usa la app empaquetada (antes se salteaba en silencio sin avisar). La prueba de DOCX sigue salteándose cuando falta `python-docx`, pero eso es correcto: esa librería es solo para construir el archivo de prueba, la app nunca la usa en producción. Se agregó además una vista para ver los ejemplos guardados de cada capacidad antes de pedir una mejora.

## Addendum 5: API de integración — el cerebro se puede llamar desde otro programa

El hueco identificado tras el Addendum 4: todo lo construido funcionaba desde la interfaz de chat, pero no había forma de que "otra cosa que estás desarrollando" (un script, una automatización propia) le mandara pedidos al cerebro y recibiera su decisión, salvo reimplementar el token de sesión rotativo pensado solo para la pestaña del navegador.

Se agregó una clave de integración estable (`iqk_...`), generada desde Configuración → Integraciones, y un endpoint bloqueante `POST /api/integration/ask` que resuelve el pedido internamente (mismo camino que `/api/chat`: heurística de razonamiento, reintento local con más contexto, búsqueda web opcional, escalamiento con contexto comprimido) y devuelve ya la respuesta decidida — incluyendo `escalated` (si terminó en Gemini o no) — en vez de que el programa externo tenga que hacer polling manual. Documentado en `docs/ARQUITECTURA.md`.

Verificado en dos niveles:
- 6 tests HTTP reales contra un servidor real (`tests/test_http.py`): ciclo de vida de la clave, rechazo sin clave o con clave incorrecta, que `ask` funciona sin ningún token de sesión (probando que es independiente de la interfaz), validación de `wait_seconds`, `status` devuelve el mismo resultado que `ask`, y que sigue exigiendo loopback (Host/Origin) igual que el resto del servidor.
- Manual, de punta a punta: se levantó la app real, se generó la clave desde la interfaz en el navegador (capturado en el DOM: "Clave activa..."), y se llamó `/api/integration/ask` con `curl` usando *solo* esa clave, sin token de sesión, simulando exactamente a un programa externo — devolvió un JSON con la decisión completa.

Sigue siendo integración en la misma máquina (loopback), no un servicio expuesto a la red — eso es una decisión de diseño heredada del resto del servidor, no algo que haya quedado pendiente.
