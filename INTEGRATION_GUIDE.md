# 🚀 Guide d'Intégration du Système d'Analyse des Logs

Ce guide explique comment intégrer le système d'analyse des logs dans CheckEasy.

## 📋 Table des matières

1. [Installation rapide](#installation-rapide)
2. [Intégration dans make_request.py](#intégration-dans-make_requestpy)
3. [Utilisation](#utilisation)
4. [Exemples](#exemples)
5. [Personnalisation](#personnalisation)

---

## 🎯 Installation rapide

### Étape 1 : Installer les dépendances

```bash
pip install tqdm
```

Ou mettre à jour depuis `requirements.txt` :

```bash
pip install -r requirements.txt
```

### Étape 2 : Tester le système

Exécuter la démonstration :

```bash
python demo_log_analysis.py
```

Cela va :
- ✅ Générer des logs de test
- ✅ Créer un fichier de log dans `logs_output/`
- ✅ Proposer de générer un rapport HTML
- ✅ Ouvrir le rapport dans votre navigateur

---

## 🔧 Intégration dans make_request.py

### Option 1 : Intégration automatique (RECOMMANDÉ)

Ajouter **au tout début** de `make_request.py`, juste après les imports :

```python
# ========== IMPORTS EXISTANTS ==========
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
# ... autres imports ...

# ========== ACTIVATION CAPTURE DES LOGS ==========
from enable_log_capture import enable_log_capture
enable_log_capture()  # Active la capture automatique des logs

# ========== RESTE DU CODE ==========
# Configuration logging existante...
setup_railway_logging()
# ...
```

**C'est tout !** Les logs seront automatiquement capturés à chaque exécution.

### Option 2 : Intégration manuelle avec contrôle

Si vous voulez plus de contrôle, utilisez cette approche :

```python
import os
from logs_analysis.terminal_logger import setup_terminal_log_capture, close_log_capture
import atexit

# Activer uniquement en mode développement
if os.getenv('ENABLE_LOG_CAPTURE', 'false').lower() == 'true':
    setup_terminal_log_capture("logs_output")
    atexit.register(close_log_capture)
    print("📝 Capture des logs activée")
```

Puis lancer avec :

```bash
ENABLE_LOG_CAPTURE=true python make_request.py
```

### Option 3 : Intégration conditionnelle (Railway vs Local)

```python
import os
import sys
from logs_analysis.terminal_logger import setup_terminal_log_capture, close_log_capture
import atexit

# Détecter l'environnement
is_railway = any([
    os.environ.get('RAILWAY_ENVIRONMENT'),
    os.environ.get('RAILWAY_PUBLIC_DOMAIN'),
    not sys.stderr.isatty()
])

# Activer la capture uniquement en local
if not is_railway:
    setup_terminal_log_capture("logs_output")
    atexit.register(close_log_capture)
    print("📝 Capture des logs activée (mode local)")
```

---

## 📊 Utilisation

### 1. Lancer l'application avec capture

```bash
# Méthode normale
python make_request.py

# Ou avec uvicorn
uvicorn make_request:app --reload
```

Les logs seront automatiquement sauvegardés dans `logs_output/`.

### 2. Analyser les logs capturés

Une fois l'analyse terminée, générer le rapport :

```bash
python analyze_logs.py logs_output/checkeasy_analysis_20241112_143022.log
```

### 3. Ouvrir le rapport HTML

Le rapport sera généré dans le même dossier :

```
logs_output/checkeasy_analysis_20241112_143022_report.html
```

Ouvrir ce fichier dans votre navigateur pour voir le rapport interactif.

---

## 💡 Exemples

### Exemple 1 : Analyse d'un logement complet

```python
# Dans votre code
logger.info("🚀 ANALYSE COMPLÈTE démarrée pour le logement LOG123 (parcours: Voyageur)")

for piece in pieces:
    logger.info(f"🔍 Analyse de la pièce {piece.piece_id}: {piece.nom}", 
                extra={'piece_id': piece.piece_id})
    
    # Classification
    logger.info(f"📊 ÉTAPE 1 - Classification automatique pour {piece.piece_id}")
    result = classify_room_type(piece)
    logger.info(f"Classification terminée: {result.room_type} (confiance: {result.confidence}%)",
                extra={'piece_id': piece.piece_id})
    
    # Analyse
    logger.info(f"🔬 ÉTAPE 4 - Analyse détaillée", extra={'piece_id': piece.piece_id})
    analysis = analyze_images(piece)
    logger.info(f"✅ Analyse terminée: Score {analysis.score}/10, {len(analysis.issues)} problèmes",
                extra={'piece_id': piece.piece_id})

logger.info("🎉 ANALYSE COMPLÈTE terminée")
```

Le rapport généré affichera automatiquement :
- ✅ Toutes les pièces analysées
- ✅ Progression de chaque étape
- ✅ Scores et anomalies
- ✅ Erreurs et warnings

### Exemple 2 : Ajouter des barres de progression avec tqdm

```python
from tqdm import tqdm

# Lors du traitement des images
for image in tqdm(images, desc="Traitement des images", unit="img"):
    process_image(image)

# Lors de l'analyse des pièces
for piece in tqdm(pieces, desc="Analyse des pièces", unit="pièce"):
    analyze_piece(piece)
```

### Exemple 3 : Logs structurés avec contexte

```python
# Utiliser les fonctions helper existantes avec extra data
logger.info("Traitement de l'image", extra={
    'piece_id': 'room_001',
    'operation': 'image_processing',
    'endpoint': '/analyze'
})
```

---

## 🎨 Personnalisation

### Changer le répertoire de sortie

```python
enable_log_capture(log_dir="mes_logs_custom")
```

### Ajouter des emojis personnalisés pour les pièces

Éditer `logs_analysis/log_parser.py` :

```python
ROOM_EMOJI_MAP = {
    'chambre': '🛏️',
    'cuisine': '🍽️',
    'bureau': '💼',  # Ajouter vos types
    'garage': '🚗',
    # ...
}
```

### Modifier les étapes détectées

Éditer `logs_analysis/log_parser.py` :

```python
STEP_PATTERNS = {
    'classification': r'(?:Classification|ÉTAPE 1|classify_room_type)',
    'ma_nouvelle_etape': r'(?:Mon pattern|ÉTAPE X)',
    # ...
}
```

Puis dans `logs_analysis/log_analyzer.py` :

```python
STEP_ORDER = [
    'classification',
    'ma_nouvelle_etape',
    # ...
]

STEP_NAMES = {
    'classification': 'Classification automatique',
    'ma_nouvelle_etape': 'Ma nouvelle étape',
    # ...
}
```

### Personnaliser le style du rapport HTML

Éditer `logs_analysis/report_generator.py`, méthode `_get_css()` :

```python
def _get_css(self) -> str:
    return """
    /* Votre CSS personnalisé */
    body {
        background: linear-gradient(135deg, #votre_couleur1, #votre_couleur2);
    }
    /* ... */
    """
```

---

## 🔍 Débogage

### Les logs ne sont pas capturés

Vérifier que :
1. ✅ `enable_log_capture()` est appelé **avant** `setup_railway_logging()`
2. ✅ Le dossier `logs_output/` existe et est accessible en écriture
3. ✅ Les logs utilisent bien le logger Python standard (`logging.getLogger()`)

### Le rapport ne s'affiche pas correctement

1. ✅ Vérifier que le fichier HTML est bien généré
2. ✅ Ouvrir avec un navigateur moderne (Chrome, Firefox, Edge)
3. ✅ Vérifier la console du navigateur pour les erreurs JavaScript

### Les étapes ne sont pas détectées

1. ✅ Vérifier que les messages de log contiennent les patterns définis dans `STEP_PATTERNS`
2. ✅ Ajouter des logs explicites pour chaque étape
3. ✅ Utiliser les emojis et mots-clés définis dans les patterns

---

## 📞 Support

Pour toute question :
1. Consulter le [README.md](logs_analysis/README.md) du module
2. Exécuter `python demo_log_analysis.py` pour voir un exemple complet
3. Vérifier les logs dans `logs_output/`

---

## ✅ Checklist d'intégration

- [ ] Installer `tqdm` : `pip install tqdm`
- [ ] Ajouter `enable_log_capture()` dans `make_request.py`
- [ ] Tester avec `python demo_log_analysis.py`
- [ ] Lancer l'application et vérifier que les logs sont capturés
- [ ] Générer un rapport avec `python analyze_logs.py <fichier_log>`
- [ ] Ouvrir le rapport HTML dans le navigateur
- [ ] Personnaliser si nécessaire (emojis, étapes, CSS)

---

**🎉 Félicitations ! Le système d'analyse des logs est maintenant intégré !**

