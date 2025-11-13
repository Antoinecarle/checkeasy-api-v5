# 📊 Système d'Analyse des Logs CheckEasy

Système complet de capture, analyse et visualisation des logs du terminal pour l'application CheckEasy.

## 🎯 Fonctionnalités

- ✅ **Capture automatique** des logs du terminal (stdout/stderr)
- ✅ **Sauvegarde structurée** en format texte et JSON
- ✅ **Parsing intelligent** des logs Railway (JSON) et locaux (texte coloré)
- ✅ **Analyse par pièce** avec détection automatique des étapes
- ✅ **Rapports HTML interactifs** avec code couleur et emojis
- ✅ **Barres de progression** avec tqdm pendant l'analyse
- ✅ **Liens directs** vers les lignes de logs bruts
- ✅ **Statistiques globales** et résumés détaillés

## 📦 Installation

Aucune installation supplémentaire requise si vous avez déjà les dépendances de CheckEasy.

Si besoin, installer tqdm :
```bash
pip install tqdm
```

## 🚀 Utilisation

### Méthode 1 : Intégration automatique dans make_request.py

Ajouter au début de `make_request.py` (après les imports) :

```python
from enable_log_capture import enable_log_capture
enable_log_capture()
```

Les logs seront automatiquement capturés dans `logs_output/` à chaque exécution.

### Méthode 2 : Capture manuelle

```python
from logs_analysis.terminal_logger import setup_terminal_log_capture, close_log_capture
import atexit

# Au démarrage de l'application
setup_terminal_log_capture("logs_output")
atexit.register(close_log_capture)
```

### Analyse des logs capturés

Une fois les logs capturés, générer le rapport HTML :

```bash
python analyze_logs.py logs_output/checkeasy_analysis_20241112_143022.log
```

Options disponibles :
```bash
python analyze_logs.py <fichier_log> [-o <fichier_sortie>] [--no-progress]
```

## 📁 Structure des fichiers générés

```
logs_output/
├── checkeasy_analysis_20241112_143022.log        # Logs en format texte
├── checkeasy_analysis_20241112_143022.json       # Logs en format JSON
└── checkeasy_analysis_20241112_143022_report.html # Rapport HTML interactif
```

## 📊 Format du rapport HTML

Le rapport généré contient :

### 1. Résumé Global
- Type de parcours (Voyageur/Ménage)
- Nombre de pièces analysées
- Total d'anomalies détectées
- Nombre d'erreurs et warnings
- Score moyen global
- Durée totale du traitement

### 2. Aperçu des Étapes
- ✅ Étape 1 : Classification automatique
- ✅ Étape 2 : Injection des critères
- ✅ Étape 3 : Traitement des images
- ✅ Étape 4 : Analyse OpenAI
- ✅ Étape 5 : Parsing & validation JSON
- ✅ Étape 6 : Résumé final

### 3. Analyse par Pièce
Pour chaque pièce :
- 🛏️ Emoji et nom de la pièce
- Score sur 10 avec code couleur
- Barre de progression des étapes
- Nombre d'anomalies, erreurs, warnings
- Niveau de confiance
- Détails des étapes (dépliable)
- Liste des erreurs avec liens vers les logs bruts

### 4. Erreurs Critiques
Liste des erreurs critiques détectées avec timestamps

## 🎨 Code Couleur

- 🟢 **Vert** : Succès, score élevé (≥8/10)
- 🟡 **Jaune** : Avertissement, score moyen (5-7/10)
- 🔴 **Rouge** : Erreur, score faible (<5/10)

## 🔍 Détection Automatique

Le système détecte automatiquement :

### Types de pièces
- 🛏️ Chambre
- 🍽️ Cuisine
- 🚿 Salle de bain
- 🛋️ Salon
- 🚽 Toilettes
- 🚪 Entrée
- 🚶 Couloir
- 🌿 Balcon
- 🌳 Terrasse
- 📦 Autre

### Étapes du processus
- Classification automatique
- Injection des critères
- Traitement des images
- Analyse OpenAI
- Parsing & validation JSON
- Résumé final

### Métriques
- Score de la pièce
- Nombre d'anomalies
- Niveau de confiance
- Durée de traitement

## 📝 Exemple de sortie

```
📦 LOG SUMMARY - Analyse complète du process
Type de parcours : Voyageur

Étapes principales :
1️⃣ Classification automatique ✅
2️⃣ Injection des critères ✅
3️⃣ Traitement des images ✅
4️⃣ Analyse OpenAI ✅
5️⃣ Parsing & validation ✅
6️⃣ Résumé final ✅

──────────────────────────────
🛏️ Chambre principale (ID: room_001)
├─ Étape 1 : Classification OK (95%)
├─ Étape 2 : Analyse détaillée OK
├─ Étape 3 : Parsing OK
└─ ✅ Résultat : Score 8 / 10 — 2 anomalies détectées

⚠️ Erreurs / avertissements :
* [ERR] Erreur lors du traitement de l'image
  → Fichier : logs_output/checkeasy_analysis.log ligne 243
  → [Ouvrir dans log brut](file:///logs.log#L243)

──────────────────────────────

📊 Résumé global :
* Type de parcours : Voyageur
* 5 pièces analysées
* 8 anomalies détectées
* 0 crash critique
* Score moyen : 7.8/10
* Durée totale : 00:02:34
```

## 🛠️ Architecture

```
logs_analysis/
├── __init__.py              # Module principal
├── terminal_logger.py       # Capture des logs du terminal
├── log_parser.py           # Parsing des logs (JSON/texte)
├── log_analyzer.py         # Analyse et extraction de métriques
├── report_generator.py     # Génération de rapports HTML
└── README.md              # Documentation
```

## 🔧 Personnalisation

### Modifier les emojis des pièces

Dans `log_parser.py`, modifier le dictionnaire `ROOM_EMOJI_MAP` :

```python
ROOM_EMOJI_MAP = {
    'chambre': '🛏️',
    'cuisine': '🍽️',
    # Ajouter vos propres mappings
}
```

### Modifier les étapes détectées

Dans `log_parser.py`, modifier le dictionnaire `STEP_PATTERNS` :

```python
STEP_PATTERNS = {
    'classification': r'(?:Classification|ÉTAPE 1)',
    # Ajouter vos propres patterns
}
```

### Personnaliser le CSS du rapport

Dans `report_generator.py`, modifier la méthode `_get_css()`.

## 📞 Support

Pour toute question ou problème, consulter la documentation principale de CheckEasy.

## 📄 Licence

Même licence que le projet CheckEasy principal.

