"""
Active l'affichage amélioré des logs dans le terminal
À importer au début de make_request.py

Usage:
    # Dans make_request.py, ajouter APRÈS setup_railway_logging():
    from enable_pretty_logs import enable_pretty_logs
    enable_pretty_logs()
"""

from logs_analysis.terminal_display import setup_pretty_terminal_logging


def enable_pretty_logs():
    """
    Active l'affichage amélioré des logs dans le terminal
    Affiche les logs de manière structurée, colorée et avec des emojis
    """
    setup_pretty_terminal_logging()


if __name__ == '__main__':
    print("""
╔══════════════════════════════════════════════════════════════╗
║  CheckEasy - Affichage Amélioré des Logs du Terminal        ║
╚══════════════════════════════════════════════════════════════╝

Ce module améliore l'affichage des logs directement dans le terminal.
AUCUN FICHIER N'EST CRÉÉ - juste un affichage plus clair !

📋 INSTALLATION:
   1. Installer les dépendances:
      pip install tqdm colorama
   
   2. Ajouter dans make_request.py APRÈS setup_railway_logging():
      
      from enable_pretty_logs import enable_pretty_logs
      enable_pretty_logs()

🎯 FONCTIONNALITÉS:
   ✅ Affichage structuré par pièce
   ✅ Code couleur selon le niveau (ERROR=rouge, WARNING=jaune, etc.)
   ✅ Emojis pour chaque type de pièce (🛏️ chambre, 🍽️ cuisine, etc.)
   ✅ Progression des étapes visible
   ✅ Filtrage automatique du bruit
   ✅ Résultats mis en évidence

📊 EXEMPLE D'AFFICHAGE:

══════════════════════════════════════════════════════════════════
🛏️ CHAMBRE PRINCIPALE (ID: room_001)
══════════════════════════════════════════════════════════════════

├─ 🔍 ÉTAPE 1: Classification automatique
   ✅ Classification terminée: chambre (confiance: 95%)

├─ 💉 ÉTAPE 2: Injection des critères
   💉 Injection des critères:
      🔍 3 éléments critiques
      ➖ 2 points ignorables
      ⚠️  4 défauts fréquents

├─ 🖼️ ÉTAPE 3: Traitement des images
   🤖 OpenAI: gpt-4.1-2025-04-14 (1500 tokens)

├─ 📋 ÉTAPE 5: Parsing & validation JSON

└─ 🌟 RÉSULTAT: Score 8/10 — 2 anomalies détectées

🎨 CODE COULEUR:
   🔴 Rouge   = Erreurs
   🟡 Jaune   = Warnings
   🔵 Bleu    = Étapes
   🟢 Vert    = Succès
   🟣 Magenta = OpenAI
   🔵 Cyan    = Injection critères

💡 ASTUCE:
   Les logs sont automatiquement filtrés pour ne garder que
   l'essentiel. Fini les logs verbeux et illisibles !

""")

