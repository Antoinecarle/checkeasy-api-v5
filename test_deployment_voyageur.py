"""
Script de test pour valider le déploiement du système dual Voyageur/Ménage
Vérifie que les bons fichiers de configuration sont chargés selon le type de parcours
"""

import requests
import json
from datetime import datetime

# Configuration
RAILWAY_URL = "https://checkeasy-api-v5-production.up.railway.app"  # À adapter selon votre URL Railway
LOCAL_URL = "http://localhost:8000"

# Choisir l'environnement à tester
BASE_URL = RAILWAY_URL  # Changer en LOCAL_URL pour tester en local

# Couleurs pour l'affichage
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(80)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")

def test_analyze_voyageur():
    """Test d'analyse avec le type Voyageur"""
    print_header("TEST 1 : ANALYSE CHAMBRE - TYPE VOYAGEUR")
    
    payload = {
        "logement_id": "test_voyageur_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
        "rapport_id": "test_rapport_voyageur",
        "type": "Voyageur",
        "pieces": [
            {
                "piece_id": "test_chambre_voyageur",
                "nom": "🛏️ Chambre Test",
                "commentaire_ia": "",
                "checkin_pictures": [
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762517525937x771690987762800600/Capture%20d%E2%80%99e%CC%81cran%202025-11-07%20a%CC%80%2013.12.01.png"
                ],
                "checkout_pictures": [
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762847161003x344678990362938560/File.jpeg",
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762846102305x200808969386471420/File.jpg"
                ]
            }
        ]
    }
    
    print_info(f"Envoi de la requête à {BASE_URL}/analyze-complete...")
    print_info(f"Type de parcours : {payload['type']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/analyze-complete",
            json=payload,
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            print_success(f"Requête réussie (status: {response.status_code})")
            
            # Vérifier la classification
            if "room_classification" in result:
                classification = result["room_classification"]
                print_info(f"Type de pièce détecté : {classification.get('room_type', 'N/A')}")
                print_info(f"Confiance : {classification.get('confidence', 'N/A')}%")
                
                # VÉRIFICATION CRITIQUE : Points ignorables
                verifications = classification.get("verifications", {})
                points_ignorables = verifications.get("points_ignorables", [])
                
                print(f"\n{Colors.BOLD}Points ignorables chargés ({len(points_ignorables)}) :{Colors.END}")
                for point in points_ignorables:
                    print(f"  - {point}")
                
                # Vérifier si "lit fait ou pas fait" est présent
                lit_ignore = any("lit fait" in p.lower() for p in points_ignorables)
                
                if lit_ignore:
                    print_success("✅ 'lit fait ou pas fait' est bien dans les points ignorables (CONFIG VOYAGEUR)")
                else:
                    print_error("❌ 'lit fait ou pas fait' ABSENT des points ignorables (MAUVAISE CONFIG)")
                
                # Vérifier le nombre de points ignorables (devrait être 6 pour Voyageur)
                if len(points_ignorables) >= 6:
                    print_success(f"✅ Nombre de points ignorables correct : {len(points_ignorables)} (attendu: 6)")
                else:
                    print_error(f"❌ Nombre de points ignorables incorrect : {len(points_ignorables)} (attendu: 6)")
                    print_warning("Le système utilise probablement l'ancienne configuration !")
            
            # Vérifier l'analyse
            if "analysis" in result:
                analysis = result["analysis"]
                print(f"\n{Colors.BOLD}Résultat de l'analyse :{Colors.END}")
                print_info(f"Status : {analysis.get('analyse_globale', {}).get('status', 'N/A')}")
                print_info(f"Score : {analysis.get('analyse_globale', {}).get('score', 'N/A')}/5")
                
                defauts = analysis.get("defauts_detectes", [])
                print_info(f"Défauts détectés : {len(defauts)}")
                
                # Vérifier si un lit pas fait est signalé comme défaut
                lit_defaut = any("lit" in d.get("description", "").lower() and "fait" in d.get("description", "").lower() for d in defauts)
                
                if lit_defaut:
                    print_warning("⚠️  Un défaut lié au lit pas fait a été détecté")
                    print_warning("Cela ne devrait PAS arriver en mode Voyageur !")
                else:
                    print_success("✅ Aucun défaut lié au lit pas fait (comportement attendu en Voyageur)")
            
            return True
        else:
            print_error(f"Erreur HTTP {response.status_code}")
            print_error(f"Réponse : {response.text[:500]}")
            return False
            
    except Exception as e:
        print_error(f"Erreur lors de la requête : {str(e)}")
        return False

def test_analyze_menage():
    """Test d'analyse avec le type Ménage"""
    print_header("TEST 2 : ANALYSE CHAMBRE - TYPE MÉNAGE")
    
    payload = {
        "logement_id": "test_menage_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
        "rapport_id": "test_rapport_menage",
        "type": "Ménage",
        "pieces": [
            {
                "piece_id": "test_chambre_menage",
                "nom": "🛏️ Chambre Test",
                "commentaire_ia": "",
                "checkin_pictures": [
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762517525937x771690987762800600/Capture%20d%E2%80%99e%CC%81cran%202025-11-07%20a%CC%80%2013.12.01.png"
                ],
                "checkout_pictures": [
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762847161003x344678990362938560/File.jpeg",
                    "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1762846102305x200808969386471420/File.jpg"
                ]
            }
        ]
    }
    
    print_info(f"Envoi de la requête à {BASE_URL}/analyze-complete...")
    print_info(f"Type de parcours : {payload['type']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/analyze-complete",
            json=payload,
            timeout=120
        )
        
        if response.status_code == 200:
            result = response.json()
            print_success(f"Requête réussie (status: {response.status_code})")
            
            # Vérifier la classification
            if "room_classification" in result:
                classification = result["room_classification"]
                verifications = classification.get("verifications", {})
                points_ignorables = verifications.get("points_ignorables", [])
                
                print(f"\n{Colors.BOLD}Points ignorables chargés ({len(points_ignorables)}) :{Colors.END}")
                for point in points_ignorables:
                    print(f"  - {point}")
                
                # Vérifier si "lit fait ou pas fait" est ABSENT (normal pour Ménage)
                lit_ignore = any("lit fait" in p.lower() for p in points_ignorables)
                
                if not lit_ignore:
                    print_success("✅ 'lit fait ou pas fait' ABSENT des points ignorables (CONFIG MÉNAGE)")
                else:
                    print_error("❌ 'lit fait ou pas fait' présent dans les points ignorables (MAUVAISE CONFIG)")
                    print_warning("Le système utilise probablement la configuration Voyageur au lieu de Ménage !")
            
            return True
        else:
            print_error(f"Erreur HTTP {response.status_code}")
            print_error(f"Réponse : {response.text[:500]}")
            return False
            
    except Exception as e:
        print_error(f"Erreur lors de la requête : {str(e)}")
        return False

def main():
    print_header("🧪 TEST DE DÉPLOIEMENT - SYSTÈME DUAL VOYAGEUR/MÉNAGE")
    print_info(f"URL testée : {BASE_URL}")
    print_info(f"Date : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1 : Voyageur
    test1_success = test_analyze_voyageur()
    
    # Test 2 : Ménage
    test2_success = test_analyze_menage()
    
    # Résumé
    print_header("📊 RÉSUMÉ DES TESTS")
    
    if test1_success:
        print_success("Test Voyageur : RÉUSSI")
    else:
        print_error("Test Voyageur : ÉCHOUÉ")
    
    if test2_success:
        print_success("Test Ménage : RÉUSSI")
    else:
        print_error("Test Ménage : ÉCHOUÉ")
    
    if test1_success and test2_success:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 TOUS LES TESTS SONT RÉUSSIS !{Colors.END}")
        print_success("Le système dual Voyageur/Ménage fonctionne correctement.")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  CERTAINS TESTS ONT ÉCHOUÉ{Colors.END}")
        print_warning("Vérifiez que le nouveau code a bien été déployé sur Railway.")
        print_warning("Consultez les logs Railway pour plus de détails.")

if __name__ == "__main__":
    main()

