#!/usr/bin/env python3
"""
Script de démonstration du système d'analyse des logs CheckEasy
Génère des logs de test et crée un rapport HTML
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from logs_analysis.terminal_logger import setup_terminal_log_capture, close_log_capture
from tqdm import tqdm


def simulate_room_analysis(piece_id: str, room_name: str, room_type: str):
    """Simule l'analyse d'une pièce avec logs"""
    logger = logging.getLogger(__name__)
    
    logger.info(f"🔍 Analyse de la pièce {piece_id}: {room_name}", extra={'piece_id': piece_id})
    
    # Étape 1: Classification
    logger.info(f"📊 ÉTAPE 1 - Classification automatique pour {piece_id}")
    time.sleep(0.2)
    logger.info(f"Classification terminée pour la pièce {piece_id}: {room_type} (confiance: 95%)", extra={'piece_id': piece_id})
    
    # Étape 2: Injection des critères
    logger.info(f"🔧 ÉTAPE 2 - Injection des critères automatiques dans le payload d'analyse", extra={'piece_id': piece_id})
    logger.info(f"📌 INJECTION DES CRITÈRES:", extra={'piece_id': piece_id})
    logger.info(f"   🔍 Éléments critiques injectés (3): ['propreté', 'ordre', 'état']", extra={'piece_id': piece_id})
    
    # Étape 3: Traitement des images
    logger.info(f"🖼️ Traitement des images pour la pièce {piece_id}", extra={'piece_id': piece_id})
    for i in tqdm(range(5), desc=f"Images {room_name}", leave=False):
        time.sleep(0.1)
    logger.info(f"✅ Traitement terminé: 5 images pour {piece_id}", extra={'piece_id': piece_id})
    
    # Étape 4: Analyse OpenAI
    logger.info(f"🔬 ÉTAPE 4 - Analyse détaillée avec critères spécifiques au type '{room_type}'", extra={'piece_id': piece_id})
    logger.info(f"OpenAI request - Model: gpt-4.1-2025-04-14, Tokens: 1500", extra={'piece_id': piece_id})
    time.sleep(0.3)
    
    # Simuler quelques warnings/erreurs aléatoires
    import random
    if random.random() > 0.7:
        logger.warning(f"⚠️ Qualité d'image moyenne détectée pour {piece_id}", extra={'piece_id': piece_id})
    
    if random.random() > 0.9:
        logger.error(f"❌ Erreur lors du traitement de l'image 3 pour {piece_id}", extra={'piece_id': piece_id})
    
    # Étape 5: Parsing JSON
    logger.info(f"📋 ÉTAPE 5 - Parsing & validation JSON pour {piece_id}", extra={'piece_id': piece_id})
    time.sleep(0.1)
    
    # Résultat final
    score = random.randint(6, 10)
    anomalies = random.randint(0, 5)
    logger.info(f"✅ Analyse terminée: Score {score}/10, {anomalies} problèmes détectés", extra={'piece_id': piece_id})
    logger.info(f"🎉 Analyse combinée terminée avec succès pour la pièce {piece_id}", extra={'piece_id': piece_id})
    
    return score, anomalies


def main():
    """Fonction principale de démonstration"""
    print("="*70)
    print("🚀 DÉMONSTRATION DU SYSTÈME D'ANALYSE DES LOGS CHECKEASY")
    print("="*70)
    print()
    
    # Activer la capture des logs
    log_capture = setup_terminal_log_capture("logs_output")
    
    # Configurer le logger
    logger = logging.getLogger(__name__)
    
    # Simuler une analyse complète
    logger.info("🚀 ANALYSE COMPLÈTE démarrée pour le logement LOG_DEMO_001 (parcours: Voyageur)")
    
    # Liste des pièces à analyser
    rooms = [
        ("room_001", "Chambre principale", "chambre"),
        ("room_002", "Cuisine", "cuisine"),
        ("room_003", "Salle de bain", "salle de bain"),
        ("room_004", "Salon", "salon"),
        ("room_005", "Toilettes", "toilettes"),
    ]
    
    total_score = 0
    total_anomalies = 0
    
    # Analyser chaque pièce avec barre de progression
    print("\n📊 Analyse des pièces en cours...\n")
    for piece_id, room_name, room_type in tqdm(rooms, desc="Pièces analysées"):
        score, anomalies = simulate_room_analysis(piece_id, room_name, room_type)
        total_score += score
        total_anomalies += anomalies
        time.sleep(0.2)
    
    # Résumé final
    avg_score = total_score / len(rooms)
    logger.info(f"🎉 ANALYSE COMPLÈTE terminée pour le logement LOG_DEMO_001")
    logger.info(f"📊 Résumé: {len(rooms)} pièces analysées, score moyen: {avg_score:.1f}/10, {total_anomalies} anomalies détectées")
    
    # Fermer la capture
    print("\n")
    close_log_capture()
    
    # Trouver le fichier de log généré
    logs_dir = Path("logs_output")
    log_files = sorted(logs_dir.glob("checkeasy_analysis_*.log"))
    
    if log_files:
        latest_log = log_files[-1]
        print("\n" + "="*70)
        print("📊 GÉNÉRATION DU RAPPORT")
        print("="*70)
        print(f"\n📄 Fichier de log généré: {latest_log}")
        print("\n🔍 Pour générer le rapport HTML, exécutez:")
        print(f"\n   python analyze_logs.py {latest_log}")
        print("\n" + "="*70)
        
        # Proposer de générer le rapport automatiquement
        response = input("\n❓ Voulez-vous générer le rapport HTML maintenant? (o/n): ")
        if response.lower() in ['o', 'oui', 'y', 'yes']:
            print("\n🚀 Génération du rapport en cours...\n")
            from logs_analysis.log_parser import LogParser
            from logs_analysis.log_analyzer import LogAnalyzer
            from logs_analysis.report_generator import ReportGenerator
            
            # Parser
            parser = LogParser()
            entries = parser.parse_file(str(latest_log))
            
            # Analyser
            analyzer = LogAnalyzer(entries)
            analyzer.analyze()
            
            # Générer le rapport
            report_path = latest_log.parent / f"{latest_log.stem}_report.html"
            generator = ReportGenerator(analyzer)
            generator.generate_html_report(str(report_path), str(latest_log.absolute()))
            
            print(f"\n✅ Rapport généré avec succès!")
            print(f"🌐 Ouvrez le fichier dans votre navigateur:")
            print(f"   file:///{report_path.absolute()}")
            
            # Ouvrir automatiquement dans le navigateur
            import webbrowser
            try:
                webbrowser.open(f"file:///{report_path.absolute()}")
                print("\n🌐 Rapport ouvert dans le navigateur!")
            except:
                print("\n⚠️  Impossible d'ouvrir automatiquement le navigateur")
    
    print("\n✅ Démonstration terminée!\n")


if __name__ == '__main__':
    main()

