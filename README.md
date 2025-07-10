# CheckEasy API V5 🏠🔍

API d'analyse intelligente d'images pour l'inspection automatisée de logements avec IA.

## 🚀 Fonctionnalités

### 🔍 Analyse d'Images avec IA
- **Analyse comparative** : Compare les photos d'entrée et de sortie des pièces
- **Détection automatique** : Identifie les problèmes de propreté, dégâts, objets manquants
- **Classification intelligente** : Reconnaissance automatique du type de pièce
- **Critères spécialisés** : Chaque type de pièce a ses propres critères de vérification

### 🎯 Endpoints Principaux

| Endpoint | Description |
|----------|-------------|
| `POST /analyze` | Analyse détaillée avec critères personnalisés |
| `POST /classify-room` | Classification automatique du type de pièce |
| `POST /analyze-with-classification` | Analyse complète avec classification automatique |
| `POST /analyze-etapes` | Analyse spécifique des étapes de nettoyage |
| `POST /analyze-complete` | **🔥 Analyse exhaustive** + webhook automatique |

### 🧠 Intelligence Artificielle
- **Modèle** : GPT-4.1 Turbo et GPT-4o pour une précision maximale
- **Vision avancée** : Analyse d'images haute résolution avec détection fine
- **Prompts dynamiques** : Instructions adaptées selon le type de pièce
- **Synthèse globale** : Recommandations et score automatique du logement

## 📦 Installation

### Prérequis
- Python 3.8+
- Clé API OpenAI

### Installation locale
```bash
# Cloner le repository
git clone https://github.com/YOUR_USERNAME/checkeasy-api-v5.git
cd checkeasy-api-v5

# Installer les dépendances
pip install -r requirements.txt

# Variables d'environnement
export OPENAI_API_KEY="your-openai-api-key"

# Lancer l'API
python make_request.py
```

## 🌐 Déploiement

### Railway (Recommandé)
1. Connecter le repository GitHub à Railway
2. Définir les variables d'environnement :
   - `OPENAI_API_KEY` : Votre clé API OpenAI
   - `ENVIRONMENT` : "production" ou "staging"
   - `ROOM_TEMPLATES_CONFIG` : Configuration JSON des types de pièces (optionnel)

### Variables d'environnement

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `OPENAI_API_KEY` | Clé API OpenAI | ✅ |
| `ENVIRONMENT` | Environment (production/staging) | ❌ |
| `RAILWAY_ENVIRONMENT` | Détection auto Railway | ❌ |
| `ROOM_TEMPLATES_CONFIG` | Config JSON types de pièces | ❌ |

## 🎛️ Configuration des Types de Pièces

L'API supporte la configuration dynamique des types de pièces via l'interface d'administration.

### Interface d'Administration
Accédez à `/admin` pour gérer les types de pièces :
- ✅ Créer nouveaux types de pièces
- ✏️ Modifier les critères de vérification
- 🗑️ Supprimer des types de pièces
- 📤 Exporter la configuration pour Railway

### Types de Pièces par Défaut
- 🍽️ **Cuisine** : Joints silicone, électroménager, évacuations
- 🚿 **Salle de bain** : Étanchéité, ventilation, joints sanitaires
- 🛏️ **Chambre** : Murs, prises électriques, stores/volets
- 📦 **Autre** : Vérifications générales

## 🔗 Webhook Integration

L'API s'intègre automatiquement avec Bubble.io via webhook :

### Détection Automatique d'Environnement
- **Production** : `https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia`
- **Staging** : `https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia`

### Test du Webhook
```bash
# Tester la configuration
GET /webhook/test

# Envoyer un webhook de test
POST /webhook/test-send
```

## 📊 Format des Réponses

### Analyse Simple
```json
{
  "piece_id": "piece_001",
  "nom_piece": "Cuisine 🍽️",
  "analyse_globale": {
    "status": "attention",
    "score": 7.5,
    "temps_nettoyage_estime": "15-20 minutes",
    "commentaire_global": "Quelques détails à rectifier pour une propreté optimale"
  },
  "preliminary_issues": [...]
}
```

### Analyse Complète avec Enrichissement
```json
{
  "logement_id": "logement_123",
  "pieces_analysis": [...],
  "total_issues_count": 8,
  "analysis_enrichment": {
    "summary": {
      "missing_items": ["Vase décoratif disparu"],
      "damages": ["Aucun dégât constaté"],
      "cleanliness_issues": ["Traces sur la hotte"],
      "layout_problems": ["Lampe mal positionnée"]
    },
    "recommendations": [
      "Nettoyer la hotte aspirante en profondeur",
      "Retrouver le vase décoratif manquant",
      "..."
    ],
    "global_score": {
      "score": 3,
      "label": "BON",
      "description": "Logement en bon état avec quelques points d'attention"
    }
  }
}
```

## 🔧 Développement

### Structure du Projet
```
├── make_request.py          # API principale FastAPI
├── image_converter.py       # Traitement et conversion d'images
├── requirements.txt         # Dépendances Python
├── runtime.txt             # Version Python pour Railway
├── Procfile                # Configuration Railway
├── templates/
│   └── admin.html          # Interface d'administration
└── room_classfication/
    └── room-verification-templates.json  # Configuration types de pièces
```

### API Endpoints de Gestion
- `GET /room-templates` : Lister tous les types de pièces
- `POST /room-templates` : Créer un nouveau type
- `PUT /room-templates/{type}` : Modifier un type existant
- `DELETE /room-templates/{type}` : Supprimer un type
- `GET /room-templates/export/railway-env` : Export pour Railway

## 📝 Exemples d'Usage

### Analyse Rapide avec Classification Auto
```python
import requests

payload = {
    "piece_id": "piece_001",
    "nom": "Pièce inconnue",
    "checkin_pictures": [{"piece_id": "piece_001", "url": "image_url"}],
    "checkout_pictures": [{"piece_id": "piece_001", "url": "image_url"}]
}

response = requests.post("/analyze-with-classification", json=payload)
```

### Analyse Complète avec Webhook
```python
payload = {
    "logement_id": "logement_123",
    "rapport_id": "rapport_456", 
    "pieces": [
        {
            "piece_id": "piece_001",
            "nom": "Cuisine",
            "checkin_pictures": [...],
            "checkout_pictures": [...],
            "etapes": [
                {
                    "etape_id": "etape_001",
                    "task_name": "Nettoyer l'évier", 
                    "consigne": "Nettoyer et désinfecter l'évier",
                    "checking_picture": "url_avant",
                    "checkout_picture": "url_apres"
                }
            ]
        }
    ]
}

# Analyse complète + webhook automatique vers Bubble
response = requests.post("/analyze-complete", json=payload)
```

## 🤝 Contribution

1. Fork le projet
2. Créer une branche feature (`git checkout -b feature/AmazingFeature`)
3. Commit les changements (`git commit -m 'Add AmazingFeature'`)
4. Push sur la branche (`git push origin feature/AmazingFeature`)
5. Ouvrir une Pull Request

## 📄 Licence

Ce projet est sous licence privée. Tous droits réservés.

## 🆘 Support

Pour toute question ou problème :
- 📧 Email : support@checkeasy.com
- 🐛 Issues : [GitHub Issues](https://github.com/YOUR_USERNAME/checkeasy-api-v5/issues)

---

## 🔥 Nouveautés V5

- ✨ **Analyse avec enrichissement IA** : Synthèse globale et recommandations
- 🎯 **Classification automatique** : Reconnaissance intelligente des types de pièces  
- 🔗 **Webhook automatique** : Intégration transparente avec Bubble.io
- 🎛️ **Interface d'admin** : Gestion dynamique des configurations
- 📊 **Statistiques avancées** : Répartition des issues par type et gravité
- 🚀 **Performance optimisée** : Traitement parallèle et gestion d'erreurs robuste

**Powered by GPT-4.1 & FastAPI** 🚀 