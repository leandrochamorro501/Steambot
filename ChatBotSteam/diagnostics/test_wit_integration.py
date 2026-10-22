import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from nlu.wit_client import detect_intent

tests = [
    "Quiero un juego de terror y survival tipo Resident Evil por menos de 20 dolares",
    "Algo de mundo abierto y exploración",
    "Dame un roguelike difícil tipo Hades",
    "Quiero algo cooperativo de granja relajante",
    "Juegos de ciencia ficción cyberpunk con buen historia",
    "Un FPS multijugador competitivo online",
    "Algo tipo Stardew Valley para jugar con amigos",
    "Quiero un JRPG de anime con buena narrativa",
    "Mejor que sea más barato",
    "Cuánto cuesta Elden Ring",
    "Hola",
    "¿Qué puedes hacer?",
    "Algo de plataformas con pixel art difícil",
    "Un souls-like de dark fantasy",
    "Juegos de zombies en modo cooperativo online",
]

print("=" * 70)
print("TEST DE INTEGRACIÓN WIT.AI — POST ENTRENAMIENTO")
print("=" * 70)
for i, query in enumerate(tests, 1):
    result = detect_intent(query)
    intent = result.get("intent_type")
    confidence = result.get("_confidence", 0.0)
    tags = result.get("tags", [])
    genre = result.get("genre")
    max_p = result.get("max_price_usd")
    print(f"\n[{i:02d}] {query}")
    print(f"     Intent: {intent} ({confidence:.2f}) | Tags: {tags} | Genre: {genre} | MaxPrice: {max_p}")
