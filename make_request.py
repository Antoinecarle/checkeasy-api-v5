from typing import List, Literal, Optional
from pydantic import BaseModel, Field
import logging
from openai import OpenAI
import json
import os
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from image_converter import process_pictures_list, process_etapes_images, is_valid_image_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Modèles Pydantic pour la structure de réponse et requête
class Picture(BaseModel):
    piece_id: str
    url: str

class InputData(BaseModel):
    piece_id: str
    nom: str
    commentaire_ia: str = ""
    checkin_pictures: List[Picture]
    checkout_pictures: List[Picture]
    etapes: List[str] = []
    elements_critiques: List[str] = []
    points_ignorables: List[str] = []
    defauts_frequents: List[str] = []

class AnalyseGlobale(BaseModel):
    status: Literal["ok", "attention", "probleme"]
    score: float = Field(ge=0, le=10)
    temps_nettoyage_estime: str
    commentaire_global: str = Field(description="Résumé humain de l'état général de la pièce, incluant propreté et agencement")

class Probleme(BaseModel):
    description: str
    category: Literal["missing_item", "damage", "cleanliness", "positioning", "added_item", "image_quality", "wrong_room"]
    severity: Literal["low", "medium", "high"]
    confidence: int = Field(ge=0, le=100)

class AnalyseResponse(BaseModel):
    piece_id: str
    nom_piece: str
    analyse_globale: AnalyseGlobale
    preliminary_issues: List[Probleme]

# Nouveaux modèles pour la classification de pièces
class RoomClassificationInput(BaseModel):
    piece_id: str
    nom: str = ""
    checkin_pictures: List[Picture]
    checkout_pictures: List[Picture] = []

class RoomVerifications(BaseModel):
    elements_critiques: List[str]
    points_ignorables: List[str]
    defauts_frequents: List[str]

class RoomClassificationResponse(BaseModel):
    piece_id: str
    room_type: str
    room_name: str
    room_icon: str
    confidence: int
    verifications: RoomVerifications

# Créer l'application FastAPI
app = FastAPI(
    title="API d'Analyse d'Images",
    description="API pour analyser les différences entre les photos d'entrée et de sortie d'une pièce",
    version="1.0.0"
)

# Configurer CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monter les fichiers statiques
app.mount("/static", StaticFiles(directory="templates"), name="static")

@app.get("/admin")
async def serve_admin_interface():
    """Servir l'interface d'administration pour gérer les room templates"""
    return FileResponse("templates/admin.html")

# Client OpenAI global
import os

# Configuration de la clé API - priorité aux variables d'environnement Railway
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

try:
    # Approche compatible Railway - pas d'arguments supplémentaires
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    client = OpenAI()
    logger.info("✅ Client OpenAI initialisé avec succès")
except Exception as e:
    logger.error(f"❌ Erreur critique lors de l'initialisation du client OpenAI: {e}")
    logger.error(f"   Clé API disponible: {'Oui' if OPENAI_API_KEY else 'Non'}")
    logger.error(f"   Longueur clé: {len(OPENAI_API_KEY) if OPENAI_API_KEY else 0}")
    try:
        # Fallback - essayer sans aucune configuration spéciale
        import openai
        openai.api_key = OPENAI_API_KEY
        client = openai.OpenAI()
        logger.info("✅ Client OpenAI initialisé avec fallback")
    except Exception as e2:
        logger.error(f"❌ Erreur aussi avec fallback: {e2}")
        client = None

# Charger les templates de vérification des pièces
def load_room_templates():
    """Charger les templates de vérification depuis variables d'environnement ou fichier JSON"""
    try:
        # 🔥 PRIORITÉ 1: Variable d'environnement Railway (production)
        room_templates_env = os.environ.get('ROOM_TEMPLATES_CONFIG')
        if room_templates_env:
            try:
                logger.info("📡 Chargement des templates depuis les variables d'environnement Railway")
                return json.loads(room_templates_env)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Erreur lors du parsing JSON de ROOM_TEMPLATES_CONFIG: {e}")
        
        # 🔥 PRIORITÉ 2: Fichier local (développement/fallback)
        possible_paths = [
            "room_classfication/room-verification-templates.json",
            "room-verification-templates.json",
            os.path.join(os.path.dirname(__file__), "room_classfication", "room-verification-templates.json")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"📁 Chargement des templates depuis le fichier: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        
        # 🔥 PRIORITÉ 3: Configuration par défaut
        logger.warning("⚠️ Aucun template trouvé, utilisation de la configuration par défaut")
        return {
            "room_types": {
                "cuisine": {
                    "name": "Cuisine",
                    "icon": "🍽️",
                    "verifications": {
                        "elements_critiques": ["Joints silicone évier", "État robinetterie", "Évacuations", "Électroménager"],
                        "points_ignorables": ["Petites traces sur murs", "Variations couleur joints"],
                        "defauts_frequents": ["Moisissures sous évier", "Joints noircis", "Traces de calcaire"]
                    }
                },
                "salle_de_bain": {
                    "name": "Salle de bain",
                    "icon": "🚿",
                    "verifications": {
                        "elements_critiques": ["Étanchéité douche/baignoire", "Ventilation", "Joints sanitaires"],
                        "points_ignorables": ["Traces de calcaire légères", "Petites traces sur miroir"],
                        "defauts_frequents": ["Moisissures plafond", "Joints silicone noirs", "Fuites cachées"]
                    }
                },
                "autre": {
                    "name": "Autre",
                    "icon": "📦",
                    "verifications": {
                        "elements_critiques": ["Vérifications générales"],
                        "points_ignorables": ["Usure normale"],
                        "defauts_frequents": ["Dégradations diverses"]
                    }
                }
            }
        }
    except Exception as e:
        logger.error(f"❌ Erreur critique lors du chargement des templates: {e}")
        raise HTTPException(status_code=500, detail="Erreur lors du chargement des templates de vérification")

# Charger les templates au démarrage
ROOM_TEMPLATES = load_room_templates()

# ═══════════════════════════════════════════════════════════════
# 🔗 CONFIGURATION WEBHOOK
# ═══════════════════════════════════════════════════════════════

def detect_environment() -> str:
    """
    Détecte l'environnement d'exécution (staging vs production)
    
    Returns:
        str: "staging" ou "production"
    """
    # Méthode 1: Variable d'environnement explicite
    env = os.environ.get('ENVIRONMENT', '').lower()
    if env in ['staging', 'stage', 'test']:
        logger.info("🔧 Environnement détecté: STAGING (via ENVIRONMENT)")
        return "staging"
    elif env in ['production', 'prod', 'live']:
        logger.info("🚀 Environnement détecté: PRODUCTION (via ENVIRONMENT)")
        return "production"
    
    # Méthode 2: Variable Railway
    railway_env = os.environ.get('RAILWAY_ENVIRONMENT', '').lower()
    if railway_env == 'production':
        logger.info("🚀 Environnement détecté: PRODUCTION (via RAILWAY_ENVIRONMENT)")
        return "production"
    
    # Méthode 3: URL de l'application
    railway_public_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if 'staging' in railway_public_domain.lower():
        logger.info("🔧 Environnement détecté: STAGING (via RAILWAY_PUBLIC_DOMAIN)")
        return "staging"
    elif railway_public_domain and 'staging' not in railway_public_domain.lower():
        logger.info("🚀 Environnement détecté: PRODUCTION (via RAILWAY_PUBLIC_DOMAIN)")
        return "production"
    
    # Méthode 4: Nom du service Railway
    railway_service = os.environ.get('RAILWAY_SERVICE_NAME', '').lower()
    if 'staging' in railway_service or 'test' in railway_service:
        logger.info("🔧 Environnement détecté: STAGING (via RAILWAY_SERVICE_NAME)")
        return "staging"
    
    # Par défaut: staging pour la sécurité
    logger.warning("⚠️ Environnement indéterminé, utilisation de STAGING par défaut")
    return "staging"

def get_webhook_url(environment: str) -> str:
    """
    Retourne l'URL du webhook selon l'environnement
    
    Args:
        environment: "staging" ou "production"
        
    Returns:
        str: URL du webhook Bubble
    """
    if environment == "production":
        return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia"
    else:  # staging par défaut
        return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia"

async def send_webhook(payload: dict, webhook_url: str) -> bool:
    """
    Envoie le webhook de manière asynchrone
    
    Args:
        payload: Données à envoyer
        webhook_url: URL du webhook Bubble
        
    Returns:
        bool: True si succès, False sinon
    """
    try:
        logger.info(f"📤 Envoi webhook vers: {webhook_url}")
        
        # Configuration du timeout et des headers
        timeout = aiohttp.ClientTimeout(total=30)  # 30 secondes max
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'CheckEasy-API-V5'
        }
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers=headers
            ) as response:
                if response.status == 200:
                    response_text = await response.text()
                    logger.info(f"✅ Webhook envoyé avec succès (200): {response_text[:200]}...")
                    return True
                else:
                    error_text = await response.text()
                    logger.warning(f"⚠️ Webhook réponse non-200 ({response.status}): {error_text[:200]}...")
                    return False
                    
    except asyncio.TimeoutError:
        logger.error("❌ Timeout lors de l'envoi du webhook")
        return False
    except aiohttp.ClientError as e:
        logger.error(f"❌ Erreur client lors de l'envoi du webhook: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur inattendue lors de l'envoi du webhook: {e}")
        return False

def build_dynamic_prompt(input_data: InputData) -> str:
    """
    Construire un prompt dynamique basé sur les critères spécifiques de la pièce
    """
    
    base_prompt = """🔄 RESET COMPLET - NOUVELLE ANALYSE INDÉPENDANTE 🔄

🚫 OUBLIE TOTALEMENT toutes les analyses précédentes, instructions passées, et critères antérieurs
🚫 IGNORE complètement toute mémoire d'analyses précédentes ou de signalements antérieurs  
🚫 EFFACE toute connaissance de problèmes déjà identifiés dans d'autres pièces ou analyses
🚫 ANNULE tous les paramètres, critères et instructions de sessions précédentes
🚫 RECOMMENCE À ZÉRO avec une base de réflexion totalement neutre et vierge

⚡ CETTE ANALYSE EST UNIQUE ET INDÉPENDANTE ⚡
⚡ Seules les instructions DE CETTE REQUÊTE comptent
⚡ Aucune continuité avec les analyses précédentes
⚡ Base de réflexion totalement réinitialisée

═══════════════════════════════════════════════════════════════

Tu es un expert en inspection de propreté avec une grande expérience dans le nettoyage professionnel.
Ta mission est d'analyser l'état d'une pièce comme le ferait un agent de ménage expérimenté.

FOCUS PRINCIPAL :
1. Propreté et hygiène avant tout
   - Traces, taches, poussière
   - État des surfaces (plan de travail, évier, électroménager)
   - Présence de déchets ou d'aliments

2. Attention particulière aux détails
   - Même les plus petites miettes ou traces
   - État des coins et recoins
   - Zones souvent oubliées (derrière les objets, sous les appareils)

3. Organisation et rangement
   - Vaisselle laissée (propre ou sale)
   - Objets mal rangés ou laissés en désordre
   - Présence d'objets qui ne devraient pas être là"""

    # Ajouter les instructions spécifiques si présentes
    if input_data.commentaire_ia:
        base_prompt += f"""

🤖 INSTRUCTIONS SPÉCIALES DE L'IA :
{input_data.commentaire_ia}
🚫 RÈGLE ABSOLUE : Ces instructions sont PRIORITAIRES et OBLIGATOIRES.
🚫 AUCUNE exception ne peut être faite à ces directives.
🚫 Si une instruction spéciale contredit une autre règle, TOUJOURS suivre l'instruction spéciale."""

    if input_data.elements_critiques:
        base_prompt += f"""

🔍 ÉLÉMENTS CRITIQUES À VÉRIFIER EN PRIORITÉ ABSOLUE :
{chr(10).join(f"• {element}" for element in input_data.elements_critiques)}
🚨 OBLIGATION : Ces éléments nécessitent une attention MAXIMALE et OBLIGATOIRE.
🚨 MÊME le plus petit défaut sur ces éléments DOIT être signalé.
🚨 Aucune tolérance n'est accordée pour ces éléments critiques."""

    if input_data.points_ignorables:
        base_prompt += f"""

🚫 POINTS À IGNORER ABSOLUMENT (usure normale acceptable) :
{chr(10).join(f"• {point}" for point in input_data.points_ignorables)}
🚫 RÈGLE STRICTE : Ces éléments ne doivent JAMAIS être remontés comme problèmes.
🚫 MÊME si ces changements sont visibles, NE PAS les mentionner dans preliminary_issues.
🚫 Ces éléments sont considérés comme NORMAUX et ACCEPTABLES dans tous les cas.
🚫 IGNORER TOTALEMENT ces aspects, peu importe leur ampleur."""

    if input_data.defauts_frequents:
        base_prompt += f"""

⚠️ DÉFAUTS FRÉQUENTS À RECHERCHER ACTIVEMENT ET OBLIGATOIREMENT :
{chr(10).join(f"• {defaut}" for defaut in input_data.defauts_frequents)}
🎯 Exemple de defauts fréquents présent dans cette piece, cette liste n'est pas exhaustive.
🎯 OBLIGATION : Chercher activement ce type de problèmes dans chaque image.
🎯 Ces défauts sont prioritaires et doivent être détectés même s'ils sont subtils.
🎯 Examiner minutieusement pour identifier ces problèmes fréquents."""

    base_prompt += """

INSTRUCTIONS D'ANALYSE :
1. Compare méticuleusement les photos d'entrée avec celles de sortie
2. Identifie les changements significatifs EN RESPECTANT ABSOLUMENT les points à ignorer définis ci-dessus
3. Utilise des descriptions précises qu'un agent de ménage comprendrait immédiatement
4. Indique les positions exactes pour faciliter la vérification
5. Évalue la gravité en pensant au temps de nettoyage nécessaire
6. RESPECTE ABSOLUMENT et EN PRIORITÉ les instructions spéciales, points ignorables et éléments critiques définis ci-dessus

🚫 RÈGLE FONDAMENTALE : Si un élément est dans les "points ignorables", NE JAMAIS le remonter, même s'il est visible.
🔍 RÈGLE FONDAMENTALE : Si un élément est dans les "éléments critiques", TOUJOURS le signaler, même pour de micro-défauts.
⚠️ RÈGLE FONDAMENTALE : Si un élément est dans les "défauts fréquents", le chercher activement et prioritairement.

CRITÈRES DE SÉVÉRITÉ :
- LOW : Rapide à nettoyer (< 2 min)
  Exemple : quelques miettes, un objet déplacé

- MEDIUM : Nécessite une attention particulière (2-5 min)
  Exemple : taches séchées, vaisselle sale dans l'évier

- HIGH : Demande un nettoyage important (> 5 min)
  Exemple : surfaces très sales, nombreux déchets

FORMAT DES DESCRIPTIONS :
- Sois TRÈS précis sur ce qui doit être nettoyé
- Commence par le problème principal
- Indique la position exacte
- Ajoute des détails sur l'état (sec, collant, etc.)

Exemple de bonnes descriptions :
✅ "Accumulation de miettes et de taches de café séchées sur le plan de travail à droite de l'évier, couvrant une zone de 30x20 cm"
✅ "Présence d'une pile de 4 assiettes sales dans l'évier avec des restes alimentaires visibles"
✅ "Traces de doigts et éclaboussures sur toute la surface de la plaque de cuisson"

RÉPONDS UNIQUEMENT EN FORMAT JSON qui correspond exactement au schéma suivant:
{
    "piece_id": "string",
    "nom_piece": "string",
    "analyse_globale": {
        "status": "ok" | "attention" | "probleme",
        "score": number (0-5),
        "temps_nettoyage_estime": "string",
        "commentaire_global": "string (résumé humain de l'état général)"
    },
    "preliminary_issues": [
        {
            "description": "string (phrase complète et détaillée)",
            "category": "missing_item" | "damage" | "cleanliness" | "positioning" | "added_item" | "image_quality" | "wrong_room",
            "severity": "low" | "medium" | "high",
            "confidence": number (0-100)
        }
    ]
}

IMPORTANT :
- Le score doit refléter l'état général de propreté (10 = parfaitement propre)
- Le temps de nettoyage doit inclure TOUS les problèmes identifiés
- La confiance doit être basée sur la visibilité claire du problème
- Privilégie toujours la catégorie 'cleanliness' pour les problèmes de propreté

📝 COMMENTAIRE GLOBAL - INSTRUCTIONS SPÉCIALES :
Le commentaire_global doit être une phrase naturelle et humaine qui résume l'état général de la pièce.
Cette phrase sera lue par des humains pour comprendre rapidement l'état de la pièce.

EXEMPLES de bons commentaires globaux :
✅ "La pièce est globalement propre avec quelques détails mineurs à rectifier comme des traces de doigts sur les interrupteurs."
✅ "L'état nécessite une attention particulière avec plusieurs taches et des éléments mal rangés qui demandent un nettoyage approfondi."
✅ "Excellente propreté générale, la pièce est prête avec juste un léger dépoussiérage des surfaces."
✅ "Problèmes significatifs détectés incluant des moisissures et un manque de propreté général nécessitant une intervention complète."

Le commentaire doit :
- Être rédigé de façon naturelle et professionnelle
- Refléter le sentiment général (positif, neutre, négatif)
- Mentionner les aspects principaux (propreté, agencement, défauts majeurs)
- Être compréhensible par un non-expert
- Faire entre 15 et 50 mots
- Éviter le jargon technique

🚫 RAPPEL OBLIGATOIRE AVANT DE RÉPONDRE :
- Vérifier que AUCUN élément des "points ignorables" n'est mentionné dans preliminary_issues
- Vérifier que TOUS les "éléments critiques" ont été scrupuleusement examinés
- Vérifier que les "défauts fréquents" ont été activement recherchés
- RESPECTER ABSOLUMENT les instructions spéciales qui sont PRIORITAIRES sur tout le reste

🚫 SI UN DOUTE EXISTE : En cas de conflit entre les règles, TOUJOURS privilégier :
1. Les instructions spéciales du commentaire_ia (PRIORITÉ ABSOLUE)
2. Les points ignorables (NE JAMAIS les remonter)
3. Les éléments critiques (TOUJOURS les signaler)
4. Les défauts fréquents (TOUJOURS les chercher)"""

    return base_prompt

def analyze_images(input_data: InputData) -> AnalyseResponse:
    """
    Analyser les images d'entrée et de sortie et retourner une réponse structurée.
    """
    try:
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible dans analyze_images")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible - Client non initialisé")
        # 🔄 TRAITEMENT DES IMAGES - Conversion automatique des formats non supportés
        logger.info(f"🖼️ Traitement des images pour la pièce {input_data.piece_id}")
        
        # Traiter les images de checkin
        processed_checkin = process_pictures_list([pic.dict() for pic in input_data.checkin_pictures])
        
        # Traiter les images de checkout  
        processed_checkout = process_pictures_list([pic.dict() for pic in input_data.checkout_pictures])
        
        logger.info(f"✅ Traitement terminé: {len(processed_checkin)} checkin + {len(processed_checkout)} checkout")

        # Préparer le message avec les images valides uniquement
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Analyse les différences entre ces photos d'entrée et de sortie d'une {input_data.nom}. Fournis une réponse JSON structurée. forcer l'analyse des images pour detecter mêmes les plus petits détails",
                    "reasoning": {
                        "effort": "high"
                    }
                },
                
            ]
        }
        
        # Filtrer et ajouter seulement les photos d'entrée valides
        valid_checkin = []
        for photo in processed_checkin:
            if is_valid_image_url(photo['url']) and not photo['url'].startswith('data:image/gif;base64,R0lGOD'):
                valid_checkin.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": photo['url'],
                        "detail": "high"
                    }
                })
            
        # Filtrer et ajouter seulement les photos de sortie valides  
        valid_checkout = []
        for photo in processed_checkout:
            if is_valid_image_url(photo['url']) and not photo['url'].startswith('data:image/gif;base64,R0lGOD'):
                valid_checkout.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": photo['url'],
                        "detail": "high"
                    }
                })
        
        logger.info(f"📷 Images valides envoyées à OpenAI: {len(valid_checkin)} checkin + {len(valid_checkout)} checkout (sur {len(processed_checkin)}+{len(processed_checkout)} traitées)")
        
        # Si aucune image valide, ajouter une note
        if len(valid_checkin) == 0 and len(valid_checkout) == 0:
            user_message["content"].append({
                "type": "text",
                "text": "⚠️ Aucune image disponible - Fournir une analyse générique basée sur le type de pièce uniquement."
            })

        # Construire le prompt dynamique
        dynamic_prompt = build_dynamic_prompt(input_data)

        # Faire l'appel API avec response_format et gestion d'erreurs robuste
        try:
            response = client.chat.completions.create(
                model= "gpt-4.1-2025-04-14", #"o3-2025-04-16",
                messages=[
                    {
                        "role": "system",
                        "content": dynamic_prompt
                    },
                    user_message
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=16000
                #temperature=1,
                #max_completion_tokens=16000
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de l'analyse: {error_str}")
            
            # Gestion spécifique des erreurs d'images
            if "invalid_image_format" in error_str or "unsupported image" in error_str:
                logger.warning("⚠️ Erreur de format d'image détectée, tentative avec fallback sans images")
                
                # Créer un message sans images comme fallback
                fallback_message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analyse de la pièce '{input_data.nom}' (ID: {input_data.piece_id}). Les images sont indisponibles, fournir une analyse générique basée sur le type de pièce. Retourner une réponse JSON valide avec analyse_globale et preliminary_issues vides ou génériques."
                        }
                    ]
                }
                
                try:
                    # Tentative sans images
                    response = client.chat.completions.create(
                        model="gpt-4.1-2025-04-14",
                        messages=[
                            {
                                "role": "system",
                                "content": dynamic_prompt
                            },
                            fallback_message
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=16000
                    )
                    logger.info("✅ Analyse réussie en mode fallback (sans images)")
                except Exception as fallback_error:
                    logger.error(f"❌ Échec du fallback OpenAI: {fallback_error}")
                    # Retourner une réponse par défaut
                    return AnalyseResponse(
                        piece_id=input_data.piece_id,
                        nom_piece=input_data.nom,
                        analyse_globale=AnalyseGlobale(
                            status="attention",
                            score=5.0,
                            temps_nettoyage_estime="Non estimable",
                            commentaire_global="Analyse impossible : images indisponibles ou format non supporté"
                        ),
                        preliminary_issues=[
                            Probleme(
                                description="Impossibilité d'analyser les images - formats non supportés",
                                category="image_quality",
                                severity="medium",
                                confidence=100
                            )
                        ]
                    )
            else:
                # Autres erreurs OpenAI
                logger.error(f"❌ Erreur OpenAI non récupérable: {error_str}")
                raise HTTPException(status_code=500, detail=f"Erreur de l'API OpenAI: {error_str}")

        # Parser la réponse avec Pydantic
        return AnalyseResponse.model_validate_json(response.choices[0].message.content)

    except Exception as e:
        logger.error(f"Erreur lors de l'analyse: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze", response_model=AnalyseResponse)
async def analyze_room(input_data: InputData):
    """
    Endpoint pour analyser les photos d'une pièce avec critères personnalisés.
    
    Cette API analyse les différences entre les photos d'entrée et de sortie d'une pièce
    en tenant compte de critères spécifiques définis pour optimiser le processus de nettoyage.
    
    **Paramètres principaux :**
    - `piece_id` : Identifiant unique de la pièce
    - `nom` : Nom/type de la pièce (ex: "Cuisine", "Chambre")
    - `checkin_pictures` : Photos de la pièce avant nettoyage
    - `checkout_pictures` : Photos de la pièce après nettoyage
    
    **Paramètres d'optimisation :**
    - `commentaire_ia` : Instructions spéciales prioritaires (ex: "ne pas remonter les miettes sur la table")
    - `elements_critiques` : Liste des éléments à vérifier en priorité (ex: ["Murs (trous, impacts)", "Prises électriques"])
    - `points_ignorables` : Liste des éléments à ignorer car usure normale (ex: ["Traces légères aux murs", "Petites marques sur plinthes"])
    - `defauts_frequents` : Liste des défauts fréquents à rechercher activement (ex: ["Traces de meubles", "Impacts portes"])
    
    **Exemple de requête :**
    ```json
    {
        "piece_id": "chambre_001",
        "nom": "Chambre",
        "commentaire_ia": "Ne pas signaler les légères traces sur les murs blancs",
        "elements_critiques": ["Murs (trous, impacts)", "Prises électriques", "Stores/volets"],
        "points_ignorables": ["Traces légères aux murs", "Petites marques sur plinthes"],
        "defauts_frequents": ["Traces de meubles", "Impacts portes", "Trous fixations"],
        "checkin_pictures": [...],
        "checkout_pictures": [...]
    }
    ```
    
    **Réponse :**
    - `analyse_globale` : État général avec score et temps de nettoyage estimé
    - `preliminary_issues` : Liste détaillée des problèmes détectés avec sévérité et confiance
    
    L'IA adapte son analyse en fonction des critères fournis :
    - Priorité maximale aux éléments critiques
    - Ignore les points définis comme normaux
    - Recherche activement les défauts fréquents
    - Respecte absolument les instructions du commentaire_ia
    """
    try:
        return analyze_images(input_data)
    except Exception as e:
        logger.error(f"Erreur lors de la requête: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def classify_room_type(input_data: RoomClassificationInput) -> RoomClassificationResponse:
    """
    Classifier le type de pièce à partir des images et retourner les critères de vérification
    """
    try:
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible dans classify_room_type")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible - Client non initialisé")
        # Créer le prompt de classification
        room_types_list = list(ROOM_TEMPLATES["room_types"].keys())
        room_descriptions = []
        for room_key, room_info in ROOM_TEMPLATES["room_types"].items():
            room_descriptions.append(f"- {room_key}: {room_info['name']} {room_info['icon']}")
        
        classification_prompt = f"""Tu es un expert en classification d'espaces intérieurs.
Ta mission est d'analyser les images fournies et de déterminer précisément le type de pièce.

TYPES DE PIÈCES DISPONIBLES :
{chr(10).join(room_descriptions)}

INSTRUCTIONS :
1. Analyse attentivement les images fournies
2. Identifie les éléments caractéristiques (électroménager, sanitaires, mobilier, etc.)
3. Détermine le type de pièce le plus probable
4. Évalue ta confiance dans cette classification (0-100%)

CRITÈRES D'IDENTIFICATION :
- cuisine : électroménager, évier, plan de travail, plaques de cuisson
- salle_de_bain : douche, baignoire, lavabo, WC, carrelage mural
- chambre : lit, armoire, commode, espace de repos
- salon : canapé, TV, table basse, espace de vie
- bureau : bureau, chaise de bureau, ordinateur, rangements
- entree : porte d'entrée, hall, couloir, espace de passage
- wc : toilettes uniquement, espace réduit
- balcon : extérieur, garde-corps, plantes, mobilier de jardin
- autre : si aucune catégorie ne correspond parfaitement

RÉPONDS UNIQUEMENT EN FORMAT JSON :
{{
    "room_type": "type_de_piece",
    "confidence": nombre_entre_0_et_100
}}

IMPORTANT : 
- Utilise EXACTEMENT un des types de la liste : {', '.join(room_types_list)}
- La confiance doit refléter la certitude de ta classification
- Analyse tous les éléments visibles pour une classification précise"""

        # 🔄 TRAITEMENT DES IMAGES pour la classification
        logger.info(f"🖼️ Traitement des images pour classification de la pièce {input_data.piece_id}")
        
        # Traiter toutes les images disponibles
        all_pictures_raw = [pic.dict() for pic in input_data.checkin_pictures] + [pic.dict() for pic in input_data.checkout_pictures]
        all_pictures_processed = process_pictures_list(all_pictures_raw)
        
        logger.info(f"✅ Traitement terminé: {len(all_pictures_processed)} images pour classification")

        # Préparer le message avec les images valides uniquement
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": classification_prompt
                }
            ]
        }
        
        # Filtrer et ajouter seulement les images valides (exclure les placeholders)
        valid_images = []
        for photo in all_pictures_processed:
            if is_valid_image_url(photo['url']) and not photo['url'].startswith('data:image/gif;base64,R0lGOD'):
                valid_images.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": photo['url'],
                        "detail": "high"
                    }
                })
        
        logger.info(f"📷 Images valides envoyées à OpenAI: {len(valid_images)}/{len(all_pictures_processed)}")
        
        # Si aucune image valide, ajouter une note et adapter le prompt
        if len(valid_images) == 0:
            user_message["content"].append({
                "type": "text",
                "text": f"⚠️ Aucune image disponible - Classification basée uniquement sur le nom de la pièce: '{input_data.nom}'. Si le nom n'est pas fourni ou peu informatif, utiliser 'autre' avec une confiance faible."
            })
        
        # Appel à l'API OpenAI avec gestion d'erreurs robuste
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[user_message],
                max_tokens=200,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de la classification: {error_str}")
            
            # Gestion spécifique des erreurs d'images
            if "invalid_image_format" in error_str or "unsupported image" in error_str:
                logger.warning("⚠️ Erreur de format d'image détectée, tentative avec fallback")
                
                # Créer un message sans images comme fallback
                fallback_message = {
                    "role": "user", 
                    "content": [
                        {
                            "type": "text",
                            "text": f"{classification_prompt}\n\nNOTE: Analyse basée sur le nom de la pièce uniquement car les images sont indisponibles."
                        }
                    ]
                }
                
                try:
                    # Tentative sans images
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[fallback_message],
                        max_tokens=200,
                        temperature=0.1,
                        response_format={"type": "json_object"}
                    )
                    logger.info("✅ Classification réussie en mode fallback (sans images)")
                except Exception as fallback_error:
                    logger.error(f"❌ Échec du fallback OpenAI: {fallback_error}")
                    # Retourner une classification par défaut
                    return RoomClassificationResponse(
                        piece_id=input_data.piece_id,
                        room_type="autre",
                        room_name="Pièce",
                        room_icon="🏠",
                        confidence=10,
                        verifications=RoomVerifications(
                            elements_critiques=["État général des surfaces", "Propreté générale"],
                            points_ignorables=["Petites traces d'usage"],
                            defauts_frequents=["Traces diverses", "Poussière"]
                        )
                    )
            else:
                # Autres erreurs OpenAI
                logger.error(f"❌ Erreur OpenAI non récupérable: {error_str}")
                raise HTTPException(status_code=500, detail=f"Erreur de l'API OpenAI: {error_str}")
        
        # Parser la réponse
        response_content = response.choices[0].message.content
        if response_content is None:
            logger.error("❌ Réponse OpenAI vide")
            raise ValueError("Réponse OpenAI vide")
            
        response_content = response_content.strip()
        logger.info(f"Réponse brute de classification: {response_content}")
        
        classification_result = json.loads(response_content)
        
        # Récupérer le type de pièce et la confiance
        detected_room_type = classification_result.get("room_type", "autre")
        confidence = classification_result.get("confidence", 50)
        
        # Si confiance = 0, l'ajuster à 10 minimum pour éviter les problèmes
        if confidence == 0:
            confidence = 10
            logger.info(f"📊 Confiance ajustée de 0 à {confidence} pour éviter une valeur nulle")
        
        # Vérifier que le type détecté existe dans nos templates
        if detected_room_type not in ROOM_TEMPLATES["room_types"]:
            logger.warning(f"Type de pièce non reconnu: {detected_room_type}, utilisation de 'autre'")
            detected_room_type = "autre"
            confidence = max(confidence - 20, 10)  # Réduire la confiance
        else:
            logger.info(f"✅ Type de pièce '{detected_room_type}' reconnu avec succès")
        
        # Récupérer les informations du template
        room_info = ROOM_TEMPLATES["room_types"][detected_room_type]
        
        # Créer la réponse
        return RoomClassificationResponse(
            piece_id=input_data.piece_id,
            room_type=detected_room_type,
            room_name=room_info["name"],
            room_icon=room_info["icon"],
            confidence=confidence,
            verifications=RoomVerifications(
                elements_critiques=room_info["verifications"]["elements_critiques"],
                points_ignorables=room_info["verifications"]["points_ignorables"],
                defauts_frequents=room_info["verifications"]["defauts_frequents"]
            )
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de parsing JSON: {e}")
        try:
            logger.error(f"Contenu reçu: {response_content}")
        except NameError:
            logger.error("Contenu de réponse non disponible")
        # Retourner une classification par défaut en cas d'erreur de parsing
        return RoomClassificationResponse(
            piece_id=input_data.piece_id,
            room_type="autre",
            room_name="Autre",
            room_icon="📦",
            confidence=10,
            verifications=RoomVerifications(
                elements_critiques=["État général des surfaces", "Propreté générale"],
                points_ignorables=["Petites traces d'usage"],
                defauts_frequents=["Traces diverses", "Poussière"]
            )
        )
    except Exception as e:
        logger.error(f"Erreur lors de la classification: {str(e)}")
        # Retourner une classification par défaut en cas d'erreur générale
        return RoomClassificationResponse(
            piece_id=input_data.piece_id,
            room_type="autre",
            room_name="Autre",
            room_icon="📦",
            confidence=10,
            verifications=RoomVerifications(
                elements_critiques=["État général des surfaces", "Propreté générale"],
                points_ignorables=["Petites traces d'usage"],
                defauts_frequents=["Traces diverses", "Poussière"]
            )
        )

@app.post("/classify-room", response_model=RoomClassificationResponse)
async def classify_room(input_data: RoomClassificationInput):
    """
    Endpoint pour classifier automatiquement le type de pièce et retourner les critères de vérification.
    
    Cette API analyse les images d'une pièce pour déterminer automatiquement son type 
    (cuisine, salle de bain, chambre, etc.) et retourne les critères de vérification 
    spécifiques à ce type de pièce.
    
    **Paramètres :**
    - `piece_id` : Identifiant unique de la pièce
    - `nom` : Nom optionnel de la pièce (peut être vide)
    - `checkin_pictures` : Photos de la pièce (obligatoire)
    - `checkout_pictures` : Photos supplémentaires (optionnel)
    
    **Exemple de requête :**
    ```json
    {
        "piece_id": "piece_001",
        "nom": "",
        "checkin_pictures": [
            {
                "piece_id": "piece_001",
                "url": "https://example.com/image1.jpg"
            }
        ],
        "checkout_pictures": []
    }
    ```
    
    **Réponse :**
    - `room_type` : Type détecté (cuisine, salle_de_bain, chambre, etc.)
    - `room_name` : Nom complet de la pièce
    - `room_icon` : Emoji représentant la pièce
    - `confidence` : Niveau de confiance de la classification (0-100%)
    - `verifications` : Critères de vérification spécifiques :
        - `elements_critiques` : Éléments à vérifier en priorité
        - `points_ignorables` : Points d'usure normale à ignorer
        - `defauts_frequents` : Défauts fréquents à rechercher
    
    **Exemple de réponse :**
    ```json
    {
        "piece_id": "piece_001",
        "room_type": "cuisine",
        "room_name": "Cuisine",
        "room_icon": "🍽️",
        "confidence": 95,
        "verifications": {
            "elements_critiques": ["Joints silicone évier", "État robinetterie", "Évacuations", "Électroménager"],
            "points_ignorables": ["Petites traces sur murs", "Variations couleur joints"],
            "defauts_frequents": ["Moisissures sous évier", "Joints noircis", "Traces de calcaire"]
        }
    }
    ```
    
    L'IA analyse les éléments visuels caractéristiques pour déterminer le type de pièce
    et retourne automatiquement les critères de vérification appropriés.
    """
    logger.info(f"Classification démarrée pour la pièce {input_data.piece_id}")
    
    try:
        result = classify_room_type(input_data)
        logger.info(f"Classification terminée pour la pièce {input_data.piece_id}: {result.room_type} (confiance: {result.confidence}%)")
        return result
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint classify-room: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Nouveau modèle pour la réponse combinée
class CombinedAnalysisResponse(BaseModel):
    piece_id: str
    nom_piece: str
    # Informations de classification
    room_classification: RoomClassificationResponse
    # Résultats de l'analyse
    analyse_globale: AnalyseGlobale
    issues: List[Probleme]  # Renommé de preliminary_issues en issues

def analyze_with_auto_classification(input_data: InputData) -> CombinedAnalysisResponse:
    """
    Effectuer d'abord la classification, puis l'analyse avec injection des critères automatiques
    """
    try:
        # ÉTAPE 1: Classification de la pièce
        logger.info(f"🔍 ÉTAPE 1 - Classification automatique pour la pièce {input_data.piece_id}")
        
        # Convertir InputData en RoomClassificationInput
        classification_input = RoomClassificationInput(
            piece_id=input_data.piece_id,
            nom=input_data.nom,
            checkin_pictures=input_data.checkin_pictures,
            checkout_pictures=input_data.checkout_pictures
        )
        
        # Effectuer la classification
        classification_result = classify_room_type(classification_input)
        
        logger.info(f"✅ Classification terminée: {classification_result.room_type} ({classification_result.confidence}%)")
        logger.info(f"📝 Nom détecté: {classification_result.room_name} {classification_result.room_icon}")
        
        # ÉTAPE 2: Injection des critères dans les données d'analyse
        logger.info(f"🔧 ÉTAPE 2 - Injection des critères automatiques dans le payload d'analyse")
        
        # Créer une copie modifiée des données d'entrée avec les critères injectés
        enhanced_input_data = InputData(
            piece_id=input_data.piece_id,
            nom=f"{classification_result.room_name} {classification_result.room_icon}",
            commentaire_ia=input_data.commentaire_ia,
            checkin_pictures=input_data.checkin_pictures,
            checkout_pictures=input_data.checkout_pictures,
            etapes=input_data.etapes,
            # INJECTION DES CRITÈRES AUTOMATIQUES
            elements_critiques=classification_result.verifications.elements_critiques,
            points_ignorables=classification_result.verifications.points_ignorables,
            defauts_frequents=classification_result.verifications.defauts_frequents
        )
        
        # Logs détaillés de l'injection
        logger.info(f"📌 INJECTION DES CRITÈRES:")
        logger.info(f"   🔍 Éléments critiques injectés ({len(enhanced_input_data.elements_critiques)}): {enhanced_input_data.elements_critiques}")
        logger.info(f"   ➖ Points ignorables injectés ({len(enhanced_input_data.points_ignorables)}): {enhanced_input_data.points_ignorables}")
        logger.info(f"   ⚠️ Défauts fréquents injectés ({len(enhanced_input_data.defauts_frequents)}): {enhanced_input_data.defauts_frequents}")
        
        # ÉTAPE 3: Analyse avec les critères injectés
        logger.info(f"🔬 ÉTAPE 3 - Analyse détaillée avec critères spécifiques au type '{classification_result.room_type}'")
        
        analysis_result = analyze_images(enhanced_input_data)
        
        logger.info(f"✅ Analyse terminée: Score {analysis_result.analyse_globale.score}/10, {len(analysis_result.preliminary_issues)} problèmes détectés")
        
        # ÉTAPE 4: Combinaison des résultats
        logger.info(f"🔄 ÉTAPE 4 - Combinaison des résultats de classification et d'analyse")
        
        combined_result = CombinedAnalysisResponse(
            piece_id=input_data.piece_id,
            nom_piece=f"{classification_result.room_name} {classification_result.room_icon}",
            room_classification=classification_result,
            analyse_globale=analysis_result.analyse_globale,
            issues=analysis_result.preliminary_issues
        )
        
        logger.info(f"🎉 Analyse combinée terminée avec succès pour la pièce {input_data.piece_id}")
        
        return combined_result
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'analyse combinée: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse combinée: {str(e)}")

@app.post("/analyze-with-classification", response_model=CombinedAnalysisResponse)
async def analyze_with_classification(input_data: InputData):
    """
    Endpoint combiné qui effectue automatiquement la classification puis l'analyse détaillée.
    
    Cet endpoint combine les deux fonctionnalités :
    1. **Classification automatique** du type de pièce
    2. **Analyse détaillée** avec injection automatique des critères spécifiques au type détecté
    
    **Workflow automatique :**
    1. 🔍 L'IA analyse les images pour déterminer le type de pièce
    2. 🔧 Injection automatique des critères de vérification correspondants
    3. 🔬 Analyse détaillée avec les critères spécialisés
    4. 📊 Retour des résultats combinés
    
    **Paramètres :**
    - Utilise le même payload que `/analyze`
    - Les champs `elements_critiques`, `points_ignorables`, `defauts_frequents` sont **automatiquement injectés**
    - Le champ `commentaire_ia` reste utilisable pour des instructions supplémentaires
    
    **Exemple de requête :**
    ```json
    {
        "piece_id": "piece_auto_001",
        "nom": "Pièce inconnue",
        "commentaire_ia": "Attention particulière aux détails",
        "checkin_pictures": [...],
        "checkout_pictures": [...],
        "elements_critiques": [],  // ⚠️ SERA AUTOMATIQUEMENT REMPLI
        "points_ignorables": [],   // ⚠️ SERA AUTOMATIQUEMENT REMPLI  
        "defauts_frequents": []    // ⚠️ SERA AUTOMATIQUEMENT REMPLI
    }
    ```
    
    **Réponse enrichie :**
    - `room_classification` : Résultats complets de la classification
    - `analyse_globale` : Analyse de l'état général avec score
    - `preliminary_issues` : Problèmes détectés avec les critères spécialisés
    
    **Avantages :**
    - 🎯 Précision maximale grâce aux critères spécialisés par type de pièce
    - ⚡ Une seule requête pour classification + analyse
    - 🔧 Injection automatique des bonnes pratiques de vérification
    - 📝 Logs détaillés pour traçabilité
    
    **Cas d'usage optimal :**
    - Analyse rapide de pièces non identifiées
    - Workflow automatisé sans intervention manuelle
    - Garantie d'utilisation des bons critères de vérification
    """
    logger.info(f"🚀 Analyse combinée démarrée pour la pièce {input_data.piece_id}")
    
    try:
        result = analyze_with_auto_classification(input_data)
        logger.info(f"🎯 Analyse combinée terminée pour la pièce {input_data.piece_id}")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-with-classification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Nouveau modèle pour l'analyse des étapes
class Etape(BaseModel):
    etape_id: str
    task_name: str
    consigne: str
    checking_picture: str
    checkout_picture: str

class PieceWithEtapes(BaseModel):
    piece_id: str
    nom: str
    commentaire_ia: str = ""
    checkin_pictures: List[Picture]
    checkout_pictures: List[Picture] 
    etapes: List[Etape]

class EtapesAnalysisInput(BaseModel):
    logement_id: str
    rapport_id: str
    pieces: List[PieceWithEtapes]

class EtapeIssue(BaseModel):
    etape_id: str
    description: str
    category: Literal["missing_item", "damage", "cleanliness", "positioning", "added_item", "image_quality", "wrong_room"]
    severity: Literal["low", "medium", "high"]
    confidence: int = Field(ge=0, le=100)

class EtapesAnalysisResponse(BaseModel):
    preliminary_issues: List[EtapeIssue]

def analyze_etapes(input_data: EtapesAnalysisInput) -> EtapesAnalysisResponse:
    """
    Analyser toutes les étapes du logement en comparant les images selon leurs consignes
    """
    try:
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible dans analyze_etapes")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible - Client non initialisé")
        all_issues = []
        
        for piece in input_data.pieces:
            # 🔄 TRAITEMENT DES IMAGES DES ÉTAPES pour cette pièce
            logger.info(f"🖼️ Traitement des images des étapes pour la pièce {piece.piece_id}")
            processed_etapes = process_etapes_images([etape.dict() for etape in piece.etapes])
            logger.info(f"✅ {len(processed_etapes)} étapes traitées pour la pièce {piece.piece_id}")
            
            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]  # Garder l'objet original pour les autres propriétés
                logger.info(f"🔍 Analyse de l'étape {etape.etape_id}: {etape.task_name}")
                
                # Construire le prompt spécifique pour l'étape
                etape_prompt = f"""🔄 RESET COMPLET - NOUVELLE ANALYSE D'ÉTAPE INDÉPENDANTE 🔄

🚫 OUBLIE TOTALEMENT toutes les analyses précédentes
🚫 IGNORE complètement toute mémoire d'analyses précédentes
🚫 EFFACE toute connaissance de problèmes déjà identifiés
🚫 RECOMMENCE À ZÉRO avec une base de réflexion totalement neutre

⚡ CETTE ANALYSE EST UNIQUE ET INDÉPENDANTE ⚡

Tu es un expert en vérification de tâches ménagères. Ta mission est d'analyser si une consigne spécifique a été correctement exécutée.

🎯 TÂCHE À VÉRIFIER : {etape.task_name}
📋 CONSIGNE EXACTE : {etape.consigne}

INSTRUCTIONS D'ANALYSE :
1. Compare UNIQUEMENT la photo "avant" (checking_picture) avec la photo "après" (checkout_picture)
2. Vérifie si la consigne "{etape.consigne}" a été correctement exécutée
3. Sois MÉTICULEUX et RIGOUREUX dans ta vérification
4. Concentre-toi EXCLUSIVEMENT sur ce que demande la consigne

CRITÈRES D'ÉVALUATION :
- La tâche demandée a-t-elle été réalisée complètement ?
- Y a-t-il des éléments non conformes à la consigne ?
- L'état final correspond-il à ce qui était attendu ?

IMPORTANT :
- Analyse UNIQUEMENT cette tâche spécifique
- Ne signale QUE les problèmes liés à cette consigne précise
- Ignore tout ce qui n'est pas directement lié à la consigne

RÉPONSE ATTENDUE EN JSON :
{{
    "etape_id": "{etape.etape_id}",
    "issues": [
        {{
            "description": "Description précise du problème détecté",
            "category": "cleanliness|positioning|missing_item|damage|added_item|image_quality",
            "severity": "low|medium|high",
            "confidence": 85
        }}
    ]
}}

Si aucun problème détecté, retourne : {{"etape_id": "{etape.etape_id}", "issues": []}}"""

                # Récupérer les URLs traitées (peuvent être None si invalides)
                checking_url = etape_data['checking_picture'] 
                checkout_url = etape_data['checkout_picture']
                
                # Déterminer si les URLs sont utilisables (non None et non placeholders)
                checking_usable = checking_url is not None and not (isinstance(checking_url, str) and checking_url.startswith('data:image/gif;base64,R0lGOD'))
                checkout_usable = checkout_url is not None and not (isinstance(checkout_url, str) and checkout_url.startswith('data:image/gif;base64,R0lGOD'))
                
                logger.info(f"🔍 Validation images pour étape {etape.etape_id}: checking_usable={checking_usable}, checkout_usable={checkout_usable}")
                
                # Construire le message en fonction des images disponibles
                user_content = [
                    {
                        "type": "text",
                        "text": f"Analyse cette étape selon la consigne : {etape.consigne}"
                    }
                ]
                
                # Ajouter images seulement si elles sont utilisables
                if checking_usable:
                    user_content.extend([
                        {
                            "type": "text", 
                            "text": "Photo AVANT (checking_picture):"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": checking_url,
                                "detail": "high"
                            }
                        }
                    ])
                else:
                    user_content.append({
                        "type": "text", 
                        "text": "Photo AVANT: Image non conforme ou indisponible"
                    })
                
                if checkout_usable:
                    user_content.extend([
                        {
                            "type": "text",
                            "text": "Photo APRÈS (checkout_picture):"
                        },
                        {
                            "type": "image_url", 
                            "image_url": {
                                "url": checkout_url,
                                "detail": "high"
                            }
                        }
                    ])
                else:
                    user_content.append({
                        "type": "text",
                        "text": "Photo APRÈS: Image non conforme ou indisponible"
                    })
                
                # Message adapté selon les images disponibles
                if not checking_usable and not checkout_usable:
                    user_content.append({
                        "type": "text",
                        "text": "⚠️ ATTENTION: Aucune image exploitable pour cette étape. Signaler l'impossibilité d'analyse visuelle comme problème."
                    })
                elif not checking_usable:
                    user_content.append({
                        "type": "text", 
                        "text": "⚠️ Analyse limitée: Photo AVANT non conforme. Analyser uniquement la photo APRÈS mais signaler l'impossibilité de vérifier l'évolution."
                    })
                elif not checkout_usable:
                    user_content.append({
                        "type": "text",
                        "text": "⚠️ Analyse limitée: Photo APRÈS non conforme. Analyser uniquement la photo AVANT mais signaler l'impossibilité de vérifier le résultat."
                    })
                
                user_message = {
                    "role": "user", 
                    "content": user_content
                }

                # Faire l'appel API avec gestion d'erreurs robuste
                try:
                    response = client.chat.completions.create(
                        model="gpt-4.1-2025-04-14",
                        messages=[
                            {
                                "role": "system",
                                "content": etape_prompt
                            },
                            user_message
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=16000
                    )
                except Exception as openai_error:
                    error_str = str(openai_error)
                    logger.error(f"❌ Erreur OpenAI lors de l'analyse de l'étape {etape.etape_id}: {error_str}")
                    
                    # Gestion spécifique des erreurs d'images
                    if "invalid_image_format" in error_str or "unsupported image" in error_str:
                        logger.warning(f"⚠️ Erreur de format d'image détectée pour l'étape {etape.etape_id}, tentative avec fallback")
                        
                        # Créer un message sans images comme fallback
                        fallback_message = {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Analyse de l'étape '{etape.task_name}' avec consigne: '{etape.consigne}'. Les images sont indisponibles ou en format non supporté. Fournir une réponse JSON générique indiquant un problème d'image."
                                }
                            ]
                        }
                        
                        try:
                            # Tentative sans images
                            response = client.chat.completions.create(
                                model="gpt-4.1-2025-04-14",
                                messages=[
                                    {
                                        "role": "system",
                                        "content": etape_prompt
                                    },
                                    fallback_message
                                ],
                                response_format={"type": "json_object"},
                                temperature=0.2,
                                max_tokens=16000
                            )
                            logger.info(f"✅ Analyse de l'étape {etape.etape_id} réussie en mode fallback (sans images)")
                        except Exception as fallback_error:
                            logger.error(f"❌ Échec du fallback OpenAI pour l'étape {etape.etape_id}: {fallback_error}")
                            # Ajouter un problème générique pour cette étape
                            all_issues.append(EtapeIssue(
                                etape_id=etape.etape_id,
                                description=f"Impossibilité d'analyser l'étape '{etape.task_name}' - images en format non supporté",
                                category="image_quality",
                                severity="medium",
                                confidence=100
                            ))
                            logger.info(f"⚠️ Problème générique ajouté pour l'étape {etape.etape_id}")
                            continue  # Passer à l'étape suivante
                    else:
                        # Autres erreurs OpenAI - ajouter un problème générique
                        logger.error(f"❌ Erreur OpenAI non récupérable pour l'étape {etape.etape_id}: {error_str}")
                        all_issues.append(EtapeIssue(
                            etape_id=etape.etape_id,
                            description=f"Erreur technique lors de l'analyse de l'étape '{etape.task_name}'",
                            category="image_quality",
                            severity="medium",
                            confidence=100
                        ))
                        continue  # Passer à l'étape suivante
                
                # Parser la réponse
                response_content = response.choices[0].message.content.strip()
                etape_result = json.loads(response_content)
                
                # Ajouter les issues trouvées avec l'etape_id
                if "issues" in etape_result and etape_result["issues"]:
                    for issue in etape_result["issues"]:
                        all_issues.append(EtapeIssue(
                            etape_id=etape.etape_id,
                            description=issue["description"],
                            category=issue["category"], 
                            severity=issue["severity"],
                            confidence=issue["confidence"]
                        ))
                
                logger.info(f"✅ Analyse terminée pour l'étape {etape.etape_id}: {len(etape_result.get('issues', []))} problèmes détectés")

        return EtapesAnalysisResponse(preliminary_issues=all_issues)

    except Exception as e:
        logger.error(f"Erreur lors de l'analyse des étapes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze-etapes", response_model=EtapesAnalysisResponse)
async def analyze_etapes_endpoint(input_data: EtapesAnalysisInput):
    """
    Endpoint pour analyser spécifiquement les étapes de nettoyage.
    
    Cet endpoint se concentre exclusivement sur l'analyse des étapes individuelles 
    en comparant les photos "avant" et "après" selon les consignes spécifiques.
    
    **Fonctionnalité :**
    - Analyse chaque étape individuellement
    - Compare checking_picture vs checkout_picture  
    - Vérifie si la consigne a été correctement exécutée
    - Retourne uniquement les problèmes détectés par étape
    
    **Structure du payload :**
    ```json
    {
        "logement_id": "1745691114127x167355942685376500",
        "pieces": [
            {
                "piece_id": "1745856961367x853186102447308800",
                "nom": "Cuisine",
                "commentaire_ia": "Instructions spéciales",
                "checkin_pictures": [...],
                "checkout_pictures": [...],
                "etapes": [
                    {
                        "etape_id": "1745857142659x605188923525693400",
                        "task_name": "Vider le lave vaisselle",
                        "consigne": "vider la vaisselle",
                        "checking_picture": "URL_image_avant",
                        "checkout_picture": "URL_image_après"
                    }
                ]
            }
        ]
    }
    ```
    
    **Réponse :**
    ```json
    {
        "preliminary_issues": [
            {
                "etape_id": "1745857142659x605188923525693400",
                "description": "La vaisselle n'a pas été complètement vidée du lave-vaisselle",
                "category": "cleanliness",
                "severity": "medium", 
                "confidence": 85
            }
        ]
    }
    ```
    
    **Caractéristiques de l'analyse :**
    - 🎯 Focus exclusif sur la consigne de l'étape
    - 🔍 Comparaison méticuleuse avant/après
    - 📝 Signalement uniquement des problèmes liés à la tâche
    - ⚡ Analyse indépendante de chaque étape
    - 🚫 Ignore les éléments non liés à la consigne
    
    **Categories d'issues :**
    - `cleanliness` : Problèmes de propreté
    - `positioning` : Mauvais positionnement/rangement  
    - `missing_item` : Éléments manquants
    - `damage` : Dégâts ou casse
    - `added_item` : Éléments ajoutés incorrectement
    - `image_quality` : Problèmes de qualité d'image
    
    **Sévérités :**
    - `low` : Problème mineur
    - `medium` : Problème modéré nécessitant attention
    - `high` : Problème majeur nécessitant intervention
    """
    logger.info(f"🚀 Analyse des étapes démarrée pour le logement {input_data.logement_id}")
    
    try:
        result = analyze_etapes(input_data)
        total_issues = len(result.preliminary_issues)
        logger.info(f"🎯 Analyse des étapes terminée pour le logement {input_data.logement_id}: {total_issues} problèmes détectés")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-etapes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Nouveau modèle pour la synthèse globale du logement
class LogementSummary(BaseModel):
    missing_items: List[str] = Field(description="Liste des objets manquants reformulée")
    damages: List[str] = Field(description="Synthèse des éléments abîmés, cassés ou dégradés")
    cleanliness_issues: List[str] = Field(description="Points concernant le manque de propreté")
    layout_problems: List[str] = Field(description="Objets déplacés ou mal agencés")

class GlobalScore(BaseModel):
    score: int = Field(ge=1, le=5, description="Note globale de 1 à 5")
    label: str = Field(description="Label textuel (EXCELLENT, TRÈS BON, BON, MOYEN, MÉDIOCRE)")
    description: str = Field(description="Description détaillée de l'état général")

class LogementAnalysisEnrichment(BaseModel):
    summary: LogementSummary
    recommendations: List[str] = Field(min_items=5, max_items=5, description="5 recommandations concrètes et priorisées")
    global_score: GlobalScore

class CompleteAnalysisResponse(BaseModel):
    logement_id: str
    rapport_id: str
    pieces_analysis: List[CombinedAnalysisResponse]  # Résultats de l'analyse avec classification pour chaque pièce
    total_issues_count: int
    etapes_issues_count: int 
    general_issues_count: int
    # Enrichissement avec synthèse globale
    analysis_enrichment: LogementAnalysisEnrichment

def generate_logement_enrichment(logement_id: str, pieces_analysis: List[CombinedAnalysisResponse], total_issues: int, general_issues: int, etapes_issues: int) -> LogementAnalysisEnrichment:
    """
    Générer une synthèse globale et des recommandations pour le logement
    """
    try:
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible pour l'enrichissement")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible")

        # Créer un résumé structuré des problèmes détectés
        issues_summary = []
        for piece in pieces_analysis:
            piece_issues = []
            for issue in piece.issues:
                piece_issues.append({
                    "description": issue.description,
                    "category": issue.category,
                    "severity": issue.severity,
                    "confidence": issue.confidence
                })
            
            if piece_issues:  # Seulement ajouter les pièces avec des problèmes
                issues_summary.append({
                    "piece_name": piece.nom_piece,
                    "piece_id": piece.piece_id,
                    "room_type": piece.room_classification.room_type,
                    "global_score": piece.analyse_globale.score,
                    "global_status": piece.analyse_globale.status,
                    "issues": piece_issues
                })

        # Construire le prompt pour la synthèse globale
        synthesis_prompt = f"""Tu es un expert en gestion immobilière et en maintenance de logements. 

Ta mission est d'analyser le rapport détaillé d'inspection d'un logement et de produire une synthèse claire, exploitable et orientée action.

📊 DONNÉES D'ENTRÉE :
- Logement ID: {logement_id}
- Total des problèmes détectés: {total_issues}
- Problèmes généraux: {general_issues}  
- Problèmes d'étapes: {etapes_issues}

📋 DÉTAIL DES PROBLÈMES PAR PIÈCE :
{json.dumps(issues_summary, indent=2, ensure_ascii=False)}

🎯 TA MISSION :
1. **Synthétiser** les problèmes par catégories logiques
2. **Formuler** 5 recommandations concrètes et priorisées
3. **Attribuer** une note globale au logement selon le barème strict

📝 CATÉGORIES DE SYNTHÈSE :
- **missing_items** : Objets manquants, éléments disparus ou non présents
- **damages** : Éléments cassés, fissurés, abîmés, dégradés
- **cleanliness_issues** : Traces, taches, saleté, manque de propreté
- **layout_problems** : Objets déplacés, mal positionnés, désordre

⚠️ RÈGLE IMPORTANTE POUR LES CATÉGORIES VIDES :
Si aucun problème n'est détecté dans une catégorie, tu DOIS quand même renseigner un message explicite :
- missing_items vide → ["Aucun objet manquant constaté"]
- damages vide → ["Aucun dégât constaté"]
- cleanliness_issues vide → ["Aucun problème de propreté majeur détecté"]
- layout_problems vide → ["Aucun problème d'agencement constaté"]

🚫 NE JAMAIS laisser de listes vides [] - toujours fournir un message explicite.

🏆 BARÈME DE NOTATION STRICT :
- **5/5 – EXCELLENT** : Aucun problème détecté, état irréprochable
- **4/5 – TRÈS BON** : Quelques détails mineurs, maintenance préventive recommandée  
- **3/5 – BON** : Quelques points d'attention, actions de maintenance nécessaires
- **2/5 – MOYEN** : Plusieurs problèmes identifiés, interventions rapides nécessaires
- **1/5 – MÉDIOCRE** : Nombreux problèmes, actions correctives urgentes requises

🔍 CRITÈRES DE NOTATION :
- Nombre total de problèmes
- Gravité (severity: low/medium/high)
- Impact sur l'habitabilité
- Urgence des interventions nécessaires

💡 RECOMMANDATIONS - RÈGLES :
- Exactement 5 recommandations
- Concrètes et exploitables
- Priorisées par importance/urgence
- Basées UNIQUEMENT sur les constats réels
- Pas d'hallucination ou d'invention

📋 FORMAT JSON EXACT À RETOURNER :
{{
    "summary": {{
        "missing_items": ["Liste des objets manquants reformulés en phrases claires OU 'Aucun objet manquant constaté' si vide"],
        "damages": ["Liste des dégâts et éléments abîmés OU 'Aucun dégât constaté' si vide"],
        "cleanliness_issues": ["Liste des problèmes de propreté OU 'Aucun problème de propreté majeur détecté' si vide"],
        "layout_problems": ["Liste des problèmes d'agencement OU 'Aucun problème d'agencement constaté' si vide"]
    }},
    "recommendations": [
        "Recommandation 1 (la plus prioritaire)",
        "Recommandation 2",
        "Recommandation 3", 
        "Recommandation 4",
        "Recommandation 5"
    ],
    "global_score": {{
        "score": 3,
        "label": "BON",
        "description": "Description explicative de l'état général et justification de la note"
    }}
}}

⚠️ IMPORTANT :
- Base-toi UNIQUEMENT sur les données fournies
- Sois précis et factuel
- Évite les formulations vagues
- Respecte le barème de notation strictement
- Les recommandations doivent être directement actionnables"""

        # Faire l'appel API pour la synthèse avec gestion d'erreurs robuste
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-2025-04-14",
                messages=[
                    {
                        "role": "system", 
                        "content": synthesis_prompt
                    },
                    {
                        "role": "user",
                        "content": f"Génère la synthèse globale pour le logement {logement_id} basée sur les données d'inspection fournies."
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=8000
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de l'enrichissement du logement {logement_id}: {error_str}")
            
            # En cas d'erreur OpenAI, fournir un enrichissement de fallback
            logger.warning("⚠️ Génération d'un enrichissement de fallback")
            
            # Créer un enrichissement basique basé sur les statistiques
            if total_issues == 0:
                fallback_score = 5
                fallback_label = "EXCELLENT"
                fallback_description = "Aucun problème détecté, logement en excellent état"
            elif total_issues <= 2:
                fallback_score = 4
                fallback_label = "TRÈS BON"
                fallback_description = f"{total_issues} problème(s) mineur(s) détecté(s)"
            elif total_issues <= 5:
                fallback_score = 3
                fallback_label = "BON"
                fallback_description = f"{total_issues} problèmes détectés nécessitant attention"
            elif total_issues <= 10:
                fallback_score = 2
                fallback_label = "MOYEN"
                fallback_description = f"{total_issues} problèmes identifiés nécessitant intervention"
            else:
                fallback_score = 1
                fallback_label = "MÉDIOCRE"
                fallback_description = f"{total_issues} problèmes majeurs nécessitant actions correctives urgentes"
            
            return LogementAnalysisEnrichment(
                summary=LogementSummary(
                    missing_items=["Analyse indisponible - problème technique"],
                    damages=["Analyse indisponible - problème technique"],
                    cleanliness_issues=["Analyse indisponible - problème technique"],
                    layout_problems=["Analyse indisponible - problème technique"]
                ),
                recommendations=[
                    "Vérifier manuellement les résultats d'analyse des pièces",
                    "Contacter le support technique pour résoudre l'erreur de synthèse",
                    "Effectuer une inspection visuelle complémentaire",
                    "Documenter les problèmes identifiés manuellement",
                    "Programmer une nouvelle analyse une fois le problème résolu"
                ],
                global_score=GlobalScore(
                    score=fallback_score,
                    label=fallback_label,
                    description=fallback_description + " (Note basée sur le nombre de problèmes détectés)"
                )
            )
        
        # Parser la réponse
        response_content = response.choices[0].message.content.strip()
        enrichment_data = json.loads(response_content)
        
        # Valider et créer l'objet LogementAnalysisEnrichment
        enrichment = LogementAnalysisEnrichment(
            summary=LogementSummary(**enrichment_data["summary"]),
            recommendations=enrichment_data["recommendations"],
            global_score=GlobalScore(**enrichment_data["global_score"])
        )
        
        logger.info(f"✅ Synthèse globale générée: Note {enrichment.global_score.score}/5 ({enrichment.global_score.label})")
        logger.info(f"   📋 {len(enrichment.recommendations)} recommandations formulées")
        
        return enrichment
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération de l'enrichissement: {str(e)}")
        # En cas d'erreur, retourner un enrichissement par défaut
        fallback_enrichment = LogementAnalysisEnrichment(
            summary=LogementSummary(
                missing_items=["Aucun objet manquant constaté"],
                damages=["Aucun dégât constaté"],
                cleanliness_issues=["Aucun problème de propreté majeur détecté"],
                layout_problems=["Aucun problème d'agencement constaté"]
            ),
            recommendations=[
                "Effectuer une inspection détaillée",
                "Planifier les interventions nécessaires", 
                "Vérifier l'état général du logement",
                "Mettre à jour l'inventaire",
                "Programmer la maintenance préventive"
            ],
            global_score=GlobalScore(
                score=3,
                label="BON",
                description="Analyse automatique indisponible, inspection manuelle recommandée"
            )
        )
        logger.warning("⚠️ Utilisation de l'enrichissement par défaut")
        return fallback_enrichment

def analyze_complete_logement(input_data: EtapesAnalysisInput) -> CompleteAnalysisResponse:
    """
    Analyse complète d'un logement : classification + analyse générale + analyse des étapes
    """
    try:
        logger.info(f"🚀 ANALYSE COMPLÈTE démarrée pour le logement {input_data.logement_id}")
        
        pieces_analysis_results = []
        
        # ÉTAPE 1: Analyse avec classification pour chaque pièce
        logger.info(f"📊 ÉTAPE 1 - Analyse avec classification pour {len(input_data.pieces)} pièces")
        
        for piece in input_data.pieces:
            logger.info(f"🔍 Analyse de la pièce {piece.piece_id}: {piece.nom}")
            
            # Filtrer les images invalides avant l'analyse
            valid_checkin_pictures = []
            for pic in piece.checkin_pictures:
                if is_valid_image_url(pic.url):
                    valid_checkin_pictures.append(pic)
                else:
                    logger.warning(f"⚠️ Image checkin invalide ignorée: {pic.url}")
            
            valid_checkout_pictures = []
            for pic in piece.checkout_pictures:
                if is_valid_image_url(pic.url):
                    valid_checkout_pictures.append(pic)
                else:
                    logger.warning(f"⚠️ Image checkout invalide ignorée: {pic.url}")
            
            logger.info(f"📷 Images valides pour pièce {piece.piece_id}: {len(valid_checkin_pictures)} checkin + {len(valid_checkout_pictures)} checkout")
            
            # Convertir PieceWithEtapes en InputData pour l'analyse générale avec images filtrées
            input_data_piece = InputData(
                piece_id=piece.piece_id,
                nom=piece.nom,
                commentaire_ia=piece.commentaire_ia,
                checkin_pictures=valid_checkin_pictures,
                checkout_pictures=valid_checkout_pictures,
                etapes=[],  # On ne passe pas les étapes ici, elles seront traitées séparément
                elements_critiques=[],  # Sera rempli automatiquement par la classification
                points_ignorables=[],   # Sera rempli automatiquement par la classification
                defauts_frequents=[]    # Sera rempli automatiquement par la classification
            )
            
            # Effectuer l'analyse avec classification automatique
            piece_analysis = analyze_with_auto_classification(input_data_piece)
            pieces_analysis_results.append(piece_analysis)
            
            logger.info(f"✅ Pièce {piece.piece_id} analysée: {len(piece_analysis.issues)} issues générales détectées")
        
        # ÉTAPE 2: Analyser les étapes et créer un mapping etape_id -> piece_id
        logger.info(f"🎯 ÉTAPE 2 - Analyse des étapes pour toutes les pièces")
        
        # Créer un mapping etape_id -> piece_id pour retrouver facilement la pièce correspondante
        etape_to_piece_mapping = {}
        for piece in input_data.pieces:
            for etape in piece.etapes:
                etape_to_piece_mapping[etape.etape_id] = piece.piece_id
        
        # Analyser les étapes
        etapes_analysis = analyze_etapes(input_data)
        
        # Grouper les issues d'étapes par piece_id
        etapes_issues_by_piece = {}
        for etape_issue in etapes_analysis.preliminary_issues:
            piece_id = etape_to_piece_mapping.get(etape_issue.etape_id)
            if piece_id:
                if piece_id not in etapes_issues_by_piece:
                    etapes_issues_by_piece[piece_id] = []
                
                # Convertir EtapeIssue en Probleme pour l'ajouter à la pièce
                probleme = Probleme(
                    description=f"[ÉTAPE] {etape_issue.description}",
                    category=etape_issue.category,
                    severity=etape_issue.severity,
                    confidence=etape_issue.confidence
                )
                etapes_issues_by_piece[piece_id].append(probleme)
        
        logger.info(f"✅ Analyse des étapes terminée: {len(etapes_analysis.preliminary_issues)} issues d'étapes détectées")
        
        # ÉTAPE 3: Ajouter les issues d'étapes aux pièces correspondantes
        logger.info(f"🔄 ÉTAPE 3 - Ajout des issues d'étapes aux pièces correspondantes")
        
        total_issues_count = 0
        general_issues_count = 0
        etapes_issues_count = len(etapes_analysis.preliminary_issues)
        
        for piece_analysis in pieces_analysis_results:
            piece_id = piece_analysis.piece_id
            
            # Compter les issues générales de cette pièce
            general_issues_count += len(piece_analysis.issues)
            
            # Ajouter les issues d'étapes à cette pièce si elle en a
            if piece_id in etapes_issues_by_piece:
                piece_analysis.issues.extend(etapes_issues_by_piece[piece_id])
                logger.info(f"   🔗 Ajouté {len(etapes_issues_by_piece[piece_id])} issues d'étapes à la pièce {piece_id}")
            
            # Compter le total des issues pour cette pièce
            total_issues_count += len(piece_analysis.issues)
        
        # ÉTAPE 4: Compilation des résultats
        logger.info(f"📊 ÉTAPE 4 - Compilation des résultats finaux")
        
        # ÉTAPE 5: Génération de la synthèse globale via IA
        logger.info(f"🧠 ÉTAPE 5 - Génération de la synthèse globale et recommandations via IA")
        
        analysis_enrichment = generate_logement_enrichment(
            logement_id=input_data.logement_id,
            pieces_analysis=pieces_analysis_results,
            total_issues=total_issues_count,
            general_issues=general_issues_count,
            etapes_issues=etapes_issues_count
        )
        
        complete_result = CompleteAnalysisResponse(
            logement_id=input_data.logement_id,
            rapport_id=input_data.rapport_id,
            pieces_analysis=pieces_analysis_results,
            total_issues_count=total_issues_count,
            etapes_issues_count=etapes_issues_count,
            general_issues_count=general_issues_count,
            analysis_enrichment=analysis_enrichment
        )
        
        logger.info(f"🎉 ANALYSE COMPLÈTE terminée pour le logement {input_data.logement_id}")
        logger.info(f"📊 RÉSUMÉ: {total_issues_count} issues totales ({general_issues_count} générales + {etapes_issues_count} étapes)")
        logger.info(f"🏆 NOTE GLOBALE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")
        
        return complete_result
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'analyse complète: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse complète: {str(e)}")

@app.post("/analyze-complete", response_model=CompleteAnalysisResponse)
async def analyze_complete_endpoint(input_data: EtapesAnalysisInput):
    """
    Endpoint d'analyse complète qui combine TOUTES les fonctionnalités.
    
    Cet endpoint effectue une analyse exhaustive d'un logement en combinant :
    1. **Classification automatique** de chaque pièce
    2. **Analyse détaillée** de chaque pièce avec critères spécialisés
    3. **Analyse spécifique** de chaque étape selon ses consignes
    4. **Regroupement unifié** de toutes les issues détectées
    5. **🔗 Webhook automatique** vers Bubble selon l'environnement
    
    **Workflow complet :**
    1. 🔍 Pour chaque pièce : Classification automatique + Analyse avec critères spécialisés
    2. 🎯 Pour chaque étape : Analyse selon la consigne spécifique  
    3. 📊 Regroupement de toutes les issues dans un format unifié
    4. 📈 Statistiques complètes (issues générales vs issues d'étapes)
    5. 🔗 Envoi webhook automatique avec le payload complet
    
    **Payload :**
    - Utilise le même format que `/analyze-etapes`
    - Contient les pièces ET leurs étapes
    - Classification et critères spécialisés appliqués automatiquement
    
    **Exemple de payload :**
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
    
         **Réponse enrichie :**
     ```json
     {
         "logement_id": "1745691114127x167355942685376500",
         "pieces_analysis": [
             {
                 "piece_id": "1745856961367x853186102447308800",
                 "nom_piece": "Cuisine 🍽️",
                 "room_classification": {...},
                 "analyse_globale": {...},
                 "issues": [
                     {
                         "description": "Traces de graisse visibles sur la hotte aspirante",
                         "category": "cleanliness",
                         "severity": "medium",
                         "confidence": 85
                     },
                     {
                         "description": "[ÉTAPE] La vaisselle n'a pas été complètement vidée",
                         "category": "cleanliness", 
                         "severity": "medium",
                         "confidence": 88
                     }
                 ]
             }
         ],
         "total_issues_count": 2,
         "etapes_issues_count": 1,
         "general_issues_count": 1,
         "analysis_enrichment": {
            "summary": {
                "missing_items": ["Vase décoratif disparu de la table de cuisine"],
                "damages": ["Aucun dégât constaté"],
                "cleanliness_issues": ["Traces de graisse sur la hotte", "Vaisselle sale laissée dans l'évier"],
                "layout_problems": ["Lampe noire ajoutée dans le coin gauche"]
            },
            "recommendations": [
                "Effectuer un nettoyage en profondeur de la hotte aspirante",
                "Vider complètement le lave-vaisselle et nettoyer l'évier",
                "Retrouver et repositionner le vase décoratif manquant",
                "Retirer la lampe ajoutée non autorisée",
                "Planifier une inspection de maintenance préventive"
            ],
            "global_score": {
                "score": 3,
                "label": "BON",
                "description": "Quelques points d'attention détectés nécessitant des actions de maintenance ciblées"
            }
        }
     }
     ```
    
    **Avantages de cet endpoint :**
    - 🎯 **Analyse exhaustive** : Combine toutes les analyses possibles
    - 📊 **Vue unifiée** : Toutes les issues regroupées par pièce avec leurs étapes
    - 🔧 **Optimisation automatique** : Classification et critères spécialisés appliqués
    - 📈 **Statistiques détaillées** : Répartition des types d'issues
    - ⚡ **Efficacité** : Une seule requête pour tout analyser
    - 🏷️ **Identification claire** : Issues générales vs issues d'étapes distinctes
    - 🧠 **Synthèse intelligente** : Analyse globale avec recommandations concrètes et note finale
    - 📋 **Format exploitable** : Données structurées pour action immédiate
    - 🔗 **Webhook automatique** : Intégration transparente avec Bubble
    
    **Cas d'usage recommandé :**
    - Analyse complète après intervention de nettoyage
    - Rapport détaillé pour validation qualité
    - Audit complet d'un logement
    - Workflow automatisé d'inspection avec notification
    """
    logger.info(f"🚀 Analyse complète démarrée pour le logement {input_data.logement_id}")
    
    try:
        # 1. Effectuer l'analyse complète
        result = analyze_complete_logement(input_data)
        logger.info(f"🎯 Analyse complète terminée pour le logement {input_data.logement_id}")
        logger.info(f"📊 Total: {result.total_issues_count} issues ({result.general_issues_count} générales + {result.etapes_issues_count} étapes)")
        
        # 2. Envoyer le webhook de manière asynchrone (ne fait pas échouer la réponse)
        try:
            # Détecter l'environnement
            environment = detect_environment()
            webhook_url = get_webhook_url(environment)
            
            # Préparer le payload pour le webhook (copie du résultat complet)
            webhook_payload = result.model_dump()
            
            # Envoyer le webhook en arrière-plan
            logger.info(f"🔗 Envoi webhook pour logement {input_data.logement_id} vers {environment}")
            webhook_success = await send_webhook(webhook_payload, webhook_url)
            
            if webhook_success:
                logger.info(f"✅ Webhook envoyé avec succès pour logement {input_data.logement_id}")
            else:
                logger.warning(f"⚠️ Échec envoi webhook pour logement {input_data.logement_id} (analyse OK)")
                
        except Exception as webhook_error:
            # Les erreurs de webhook ne doivent jamais faire échouer l'analyse
            logger.error(f"❌ Erreur webhook pour logement {input_data.logement_id}: {webhook_error}")
            logger.info("ℹ️ L'analyse continue normalement malgré l'erreur webhook")
        
        # 3. Retourner le résultat de l'analyse (indépendamment du webhook)
        return result
        
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-complete: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint de healthcheck pour Railway
@app.get("/")
async def healthcheck():
    """Endpoint simple pour vérifier que l'API fonctionne"""
    return {
        "status": "ok",
        "message": "CheckEasy API V5 is running",
        "endpoints": [
            "/analyze",
            "/classify-room", 
            "/analyze-with-classification",
            "/analyze-etapes",
            "/analyze-complete",
            "/webhook/test",
            "/webhook/test-send"
        ]
    }

@app.get("/health")
async def health():
    """Endpoint de santé pour monitoring"""
    return {"status": "healthy", "version": "5.0"}

@app.get("/webhook/test")
async def test_webhook():
    """
    Endpoint de test pour vérifier la configuration webhook
    
    Retourne les informations sur l'environnement détecté et l'URL webhook
    sans envoyer de données réelles.
    """
    try:
        # Détecter l'environnement
        environment = detect_environment()
        webhook_url = get_webhook_url(environment)
        
        # Informations d'environnement pour debug
        env_info = {
            "ENVIRONMENT": os.environ.get('ENVIRONMENT', 'non défini'),
            "RAILWAY_ENVIRONMENT": os.environ.get('RAILWAY_ENVIRONMENT', 'non défini'),
            "RAILWAY_PUBLIC_DOMAIN": os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'non défini'),
            "RAILWAY_SERVICE_NAME": os.environ.get('RAILWAY_SERVICE_NAME', 'non défini')
        }
        
        return {
            "status": "success",
            "detected_environment": environment,
            "webhook_url": webhook_url,
            "env_variables": env_info,
            "message": f"Webhook configuré pour l'environnement {environment}"
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur test webhook: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/webhook/test-send")
async def test_webhook_send():
    """
    Endpoint de test pour envoyer un webhook de test
    
    Envoie un payload de test au webhook configuré selon l'environnement.
    """
    try:
        # Détecter l'environnement
        environment = detect_environment()
        webhook_url = get_webhook_url(environment)
        
        # Payload de test
        test_payload = {
            "test": True,
            "message": "Test webhook depuis CheckEasy API V5",
            "environment": environment,
            "timestamp": "2025-01-16T10:00:00Z",
            "logement_id": "test_logement_123",
            "total_issues_count": 0,
            "analysis_enrichment": {
                "global_score": {
                    "score": 5,
                    "label": "EXCELLENT",
                    "description": "Test de webhook - tout fonctionne parfaitement"
                }
            }
        }
        
        # Envoyer le webhook
        logger.info(f"🧪 Test d'envoi webhook vers {environment}")
        webhook_success = await send_webhook(test_payload, webhook_url)
        
        return {
            "status": "success" if webhook_success else "failed",
            "environment": environment,
            "webhook_url": webhook_url,
            "webhook_sent": webhook_success,
            "test_payload": test_payload,
            "message": "Webhook de test envoyé avec succès" if webhook_success else "Échec envoi webhook de test"
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur test envoi webhook: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

# ═══════════════════════════════════════════════════════════════
# 🔧 ENDPOINTS CRUD POUR GESTION DES ROOM TEMPLATES
# ═══════════════════════════════════════════════════════════════

class RoomTypeCreate(BaseModel):
    room_type_key: str = Field(description="Clé unique du type de pièce (ex: 'cuisine', 'salle_de_bain')")
    name: str = Field(description="Nom d'affichage de la pièce")
    icon: str = Field(description="Icône de la pièce (emoji ou texte)")
    verifications: RoomVerifications

class RoomTypeUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    verifications: Optional[RoomVerifications] = None

def save_room_templates(templates_data):
    """Sauvegarder les templates dans le fichier JSON et variables d'environnement Railway"""
    success_local = False
    success_env = False
    
    try:
        # 🔥 SAUVEGARDE 1: Fichier local (pour développement)
        possible_paths = [
            "room_classfication/room-verification-templates.json",
            "room-verification-templates.json",
            os.path.join(os.path.dirname(__file__), "room_classfication", "room-verification-templates.json")
        ]
        
        target_path = None
        for path in possible_paths:
            if os.path.exists(path):
                target_path = path
                break
        
        if not target_path:
            # Créer le répertoire si nécessaire
            os.makedirs("room_classfication", exist_ok=True)
            target_path = "room_classfication/room-verification-templates.json"
        
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ Templates sauvegardés dans le fichier: {target_path}")
        success_local = True
        
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde fichier local: {e}")
    
    try:
        # 🔥 SAUVEGARDE 2: Variable d'environnement (pour Railway production)
        templates_json = json.dumps(templates_data, ensure_ascii=False, separators=(',', ':'))
        
        # Note: En production Railway, cette mise à jour nécessitera un redémarrage
        # Pour une vraie persistence, il faudrait utiliser l'API Railway ou une DB
        os.environ['ROOM_TEMPLATES_CONFIG'] = templates_json
        
        logger.info("✅ Templates mis à jour dans les variables d'environnement")
        success_env = True
        
        # 🔥 IMPORTANT: Informer l'utilisateur pour Railway
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            logger.warning("⚠️ RAILWAY: Les modifications seront perdues au prochain déploiement!")
            logger.warning("💡 Utilisez l'interface d'admin Railway pour définir ROOM_TEMPLATES_CONFIG de façon permanente")
        
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde variable d'environnement: {e}")
    
    # Succès si au moins une méthode a fonctionné
    return success_local or success_env

def get_current_templates_as_env_var():
    """Retourner la configuration actuelle sous forme de variable d'environnement"""
    try:
        global ROOM_TEMPLATES
        return json.dumps(ROOM_TEMPLATES, ensure_ascii=False, separators=(',', ':'))
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération de la variable d'environnement: {e}")
        return None

@app.get("/room-templates")
async def get_all_room_templates():
    """Récupérer tous les types de pièces configurés"""
    try:
        global ROOM_TEMPLATES
        return {
            "success": True,
            "room_types": ROOM_TEMPLATES.get("room_types", {})
        }
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/room-templates/export/railway-env")
async def export_templates_for_railway():
    """🚀 Exporter la configuration actuelle pour Railway (variable d'environnement)"""
    try:
        env_var_value = get_current_templates_as_env_var()
        if env_var_value:
            return {
                "success": True,
                "message": "Configuration exportée pour Railway",
                "instructions": [
                    "1. Copiez la valeur 'env_var_value' ci-dessous",
                    "2. Allez dans Railway Dashboard > Variables",
                    "3. Créez/modifiez la variable: ROOM_TEMPLATES_CONFIG",
                    "4. Collez la valeur et sauvegardez",
                    "5. Railway redémarrera automatiquement avec la nouvelle config"
                ],
                "variable_name": "ROOM_TEMPLATES_CONFIG",
                "env_var_value": env_var_value,
                "railway_command": f"railway variables set ROOM_TEMPLATES_CONFIG='{env_var_value}'"
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de l'export")
    except Exception as e:
        logger.error(f"Erreur lors de l'export Railway: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/room-templates/{room_type_key}")
async def get_room_template(room_type_key: str):
    """Récupérer un type de pièce spécifique"""
    try:
        global ROOM_TEMPLATES
        room_types = ROOM_TEMPLATES.get("room_types", {})
        
        if room_type_key not in room_types:
            raise HTTPException(status_code=404, detail="Type de pièce non trouvé")
        
        return {
            "success": True,
            "room_type_key": room_type_key,
            "room_type": room_types[room_type_key]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du template {room_type_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/room-templates")
async def create_room_template(room_data: RoomTypeCreate):
    """Créer un nouveau type de pièce"""
    try:
        global ROOM_TEMPLATES
        
        # Vérifier si la clé existe déjà
        room_types = ROOM_TEMPLATES.get("room_types", {})
        if room_data.room_type_key in room_types:
            raise HTTPException(status_code=400, detail="Ce type de pièce existe déjà")
        
        # Ajouter le nouveau type
        if "room_types" not in ROOM_TEMPLATES:
            ROOM_TEMPLATES["room_types"] = {}
        
        ROOM_TEMPLATES["room_types"][room_data.room_type_key] = {
            "name": room_data.name,
            "icon": room_data.icon,
            "verifications": room_data.verifications.dict()
        }
        
        # Sauvegarder dans le fichier
        if save_room_templates(ROOM_TEMPLATES):
            return {
                "success": True,
                "message": "Type de pièce créé avec succès",
                "room_type_key": room_data.room_type_key
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création du template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/room-templates/{room_type_key}")
async def update_room_template(room_type_key: str, room_data: RoomTypeUpdate):
    """Mettre à jour un type de pièce existant"""
    try:
        global ROOM_TEMPLATES
        room_types = ROOM_TEMPLATES.get("room_types", {})
        
        if room_type_key not in room_types:
            raise HTTPException(status_code=404, detail="Type de pièce non trouvé")
        
        # Mettre à jour les champs fournis
        if room_data.name is not None:
            room_types[room_type_key]["name"] = room_data.name
        
        if room_data.icon is not None:
            room_types[room_type_key]["icon"] = room_data.icon
        
        if room_data.verifications is not None:
            room_types[room_type_key]["verifications"] = room_data.verifications.dict()
        
        # Sauvegarder dans le fichier
        if save_room_templates(ROOM_TEMPLATES):
            return {
                "success": True,
                "message": "Type de pièce mis à jour avec succès",
                "room_type": room_types[room_type_key]
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du template {room_type_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/room-templates/{room_type_key}")
async def delete_room_template(room_type_key: str):
    """Supprimer un type de pièce"""
    try:
        global ROOM_TEMPLATES
        room_types = ROOM_TEMPLATES.get("room_types", {})
        
        if room_type_key not in room_types:
            raise HTTPException(status_code=404, detail="Type de pièce non trouvé")
        
        # Supprimer le type de pièce
        deleted_room = room_types.pop(room_type_key)
        
        # Sauvegarder dans le fichier
        if save_room_templates(ROOM_TEMPLATES):
            return {
                "success": True,
                "message": "Type de pièce supprimé avec succès",
                "deleted_room": deleted_room
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du template {room_type_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 