#!/usr/bin/env python3
"""
Script rapide pour analyser le dernier fichier de log généré
Usage: python quick_analyze.py
"""

import sys
from pathlib import Path
import webbrowser
from logs_analysis.log_parser import LogParser
from logs_analysis.log_analyzer import LogAnalyzer
from logs_analysis.report_generator import ReportGenerator


def find_latest_log(log_dir: str = "logs_output") -> Path:
    """Trouve le dernier fichier de log généré"""
    logs_path = Path(log_dir)
    
    if not logs_path.exists():
        print(f"❌ Le dossier {log_dir} n'existe pas")
        print(f"💡 Assurez-vous d'avoir exécuté l'application avec la capture de logs activée")
        sys.exit(1)
    
    # Chercher les fichiers .log
    log_files = sorted(logs_path.glob("checkeasy_analysis_*.log"))
    
    if not log_files:
        print(f"❌ Aucun fichier de log trouvé dans {log_dir}")
        print(f"💡 Exécutez d'abord l'application ou lancez: python demo_log_analysis.py")
        sys.exit(1)
    
    return log_files[-1]


def main():
    print("="*70)
    print("⚡ ANALYSE RAPIDE DES LOGS CHECKEASY")
    print("="*70)
    print()
    
    # Trouver le dernier fichier de log
    print("🔍 Recherche du dernier fichier de log...")
    latest_log = find_latest_log()
    print(f"✅ Fichier trouvé: {latest_log}")
    print(f"📅 Taille: {latest_log.stat().st_size / 1024:.1f} KB")
    print()
    
    # Demander confirmation
    response = input("❓ Analyser ce fichier et générer le rapport HTML? (o/n): ")
    if response.lower() not in ['o', 'oui', 'y', 'yes', '']:
        print("❌ Analyse annulée")
        sys.exit(0)
    
    print()
    print("="*70)
    print("🚀 ANALYSE EN COURS")
    print("="*70)
    print()
    
    # Étape 1: Parser
    print("📖 Étape 1/3: Parsing des logs...")
    parser = LogParser()
    entries = parser.parse_file(str(latest_log), show_progress=True)
    print(f"✅ {len(entries)} entrées parsées\n")
    
    # Étape 2: Analyser
    print("🔍 Étape 2/3: Analyse des données...")
    analyzer = LogAnalyzer(entries)
    rooms = analyzer.analyze(show_progress=True)
    print(f"✅ {len(rooms)} pièces analysées\n")
    
    # Étape 3: Générer le rapport
    print("📝 Étape 3/3: Génération du rapport HTML...")
    report_path = latest_log.parent / f"{latest_log.stem}_report.html"
    generator = ReportGenerator(analyzer)
    generator.generate_html_report(str(report_path), str(latest_log.absolute()))
    print()
    
    # Afficher le résumé
    summary = analyzer.global_summary
    print("="*70)
    print("📊 RÉSUMÉ DE L'ANALYSE")
    print("="*70)
    print(f"🎯 Type de parcours: {summary.parcours_type}")
    print(f"🏠 Pièces analysées: {summary.total_rooms}")
    print(f"⚠️  Anomalies détectées: {summary.total_anomalies}")
    print(f"❌ Erreurs: {summary.total_errors}")
    print(f"⚡ Warnings: {summary.total_warnings}")
    print(f"📊 Score moyen: {summary.average_score:.1f}/10")
    if summary.total_duration:
        print(f"⏱️  Durée totale: {summary.total_duration}")
    print("="*70)
    print()
    
    # Afficher les erreurs critiques
    if summary.critical_errors:
        print("🚨 ERREURS CRITIQUES DÉTECTÉES:")
        for i, error in enumerate(summary.critical_errors[:5], 1):
            print(f"   {i}. {error.message[:100]}...")
        if len(summary.critical_errors) > 5:
            print(f"   ... et {len(summary.critical_errors) - 5} autres erreurs")
        print()
    
    # Afficher le top 3 des pièces avec le plus d'erreurs
    rooms_with_errors = [(room.piece_id, room.room_name, len(room.errors)) 
                         for room in rooms.values() if room.errors]
    if rooms_with_errors:
        rooms_with_errors.sort(key=lambda x: x[2], reverse=True)
        print("🔴 TOP 3 DES PIÈCES AVEC LE PLUS D'ERREURS:")
        for i, (piece_id, room_name, error_count) in enumerate(rooms_with_errors[:3], 1):
            print(f"   {i}. {room_name} ({piece_id}): {error_count} erreurs")
        print()
    
    # Afficher le top 3 des meilleures pièces
    rooms_with_scores = [(room.piece_id, room.room_name, room.score) 
                         for room in rooms.values() if room.score is not None]
    if rooms_with_scores:
        rooms_with_scores.sort(key=lambda x: x[2], reverse=True)
        print("🌟 TOP 3 DES MEILLEURES PIÈCES:")
        for i, (piece_id, room_name, score) in enumerate(rooms_with_scores[:3], 1):
            print(f"   {i}. {room_name} ({piece_id}): {score}/10")
        print()
    
    print("="*70)
    print("✅ RAPPORT GÉNÉRÉ AVEC SUCCÈS!")
    print("="*70)
    print(f"\n📄 Fichier de log: {latest_log}")
    print(f"📊 Rapport HTML: {report_path}")
    print(f"\n🌐 URL du rapport:")
    print(f"   file:///{report_path.absolute()}")
    print()
    
    # Proposer d'ouvrir dans le navigateur
    response = input("❓ Ouvrir le rapport dans le navigateur? (o/n): ")
    if response.lower() in ['o', 'oui', 'y', 'yes', '']:
        try:
            webbrowser.open(f"file:///{report_path.absolute()}")
            print("✅ Rapport ouvert dans le navigateur!")
        except Exception as e:
            print(f"❌ Impossible d'ouvrir le navigateur: {e}")
            print(f"💡 Ouvrez manuellement le fichier: {report_path}")
    
    print("\n🎉 Analyse terminée!\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Analyse interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur lors de l'analyse: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

