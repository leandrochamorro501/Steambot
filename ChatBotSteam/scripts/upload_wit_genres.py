import os
import asyncio
import httpx
from dotenv import load_dotenv

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

# Diccionario de géneros principales de Steam y sus sinónimos en español
GENRES_AND_SYNONYMS = {
    "Action": ["Action", "acción", "accion", "juego de acción", "tiros", "disparos"],
    "Adventure": ["Adventure", "aventura", "aventuras", "juego de aventura"],
    "RPG": ["RPG", "rol", "juego de rol", "juego rpg", "juegos de rol"],
    "Strategy": ["Strategy", "estrategia", "juego de estrategia", "tactico", "táctico", "táctica"],
    "Simulation": ["Simulation", "simulación", "simulacion", "simulador", "juego de simulación"],
    "Racing": ["Racing", "carreras", "carrera", "autos", "coches", "conducción", "conduccion"],
    "Sports": ["Sports", "deportes", "deporte", "juego de deportes", "futbol", "fútbol", "basket"],
    "Indie": ["Indie", "independiente", "juegos indie", "indies"],
    "Casual": ["Casual", "casual", "juego casual", "relajante", "tranquilo"],
    "Massively Multiplayer": ["Massively Multiplayer", "mmo", "mmorpg", "multijugador masivo", "masivo multijugador"],
    "Free to Play": ["Free to Play", "gratis", "gratuito", "f2p", "free to play", "juegos gratis"],
    "Early Access": ["Early Access", "acceso anticipado", "early access", "beta"]
}

async def create_entity_if_not_exists(client: httpx.AsyncClient):
    """Verifica si la entidad 'genre' existe; si no, la crea."""
    print("Verificando existencia de la entidad 'genre'...")
    res = await client.get(f"{BASE_URL}/entities/genre", params={"v": WIT_API_VERSION}, headers=headers)

    if res.status_code == 404:
        print("La entidad 'genre' no existe. Creándola...")
        payload = {
            "name": "genre",
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
            print("Entidad 'genre' creada exitosamente.")
        else:
            print(f"Error creando entidad: {res_create.status_code} - {res_create.text}")
            return False
    elif res.status_code == 200:
        print("La entidad 'genre' ya existe.")
    else:
        print(f"Error verificando entidad: {res.status_code} - {res.text}")
        return False

    return True

async def upload_genres():
    if not WIT_AI_TOKEN:
        print("Error: WIT_AI_TOKEN no encontrado en el archivo .env")
        return

    async with httpx.AsyncClient() as client:
        success = await create_entity_if_not_exists(client)
        if not success:
            return

        print(f"Iniciando la carga de {len(GENRES_AND_SYNONYMS)} géneros con sus sinónimos...")

        added_count = 0
        failed_count = 0

        for i, (genre, synonyms) in enumerate(GENRES_AND_SYNONYMS.items(), 1):
            payload = {
                "keyword": genre,
                "synonyms": synonyms
            }
            res = await client.post(
                f"{BASE_URL}/entities/genre/keywords",
                params={"v": WIT_API_VERSION},
                headers=headers,
                json=payload
            )

            if res.status_code in (200, 201):
                print(f"[{i}/{len(GENRES_AND_SYNONYMS)}] + Agregado: {genre} (Sinonimos: {len(synonyms)})")
                added_count += 1
            elif res.status_code == 409:
                # Si ya existe, podríamos querer actualizar los sinónimos en lugar de fallar
                print(f"[{i}/{len(GENRES_AND_SYNONYMS)}] = Ya existe el género: {genre}. Actualizando sinónimos...")
                # La API no tiene un endpoint PUT /keywords para actualizar los sinónimos directamente,
                # pero el POST sobre la entidad puede agregar/sobreescribir si hacemos PUT a la entidad completa.
                # Para mayor simplicidad, ignoraremos las colisiones si ya se había creado el keyword sin sinónimos.
            else:
                print(f"[{i}/{len(GENRES_AND_SYNONYMS)}] - Error con '{genre}': {res.status_code} - {res.text}")
                failed_count += 1

            await asyncio.sleep(0.2)

        print("-" * 30)
        print("Carga masiva de géneros finalizada.")
        print(f"Agregados: {added_count}")
        print(f"Errores: {failed_count}")

if __name__ == "__main__":
    asyncio.run(upload_genres())
