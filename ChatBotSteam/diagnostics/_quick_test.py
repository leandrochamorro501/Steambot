import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from nlu.wit_client import detect_intent

tests = [
    ("Hola",                              "CASUAL_CHAT"),
    ("Chao",                              "CASUAL_CHAT"),
    ("Gracias",                           "CASUAL_CHAT"),
    ("Buenas",                            "CASUAL_CHAT"),
    ("Ok entendido",                      "CASUAL_CHAT"),
    ("Recomiendame juegos de terror",     "SEARCH_GAME"),
    ("Un roguelike dificil tipo Hades",   "SEARCH_GAME"),
    ("Algo cooperativo de granja",        "SEARCH_GAME"),
    ("Cuanto cuesta Elden Ring",          "CHECK_PRICE"),
    ("Que puedes hacer",                  "ASK_CAPABILITIES"),
    ("Dame mas opciones",                 "REFINE_SEARCH"),
    ("Lo mismo pero cooperativo",         "REFINE_SEARCH"),
    ("Juegos de ciencia ficcion cyberpunk","SEARCH_GAME"),
    ("Recomiendame cualquier juego",      "RANDOM_GAME"),
]

print("Intent              | Conf | is_game | OK | Frase")
print("-" * 72)
all_ok = True
for text, expected in tests:
    r = detect_intent(text)
    got = r.get("intent_type")
    conf = r.get("_confidence", 0)
    is_game = r.get("is_game_query")
    ok = "OK" if got == expected else "!!"
    if got != expected:
        all_ok = False
    print(f"{ok} {got:<20} {conf:.2f}  {str(is_game):<7} | {text}")

print()
print("TODOS CORRECTOS" if all_ok else "** HAY CASOS INCORRECTOS **")
