# Componentes de terceros

El código incluye pypdf 6.10.0, bajo BSD-3-Clause; su licencia se conserva en `pypdf-LICENSE.txt` y su código en `vendor/pypdf`.

El lanzador se construye con Go. La licencia de la distribución utilizada se conserva en `Go-LICENSE.txt`.

En la primera ejecución se descarga Python 3.13.15 desde python.org; su distribución conserva su licencia PSF. La preparación del motor descarga Ollama 0.34.2 desde su repositorio oficial y Qwen3 4B o 1.7B desde el registro de Ollama. Estos componentes no están incluidos como pesos o binarios en el ZIP de la aplicación y mantienen sus respectivas licencias. Qwen3 4B y 1.7B se publican bajo Apache-2.0; Ollama, bajo MIT.

Fuentes: https://www.python.org/ · https://github.com/ollama/ollama · https://huggingface.co/Qwen/Qwen3-4B · https://huggingface.co/Qwen/Qwen3-1.7B
