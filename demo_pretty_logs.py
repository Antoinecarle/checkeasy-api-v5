#!/usr/bin/env python3
"""
Démonstration de l'affichage amélioré des logs dans le terminal
Lance une simulation d'analyse pour voir le rendu
"""

import logging
import time
from tqdm import tqdm
from logs_analysis.terminal_display import setup_pretty_terminal_logging, print_summary_box

# Configurer le logging de base
logging.basicConfig(level=logging.INFO)

# Activer l'affichage amélioré
setup_pretty_terminal_logging()

logger = logging.getLogger(__name__)


def simulate_room_analysis(piece_id: str, room_name: str, room_type: str, has_errors: bool = False):
    """Simule l'analyse d'une pièce"""
    
    # En-tête de la pièce
    logger.info(f"🔍 Analyse de la pièce {piece_id}: {room_name}", extra={'piece_id': piece_id})
    time.sleep(0.3)
    
    # Étape 1: Classification
    logger.info(f"📊 ÉTAPE 1 - Classification automatique pour {piece_id}")
    time.sleep(0.2)
    logger.info(f"Classification terminée pour la pièce {piece_id}: {room_type} (confiance: 95%)", 
                extra={'piece_id': piece_id})
    time.sleep(0.2)
    
    # Étape 2: Injection des critères
    logger.info(f"🔧 ÉTAPE 2 - Injection des critères automatiques dans le payload d'analyse", 
                extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"📌 INJECTION DES CRITÈRES:", extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"   🔍 Éléments critiques injectés (3): ['propreté', 'ordre', 'état']", 
                extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"   ➖ Points ignorables injectés (2): ['usure normale', 'décoration']", 
                extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"   ⚠️ Défauts fréquents injectés (4): ['taches', 'poussière', 'désordre', 'odeur']", 
                extra={'piece_id': piece_id})
    time.sleep(0.2)
    
    # Étape 3: Traitement des images
    logger.info(f"🖼️ ÉTAPE 3 - Traitement des images pour la pièce {piece_id}", 
                extra={'piece_id': piece_id})
    
    # Barre de progression pour les images
    for i in tqdm(range(5), desc=f"   Images {room_name}", leave=False, colour='cyan'):
        time.sleep(0.1)
    
    logger.info(f"✅ Traitement terminé: 5 images pour {piece_id}", extra={'piece_id': piece_id})
    time.sleep(0.2)
    
    # Étape 4: Analyse OpenAI
    logger.info(f"🔬 ÉTAPE 4 - Analyse détaillée avec critères spécifiques au type '{room_type}'", 
                extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"OpenAI request - Model: gpt-4.1-2025-04-14, Tokens: 1500", 
                extra={'piece_id': piece_id})
    time.sleep(0.5)
    
    # Simuler des erreurs/warnings si demandé
    if has_errors:
        logger.warning(f"⚠️ Qualité d'image moyenne détectée pour {piece_id}", 
                      extra={'piece_id': piece_id})
        time.sleep(0.1)
        logger.error(f"❌ Erreur lors du traitement de l'image 3 pour {piece_id}", 
                    extra={'piece_id': piece_id})
        time.sleep(0.2)
    
    # Étape 5: Parsing JSON
    logger.info(f"📋 ÉTAPE 5 - Parsing & validation JSON pour {piece_id}", 
                extra={'piece_id': piece_id})
    time.sleep(0.2)
    
    # Résultat final
    import random
    score = random.randint(6, 10) if not has_errors else random.randint(4, 7)
    anomalies = random.randint(0, 3) if not has_errors else random.randint(3, 8)
    
    logger.info(f"✅ Analyse terminée: Score {score}/10, {anomalies} problèmes détectés", 
                extra={'piece_id': piece_id})
    time.sleep(0.1)
    logger.info(f"🎉 Analyse combinée terminée avec succès pour la pièce {piece_id}", 
                extra={'piece_id': piece_id})
    time.sleep(0.3)
    
    return score, anomalies


def main():
    """Fonction principale de démonstration"""
    
    logger.info("🚀 ANALYSE COMPLÈTE démarrée pour le logement DEMO_001 (parcours: Voyageur)")
    time.sleep(0.5)
    
    # Liste des pièces à analyser
    rooms = [
        ("room_001", "Chambre principale", "chambre", False),
        ("room_002", "Cuisine", "cuisine", False),
        ("room_003", "Salle de bain", "salle de bain", True),  # Avec erreurs
        ("room_004", "Salon", "salon", False),
        ("room_005", "Toilettes", "toilettes", False),
    ]
    
    total_score = 0
    total_anomalies = 0
    
    # Analyser chaque pièce avec barre de progression globale
    print()
    for piece_id, room_name, room_type, has_errors in tqdm(
        rooms, 
        desc="🏠 Progression globale", 
        unit="pièce",
        colour='green'
    ):
        score, anomalies = simulate_room_analysis(piece_id, room_name, room_type, has_errors)
        total_score += score
        total_anomalies += anomalies
        time.sleep(0.5)
    
    # Résumé final
    avg_score = total_score / len(rooms)
    logger.info(f"🎉 ANALYSE COMPLÈTE terminée pour le logement DEMO_001")
    time.sleep(0.2)
    
    # Afficher un résumé dans une boîte
    print()
    print_summary_box("RÉSUMÉ DE L'ANALYSE", {
        "🎯 Type de parcours": "Voyageur",
        "🏠 Pièces analysées": f"{len(rooms)}",
        "📊 Score moyen": f"{avg_score:.1f}/10",
        "⚠️  Anomalies détectées": f"{total_anomalies}",
        "❌ Erreurs critiques": "1",
        "⏱️  Durée totale": "00:00:45"
    })
    
    print("\n✅ Démonstration terminée !\n")
    print("💡 Pour activer cet affichage dans votre application:")
    print("   1. pip install tqdm colorama")
    print("   2. Ajouter dans make_request.py:")
    print("      from enable_pretty_logs import enable_pretty_logs")
    print("      enable_pretty_logs()")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Démonstration interrompue\n")

