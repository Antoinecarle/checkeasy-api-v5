"""
Script pour activer la capture des logs du terminal
À importer au début de make_request.py ou à exécuter avant de lancer l'application

Usage:
    # Dans make_request.py, ajouter en haut du fichier:
    from enable_log_capture import enable_log_capture
    enable_log_capture()
"""

import os
import sys
from logs_analysis.terminal_logger import setup_terminal_log_capture, close_log_capture
import atexit


def enable_log_capture(log_dir: str = "logs_output"):
    """
    Active la capture automatique des logs du terminal
    
    Args:
        log_dir: Répertoire où sauvegarder les logs (défaut: logs_output)
    """
    # Créer le répertoire si nécessaire
    os.makedirs(log_dir, exist_ok=True)
    
    # Configurer la capture
    log_capture = setup_terminal_log_capture(log_dir)
    
    # Enregistrer la fermeture automatique à la fin du programme
    atexit.register(close_log_capture)
    
    print("✅ Capture des logs activée!")
    print(f"📁 Les logs seront sauvegardés dans: {log_dir}/")
    print()
    
    return log_capture


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════╗
║  CheckEasy - Système de Capture et Analyse des Logs         ║
╚══════════════════════════════════════════════════════════════╝

Ce module permet de capturer automatiquement tous les logs du terminal
et de générer des rapports HTML interactifs.

📋 INSTALLATION:
   1. Ajouter au début de make_request.py:
      
      from enable_log_capture import enable_log_capture
      enable_log_capture()
   
   2. Les logs seront automatiquement capturés dans logs_output/

📊 ANALYSE:
   Une fois les logs capturés, générer le rapport avec:
   
   python analyze_logs.py logs_output/checkeasy_analysis_XXXXXX.log

🎯 FONCTIONNALITÉS:
   ✅ Capture automatique de tous les logs (INFO, WARNING, ERROR)
   ✅ Sauvegarde en format texte ET JSON
   ✅ Génération de rapports HTML interactifs
   ✅ Visualisation par pièce avec progression
   ✅ Détection automatique des erreurs et anomalies
   ✅ Liens directs vers les lignes de logs
   ✅ Statistiques globales et résumés

📁 STRUCTURE:
   logs_output/
   ├── checkeasy_analysis_20241112_143022.log    (format texte)
   ├── checkeasy_analysis_20241112_143022.json   (format JSON)
   └── checkeasy_analysis_20241112_143022_report.html (rapport)

""")

