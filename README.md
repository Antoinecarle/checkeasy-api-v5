# CheckEasy API V5 🏠🔍

API d'analyse intelligente d'images pour l'inspection automatisée de logements avec IA.

## 🚀 Démarrage Rapide

### Installation (3 étapes)

**1. Configurer la clé API**
```bash
# Éditer le fichier .env
nano .env

# Ajouter votre clé OpenAI
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
```

### URLs disponibles
- **Documentation API** : http://localhost:8000/docs
- **Testeur API** : http://localhost:8000/api-tester
- **Admin** : http://localhost:8000/admin

## 📚 Documentation Complète

**👉 Voir [DOCUMENTATION.md](DOCUMENTATION.md) pour :**
- Architecture détaillée
- Flux de traitement IA
- Configuration avancée
- Résolution de problèmes
- Déploiement Railway
- Et bien plus...

## 🎯 Fonctionnalités

- **Analyse comparative** : Photos AVANT/APRÈS des pièces
- **Détection automatique** : Propreté, dégâts, objets manquants
- **Classification intelligente** : Reconnaissance automatique du type de pièce
- **Synthèse globale** : Recommandations et score automatique
- **Webhook automatique** : Intégration Bubble.io

## 🧠 Technologies

- **Backend** : FastAPI (Python 3.11+)
- **IA** : GPT-4.1 Turbo et GPT-4o (OpenAI)
- **Images** : Pillow avec support HEIC, HEIF, AVIF, BMP, TIFF
- **Déploiement** : Railway

## 📡 Endpoints API

| Endpoint | Description |
|----------|-------------|
| `POST /analyze-complete` | **Principal** - Analyse exhaustive + webhook |
| `POST /analyze` | Analyse détaillée avec critères personnalisés |
| `POST /classify-room` | Classification automatique du type de pièce |
| `POST /analyze-etapes` | Analyse des étapes de nettoyage |
| `GET /docs` | Documentation Swagger interactive |

## 🧪 Tester l'API

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

**Fichiers de test disponibles** :
- `parcourtest.json` - Payload complet Voyageur
- `test_analyze_payload.json` - Test `/analyze`
- `test_etape_payload.json` - Test `/analyze-etape`

## 🔧 Structure du Projet

```
checkeasy-api-v5/
├── make_request.py              # API principale FastAPI
├── image_converter.py           # Conversion images
├── parallel_processor.py        # Traitement parallèle
├── requirements.txt             # Dépendances
├── start_local.sh              # Script démarrage
├── .env                        # Variables environnement
├── DOCUMENTATION.md            # 📚 Documentation complète
├── README.md                   # Ce fichier
├── room_classfication/         # Templates pièces
├── front/                      # Configs IA (prompts, scoring)
├── templates/                  # Interfaces HTML
├── static/                     # CSS/JS
├── logs_analysis/              # Système analyse logs
└── logs_viewer/                # Gestionnaire logs
```

## 🌐 Déploiement Railway

Voir [DOCUMENTATION.md](DOCUMENTATION.md#-déploiement-railway) pour les détails complets.

**Résumé** :
1. Connecter le repo GitHub à Railway
2. Configurer les variables d'environnement
3. Railway détecte automatiquement Python
4. Build et déploiement automatiques

## 🐛 Problèmes Courants

**Module not found** :
```bash
pip3 install -r requirements.txt
```

**OPENAI_API_KEY not found** :
```bash
cat .env | grep OPENAI_API_KEY
```

**Port 8000 déjà utilisé** :
```bash
uvicorn make_request:app --port 8001 --reload
```

👉 **Plus de solutions** : Voir [DOCUMENTATION.md](DOCUMENTATION.md#-résolution-de-problèmes)
  }
}
```

---

## 📚 Pour Aller Plus Loin

**Documentation complète** : [DOCUMENTATION.md](DOCUMENTATION.md)

**Contenu** :
- Architecture technique détaillée
- Flux de traitement IA complet
- Configuration avancée
- Système de sévérité multidimensionnel
- Résolution de problèmes
- Déploiement Railway
- Logs et monitoring
- Bonnes pratiques

---

*CheckEasy API V5 - Powered by GPT-4.1 & FastAPI* 🚀