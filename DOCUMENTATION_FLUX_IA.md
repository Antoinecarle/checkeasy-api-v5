# 📚 DOCUMENTATION COMPLÈTE DU FLUX IA - CheckEasy API V5

## 🎯 Vue d'ensemble

Cette documentation explique en détail **tout le chemin de l'IA** dans l'application CheckEasy API V5, depuis la réception d'une requête jusqu'à l'envoi du webhook à Bubble.

---

## 🔄 FLUX PRINCIPAL - Endpoint `/analyze-complete`

### 📍 Point d'entrée principal
**Endpoint**: `POST /analyze-complete`
**Fichier**: `make_request.py` (ligne 6764)

### 📥 1. RÉCEPTION DU PAYLOAD

Le payload reçu suit le modèle `EtapesAnalysisInput` (ligne 3945):

```json
{
  "logement_id": "1746548810037x386469807784722400",
  "rapport_id": "1763022346287x500550419617962900",
  "type": "Voyageur",  // ou "Ménage"
  "logement_adresse": "15 Rue de la Paix, 75002 Paris",
  "date_debut": "30/07/25",
  "date_fin": "06/08/25",
  "operateur_nom": "Marie Dupont",
  "voyageur_nom": "Jean Martin",
  "pieces": [
    {
      "piece_id": "piece_001",
      "nom": "Cuisine",
      "commentaire_ia": "Instructions spéciales",
      "checkin_pictures": [...],
      "checkout_pictures": [...],
      "etapes": [
        {
          "etape_id": "etape_001",
          "task_name": "Vider le lave-vaisselle",
          "consigne": "vider la vaisselle",
          "checking_picture": "URL_avant",
          "checkout_picture": "URL_après"
        }
      ]
    }
  ]
}
```

**⚠️ IMPORTANT**: Ce payload est **SACRÉ** - il ne doit JAMAIS être modifié avant l'envoi à Bubble.

---

## 🔍 2. TRAITEMENT DES IMAGES

### 2.1 Conversion des formats
**Fichier**: `image_converter.py`
**Fonction**: `process_pictures_list()`

**Formats supportés nativement** (pas de conversion) :
- PNG, JPEG, JPG, GIF, WEBP

**Formats convertis automatiquement en JPEG** :
- HEIC, HEIF, BMP, TIFF, TIF, **AVIF**

**Processus** :
- Télécharge les images depuis les URLs
- Détecte le format par signature binaire
- Convertit les formats non supportés en JPEG optimisé pour l'IA
- Upload vers un service temporaire si nécessaire
- Retourne des URLs compatibles OpenAI

### 2.2 Normalisation des URLs
**Fonction**: `normalize_url()` (ligne 1320)

- Nettoie les URLs (espaces, caractères spéciaux)
- Valide le format
- Filtre les placeholders invalides

---

## 🧠 3. ANALYSE PAR PIÈCE (Parallélisée)

Pour chaque pièce, le système effectue **3 étapes séquentielles**:

### ÉTAPE 1: Classification automatique de la pièce
**Fonction**: `classify_room_type()` (ligne 3063)

#### 3.1.1 Chargement des templates de pièces
**Fonction**: `load_room_templates(parcours_type)` (ligne 700)

**Sources (par ordre de priorité)**:
1. Variable d'environnement Railway: `ROOM_TEMPLATES_CONFIG_VOYAGEUR` ou `ROOM_TEMPLATES_CONFIG_MENAGE`
2. Fichier local: `room_classfication/room-verification-templates-{voyageur|menage}.json`
3. Configuration par défaut (hardcodée)

**Contenu des templates**:
```json
{
  "room_types": {
    "cuisine": {
      "name": "Cuisine",
      "icon": "🍽️",
      "verifications": {
        "elements_critiques": ["Joints silicone évier", "État robinetterie"],
        "points_ignorables": ["Petites traces sur murs"],
        "defauts_frequents": ["Moisissures sous évier"]
      }
    }
  }
}
```

#### 3.1.2 Construction du prompt de classification
**Fonction**: `build_dynamic_prompt()` → `load_prompts_config()` (ligne 7645)

**Sources des prompts (par ordre de priorité)**:
1. Variable d'environnement Railway: `PROMPTS_CONFIG_VOYAGEUR` ou `PROMPTS_CONFIG_MENAGE`
2. Fichier local: `front/prompts-config-{voyageur|menage}.json`
3. Configuration par défaut

**Structure du prompt**:
```
prompts.classify_room.sections:
  - role_definition
  - types_pieces (avec injection des room_types)
  - validation_photos
  - format_reponse
```

#### 3.1.3 Appel à OpenAI pour classification
**Fonction**: `call_openai_responses()` (ligne 426)

**Configuration**:
- Modèle: Variable `OPENAI_MODEL` (défaut: `gpt-5.2-2025-12-11`)
- API: `/v1/responses` (nouvelle API OpenAI)
- Format: JSON structuré
- Max tokens: 1000

**Réponse attendue** (`RoomClassificationResponse`):
```json
{
  "piece_id": "piece_001",
  "room_type": "cuisine",
  "room_name": "Cuisine",
  "room_icon": "🍽️",
  "confidence": 95,
  "is_valid_room": true,
  "validation_message": "",
  "verifications": {
    "elements_critiques": [...],
    "points_ignorables": [...],
    "defauts_frequents": [...]
  }
}
```

---

### ÉTAPE 2: Injection des critères automatiques
**Fonction**: `analyze_with_auto_classification()` (ligne 3646)

Les critères détectés lors de la classification sont **automatiquement injectés** dans les données d'analyse:

```python
enhanced_input_data = InputData(
    piece_id=input_data.piece_id,
    nom=f"{classification_result.room_name} {classification_result.room_icon}",
    # INJECTION AUTOMATIQUE DES CRITÈRES
    elements_critiques=classification_result.verifications.elements_critiques,
    points_ignorables=classification_result.verifications.points_ignorables,
    defauts_frequents=classification_result.verifications.defauts_frequents,
    # Données originales conservées
    commentaire_ia=input_data.commentaire_ia,
    checkin_pictures=input_data.checkin_pictures,
    checkout_pictures=input_data.checkout_pictures,
    etapes=input_data.etapes
)
```

**📝 Log visible** (ligne 3725):
```
📌 INJECTION DES CRITÈRES:
   🔍 Éléments critiques injectés (5): ['Joints silicone évier', ...]
   ➖ Points ignorables injectés (3): ['Petites traces sur murs', ...]
   ⚠️ Défauts fréquents injectés (4): ['Moisissures sous évier', ...]
```

---

### ÉTAPE 3: Analyse détaillée de la pièce
**Fonction**: `analyze_images()` (ligne 1274)

#### 3.3.1 Construction du prompt d'analyse principal
**Fonction**: `build_dynamic_prompt(input_data, parcours_type)` (ligne 942)

**Chargement de la configuration**:
```python
prompts_config = load_prompts_config(parcours_type)
analyze_main_config = prompts_config.get("prompts", {}).get("analyze_main", {})
```

**Variables injectées dans le prompt** (ligne 968):
```python
variables = {
    # Variables de base
    "commentaire_ia": input_data.commentaire_ia,
    "elements_critiques": elements_critiques_formatted,  # Formaté avec puces
    "points_ignorables": points_ignorables_formatted,
    "defauts_frequents": defauts_frequents_formatted,
    "piece_nom": input_data.nom,

    # Variations alternatives (pour compatibilité)
    "elements_critiques_list": elements_critiques_formatted,
    "points_ignorables_list": points_ignorables_formatted,
    "defauts_frequents_list": defauts_frequents_formatted,

    # Métadonnées
    "nb_elements_critiques": len(input_data.elements_critiques),
    "piece_id": input_data.piece_id
}
```

**Construction du prompt complet** (ligne 1010):
```python
full_prompt = build_full_prompt_from_config(analyze_main_config, variables)
```

**📝 Log très visible du prompt final** (ligne 1016-1041):
```
🟢🟢🟢 PROMPT FINAL ENVOYÉ À OPENAI 🟢🟢🟢
📊 LONGUEUR TOTALE: 3542 caractères
📊 NOMBRE DE LIGNES: 87
🧳 TYPE PARCOURS: Voyageur
🏠 PIÈCE: Cuisine 🍽️
📜 CONTENU COMPLET DU PROMPT FINAL:
   1 | 🔄 RESET COMPLET - NOUVELLE ANALYSE INDÉPENDANTE 🔄
   2 | Tu es un expert en inspection de propreté...
   ...
```

#### 3.3.2 Préparation du message utilisateur avec images
**Code** (ligne 1302-1356):

```python
user_message = {
    "role": "user",
    "content": [
        {
            "type": "text",
            "text": f"Analyse les différences entre ces photos d'entrée et de sortie d'une {input_data.nom}...",
            "reasoning": {"effort": "high"}
        }
    ]
}

# Ajout des images checkin
for photo in processed_checkin:
    normalized_url = normalize_url(photo['url'])
    if is_valid_image_url(normalized_url):
        user_message["content"].append({
            "type": "image_url",
            "image_url": {
                "url": normalized_url,
                "detail": "high"
            }
        })

# Ajout des images checkout
for photo in processed_checkout:
    # Même processus...
```

#### 3.3.3 Appel à OpenAI pour l'analyse
**Fonction**: `call_openai_responses()` (ligne 426)

**Payload OpenAI structuré** (ligne 1370-1520):
```
🔬 PAYLOAD ENVOYÉ À OPENAI - ANALYSE
🔬 🤖 PARAMÈTRES:
   ├─ Modèle: gpt-5.2-2025-12-11
   ├─ Temperature: 0.2
   ├─ Max tokens: 16000
   └─ Response format: json_object

🔬 📋 PROMPT SYSTÈME (role: system):
   ├─ Longueur: 3542 caractères
   ├─ Nombre de lignes: 87
   └─ Pièce: Cuisine 🍽️

🔬 🎯 VARIABLES INJECTÉES:
   ├─ 🔍 Éléments critiques: 5 items
   ├─ 🚫 Points ignorables: 3 items
   └─ ⚠️ Défauts fréquents: 4 items

🔬 💬 MESSAGE UTILISATEUR (role: user):
   ├─ Éléments texte: 1
   └─ Images: 8 (4 checkin + 4 checkout)
```

**Appel API** (ligne 1530-1570):
```python
# Conversion au format Responses API
messages = [
    {"role": "system", "content": dynamic_prompt},
    user_message
]
input_content = convert_chat_messages_to_responses_input(messages)

# Appel
response = client.responses.create(
    model=OPENAI_MODEL,
    input=input_content,
    text={"format": {"type": "json_object"}},
    max_output_tokens=16000
)
```

**Réponse attendue** (`AnalyseResponse`):
```json
{
  "piece_id": "piece_001",
  "nom_piece": "Cuisine 🍽️",
  "analyse_globale": {
    "status": "attention",
    "score": 6.5,
    "temps_nettoyage_estime": "30 minutes",
    "commentaire_global": "Quelques traces de graisse..."
  },
  "preliminary_issues": [
    {
      "description": "Traces de graisse sur la hotte",
      "category": "cleanliness",
      "severity": "medium",
      "confidence": 85
    }
  ]
}
```


---

## 🔍 4. ANALYSE DES ÉTAPES (Parallélisée)

Pour chaque étape définie dans une pièce, le système effectue une analyse spécifique.

### 4.1 Traitement des images d'étapes
**Fonction**: `process_etapes_images()` (image_converter.py)

- Convertit les images `checking_picture` et `checkout_picture`
- Retourne des URLs compatibles OpenAI

### 4.2 Construction du prompt d'étape
**Fonction**: Intégré dans `analyze_complete_endpoint()` (ligne 4047-4066)

**Chargement de la configuration**:
```python
prompts_config = load_prompts_config()
analyze_etapes_config = prompts_config.get("prompts", {}).get("analyze_etapes", {})
```

**Variables injectées**:
```python
variables = {
    "task_name": etape.task_name,
    "consigne": etape.consigne,
    "etape_id": etape.etape_id
}
```

**Prompt construit**:
```python
etape_prompt = build_full_prompt_from_config(analyze_etapes_config, variables)
```

**Structure du prompt d'étape**:
```
prompts.analyze_etapes.sections:
  - role_definition: "Tu es un expert en vérification de tâches..."
  - task_template: "TÂCHE À VÉRIFIER: {task_name}\nCONSIGNE: {consigne}"
  - instructions: "Compare les deux photos..."
  - format_reponse: JSON structuré
```

### 4.3 Appel à OpenAI pour l'étape
**Code** (ligne 4186-4203):

```python
messages = [
    {"role": "system", "content": etape_prompt},
    user_message  # Contient les 2 images (avant/après)
]
input_content = convert_chat_messages_to_responses_input(messages)

response = client.responses.create(
    model=OPENAI_MODEL,
    input=input_content,
    text={"format": {"type": "json_object"}},
    max_output_tokens=16000
)
```

**Réponse attendue** (`EtapeAnalysisResult`):
```json
{
  "etape_id": "etape_001",
  "task_name": "Vider le lave-vaisselle",
  "status": "completed",
  "confidence": 90,
  "issues": [
    {
      "description": "Quelques assiettes restent dans le lave-vaisselle",
      "category": "missing_item",
      "severity": "medium",
      "confidence": 85,
      "etape_id": "etape_001"
    }
  ]
}
```

---

## 📊 5. SYNTHÈSE GLOBALE DU LOGEMENT

Une fois toutes les pièces et étapes analysées, le système génère une synthèse globale.

### 5.1 Compilation des résultats
**Fonction**: `generate_global_synthesis()` (ligne 5350)

**Agrégation des issues**:
```python
# Comptage des issues
total_issues = 0
general_issues = 0  # Issues des pièces
etapes_issues = 0   # Issues des étapes

# Résumé par pièce
issues_summary = []
for piece in pieces_analysis:
    piece_summary = {
        "piece_id": piece.piece_id,
        "nom_piece": piece.nom_piece,
        "status": piece.analyse_globale.status,
        "score": piece.analyse_globale.score,
        "nb_issues": len(piece.issues),
        "issues_details": [...]
    }
    issues_summary.append(piece_summary)
```

### 5.2 Construction du prompt de synthèse
**Code** (ligne 5456-5482):

```python
prompts_config = load_prompts_config(parcours_type)
synthesis_global_config = prompts_config.get("prompts", {}).get("synthesis_global", {})

variables = {
    "logement_id": logement_id,
    "total_issues": total_issues,
    "general_issues": general_issues,
    "etapes_issues": etapes_issues,
    "issues_summary": json.dumps(issues_summary, indent=2, ensure_ascii=False)
}

synthesis_prompt = build_full_prompt_from_config(synthesis_global_config, variables)
```

**Structure du prompt de synthèse**:
```
prompts.synthesis_global.sections:
  - role_definition: "Tu es un expert en évaluation de propreté..."
  - context_template: "LOGEMENT ID: {logement_id}\nTOTAL ISSUES: {total_issues}"
  - data_template: "RÉSUMÉ DES PIÈCES:\n{issues_summary}"
  - instructions: "Génère une note globale..."
  - format_reponse: JSON avec note et commentaire
```

### 5.3 Appel à OpenAI pour la synthèse
**Code** (ligne 5500-5550):

```python
messages = [
    {"role": "system", "content": synthesis_prompt},
    {"role": "user", "content": f"Génère la synthèse globale pour le logement {logement_id}..."}
]
input_content = convert_chat_messages_to_responses_input(messages)

response = client.responses.create(
    model=OPENAI_MODEL,
    input=input_content,
    text={"format": {"type": "json_object"}},
    max_output_tokens=2000
)
```

**Réponse attendue** (`GlobalSynthesis`):
```json
{
  "note_globale": 7.5,
  "commentaire_global": "Le logement est globalement propre avec quelques points d'attention...",
  "temps_total_estime": "2h30",
  "points_positifs": ["Cuisine bien rangée", "Salle de bain impeccable"],
  "points_amelioration": ["Traces sur les vitres", "Poussière sous le lit"]
}
```

---

## 📤 6. CONSTRUCTION DU PAYLOAD FINAL POUR BUBBLE

**⚠️ ZONE CRITIQUE - NE JAMAIS MODIFIER CE PAYLOAD**

### 6.1 Structure du payload final
**Fonction**: `analyze_complete_endpoint()` (ligne 6900-7050)

Le payload final est construit **EXACTEMENT** selon le format attendu par Bubble:

```python
final_payload = {
    # Métadonnées du logement (INTACTES)
    "logement_id": input_data.logement_id,
    "rapport_id": input_data.rapport_id,
    "type": input_data.type,
    "logement_adresse": input_data.logement_adresse,
    "date_debut": input_data.date_debut,
    "date_fin": input_data.date_fin,
    "operateur_nom": input_data.operateur_nom,
    "voyageur_nom": input_data.voyageur_nom,

    # Synthèse globale (GÉNÉRÉE PAR L'IA)
    "note_globale": synthesis.note_globale,
    "commentaire_global": synthesis.commentaire_global,
    "temps_total_estime": synthesis.temps_total_estime,

    # Résultats par pièce (GÉNÉRÉS PAR L'IA)
    "pieces": [
        {
            "piece_id": piece.piece_id,
            "nom_piece": piece.nom_piece,
            "room_type": piece.room_classification.room_type,
            "room_icon": piece.room_classification.room_icon,
            "status": piece.analyse_globale.status,
            "score": piece.analyse_globale.score,
            "temps_nettoyage_estime": piece.analyse_globale.temps_nettoyage_estime,
            "commentaire_global": piece.analyse_globale.commentaire_global,
            "issues": [
                {
                    "description": issue.description,
                    "category": issue.category,
                    "severity": issue.severity,
                    "confidence": issue.confidence,
                    "etape_id": issue.etape_id  # Si issue provient d'une étape
                }
                for issue in piece.issues
            ]
        }
        for piece in pieces_analysis
    ]
}
```


### 6.2 Détection de l'environnement
**Fonction**: `detect_environment()` (ligne 798)

**Méthodes de détection (par ordre de priorité)**:
1. Variable `VERSION`: `live` → production, `test` → staging
2. Variable `ENVIRONMENT`: `production/prod/live` → production, `staging/stage/test` → staging
3. Variable `RAILWAY_ENVIRONMENT`: `production` → production
4. Variable `RAILWAY_PUBLIC_DOMAIN`: contient "staging" → staging
5. Variable `RAILWAY_SERVICE_NAME`: contient "staging" ou "test" → staging
6. **Par défaut**: staging (sécurité)

**Log de détection** (ligne 806-846):
```
🚀 Environnement détecté: PRODUCTION (via VERSION=live)
```
ou
```
🔧 Environnement détecté: STAGING (via VERSION=test)
```

### 6.3 Sélection de l'URL du webhook
**Fonction**: `get_webhook_url(environment)` (ligne 848)

**URLs selon l'environnement**:
- **Production**: `https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia`
- **Staging**: `https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia`

---

## 🚀 7. ENVOI DU WEBHOOK À BUBBLE

### 7.1 Envoi asynchrone
**Fonction**: `send_webhook(payload, webhook_url)` (ligne 896)

**Configuration**:
```python
timeout = aiohttp.ClientTimeout(total=30)  # 30 secondes max
headers = {
    'Content-Type': 'application/json',
    'User-Agent': 'CheckEasy-API-V5'
}

async with aiohttp.ClientSession(timeout=timeout) as session:
    async with session.post(webhook_url, json=payload, headers=headers) as response:
        # Traitement de la réponse
```

**Logs d'envoi** (ligne 908-940):
```
📤 Envoi webhook vers: https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia
✅ Webhook envoyé avec succès (200): {"status":"success"}
```

### 7.2 Gestion des erreurs
**Cas d'erreur possibles**:
- `asyncio.TimeoutError`: Timeout de 30 secondes dépassé
- `aiohttp.ClientError`: Erreur réseau
- Réponse non-200: Bubble a rejeté le payload

**Logs d'erreur**:
```
❌ Timeout lors de l'envoi du webhook
❌ Erreur client lors de l'envoi du webhook: Connection refused
⚠️ Webhook réponse non-200 (400): Invalid payload format
```

---

## 🎯 POINTS DE MODIFICATION POSSIBLES

### ✅ CE QUE VOUS POUVEZ MODIFIER

#### 1. **Prompts système** (RECOMMANDÉ)
**Fichiers**:
- `front/prompts-config-voyageur.json`
- `front/prompts-config-menage.json`

**Ou variables d'environnement Railway**:
- `PROMPTS_CONFIG_VOYAGEUR`
- `PROMPTS_CONFIG_MENAGE`

**Sections modifiables**:
```json
{
  "prompts": {
    "analyze_main": {
      "sections": {
        "role_definition": "Tu es un expert...",  // ✅ MODIFIABLE
        "focus_principal": "FOCUS PRINCIPAL...",  // ✅ MODIFIABLE
        "elements_critiques_template": "...",     // ✅ MODIFIABLE
        "points_ignorables_template": "...",      // ✅ MODIFIABLE
        "defauts_frequents_template": "...",      // ✅ MODIFIABLE
        "instructions": "...",                    // ✅ MODIFIABLE
        "format_reponse": "..."                   // ✅ MODIFIABLE
      }
    },
    "classify_room": { ... },      // ✅ MODIFIABLE
    "analyze_etapes": { ... },     // ✅ MODIFIABLE
    "synthesis_global": { ... }    // ✅ MODIFIABLE
  }
}
```

**Interface d'administration**: `https://votre-api.railway.app/prompts-admin`

#### 2. **Templates de vérification des pièces**
**Fichiers**:
- `room_classfication/room-verification-templates-voyageur.json`
- `room_classfication/room-verification-templates-menage.json`

**Ou variables d'environnement Railway**:
- `ROOM_TEMPLATES_CONFIG_VOYAGEUR`
- `ROOM_TEMPLATES_CONFIG_MENAGE`

**Contenu modifiable**:
```json
{
  "room_types": {
    "cuisine": {
      "name": "Cuisine",                          // ✅ MODIFIABLE
      "icon": "🍽️",                               // ✅ MODIFIABLE
      "verifications": {
        "elements_critiques": [...],              // ✅ MODIFIABLE
        "points_ignorables": [...],               // ✅ MODIFIABLE
        "defauts_frequents": [...]                // ✅ MODIFIABLE
      }
    }
  }
}
```

**Interface d'administration**: `https://votre-api.railway.app/admin`

#### 3. **Modèle OpenAI utilisé**
**Variable d'environnement Railway**: `OPENAI_MODEL`

**Valeurs possibles**:
- `gpt-5.2-2025-12-11` (défaut actuel)
- `gpt-4o`
- `gpt-4-turbo`
- Tout autre modèle compatible avec l'API Responses

**Modification**: Dans Railway → Variables → `OPENAI_MODEL`

#### 4. **Paramètres de l'appel OpenAI**
**Fichier**: `make_request.py`

**Fonction**: `call_openai_responses()` (ligne 426)

**Paramètres modifiables**:
```python
def call_openai_responses(
    system_prompt: str,
    user_input: str = None,
    user_images: list = None,
    json_response: bool = True,
    max_tokens: int = 16000  // ✅ MODIFIABLE (ligne 431)
):
```

**Autres paramètres dans l'appel**:
```python
response_config = {
    "model": OPENAI_MODEL,
    "input": input_content,
    "max_output_tokens": max_tokens,  // ✅ MODIFIABLE
    # Vous pouvez ajouter:
    # "temperature": 0.2,             // ✅ AJOUT POSSIBLE
    # "top_p": 0.9,                   // ✅ AJOUT POSSIBLE
}
```

#### 5. **Traitement des images**
**Fichier**: `image_converter.py`

**Paramètres modifiables**:
- Qualité de compression JPEG
- Taille maximale des images
- Formats acceptés
- Service d'upload temporaire

#### 6. **Logs et debugging**
**Fichier**: `make_request.py`

**Niveaux de logs** (ligne 42-172):
- Activer/désactiver les logs détaillés
- Format des logs (JSON pour Railway, coloré pour local)
- Niveau de verbosité

---

### ❌ CE QUE VOUS NE DEVEZ JAMAIS MODIFIER

#### 1. **Structure du payload envoyé à Bubble**
**Fichier**: `make_request.py` (ligne 6900-7050)

**⚠️ INTERDIT DE MODIFIER**:
```python
final_payload = {
    "logement_id": ...,      // ❌ NE PAS MODIFIER
    "rapport_id": ...,       // ❌ NE PAS MODIFIER
    "type": ...,             // ❌ NE PAS MODIFIER
    "pieces": [...]          // ❌ NE PAS MODIFIER LA STRUCTURE
}
```

**Raison**: Bubble attend ce format exact. Toute modification cassera l'intégration.

#### 2. **Modèles Pydantic de réponse**
**Fichier**: `make_request.py` (lignes 238-332)

**⚠️ INTERDIT DE MODIFIER**:
```python
class AnalyseResponse(BaseModel):
    piece_id: str                    // ❌ NE PAS MODIFIER
    nom_piece: str                   // ❌ NE PAS MODIFIER
    analyse_globale: AnalyseGlobale  // ❌ NE PAS MODIFIER
    preliminary_issues: List[Probleme]  // ❌ NE PAS MODIFIER
```

**Raison**: Ces modèles définissent le contrat API avec Bubble.

#### 3. **URLs des webhooks Bubble**
**Fonction**: `get_webhook_url()` (ligne 848)

**⚠️ INTERDIT DE MODIFIER** (sauf si Bubble change):
```python
if environment == "production":
    return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia"
else:
    return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia"
```

#### 4. **Logique de détection d'environnement**
**Fonction**: `detect_environment()` (ligne 798)

**⚠️ MODIFIER AVEC PRÉCAUTION**: Risque d'envoyer des données de test en production ou vice-versa.

---

## 📋 RÉSUMÉ DU FLUX COMPLET

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. RÉCEPTION DU PAYLOAD                                         │
│    POST /analyze-complete                                       │
│    ├─ logement_id, rapport_id, type (Voyageur/Ménage)          │
│    ├─ pieces[] avec checkin/checkout pictures                  │
│    └─ etapes[] avec checking/checkout pictures                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. TRAITEMENT DES IMAGES                                        │
│    ├─ Conversion HEIC/WEBP → JPEG                              │
│    ├─ Upload vers service temporaire si nécessaire             │
│    └─ Normalisation des URLs                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. ANALYSE PAR PIÈCE (Parallélisée)                            │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ ÉTAPE 1: Classification automatique                   │   │
│    │ ├─ Chargement room_templates (Voyageur/Ménage)       │   │
│    │ ├─ Construction prompt classify_room                  │   │
│    │ ├─ Appel OpenAI Responses API                        │   │
│    │ └─ Retour: room_type, verifications                  │   │
│    └───────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ ÉTAPE 2: Injection des critères automatiques         │   │
│    │ ├─ elements_critiques → InputData                    │   │
│    │ ├─ points_ignorables → InputData                     │   │
│    │ └─ defauts_frequents → InputData                     │   │
│    └───────────────────────────────────────────────────────┘   │
│                            ↓                                    │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ ÉTAPE 3: Analyse détaillée de la pièce               │   │
│    │ ├─ Construction prompt analyze_main avec variables   │   │
│    │ ├─ Préparation message avec 8+ images                │   │
│    │ ├─ Appel OpenAI Responses API                        │   │
│    │ └─ Retour: analyse_globale, preliminary_issues       │   │
│    └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. ANALYSE DES ÉTAPES (Parallélisée)                           │
│    ├─ Pour chaque étape de chaque pièce                        │
│    ├─ Construction prompt analyze_etapes                       │
│    ├─ Appel OpenAI avec 2 images (avant/après)                 │
│    └─ Retour: status, issues avec etape_id                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. SYNTHÈSE GLOBALE DU LOGEMENT                                │
│    ├─ Compilation de toutes les issues                         │
│    ├─ Construction prompt synthesis_global                     │
│    ├─ Appel OpenAI avec résumé JSON                            │
│    └─ Retour: note_globale, commentaire_global                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. CONSTRUCTION DU PAYLOAD FINAL                               │
│    ⚠️ ZONE CRITIQUE - NE JAMAIS MODIFIER                       │
│    ├─ Métadonnées du logement (INTACTES)                       │
│    ├─ Synthèse globale (GÉNÉRÉE)                               │
│    └─ Résultats par pièce avec issues (GÉNÉRÉS)                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 7. ENVOI DU WEBHOOK À BUBBLE                                   │
│    ├─ Détection environnement (VERSION=live/test)              │
│    ├─ Sélection URL webhook (production/staging)               │
│    ├─ Envoi POST asynchrone avec timeout 30s                   │
│    └─ Log du résultat (succès/erreur)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 OUTILS D'ADMINISTRATION

### 1. Interface de gestion des prompts
**URL**: `https://votre-api.railway.app/prompts-admin`

**Fonctionnalités**:
- Visualiser tous les prompts (Voyageur/Ménage)
- Modifier les sections des prompts
- Prévisualiser avec injection de variables
- Sauvegarder dans Railway (variables d'environnement)

### 2. Interface de gestion des room templates
**URL**: `https://votre-api.railway.app/admin`

**Fonctionnalités**:
- Gérer les types de pièces
- Modifier les critères de vérification
- Ajouter/supprimer des pièces
- Sauvegarder dans Railway

### 3. Interface de test de l'API
**URL**: `https://votre-api.railway.app/tester`

**Fonctionnalités**:
- Tester tous les endpoints
- Charger des payloads de test
- Visualiser les réponses JSON
- Débugger les erreurs

---

## 📊 LOGS ET DEBUGGING

### Logs visibles dans Railway

**Chargement des configurations**:
```
🔧 Chargement de la config prompts pour le parcours: Voyageur
📡 Chargement depuis la variable d'environnement PROMPTS_CONFIG_VOYAGEUR
✅ Config prompts Voyageur chargée depuis variable d'environnement
```

**Appels OpenAI**:
```
🔵🔵🔵 APPEL API OPENAI RESPONSES 🔵🔵🔵
📌 MODÈLE: gpt-5.2-2025-12-11
📌 JSON RESPONSE: True
📌 MAX TOKENS: 16000
📌 IMAGES: 8
📤 Envoi de la requête à OpenAI Responses API...
✅ Réponse reçue: 2543 caractères
✅ JSON parsé avec succès
```

**Prompt final construit**:
```
🟢🟢🟢 PROMPT FINAL ENVOYÉ À OPENAI 🟢🟢🟢
📊 LONGUEUR TOTALE: 3542 caractères
🧳 TYPE PARCOURS: Voyageur
🏠 PIÈCE: Cuisine 🍽️
📜 CONTENU COMPLET DU PROMPT FINAL:
   1 | 🔄 RESET COMPLET...
   2 | Tu es un expert...
```

**Envoi webhook**:
```
📤 Envoi webhook vers: https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia
✅ Webhook envoyé avec succès (200)
```

---

## 🎓 CONCLUSION

Ce document couvre **100% du flux IA** de CheckEasy API V5. Vous savez maintenant:

✅ Comment les données entrent dans le système
✅ Comment les images sont traitées
✅ Comment les prompts sont construits et chargés
✅ Comment l'IA analyse chaque pièce et étape
✅ Comment la synthèse globale est générée
✅ Comment le payload final est construit
✅ Comment le webhook est envoyé à Bubble

**⚠️ RÈGLE D'OR**: Ne JAMAIS modifier le payload envoyé à Bubble. Toutes les modifications doivent se faire au niveau des prompts, des templates de vérification, ou des paramètres OpenAI.

Pour toute question ou modification, référez-vous aux sections "Points de modification possibles" ci-dessus.
