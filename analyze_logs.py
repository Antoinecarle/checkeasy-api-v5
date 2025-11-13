#!/usr/bin/env python3
"""
Script principal pour analyser les logs capturés et générer un rapport HTML
Usage: python analyze_logs.py <fichier_log>
"""

import sys
import argparse
from pathlib import Path
from logs_analysis.log_parser import LogParser
from logs_analysis.log_analyzer import LogAnalyzer
from logs_analysis.report_generator import ReportGenerator


def main():
    parser = argparse.ArgumentParser(
        description='Analyse les logs CheckEasy et génère un rapport HTML interactif'
    )
    parser.add_argument(
        'log_file',
        type=str,
        help='Chemin vers le fichier de logs à analyser'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='Chemin du fichier HTML de sortie (par défaut: <log_file>_report.html)'
    )
    parser.add_argument(
        '--no-progress',
        action='store_true',
        help='Désactiver les barres de progression'
    )
    
    args = parser.parse_args()
    
    # Vérifier que le fichier existe
    log_path = Path(args.log_file)
    if not log_path.exists():
        print(f"❌ Erreur: Le fichier {args.log_file} n'existe pas")
        sys.exit(1)
    
    # Définir le fichier de sortie
    if args.output:
        output_path = args.output
    else:
        output_path = log_path.parent / f"{log_path.stem}_report.html"
    
    print("="*60)
    print("🚀 ANALYSE DES LOGS CHECKEASY")
    print("="*60)
    print(f"📄 Fichier d'entrée: {log_path}")
    print(f"📊 Rapport de sortie: {output_path}")
    print("="*60)
    print()
    
    # Étape 1: Parser les logs
    print("📖 Étape 1/3: Parsing des logs...")
    parser_obj = LogParser()
    entries = parser_obj.parse_file(str(log_path), show_progress=not args.no_progress)
    print(f"✅ {len(entries)} entrées de log parsées\n")
    
    # Étape 2: Analyser les logs
    print("🔍 Étape 2/3: Analyse des logs...")
    analyzer = LogAnalyzer(entries)
    rooms = analyzer.analyze(show_progress=not args.no_progress)
    print(f"✅ {len(rooms)} pièces analysées\n")
    
    # Étape 3: Générer le rapport
    print("📝 Étape 3/3: Génération du rapport HTML...")
    generator = ReportGenerator(analyzer)
    generator.generate_html_report(str(output_path), str(log_path.absolute()))
    print()
    
    # Afficher le résumé
    summary = analyzer.global_summary
    print("="*60)
    print("📊 RÉSUMÉ DE L'ANALYSE")
    print("="*60)
    print(f"🏠 Pièces analysées: {summary.total_rooms}")
    print(f"⚠️  Anomalies détectées: {summary.total_anomalies}")
    print(f"❌ Erreurs: {summary.total_errors}")
    print(f"⚡ Warnings: {summary.total_warnings}")
    print(f"📊 Score moyen: {summary.average_score:.1f}/10")
    print(f"🎯 Type de parcours: {summary.parcours_type}")
    if summary.total_duration:
        print(f"⏱️  Durée totale: {summary.total_duration}")
    print("="*60)
    print()
    print(f"✅ Rapport généré avec succès!")
    print(f"🌐 Ouvrez le fichier dans votre navigateur:")
    print(f"   file:///{output_path.absolute()}")
    print()


if __name__ == '__main__':
    main()

