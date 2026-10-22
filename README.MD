# SteamBot

Chatbot en español para recomendar videojuegos de Steam desde una terminal o Telegram. Busca juegos por etiquetas, género y presupuesto, consulta precios regionales y mantiene el historial de recomendaciones durante la sesión.

Usa SteamSpy y Steam Store para obtener datos de juegos, DeepSeek para generar respuestas y, opcionalmente, Wit.ai para interpretar consultas. La región inicial es Chile y puede cambiarse desde cada interfaz.

## Requisitos

- Python 3.11 a 3.13 y acceso a Internet para usar el bot.
- Una clave de API de DeepSeek y un modelo habilitado en esa cuenta.
- Un token de bot de Telegram si se utiliza esa interfaz.
- Una aplicación de Wit.ai configurada si se elige `NLU_ENGINE=wit`.

## Instalación

Abre una terminal en la raíz del repositorio. En Windows (PowerShell):

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ChatBotSteam/requirements.txt
Copy-Item ChatBotSteam/.env.example ChatBotSteam/.env
```

En Linux o macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r ChatBotSteam/requirements.txt
cp ChatBotSteam/.env.example ChatBotSteam/.env
```

Edita `ChatBotSteam/.env` con tus credenciales. El archivo está excluido de Git; `.env.example` contiene únicamente valores de ejemplo.

| Variable | Uso |
| --- | --- |
| `DEEPSEEK_API_KEY` | Clave para generar respuestas y extraer intenciones en modo DeepSeek. También se acepta `DEEPSEEK_APIKEY`. |
| `DEEPSEEK_BASE_URL` | Endpoint del proveedor; por defecto `https://api.deepseek.com`. |
| `DEEPSEEK_MODEL_ID` | Modelo habilitado en tu cuenta; el ejemplo usa `deepseek-chat`. |
| `TELEGRAM_TOKEN` | Token de Telegram, necesario solo para esa interfaz. |
| `NLU_ENGINE` | `deepseek` o `wit`; el ejemplo usa `deepseek`. |
| `WIT_AI_TOKEN` | Server Access Token de tu aplicación de Wit.ai, necesario solo en modo `wit`. |

## Ejecución

Desde la raíz, en Windows:

```powershell
# Interfaz de consola
.\.venv\Scripts\python.exe ChatBotSteam/main.py

# Interfaz de Telegram (ejecutar por separado)
.\.venv\Scripts\python.exe ChatBotSteam/telegram_bot.py
```

En Linux/macOS, reemplaza `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

Ejemplos: «Quiero juegos de terror», «Algo cooperativo por menos de 20 dólares», «Cuánto cuesta Elden Ring» y «Mejor que sea más barato».

En consola están disponibles `ayuda`, `region`, `historial`, `exportar` y `salir`. En Telegram: `/start`, `/help`, `/region`, `/historial`, `/export` y `/reset`.

## Pruebas automatizadas

Desde la raíz, en Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r ChatBotSteam/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q ChatBotSteam
```

La suite automatizada bloquea conexiones de red y utiliza tasas de cambio de prueba. No necesita credenciales. GitHub Actions ejecuta esta suite y comprueba la sintaxis con Python 3.11, 3.12 y 3.13 en cada push y pull request.

Los diagnósticos manuales están en `ChatBotSteam/diagnostics/` y quedan fuera de la suite. Pueden consultar servicios reales y consumir la cuota de tu proveedor. Por ejemplo:

```powershell
.\.venv\Scripts\python.exe ChatBotSteam/diagnostics/test_deepseek.py
.\.venv\Scripts\python.exe ChatBotSteam/diagnostics/test_steamspy_diagnostics.py
```

## Estructura

```text
.github/workflows/      Comprobaciones en GitHub Actions
ChatBotSteam/
  core/                Pipeline, sesiones, APIs, generación y monedas
  models/              Intenciones, etiquetas y puntuación de juegos
  nlu/                 Cliente de Wit.ai
  scripts/             Mantenimiento de datos y entrenamiento de Wit.ai
  tests/               Pruebas automatizadas sin red
  diagnostics/         Comprobaciones manuales con servicios externos
  .env.example         Plantilla pública de configuración
  main.py              Interfaz de consola
  telegram_bot.py      Interfaz de Telegram
docs/                  CSV de etiquetas de SteamSpy
```

`ChatBotSteam/core/top_1000_cache.json` se conserva como instantánea de datos públicos para respaldar búsquedas. Puede contener precios y estadísticas antiguos. Para actualizarla manualmente, desde `ChatBotSteam/` y con el entorno activado:

```bash
python -m scripts.build_top_games_db 1000
```

Los scripts `setup_wit_ai.py`, `train_wit_ai_full.py`, `upload_wit_*.py` y `patch_wit_*.py` modifican la aplicación de Wit.ai asociada al token. Se ejecutan manualmente, después de revisar su configuración.

## Consideraciones

- El historial vive en memoria y se pierde al reiniciar; puede exportarse desde cada interfaz.
- Las consultas se envían a los servicios configurados. Evita incluir información sensible en los mensajes.
- La disponibilidad y exactitud de datos y precios dependen de los servicios externos. Las conversiones de respaldo son aproximadas.
- El proyecto no incluye una licencia de distribución. El titular debe elegirla antes de autorizar reutilización del código; los datos de terceros conservan sus condiciones de origen.

## Subir a GitHub

Desde la raíz de STEAMBOT, crea el primer commit después de revisar `git status`. La carpeta ya está inicializada con la rama `main`:

```bash
git add .
git diff --cached --stat
git commit -m "Prepare SteamBot for GitHub"
```

El repositorio de GitHub ya contiene un commit con un README. Sustituye `USUARIO` y `REPOSITORIO` por tus datos y descarga primero su historial:

```bash
git remote add origin https://github.com/USUARIO/REPOSITORIO.git
git fetch origin
git branch -r
```

Si `origin` ya está configurado, revisa `git remote -v` y omite `git remote add`.

Integra la rama remota antes del push. Estos comandos suponen que se llama `main`; si aparece otra en `git branch -r`, utiliza ese nombre:

```bash
git merge origin/main --allow-unrelated-histories --no-edit
```

`--allow-unrelated-histories` permite unir el primer commit local con el commit creado por separado en GitHub. `fetch` solo descarga el historial; la integración la realiza `merge`.

Si aparece un conflicto en el README, combina el contenido que quieras conservar y elimina los marcadores `<<<<<<<`, `=======` y `>>>>>>>`. En Windows, comprueba también que quede un único README: `README.MD` y `README.md` difieren en mayúsculas para Git. Después de resolver los conflictos:

```bash
git add .
git commit -m "Integrate existing GitHub README"
```

Cuando la integración termine correctamente:

```bash
git push -u origin main
```

Este procedimiento conserva el commit remoto existente. No requiere un push forzado.

Las reglas de `.gitignore` excluyen credenciales, entornos virtuales e historiales exportados de forma predeterminada.
