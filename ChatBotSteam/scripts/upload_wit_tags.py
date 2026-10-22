import os
import csv
import httpx
import asyncio
from dotenv import load_dotenv

# Cargar variables de entorno (asumimos que el script corre desde ChatBotSteam/scripts/)
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

WIT_AI_TOKEN = os.getenv("WIT_AI_TOKEN")
WIT_API_VERSION = "20240601"
BASE_URL = "https://api.wit.ai"

headers = {
    "Authorization": f"Bearer {WIT_AI_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

csv_path = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs",
    "Tags overview - SteamSpy - All the data and stats about Steam games.csv"
)

async def create_entity_if_not_exists(client: httpx.AsyncClient):
    """Verifica si la entidad 'tags' existe; si no, la crea."""
    print("Verificando existencia de la entidad 'tags'...")
    res = await client.get(f"{BASE_URL}/entities/tags", params={"v": WIT_API_VERSION}, headers=headers)

    if res.status_code == 404:
        print("La entidad 'tags' no existe. Creándola...")
        payload = {
            "name": "tags",
            "roles": [],
            "lookups": ["free-text", "keywords"]
        }
        res_create = await client.post(
            f"{BASE_URL}/entities",
            params={"v": WIT_API_VERSION},
            headers=headers,
            json=payload
        )
        if res_create.status_code in (200, 201):
            print("Entidad 'tags' creada exitosamente.")
        else:
            print(f"Error creando entidad: {res_create.status_code} - {res_create.text}")
            return False
    elif res.status_code == 200:
        print("La entidad 'tags' ya existe.")
    else:
        print(f"Error verificando entidad: {res.status_code} - {res.text}")
        return False

    return True

async def upload_tags():
    if not WIT_AI_TOKEN:
        print("Error: WIT_AI_TOKEN no encontrado en el archivo .env")
        return

    # Extraer los tags del CSV
    tags = []
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        next(reader)  # Saltar la cabecera
        for row in reader:
            if len(row) > 1:
                tags.append(row[1].strip())

    print(f"Se encontraron {len(tags)} tags en el CSV.")

    async with httpx.AsyncClient() as client:
        success = await create_entity_if_not_exists(client)
        if not success:
            return

        print("Iniciando la carga de keywords...")

        # Para no saturar la API (Rate Limits), enviaremos en lotes pequeños o con delay
        added_count = 0
        failed_count = 0

        for i, tag in enumerate(tags, 1):
            payload = {
                "keyword": tag,
                "synonyms": [tag] # El tag mismo actúa como sinónimo base
            }
            res = await client.post(
                f"{BASE_URL}/entities/tags/keywords",
                params={"v": WIT_API_VERSION},
                headers=headers,
                json=payload
            )

            if res.status_code in (200, 201):
                print(f"[{i}/{len(tags)}] + Agregado: {tag}")
                added_count += 1
            elif res.status_code == 409:
                print(f"[{i}/{len(tags)}] = Ya existe: {tag}")
            else:
                print(f"[{i}/{len(tags)}] - Error con '{tag}': {res.status_code} - {res.text}")
                failed_count += 1

            # Pequeño delay para evitar rate limits de Meta
            await asyncio.sleep(0.1)

        print("-" * 30)
        print("Carga masiva finalizada.")
        print(f"Nuevos agregados: {added_count}")
        print(f"Errores: {failed_count}")

if __name__ == "__main__":
    asyncio.run(upload_tags())
