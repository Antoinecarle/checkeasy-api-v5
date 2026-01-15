# 📚 CheckEasy API V5 - Documentation Complète

> **Dernière mise à jour** : 2026-01-14  
> **Version** : 5.0.0

---

## 🎯 Vue d'ensemble

CheckEasy API V5 est une API d'analyse intelligente d'images pour l'inspection automatisée de logements avec IA.

### Fonctionnalités principales
- **Analyse comparative** : Compare les photos AVANT/APRÈS des pièces
- **Détection automatique** : Identifie problèmes de propreté, dégâts, objets manquants
- **Classification intelligente** : Reconnaissance automatique du type de pièce
- **Synthèse globale** : Recommandations et score automatique du logement
- **Webhook automatique** : Intégration transparente avec Bubble.io

### Technologies
- **Backend** : FastAPI (Python 3.11+)
- **IA** : GPT-4.1 Turbo et GPT-4o (OpenAI)
- **Images** : Pillow avec support HEIC, HEIF, AVIF, BMP, TIFF
- **Déploiement** : Railway

---

## 🚀 Démarrage Rapide

### Prérequis
- Python 3.11+
- Clé API OpenAI

### Installation locale (3 étapes)

**1. Configurer la clé API**
```bash
# Éditer le fichier .env
nano .env

# Ajouter votre clé
OPENAI_API_KEY=sk-proj-VOTRE_CLE_ICI
VERSION=test
```

**2. Installer les dépendances**
```bash
pip3 install -r requirements.txt
```

**3. Lancer le serveur**
```bash
./start_local.sh
# OU
uvicorn make_request:app --host 0.0.0.0 --port 8000 --reload
```

### URLs disponibles
| Interface | URL | Description |
|-----------|-----|-------------|
| **Documentation API** | http://localhost:8000/docs | Swagger interactif |
| **Testeur API** | http://localhost:8000/api-tester | Interface de test |
| **Admin Templates** | http://localhost:8000/admin | Gestion templates |
| **Admin Scoring** | http://localhost:8000/scoring-admin | Gestion scoring |
| **Logs Viewer** | http://localhost:8000/logs-viewer | Logs temps réel |

---

## 📡 Endpoints API

### POST /analyze-complete
**Endpoint principal** - Analyse exhaustive + webhook automatique

**Payload** :
```json
{
  "logement_id": "string",
  "rapport_id": "string",
  "type": "Voyageur",  // ou "Ménage"
  "logement_adresse": "string",
  "date_debut": "DD/MM/YY",
  "date_fin": "DD/MM/YY",
  "operateur_nom": "string",
  "voyageur_nom": "string",
  "pieces": [
    {
      "piece_id": "string",
      "nom": "string",
      "commentaire_ia": "string",
      "checkin_pictures": [{"url": "string"}],
      "checkout_pictures": [{"url": "string"}],
      "etapes": [
        {
          "etape_id": "string",
          "task_name": "string",
          "consigne": "string",
          "checking_picture": "url",
          "checkout_picture": "url"
        }
      ]
    }
  ]
}
```

### Autres endpoints
- `POST /analyze` - Analyse détaillée avec critères personnalisés
- `POST /classify-room` - Classification automatique du type de pièce
- `POST /analyze-with-classification` - Analyse + classification
- `POST /analyze-etapes` - Analyse des étapes de nettoyage

---

## 🔄 Flux de Traitement IA

### 1. Réception du payload
- Validation du modèle Pydantic `EtapesAnalysisInput`
- Extraction des informations logement et pièces

### 2. Traitement des images
**Fichier** : `image_converter.py`

**Formats supportés nativement** : PNG, JPEG, JPG, GIF, WEBP
**Formats convertis en JPEG** : HEIC, HEIF, BMP, TIFF, TIF, AVIF

**Normalisation automatique des URLs** :
- URLs commençant par `//` → Ajout automatique de `https:`
- Exemple : `//cdn.bubble.io/image.avif` → `https://cdn.bubble.io/image.avif`
- Correction des doubles protocoles (`https:https://`)
- Nettoyage des espaces et caractères invalides

**Processus** :
- Normalisation de l'URL
- Téléchargement depuis URLs
- Détection format par signature binaire
- Conversion si nécessaire (qualité 98%)
- Upload vers service temporaire
- Retour URLs compatibles OpenAI

### 3. Analyse par pièce (parallélisée)

Pour chaque pièce, 3 étapes séquentielles :

**ÉTAPE 1 : Classification automatique**
- Fonction : `classify_room_type()` (ligne 3063)
- Utilise uniquement les `checkin_pictures`
- Charge templates depuis Railway ou fichiers locaux
- Appel GPT-4o avec vision
- Retourne : type de pièce (Cuisine, Chambre, etc.)

**ÉTAPE 2 : Analyse AVANT/APRÈS**
- Fonction : `analyze_room_with_openai()` (ligne 2500)
- Compare checkin vs checkout pictures
- Utilise prompts spécifiques au type de pièce
- Détecte : propreté, dégâts, objets manquants
- Retourne : liste d'issues avec sévérité

**ÉTAPE 3 : Analyse des étapes de nettoyage**
- Fonction : `analyze_etape_with_openai()` (ligne 4500)
- Vérifie chaque tâche (vider lave-vaisselle, etc.)
- Compare checking_picture vs checkout_picture
- Retourne : statut (fait/non fait) + commentaire

### 4. Synthèse globale
- Fonction : `generate_global_synthesis()` (ligne 5200)
- Agrège toutes les analyses
- Génère recommandations IA
- Calcule score global (/10)
- Détermine état général (Excellent, Bon, Moyen, Mauvais)

### 5. Construction du payload final
- Conserve le payload original INTACT
- Ajoute les résultats d'analyse dans chaque pièce
- Ajoute la synthèse globale

### 6. Envoi du webhook
- POST vers Bubble.io
- Retry automatique (3 tentatives)
- Logs détaillés

---

## ⚙️ Configuration

### Variables d'environnement (.env)

```bash
# Obligatoire
OPENAI_API_KEY=sk-proj-VOTRE_CLE_ICI

# Optionnel
OPENAI_MODEL=gpt-4o                    # Modèle par défaut
VERSION=test                            # Active logs détaillés
BUBBLE_WEBHOOK_URL=https://...         # URL webhook Bubble

# Configuration Railway (variables automatiques)
ROOM_TEMPLATES_CONFIG_VOYAGEUR=...     # Templates pièces Voyageur
ROOM_TEMPLATES_CONFIG_MENAGE=...       # Templates pièces Ménage
PROMPTS_CONFIG_VOYAGEUR=...            # Prompts Voyageur
PROMPTS_CONFIG_MENAGE=...              # Prompts Ménage
SCORING_CONFIG_VOYAGEUR=...            # Scoring Voyageur
SCORING_CONFIG_MENAGE=...              # Scoring Ménage
```

### Fichiers de configuration

**Templates de pièces** :
- `room_classfication/room-verification-templates-voyageur.json`
- `room_classfication/room-verification-templates-menage.json`

**Prompts IA** :
- `front/prompts-config-voyageur.json`
- `front/prompts-config-menage.json`

**Scoring** :
- `front/scoring-config-voyageur.json`
- `front/scoring-config-menage.json`

---

## 🎯 Système de Sévérité

### Parcours Voyageur (multidimensionnel)

**5 dimensions évaluées** :
1. **Impact fonctionnel** : L'objet est-il essentiel ?
2. **Valeur de remplacement** : Coût > 10€ ?
3. **Responsabilité** : Faute du voyageur ou usure normale ?
4. **Urgence** : Nécessite intervention immédiate ?
5. **Fréquence** : Problème isolé ou récurrent ?

**Niveaux de sévérité** :
- **HIGH** : 4-5 dimensions critiques (ex: TV cassée, clés perdues)
- **MEDIUM** : 2-3 dimensions critiques (ex: verre cassé, objet manquant >10€)
- **LOW** : 0-1 dimension critique (ex: lit pas fait, serviette mal pliée)

**Règles spéciales** :
- Objet manquant : MEDIUM minimum (même si <10€)
- Seuil valeur : 10€ (en dessous = LOW sauf si manquant)
- Tolérance élevée pour usage normal

### Parcours Ménage (simplifié)

**Critères** :
- **HIGH** : Problème grave nécessitant intervention
- **MEDIUM** : Problème modéré à corriger
- **LOW** : Détail mineur

---

## 🔧 Architecture Technique

### Structure du projet
```
checkeasy-api-v5/
├── make_request.py              # API principale FastAPI
├── image_converter.py           # Conversion images
├── parallel_processor.py        # Traitement parallèle
├── requirements.txt             # Dépendances Python
├── runtime.txt                  # Version Python (3.11.10)
├── Procfile                     # Config Railway
├── start_local.sh              # Script démarrage local
├── .env                        # Variables environnement
├── room_classfication/         # Templates pièces
│   ├── room-verification-templates-voyageur.json
│   └── room-verification-templates-menage.json
├── front/                      # Configs IA
│   ├── prompts-config-voyageur.json
│   ├── prompts-config-menage.json
│   ├── scoring-config-voyageur.json
│   └── scoring-config-menage.json
├── templates/                  # Interfaces HTML
│   ├── admin.html
│   ├── api-tester.html
│   ├── scoring-admin.html
│   └── logs_viewer.html
├── static/                     # CSS/JS
├── logs_analysis/              # Système analyse logs
└── logs_viewer/                # Gestionnaire logs
```

### Fichiers principaux

**make_request.py** (~7000 lignes)
- Tous les endpoints FastAPI
- Logique métier complète
- Gestion erreurs et fallbacks
- Système de logging
- Webhooks Bubble

**image_converter.py** (~500 lignes)
- Conversion formats images
- Support HEIC, HEIF, AVIF, BMP, TIFF
- Optimisation pour OpenAI
- Upload service temporaire

**parallel_processor.py**
- Traitement parallèle des pièces
- Gestion cache résultats
- Optimisation performances

---

## 🐛 Résolution de Problèmes

### Erreur : "Module not found"
```bash
pip3 install -r requirements.txt
```

### Erreur : "OPENAI_API_KEY not found"
```bash
# Vérifier le fichier .env
cat .env | grep OPENAI_API_KEY

# Ou exporter manuellement
export OPENAI_API_KEY=sk-proj-VOTRE_CLE_ICI
```

### Erreur : "Port 8000 already in use"
```bash
# Changer le port
uvicorn make_request:app --host 0.0.0.0 --port 8001 --reload
```

### Images AVIF non supportées
- Vérifier Pillow >= 10.0.0 : `pip show Pillow`
- Installer libavif si nécessaire (optionnel)

### Webhook ne fonctionne pas
- Vérifier `BUBBLE_WEBHOOK_URL` dans .env
- Consulter les logs : http://localhost:8000/logs-viewer
- Vérifier les retry (3 tentatives automatiques)

---

## 📊 Logs et Monitoring

### Système de logs structurés

**Niveaux** :
- 🟢 **INFO** : Informations générales
- 🟡 **WARNING** : Avertissements
- 🔴 **ERROR** : Erreurs

**Visualisation** :
- Terminal : logs en temps réel
- Interface web : http://localhost:8000/logs-viewer
- Fichiers : sauvegarde automatique

### Logs Analysis

**Module** : `logs_analysis/`

**Fonctionnalités** :
- Capture automatique stdout/stderr
- Parsing logs Railway (JSON) et locaux (texte)
- Analyse par pièce avec détection étapes
- Rapports HTML interactifs
- Statistiques globales

**Utilisation** :
```python
from logs_analysis import TerminalLogger

# Capturer les logs
logger = TerminalLogger()
logger.start_capture()
# ... exécuter code ...
logger.stop_capture()
logger.save_logs("logs/session.txt")
```

---

## 🚀 Déploiement Railway

### Configuration

**Fichiers requis** :
- `Procfile` : `web: uvicorn make_request:app --host 0.0.0.0 --port $PORT`
- `runtime.txt` : `python-3.11.10`
- `requirements.txt` : toutes les dépendances

**Variables d'environnement Railway** :
- `OPENAI_API_KEY` : Clé API OpenAI
- `VERSION` : `production` ou `test`
- `BUBBLE_WEBHOOK_URL` : URL webhook Bubble
- Configs JSON (templates, prompts, scoring)

### Déploiement

1. Connecter le repo GitHub à Railway
2. Configurer les variables d'environnement
3. Railway détecte automatiquement Python
4. Build et déploiement automatiques

### Monitoring

- Logs Railway : dashboard Railway
- Métriques : CPU, RAM, requêtes
- Alertes : erreurs critiques

---

## 📝 Changelog Important

### 2026-01-14 : Support AVIF
- Ajout format AVIF dans `CONVERSION_FORMATS`
- Conversion automatique AVIF → JPEG
- Tests complets

### 2026-01-14 : Classification checkin_pictures uniquement
- Classification basée sur photos AVANT uniquement
- Plus de confusion avec photos APRÈS
- Précision améliorée

### 2026-01-14 : Système sévérité multidimensionnel Voyageur
- 5 dimensions d'évaluation
- Seuil 10€ pour objets manquants/endommagés
- Tolérance zéro objets manquants (MEDIUM minimum)
- Critères souples pour usage normal

---

## 🧪 Tests

### Fichiers de test disponibles
- `parcourtest.json` : Payload complet Voyageur
- `test_analyze_payload.json` : Test `/analyze`
- `test_etape_payload.json` : Test `/analyze-etape`

### Tester l'API

**Interface graphique** :
```
http://localhost:8000/api-tester
```

**cURL** :
```bash
curl -X POST "http://localhost:8000/analyze-complete" \
  -H "Content-Type: application/json" \
  -d @parcourtest.json
```

**Python** :
```python
import requests
response = requests.post(
    'http://localhost:8000/analyze-complete',
    json=payload
)
print(response.json())
```

---

## 📚 Informations Complémentaires

### Modèles OpenAI utilisés

**Classification pièces** : GPT-4o (rapide, vision)
**Analyse AVANT/APRÈS** : GPT-4.1 Turbo (précision maximale)
**Analyse étapes** : GPT-4o (équilibre vitesse/qualité)
**Synthèse globale** : GPT-4.1 Turbo (raisonnement avancé)

### Limites connues

- **Taille images** : Max 20MB par image
- **Timeout** : 5 minutes par analyse complète
- **Formats** : Tous formats convertis en JPEG (perte qualité minime)
- **Parallélisation** : Max 5 pièces simultanées

### Performance

- **Analyse 1 pièce** : ~15-30 secondes
- **Analyse 5 pièces** : ~45-90 secondes (parallèle)
- **Conversion image** : ~1-3 secondes
- **Webhook** : ~1-2 secondes

---

## 🎯 Bonnes Pratiques

### Modification des prompts

1. Utiliser l'interface admin : http://localhost:8000/admin
2. Tester avec payloads de test
3. Vérifier les résultats avant production
4. Sauvegarder backup avant modification

### Modification des templates pièces

1. Respecter la structure JSON existante
2. Tester la classification après modification
3. Vérifier tous les types de pièces

### Debugging

1. Activer `VERSION=test` pour logs détaillés
2. Utiliser logs-viewer pour visualisation
3. Consulter les logs Railway en production
4. Tester localement avant déploiement

---

## 📞 Support

### En cas de problème

1. Consulter cette documentation
2. Vérifier les logs : http://localhost:8000/logs-viewer
3. Tester avec payloads d'exemple
4. Vérifier configuration .env
5. Consulter documentation OpenAI

### Ressources

- **Documentation FastAPI** : https://fastapi.tiangolo.com
- **Documentation OpenAI** : https://platform.openai.com/docs
- **Documentation Pillow** : https://pillow.readthedocs.io
- **Railway Docs** : https://docs.railway.app

---

*Documentation générée le 2026-01-14 - CheckEasy API V5*

