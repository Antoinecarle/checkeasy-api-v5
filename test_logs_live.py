#!/usr/bin/env python3
"""
Script de test pour vérifier les logs en temps réel
"""
import requests
import json
import time
import threading

# Configuration
API_URL = "https://checkeasy-api-staging-production.up.railway.app"
LOGS_API = f"{API_URL}/api/logs"
DEBUG_API = f"{API_URL}/api/logs-debug"

def monitor_logs():
    """Monitore les logs en temps réel"""
    print("\n📊 Monitoring des logs en temps réel...\n")
    
    for i in range(30):  # Vérifier pendant 30 secondes
        try:
            response = requests.get(DEBUG_API, timeout=5)
            data = response.json()
            
            print(f"[{i}s] Actives: {data['active_requests']}, Complétées: {data['completed_requests']}, Total: {data['total_requests']}")
            
            if data['total_requests'] > 0:
                print(f"     IDs: {data['requests_ids']}")
                
                # Afficher les détails de la première requête
                request_id = data['requests_ids'][0]
                response = requests.get(f"{LOGS_API}/{request_id}", timeout=5)
                req_data = response.json()
                
                if req_data['status'] == 'ok':
                    req = req_data['request']
                    print(f"     Status: {req['status']}, Logs: {len(req['logs'])}, Étapes: {len(req['steps'])}")
                    
                    if req['logs']:
                        print(f"     Dernier log: {req['logs'][-1]['message']}")
            
            time.sleep(1)
        except Exception as e:
            print(f"[{i}s] ❌ Erreur: {e}")
            time.sleep(1)

def test_analyze_complete():
    """Lance une requête /analyze-complete"""
    print("🚀 Lancement d'une requête /analyze-complete...\n")

    test_payload = {
        "logement_id": "test-logement-001",
        "rapport_id": "test-rapport-001",
        "type": "Voyageur",
        "pieces": [
            {
                "piece_id": "piece-001",
                "nom": "Chambre",
                "commentaire_ia": "",
                "checkin_pictures": [
                    {"piece_id": "piece-001", "url": "https://via.placeholder.com/400"}
                ],
                "checkout_pictures": [
                    {"piece_id": "piece-001", "url": "https://via.placeholder.com/400"}
                ],
                "etapes": [
                    {
                        "etape_id": "etape-001",
                        "task_name": "Vérifier la propreté",
                        "consigne": "Vérifier que la chambre est propre",
                        "checking_picture": "https://via.placeholder.com/400",
                        "checkout_picture": "https://via.placeholder.com/400"
                    }
                ]
            }
        ]
    }
    
    try:
        response = requests.post(
            f"{API_URL}/analyze-complete",
            json=test_payload,
            timeout=120
        )
        print(f"✅ Réponse: {response.status_code}\n")
        return True
    except Exception as e:
        print(f"❌ Erreur: {e}\n")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 TEST DES LOGS EN TEMPS RÉEL")
    print("=" * 60)
    
    # Lancer le monitoring dans un thread séparé
    monitor_thread = threading.Thread(target=monitor_logs, daemon=True)
    monitor_thread.start()
    
    # Attendre un peu avant de lancer la requête
    time.sleep(2)
    
    # Lancer la requête
    test_analyze_complete()
    
    # Attendre la fin du monitoring
    monitor_thread.join()
    
    print("\n" + "=" * 60)
    print("✅ Test terminé")
    print("=" * 60)

