"""
Script de test pour vérifier le système de logs en temps réel
"""
import requests
import json
import time

# Payload de test simple
test_payload = {
    "piece_id": "test_logs_001",
    "nom": "Cuisine",
    "type": "Voyageur",
    "commentaire_ia": "Test du système de logs en temps réel",
    "checkin_pictures": [
        {
            "piece_id": "test_logs_001",
            "url": "https://s3.eu-central-1.amazonaws.com/checkeasy.appgyver/1745856961367x853186102447308800/1745857142659x605188923525693400/1745857142659x605188923525693400_checking.jpg",
            "description": "Photo avant"
        }
    ],
    "checkout_pictures": [
        {
            "piece_id": "test_logs_001",
            "url": "https://s3.eu-central-1.amazonaws.com/checkeasy.appgyver/1745856961367x853186102447308800/1745857142659x605188923525693400/1745857142659x605188923525693400_checkout.jpg",
            "description": "Photo après"
        }
    ],
    "etapes": [],
    "elements_critiques": ["Plan de travail", "Évier"],
    "points_ignorables": ["Traces légères"],
    "defauts_frequents": ["Taches"]
}

print("🚀 Lancement du test du système de logs...")
print("📋 Ouvrez http://localhost:8000/logs-viewer dans votre navigateur")
print("⏳ Envoi de la requête dans 3 secondes...")
time.sleep(3)

print("\n📤 Envoi de la requête /analyze...")
response = requests.post(
    "http://localhost:8000/analyze",
    json=test_payload,
    timeout=120
)

print(f"\n✅ Réponse reçue - Status: {response.status_code}")
if response.status_code == 200:
    result = response.json()
    print(f"📊 Issues détectées: {len(result.get('preliminary_issues', []))}")
    print(f"🎯 Score: {result.get('analyse_globale', {}).get('score', 'N/A')}/5")
    print(f"💬 Commentaire: {result.get('analyse_globale', {}).get('commentaire_global', 'N/A')}")
else:
    print(f"❌ Erreur: {response.text}")

print("\n✨ Test terminé ! Vérifiez l'interface de logs pour voir le workflow.")

