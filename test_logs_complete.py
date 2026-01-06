#!/usr/bin/env python3
"""
Script de test pour vérifier le système de logs avec /analyze-complete
"""
import requests
import json
import time
from datetime import datetime

# Configuration
API_URL = "http://localhost:8000"
LOGS_API = f"{API_URL}/api/logs"
DEBUG_API = f"{API_URL}/api/logs-debug"

def test_logs_system():
    """Test le système de logs"""
    print("🧪 Test du système de logs avec /analyze-complete\n")
    
    # 1. Vérifier l'état initial
    print("1️⃣ État initial du système:")
    try:
        response = requests.get(DEBUG_API)
        data = response.json()
        print(f"   ✅ Requêtes actives: {data['active_requests']}")
        print(f"   ✅ Requêtes complétées: {data['completed_requests']}")
        print(f"   ✅ Total: {data['total_requests']}\n")
    except Exception as e:
        print(f"   ❌ Erreur: {e}\n")
        return
    
    # 2. Créer une requête de test simple
    print("2️⃣ Création d'une requête de test:")
    test_payload = {
        "logement_id": "test-logement-001",
        "rapport_id": "test-rapport-001",
        "pieces": [
            {
                "piece_id": "piece-001",
                "nom": "Chambre",
                "type": "Chambre",
                "checkin_pictures": ["https://via.placeholder.com/400"],
                "checkout_pictures": ["https://via.placeholder.com/400"],
                "elements_critiques": [],
                "points_ignorables": [],
                "defauts_frequents": [],
                "commentaire_ia": ""
            }
        ]
    }
    
    print(f"   📤 Envoi de la requête...")
    try:
        response = requests.post(
            f"{API_URL}/analyze-complete",
            json=test_payload,
            timeout=60
        )
        print(f"   ✅ Réponse: {response.status_code}\n")
    except Exception as e:
        print(f"   ❌ Erreur: {e}\n")
        return
    
    # 3. Vérifier les logs après la requête
    print("3️⃣ Vérification des logs après la requête:")
    time.sleep(2)  # Attendre un peu
    
    try:
        response = requests.get(DEBUG_API)
        data = response.json()
        print(f"   ✅ Requêtes actives: {data['active_requests']}")
        print(f"   ✅ Requêtes complétées: {data['completed_requests']}")
        print(f"   ✅ Total: {data['total_requests']}")
        
        if data['total_requests'] > 0:
            print(f"   📋 IDs des requêtes: {data['requests_ids']}\n")
            
            # 4. Récupérer les détails de la première requête
            print("4️⃣ Détails de la requête:")
            request_id = data['requests_ids'][0]
            response = requests.get(f"{LOGS_API}/{request_id}")
            req_data = response.json()
            
            if req_data['status'] == 'ok':
                req = req_data['request']
                print(f"   📌 ID: {req['request_id']}")
                print(f"   📌 Endpoint: {req['endpoint']}")
                print(f"   📌 Status: {req['status']}")
                print(f"   📌 Logs: {len(req['logs'])} entrées")
                print(f"   📌 Étapes: {len(req['steps'])} étapes")
                
                if req['logs']:
                    print(f"\n   📝 Premiers logs:")
                    for log in req['logs'][:3]:
                        print(f"      - [{log['level']}] {log['message']}")
                
                if req['steps']:
                    print(f"\n   ⚙️ Étapes:")
                    for step in req['steps']:
                        print(f"      - {step['name']} ({step['status']}) - {len(step['logs'])} logs")
        else:
            print("   ⚠️ Aucune requête trouvée!\n")
            
    except Exception as e:
        print(f"   ❌ Erreur: {e}\n")

if __name__ == "__main__":
    test_logs_system()

