# 📋 API Documentation - CheckEasy V5

## 🌐 Service URL
**Production:** `https://admin-staging-454a.up.railway.app/`

## 📖 Vue d'ensemble

Cette API analyse les différences entre les photos d'entrée et de sortie d'une pièce pour le nettoyage professionnel. Elle utilise l'IA pour détecter automatiquement le type de pièce et appliquer les critères de vérification appropriés.

### 🔧 Fonctionnalités principales
- 🔍 **Classification automatique** du type de pièce
- 📊 **Analyse détaillée** avec critères personnalisés
- 🎯 **Analyse combinée** (classification + analyse en une requête)
- ⚡ **Optimisation** avec critères spécialisés par type de pièce

---

## 🛠️ Endpoints disponibles

### 1. 📊 Analyse standard
**POST** `/analyze`

Analyse les photos avec des critères personnalisés définis manuellement.

#### URL complète
```
https://admin-staging-454a.up.railway.app/analyze
```

#### Payload d'exemple
```json
{
  "piece_id": "chambre_001",
  "nom": "Chambre principale",
  "commentaire_ia": "Ne pas signaler les légères traces sur les murs blancs",
  "checkin_pictures": [
    {
      "piece_id": "chambre_001",
      "url": "https://example.com/checkin1.jpg"
    },
    {
      "piece_id": "chambre_001", 
      "url": "https://example.com/checkin2.jpg"
    }
  ],
  "checkout_pictures": [
    {
      "piece_id": "chambre_001",
      "url": "https://example.com/checkout1.jpg"
    },
    {
      "piece_id": "chambre_001",
      "url": "https://example.com/checkout2.jpg"
    }
  ],
  "elements_critiques": [
    "Murs (trous, impacts)",
    "Prises électriques",
    "Stores/volets"
  ],
  "points_ignorables": [
    "Traces légères aux murs",
    "Petites marques sur plinthes"
  ],
  "defauts_frequents": [
    "Traces de meubles",
    "Impacts portes",
    "Trous fixations"
  ]
}
```

#### Réponse exemple
```json
{
  "piece_id": "chambre_001",
  "nom_piece": "Chambre principale",
  "analyse_globale": {
    "status": "attention",
    "score": 7.5,
    "temps_nettoyage_estime": "15 minutes",
    "commentaire_global": "La pièce est globalement propre avec quelques détails mineurs à rectifier comme des traces de doigts sur les interrupteurs."
  },
  "preliminary_issues": [
    {
      "description": "Traces de doigts visibles sur l'interrupteur principal près de la porte d'entrée",
      "category": "cleanliness",
      "severity": "low",
      "confidence": 90
    },
    {
      "description": "Trou de fixation de 2mm visible dans le mur à droite de la fenêtre",
      "category": "damage",
      "severity": "medium",
      "confidence": 95
    }
  ]
}
```

---

### 2. 🔍 Classification de pièce
**POST** `/classify-room`

Détermine automatiquement le type de pièce et retourne les critères de vérification appropriés.

#### URL complète
```
https://admin-staging-454a.up.railway.app/classify-room
```

#### Payload d'exemple
```json
{
  "piece_id": "piece_inconnue_001",
  "nom": "",
  "checkin_pictures": [
    {
      "piece_id": "piece_inconnue_001",
      "url": "https://example.com/unknown_room1.jpg"
    },
    {
      "piece_id": "piece_inconnue_001",
      "url": "https://example.com/unknown_room2.jpg"
    }
  ],
  "checkout_pictures": []
}
```

#### Réponse exemple
```json
{
  "piece_id": "piece_inconnue_001",
  "room_type": "cuisine",
  "room_name": "Cuisine",
  "room_icon": "🍽️",
  "confidence": 95,
  "verifications": {
    "elements_critiques": [
      "Joints silicone évier",
      "État robinetterie", 
      "Évacuations",
      "Électroménager"
    ],
    "points_ignorables": [
      "Petites traces sur murs",
      "Variations couleur joints"
    ],
    "defauts_frequents": [
      "Moisissures sous évier",
      "Joints noircis",
      "Traces de calcaire"
    ]
  }
}
```

---

### 4. 🎯 Analyse des étapes
**POST** `/analyze-etapes`

Analyse spécifiquement les étapes de nettoyage en comparant les photos "avant" et "après" selon les consignes spécifiques de chaque tâche. Cet endpoint se concentre exclusivement sur la vérification de l'exécution des tâches individuelles.

#### URL complète
```
https://admin-staging-454a.up.railway.app/analyze-etapes
```

#### Payload d'exemple
```json
{
  "logement_id": "1745691114127x167355942685376500",
  "pieces": [
    {
      "piece_id": "1745856961367x853186102447308800",
      "nom": "Cuisine",
      "commentaire_ia": "Insister sur le rangement des placards",
      "checkin_pictures": [
        {
          "piece_id": "1745856961367x853186102447308800",
          "url": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1745926170630x630331492662763400/image.jpg"
        }
      ],
      "checkout_pictures": [
        {
          "piece_id": "1745856961367x853186102447308800",
          "url": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1746101804276x940176071591078300/image.jpg"
        }
      ],
      "etapes": [
        {
          "etape_id": "1745857142659x605188923525693400",
          "task_name": "Vider le lave vaisselle",
          "consigne": "vider la vaisselle",
          "checking_picture": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1745857158831x399350816269492540/Capture%20d%E2%80%99e%CC%81cran%202025-04-16%20a%CC%80%2018.15.08.png",
          "checkout_picture": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1746101815112x250855831291396640/image.jpg"
        },
        {
          "etape_id": "1745857142659x605188923525693401",
          "task_name": "Nettoyer plan de travail",
          "consigne": "nettoyer et désinfecter le plan de travail",
          "checking_picture": "https://example.com/before_counter.jpg",
          "checkout_picture": "https://example.com/after_counter.jpg"
        }
      ]
    }
  ]
}
```

#### Réponse exemple
```json
{
  "preliminary_issues": [
    {
      "etape_id": "1745857142659x605188923525693400",
      "description": "La vaisselle n'a pas été complètement vidée du lave-vaisselle - quelques assiettes restent dans le bac inférieur",
      "category": "cleanliness",
      "severity": "medium",
      "confidence": 85
    },
    {
      "etape_id": "1745857142659x605188923525693401", 
      "description": "Des traces de liquide sont encore visibles sur le plan de travail près de l'évier",
      "category": "cleanliness",
      "severity": "low",
      "confidence": 78
    }
  ]
}
```

#### Caractéristiques spécifiques :
- **🎯 Focus exclusif** : Analyse uniquement la tâche spécifiée dans la consigne
- **🔍 Comparaison précise** : Compare méthodiquement la photo avant (checking_picture) avec la photo après (checkout_picture)
- **📝 Signalement ciblé** : Ne remonte que les problèmes directement liés à la consigne de l'étape
- **⚡ Analyse indépendante** : Chaque étape est analysée séparément sans influence des autres
- **🚫 Ignore le superflu** : Éléments non liés à la consigne spécifique ignorés

#### Types de consignes supportées :
- **Nettoyage** : "nettoyer le lavabo", "désinfecter les surfaces"
- **Rangement** : "vider la vaisselle", "ranger les objets"
- **Organisation** : "plier et ranger le linge", "organiser les produits"
- **Vérification** : "vérifier l'état des joints", "contrôler la propreté"

#### Catégories d'issues détectées :
- `cleanliness` : Problèmes de propreté et hygiène
- `positioning` : Mauvais positionnement ou rangement
- `missing_item` : Éléments manquants ou non traités  
- `damage` : Dégâts ou détériorations
- `added_item` : Éléments ajoutés incorrectement
- `image_quality` : Problèmes de qualité d'image empêchant l'analyse

#### Niveaux de sévérité :
- `low` : Problème mineur, recommandation d'amélioration
- `medium` : Problème modéré nécessitant attention
- `high` : Problème majeur nécessitant intervention immédiate

---

### 5. 🎯 Analyse complète (ENDPOINT FINAL - RECOMMANDÉ)
**POST** `/analyze-complete`

**L'endpoint ultime qui combine TOUTES les analyses** : classification automatique + analyse détaillée des pièces + analyse spécifique des étapes. Retourne un résultat unifié avec toutes les issues regroupées.

#### URL complète
```
https://admin-staging-454a.up.railway.app/analyze-complete
```

#### Payload d'exemple
```json
{
  "logement_id": "1745691114127x167355942685376500",
  "pieces": [
    {
      "piece_id": "1745856961367x853186102447308800",
      "nom": "Cuisine",
      "commentaire_ia": "Attention particulière aux détails de propreté",
      "checkin_pictures": [
        {
          "piece_id": "1745856961367x853186102447308800",
          "url": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1745926170630x630331492662763400/image.jpg"
        }
      ],
      "checkout_pictures": [
        {
          "piece_id": "1745856961367x853186102447308800",
          "url": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1746101804276x940176071591078300/image.jpg"
        }
      ],
      "etapes": [
        {
          "etape_id": "1745857142659x605188923525693400",
          "task_name": "Vider le lave vaisselle",
          "consigne": "vider la vaisselle",
          "checking_picture": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1745857158831x399350816269492540/Capture%20d%E2%80%99e%CC%81cran%202025-04-16%20a%CC%80%2018.15.08.png",
          "checkout_picture": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1746101815112x250855831291396640/image.jpg"
        },
        {
          "etape_id": "1745857142659x605188923525693401",
          "task_name": "Nettoyer plan de travail",
          "consigne": "nettoyer et désinfecter le plan de travail",
          "checking_picture": "https://example.com/before_counter.jpg",
          "checkout_picture": "https://example.com/after_counter.jpg"
        }
      ]
    }
  ]
}
```

#### Réponse exemple
```json
{
  "logement_id": "1745691114127x167355942685376500",
  "pieces_analysis": [
    {
      "piece_id": "1745856961367x853186102447308800",
      "nom_piece": "Cuisine 🍽️",
      "room_classification": {
        "piece_id": "1745856961367x853186102447308800",
        "room_type": "cuisine",
        "room_name": "Cuisine",
        "room_icon": "🍽️",
        "confidence": 95,
        "verifications": {
          "elements_critiques": ["Joints silicone évier", "État robinetterie"],
          "points_ignorables": ["Petites traces sur murs"],
          "defauts_frequents": ["Traces de calcaire"]
        }
      },
      "analyse_globale": {
        "status": "attention",
        "score": 7.5,
        "temps_nettoyage_estime": "20 minutes",
        "commentaire_global": "La cuisine est globalement propre avec quelques détails à rectifier."
      },
      "preliminary_issues": [
        {
          "description": "Traces de graisse visibles sur la hotte aspirante",
          "category": "cleanliness",
          "severity": "medium",
          "confidence": 85
        }
      ]
    }
  ],
     "preliminary_issues": [
     {
       "description": "[Cuisine 🍽️] Traces de graisse visibles sur la hotte aspirante",
       "category": "cleanliness", 
       "severity": "medium",
       "confidence": 85
     },
     {
       "description": "[ÉTAPE] La vaisselle n'a pas été complètement vidée du lave-vaisselle",
       "category": "cleanliness",
       "severity": "medium", 
       "confidence": 88
     },
     {
       "description": "[ÉTAPE] Des traces de liquide restent visibles sur le plan de travail",
       "category": "cleanliness",
       "severity": "low",
       "confidence": 75
     }
   ],
  "total_issues_count": 3,
  "etapes_issues_count": 2,
  "general_issues_count": 1
}
```

#### Workflow automatique complet :
1. **🔍 Classification automatique** : Détermine le type de chaque pièce (cuisine, salle de bain, etc.)
2. **🔧 Injection des critères** : Applique automatiquement les critères spécialisés par type de pièce  
3. **📊 Analyse détaillée des pièces** : Analyse avec critères optimisés pour chaque type de pièce
4. **🎯 Analyse des étapes** : Vérifie chaque tâche selon sa consigne spécifique
5. **📋 Regroupement unifié** : Combine toutes les issues dans un format unifié
6. **📈 Statistiques complètes** : Compteurs par type d'issue

#### Avantages majeurs :
- **🎯 Analyse exhaustive** : Combine toutes les analyses en une seule requête
- **📊 Vue regroupée** : Toutes les issues dans `preliminary_issues` comme les autres endpoints
- **🔧 Optimisation automatique** : Classification et critères spécialisés automatiques
- **📈 Statistiques détaillées** : Répartition précise des types d'issues
- **⚡ Efficacité maximale** : Une seule requête pour analyser tout un logement
- **🏷️ Identification claire** : Préfixes `[Nom Pièce]` et `[ÉTAPE]` pour distinguer les sources

#### Structure des issues regroupées :
- **Issues générales** : Problèmes détectés au niveau de la pièce avec préfixe `[Nom Pièce]`
- **Issues d'étapes** : Problèmes liés à l'exécution des tâches avec préfixe `[ÉTAPE]`
- **Format unifié** : Même structure que les autres endpoints avec `preliminary_issues`

#### Cas d'usage optimal :
- **Audit complet** après intervention de nettoyage
- **Rapport de validation** qualité exhaustif
- **Workflow automatisé** d'inspection
- **Analyse de conformité** globale d'un logement

---

### 5. 🏢 Analyse complète logement + Webhook automatique (NOUVEAU)
**POST** `/analyze-complete`

Endpoint ultime qui combine TOUTES les fonctionnalités en une seule requête, avec envoi automatique d'un webhook à Bubble selon l'environnement. Cet endpoint effectue une analyse exhaustive d'un logement complet avec synthèse globale et notification automatique.

#### URL complète
```
https://admin-staging-454a.up.railway.app/analyze-complete
```

#### Fonctionnalités intégrées
1. **🔍 Classification automatique** de chaque pièce
2. **📊 Analyse détaillée** avec critères spécialisés par type
3. **🎯 Analyse des étapes** selon les consignes spécifiques
4. **📈 Synthèse globale** avec score 1-5 et recommandations
5. **🔗 Webhook automatique** vers Bubble (staging/production)

#### Payload d'exemple
Utilise le même format que `/analyze-etapes` :

```json
{
  "logement_id": "1745691114127x167355942685376500",
  "pieces": [
    {
      "piece_id": "1745856961367x853186102447308800",
      "nom": "Cuisine",
      "commentaire_ia": "Attention particulière aux détails",
      "checkin_pictures": [...],
      "checkout_pictures": [...],
      "etapes": [
        {
          "etape_id": "1745857142659x605188923525693400",
          "task_name": "Vider le lave vaisselle",
          "consigne": "vider la vaisselle",
          "checking_picture": "URL_avant",
          "checkout_picture": "URL_après"
        }
      ]
    }
  ]
}
```

#### Réponse complète avec enrichissement
```json
{
  "logement_id": "1745691114127x167355942685376500",
  "pieces_analysis": [
    {
      "piece_id": "1745856961367x853186102447308800",
      "nom_piece": "Cuisine 🍽️",
      "room_classification": {...},
      "analyse_globale": {...},
      "issues": [...]
    }
  ],
  "total_issues_count": 3,
  "etapes_issues_count": 1,
  "general_issues_count": 2,
  "analysis_enrichment": {
    "summary": {
      "missing_items": ["Vase décoratif disparu"],
      "damages": ["Aucun dégât constaté"],
      "cleanliness_issues": ["Traces de graisse sur hotte"],
      "layout_problems": ["Lampe ajoutée non autorisée"]
    },
    "recommendations": [
      "Effectuer un nettoyage de la hotte aspirante",
      "Retrouver le vase manquant",
      "Retirer la lampe non autorisée",
      "Planifier maintenance préventive",
      "Documenter l'état pour suivi"
    ],
    "global_score": {
      "score": 3,
      "label": "BON",
      "description": "Quelques points d'attention nécessitant actions ciblées"
    }
  }
}
```

#### 🔗 Configuration Webhook Automatique

**Environnement STAGING** :
- URL : `https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia`
- Détection : Variables `ENVIRONMENT=staging/test` ou URL contenant "staging"

**Environnement PRODUCTION** :
- URL : `https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia`  
- Détection : Variables `ENVIRONMENT=production` ou `RAILWAY_ENVIRONMENT=production`

**Payload webhook** : Identique à la réponse de l'endpoint (payload complet)

#### Avantages
- **🎯 Tout-en-un** : Une seule requête pour analyse complète + notification
- **🔗 Intégration transparente** : Webhook automatique vers Bubble
- **📊 Synthèse intelligente** : Score global et recommandations concrètes
- **⚡ Optimisé** : Toutes les analyses combinées efficacement
- **🛡️ Robuste** : Erreurs webhook n'interrompent pas l'analyse

---

### 🧪 Endpoints de Test Webhook

#### Test configuration webhook
**GET** `/webhook/test`

Vérifie la configuration webhook et l'environnement détecté sans envoyer de données.

#### Réponse exemple
```json
{
  "status": "success",
  "detected_environment": "staging",
  "webhook_url": "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia",
  "env_variables": {
    "ENVIRONMENT": "staging",
    "RAILWAY_ENVIRONMENT": "non défini",
    "RAILWAY_PUBLIC_DOMAIN": "admin-staging-454a.up.railway.app",
    "RAILWAY_SERVICE_NAME": "api-staging"
  },
  "message": "Webhook configuré pour l'environnement staging"
}
```

#### Test envoi webhook
**POST** `/webhook/test-send`

Envoie un webhook de test vers l'environnement détecté avec un payload minimal.

#### Réponse exemple
```json
{
  "status": "success",
  "environment": "staging", 
  "webhook_url": "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia",
  "webhook_sent": true,
  "test_payload": {
    "test": true,
    "message": "Test webhook depuis CheckEasy API V5",
    "environment": "staging",
    "logement_id": "test_logement_123"
  },
  "message": "Webhook de test envoyé avec succès"
}
```

---

### 3. 🎯 Analyse combinée (RECOMMANDÉ)
**POST** `/analyze-with-classification`

Effectue automatiquement la classification puis l'analyse avec injection des critères spécialisés. **C'est l'endpoint recommandé pour la plupart des cas d'usage.**

#### URL complète
```
https://admin-staging-454a.up.railway.app/analyze-with-classification
```

#### Payload d'exemple
```json
{
  "piece_id": "auto_analyse_001", 
  "nom": "Pièce à analyser",
  "commentaire_ia": "Attention particulière aux détails de propreté",
  "checkin_pictures": [
    {
      "piece_id": "auto_analyse_001",
      "url": "https://example.com/room_before1.jpg"
    },
    {
      "piece_id": "auto_analyse_001", 
      "url": "https://example.com/room_before2.jpg"
    }
  ],
  "checkout_pictures": [
    {
      "piece_id": "auto_analyse_001",
      "url": "https://example.com/room_after1.jpg"
    },
    {
      "piece_id": "auto_analyse_001",
      "url": "https://example.com/room_after2.jpg"
    }
  ],
  "elements_critiques": [],
  "points_ignorables": [],
  "defauts_frequents": []
}
```

> ⚠️ **Note importante:** Les champs `elements_critiques`, `points_ignorables`, et `defauts_frequents` seront automatiquement remplis selon le type de pièce détecté.

#### Réponse exemple
```json
{
  "piece_id": "auto_analyse_001",
  "nom_piece": "Salle de bain 🚿",
  "room_classification": {
    "piece_id": "auto_analyse_001",
    "room_type": "salle_de_bain",
    "room_name": "Salle de bain",
    "room_icon": "🚿",
    "confidence": 98,
    "verifications": {
      "elements_critiques": [
        "Étanchéité douche/baignoire",
        "Ventilation",
        "Joints sanitaires"
      ],
      "points_ignorables": [
        "Traces de calcaire légères",
        "Petites traces sur miroir"
      ],
      "defauts_frequents": [
        "Moisissures plafond",
        "Joints silicone noirs", 
        "Fuites cachées"
      ]
    }
  },
  "analyse_globale": {
    "status": "probleme",
    "score": 4.2,
    "temps_nettoyage_estime": "25 minutes",
    "commentaire_global": "Problèmes significatifs détectés incluant des moisissures et un manque de propreté général nécessitant une intervention complète."
  },
  "preliminary_issues": [
    {
      "description": "Moisissures visibles dans les joints de la douche, particulièrement dans l'angle bas gauche",
      "category": "cleanliness",
      "severity": "high",
      "confidence": 95
    },
    {
      "description": "Traces de calcaire importantes sur la robinetterie et le pommeau de douche",
      "category": "cleanliness", 
      "severity": "medium",
      "confidence": 88
    }
  ]
}
```

---

## 📝 Structure des données

### 🖼️ Picture
```json
{
  "piece_id": "string",
  "url": "string (URL de l'image)"
}
```

### 📊 Analyse Globale
```json
{
  "status": "ok | attention | probleme",
  "score": "number (0-10)",
  "temps_nettoyage_estime": "string (ex: '15 minutes')",
  "commentaire_global": "string (résumé humain de l'état général)"
}
```

#### 💬 Commentaire Global
Le champ `commentaire_global` fournit un **résumé humain et naturel** de l'état de la pièce :

**Caractéristiques :**
- 📝 Phrase naturelle et professionnelle (15-50 mots)
- 🎯 Compréhensible par un non-expert
- 😊 Reflète le sentiment général (positif/neutre/négatif)
- 🧹 Mentionne les aspects principaux (propreté, agencement, défauts)

**Exemples selon le statut :**
- **Status "ok"**: *"Excellente propreté générale, la pièce est prête avec juste un léger dépoussiérage des surfaces."*
- **Status "attention"**: *"La pièce est globalement propre avec quelques détails mineurs à rectifier comme des traces de doigts."*
- **Status "probleme"**: *"Problèmes significatifs détectés nécessitant une intervention complète de nettoyage."*

### ⚠️ Problème détecté
```json
{
  "description": "string (description détaillée)",
  "category": "missing_item | damage | cleanliness | positioning | added_item | image_quality | wrong_room",
  "severity": "low | medium | high", 
  "confidence": "number (0-100)"
}
```

---

## 🎨 Types de pièces supportés

| Type | Nom | Icône | Spécialisations |
|------|-----|-------|-----------------|
| `cuisine` | Cuisine | 🍽️ | Électroménager, évacuations, joints |
| `salle_de_bain` | Salle de bain | 🚿 | Étanchéité, ventilation, moisissures |
| `chambre` | Chambre | 🛏️ | Murs, prises, rangements |
| `salon` | Salon | 🛋️ | Mobilier, surfaces, éclairage |
| `bureau` | Bureau | 💼 | Équipements, câblage, organisation |
| `entree` | Entrée | 🚪 | Sol, éclairage, accès |
| `wc` | WC | 🚽 | Sanitaires, ventilation, hygiène |
| `balcon` | Balcon | 🌿 | Extérieur, sécurité, drainage |
| `autre` | Autre | 📦 | Critères génériques |

---

## 🚀 Exemples d'utilisation

### Curl - Analyse combinée
```bash
curl -X POST "https://admin-staging-454a.up.railway.app/analyze-with-classification" \
  -H "Content-Type: application/json" \
  -d '{
    "piece_id": "test_001",
    "nom": "Test automatique",
    "checkin_pictures": [
      {
        "piece_id": "test_001",
        "url": "https://example.com/before.jpg"
      }
    ],
    "checkout_pictures": [
      {
        "piece_id": "test_001", 
        "url": "https://example.com/after.jpg"
      }
    ],
    "elements_critiques": [],
    "points_ignorables": [],
    "defauts_frequents": []
  }'
```

### JavaScript/Fetch
```javascript
const analyzeRoom = async (roomData) => {
  const response = await fetch('https://admin-staging-454a.up.railway.app/analyze-with-classification', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(roomData)
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

// Utilisation
const result = await analyzeRoom({
  piece_id: "room_123",
  nom: "Cuisine test",
  checkin_pictures: [
    { piece_id: "room_123", url: "https://example.com/kitchen_before.jpg" }
  ],
  checkout_pictures: [
    { piece_id: "room_123", url: "https://example.com/kitchen_after.jpg" }
  ],
  elements_critiques: [],
  points_ignorables: [],
  defauts_frequents: []
});

console.log(result);
```

### Python/Requests
```python
import requests
import json

def analyze_room(room_data):
    url = "https://admin-staging-454a.up.railway.app/analyze-with-classification"
    
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=room_data
    )
    
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"API Error: {response.status_code} - {response.text}")

# Utilisation
room_data = {
    "piece_id": "room_456",
    "nom": "Salle de bain test",
    "checkin_pictures": [
        {"piece_id": "room_456", "url": "https://example.com/bathroom_before.jpg"}
    ],
    "checkout_pictures": [
        {"piece_id": "room_456", "url": "https://example.com/bathroom_after.jpg"}
    ],
    "elements_critiques": [],
    "points_ignorables": [],
    "defauts_frequents": []
}

result = analyze_room(room_data)
print(json.dumps(result, indent=2))
```

---

## ⚡ Optimisations et bonnes pratiques

### 🎯 Recommandations d'usage

1. **Utilisez `/analyze-with-classification`** pour la plupart des cas
   - Classification automatique + analyse optimisée
   - Une seule requête au lieu de deux
   - Critères spécialisés automatiquement appliqués

2. **Qualité des images**
   - Résolution minimale recommandée: 800x600px
   - Format supporté: JPG, PNG
   - Éclairage suffisant pour une bonne visibilité

3. **Structure des URLs d'images**
   - Utilisez des URLs HTTPS accessibles publiquement
   - Assurez-vous que les images restent disponibles pendant l'analyse

### 🔧 Paramètres avancés

#### Commentaire IA (Priorité absolue)
Le champ `commentaire_ia` permet de donner des instructions spéciales qui seront **prioritaires** sur tous les autres critères.

Exemples d'utilisation :
```json
{
  "commentaire_ia": "Ne pas remonter les traces légères sur les murs blancs"
}
```

```json
{
  "commentaire_ia": "Être très strict sur la propreté de l'électroménager"
}
```

#### Critères personnalisés
Si vous utilisez `/analyze` au lieu de `/analyze-with-classification`, vous pouvez définir vos propres critères :

- **elements_critiques**: Vérifiés en priorité absolue, même les micro-défauts
- **points_ignorables**: Jamais remontés, considérés comme usure normale
- **defauts_frequents**: Recherchés activement et prioritairement

---

## 🔍 Codes de réponse HTTP

| Code | Signification | Description |
|------|---------------|-------------|
| `200` | ✅ Succès | Analyse terminée avec succès |
| `400` | ❌ Erreur de requête | Payload invalide ou manquant |
| `422` | ❌ Erreur de validation | Données non conformes au schéma |
| `500` | ❌ Erreur serveur | Erreur interne de l'API ou de l'IA |

---

## 📞 Support et contact

- **URL de production:** https://admin-staging-454a.up.railway.app/
- **Documentation interactive:** https://admin-staging-454a.up.railway.app/docs
- **Statut de santé:** https://admin-staging-454a.up.railway.app/docs

---

## 🔄 Changelog

### Version 5.1 (Actuelle)
- ✅ **NOUVEAU** : Commentaire global humain dans les réponses d'analyse
- ✅ Résumé naturel de l'état général de la pièce
- ✅ Phrase compréhensible pour les non-experts

### Version 5.0
- ✅ Classification automatique des pièces
- ✅ Analyse combinée en une requête
- ✅ Critères spécialisés par type de pièce
- ✅ Injection automatique des bonnes pratiques
- ✅ Support des instructions prioritaires via `commentaire_ia`

---

*Dernière mise à jour: Janvier 2025* 

---

## 🛠️ Gestion des Types de Pièces (CRUD)

### 1. 📋 Récupérer tous les types de pièces
**GET** `/room-templates`

Récupère la liste complète des types de pièces configurés.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates
```

#### Réponse exemple
```json
{
  "success": true,
  "room_types": {
    "cuisine": {
      "name": "Cuisine",
      "icon": "🍽️",
      "verifications": {
        "elements_critiques": ["Joints silicone évier", "État robinetterie"],
        "points_ignorables": ["Petites traces sur murs"],
        "defauts_frequents": ["Moisissures sous évier", "Joints noircis"]
      }
    },
    "salle_de_bain": {
      "name": "Salle de bain",
      "icon": "🚿",
      "verifications": {
        "elements_critiques": ["Étanchéité douche/baignoire", "Ventilation"],
        "points_ignorables": ["Traces de calcaire légères"],
        "defauts_frequents": ["Moisissures plafond", "Joints silicone noirs"]
      }
    }
  }
}
```

---

### 2. 🔍 Récupérer un type de pièce spécifique
**GET** `/room-templates/{room_type_key}`

Récupère les détails d'un type de pièce spécifique.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates/cuisine
```

#### Réponse exemple
```json
{
  "success": true,
  "room_type_key": "cuisine",
  "room_type": {
    "name": "Cuisine",
    "icon": "🍽️",
    "verifications": {
      "elements_critiques": ["Joints silicone évier", "État robinetterie"],
      "points_ignorables": ["Petites traces sur murs"],
      "defauts_frequents": ["Moisissures sous évier", "Joints noircis"]
    }
  }
}
```

---

### 3. ➕ Créer un nouveau type de pièce
**POST** `/room-templates`

Crée un nouveau type de pièce avec ses critères de vérification.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates
```

#### Payload d'exemple
```json
{
  "room_type_key": "bureau",
  "name": "Bureau",
  "icon": "💼",
  "verifications": {
    "elements_critiques": [
      "État des murs",
      "Prises électriques",
      "Éclairage",
      "Câblage informatique"
    ],
    "points_ignorables": [
      "Traces légères murs",
      "Poussière normale"
    ],
    "defauts_frequents": [
      "Rayures bureau",
      "Impacts chaise",
      "Câbles endommagés"
    ]
  }
}
```

#### Réponse exemple
```json
{
  "success": true,
  "message": "Type de pièce créé avec succès",
  "room_type_key": "bureau"
}
```

---

### 4. ✏️ Mettre à jour un type de pièce
**PUT** `/room-templates/{room_type_key}`

Met à jour un type de pièce existant. Tous les champs sont optionnels.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates/bureau
```

#### Payload d'exemple
```json
{
  "name": "Bureau professionnel",
  "icon": "🏢",
  "verifications": {
    "elements_critiques": [
      "État des murs",
      "Prises électriques",
      "Éclairage LED",
      "Câblage informatique",
      "Ventilation"
    ],
    "points_ignorables": [
      "Traces légères murs",
      "Poussière normale",
      "Usure normale mobilier"
    ],
    "defauts_frequents": [
      "Rayures bureau",
      "Impacts chaise",
      "Câbles endommagés",
      "Problèmes réseau"
    ]
  }
}
```

#### Réponse exemple
```json
{
  "success": true,
  "message": "Type de pièce mis à jour avec succès",
  "room_type": {
    "name": "Bureau professionnel",
    "icon": "🏢",
    "verifications": {
      "elements_critiques": ["État des murs", "Prises électriques"],
      "points_ignorables": ["Traces légères murs"],
      "defauts_frequents": ["Rayures bureau", "Impacts chaise"]
    }
  }
}
```

---

### 5. 🗑️ Supprimer un type de pièce
**DELETE** `/room-templates/{room_type_key}`

Supprime définitivement un type de pièce.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates/bureau
```

#### Réponse exemple
```json
{
  "success": true,
  "message": "Type de pièce supprimé avec succès",
  "deleted_room": {
    "name": "Bureau professionnel",
    "icon": "🏢",
    "verifications": {
      "elements_critiques": ["État des murs", "Prises électriques"],
      "points_ignorables": ["Traces légères murs"],
      "defauts_frequents": ["Rayures bureau", "Impacts chaise"]
    }
  }
}
```

---

### 6. 🚀 Export pour Railway (persistance)
**GET** `/room-templates/export/railway-env`

Exporte la configuration actuelle sous forme de variable d'environnement Railway pour éviter la perte de données lors des déploiements.

#### URL complète
```
https://admin-staging-454a.up.railway.app/room-templates/export/railway-env
```

#### Réponse exemple
```json
{
  "success": true,
  "message": "Configuration exportée pour Railway",
  "instructions": [
    "1. Copiez la valeur 'env_var_value' ci-dessous",
    "2. Allez dans Railway Dashboard > Variables",
    "3. Créez/modifiez la variable: ROOM_TEMPLATES_CONFIG",
    "4. Collez la valeur et sauvegardez",
    "5. Railway redémarrera automatiquement avec la nouvelle config"
  ],
  "variable_name": "ROOM_TEMPLATES_CONFIG",
  "env_var_value": "{\"room_types\":{\"cuisine\":{...}}}",
  "railway_command": "railway variables set ROOM_TEMPLATES_CONFIG='{...}'"
}
```

#### 🔥 Problème résolu
**Sans cette étape** : `railway up` écrase le fichier `room-verification-templates.json` avec la version locale ❌  
**Avec cette étape** : La configuration est sauvegardée dans les variables d'environnement Railway ✅

---

## 🎨 Interface d'Administration

### Accès à l'interface web
**GET** `/admin`

Interface graphique moderne pour gérer les types de pièces.

#### URL complète
```
https://admin-staging-454a.up.railway.app/admin
```

**Fonctionnalités disponibles :**
- ✅ Visualisation de tous les types de pièces
- ✅ Recherche en temps réel
- ✅ Création de nouveaux types
- ✅ Modification des types existants
- ✅ Suppression des types
- ✅ Gestion des listes dynamiques (éléments critiques, points ignorables, défauts fréquents)
- ✅ Interface responsive et moderne

---

## 📊 Endpoints de santé et statut

### Health check principal
**GET** `/`

Vérification de l'état de l'API.

#### Réponse exemple
```json
{
  "status": "healthy",
  "version": "5.0"
}
```

### Health check détaillé
**GET** `/health`

Vérification détaillée de l'état des services.

#### Réponse exemple
```json
{
  "status": "healthy",
  "version": "5.0"
}
```

---

## 🚀 Déploiement Railway

L'API est optimisée pour Railway avec :

- ✅ **Configuration automatique** : Variables d'environnement détectées
- ✅ **Health checks** : Endpoints `/` et `/health` pour monitoring
- ✅ **Gestion des erreurs** : Logs détaillés et fallbacks
- ✅ **CORS configuré** : Accès depuis tous les domaines
- ✅ **Fichiers statiques** : Interface d'admin servie via `/admin`
- ✅ **Persistence** : Configuration sauvegardée dans `room_classfication/room-verification-templates.json`

### Variables d'environnement requises
```
OPENAI_API_KEY=sk-proj-...
PORT=8000  # Automatiquement défini par Railway
``` 
