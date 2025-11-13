from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import logging
import logging.config
import sys
import json
import os
from openai import OpenAI
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from image_converter import (
    process_pictures_list,
    process_etapes_images,
    is_valid_image_url,
    normalize_url,
    ImageConverter
)
from datetime import datetime
import re

# 🚀 CONFIGURATION LOGGING OPTIMISÉE RAILWAY
class RailwayJSONFormatter(logging.Formatter):
    """
    Formatter JSON optimisé pour Railway qui produit des logs structurés
    sans caractères spéciaux qui causent des problèmes d'interprétation
    """
    
    def format(self, record):
        # Créer un objet de log structuré
        log_obj = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Ajouter le traceback si présent
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Ajouter des champs personnalisés s'ils existent
        if hasattr(record, 'piece_id'):
            log_obj["piece_id"] = record.piece_id
        if hasattr(record, 'endpoint'):
            log_obj["endpoint"] = record.endpoint
        if hasattr(record, 'operation'):
            log_obj["operation"] = record.operation
            
        return json.dumps(log_obj, ensure_ascii=False)

def setup_railway_logging():
    """Configure le logging pour Railway avec format JSON structuré"""
    
    # Détecter si on est en environnement Railway ou local
    is_railway = any([
        os.environ.get('RAILWAY_ENVIRONMENT'),
        os.environ.get('RAILWAY_PUBLIC_DOMAIN'),
        os.environ.get('RAILWAY_SERVICE_NAME'),
        not sys.stderr.isatty()  # Pas de terminal interactif
    ])
    
    if is_railway:
        # Configuration Railway: JSON vers stdout
        logging_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "railway_json": {
                    "()": RailwayJSONFormatter,
                },
                "simple": {
                    "format": "[{levelname}] {name}: {message}",
                    "style": "{",
                }
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": "railway_json",
                    "level": "INFO"
                },
                "stderr": {
                    "class": "logging.StreamHandler", 
                    "stream": sys.stderr,
                    "formatter": "simple",
                    "level": "ERROR"
                }
            },
            "loggers": {
                "": {  # Root logger
                    "level": "INFO",
                    "handlers": ["stdout"],
                    "propagate": False
                },
                "uvicorn": {
                    "level": "WARNING", 
                    "handlers": ["stdout"],
                    "propagate": False
                },
                "fastapi": {
                    "level": "WARNING",
                    "handlers": ["stdout"], 
                    "propagate": False
                }
            }
        }
    else:
        # Configuration locale: format lisible avec couleurs
        logging_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "colored": {
                    "format": "\033[36m%(asctime)s\033[0m - \033[%(levelno)sm%(levelname)-8s\033[0m - \033[35m%(name)s\033[0m - %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "colored",
                    "level": "INFO"
                }
            },
            "loggers": {
                "": {  # Root logger
                    "level": "INFO", 
                    "handlers": ["console"],
                    "propagate": False
                }
            }
        }
    
    # Appliquer la configuration
    logging.config.dictConfig(logging_config)
    
    # Message de confirmation
    logger = logging.getLogger(__name__)
    if is_railway:
        logger.info("Logging configuré pour Railway (format JSON)")
    else:
        logger.info("Logging configuré pour développement local (format coloré)")

# Initialiser la configuration de logging
setup_railway_logging()
logger = logging.getLogger(__name__)

# 🛠️ HELPER FUNCTIONS POUR LOGGING RAILWAY-COMPATIBLE
def log_info(message: str, **kwargs):
    """Log message info avec contexte optionnel"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.info(message, extra=extra)

def log_warning(message: str, **kwargs):
    """Log message warning avec contexte optionnel"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.warning(message, extra=extra)

def log_error(message: str, **kwargs):
    """Log message error avec contexte optionnel"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.error(message, extra=extra)

def log_success(message: str, **kwargs):
    """Log message de succès"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.info(f"SUCCESS: {message}", extra=extra)

def log_openai_request(model: str, tokens: int, **kwargs):
    """Log spécialisé pour les requêtes OpenAI"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.info(f"OpenAI request - Model: {model}, Tokens: {tokens}", extra=extra)

def log_webhook(url: str, status: str, **kwargs):
    """Log spécialisé pour les webhooks"""
    extra = {k: v for k, v in kwargs.items() if k in ['piece_id', 'endpoint', 'operation']}
    logger.info(f"Webhook {status} - URL: {url}", extra=extra)

def log_environment_detection(env: str):
    """Log de détection d'environnement"""
    logger.info(f"Environment detected: {env.upper()}")

def log_template_loading(source: str, count: int = None):
    """Log de chargement des templates"""
    if count:
        logger.info(f"Templates loaded from {source} - Count: {count}")
    else:
        logger.info(f"Templates loaded from {source}")

def log_image_processing(checkin_count: int, checkout_count: int, piece_id: str = None):
    """Log de traitement d'images"""
    extra = {'piece_id': piece_id} if piece_id else {}
    logger.info(f"Image processing - Checkin: {checkin_count}, Checkout: {checkout_count}", extra=extra)

# Modèles Pydantic pour la structure de réponse et requête
class Picture(BaseModel):
    piece_id: str
    url: str

class InputData(BaseModel):
    piece_id: str
    nom: str
    type: str = "Voyageur"  # Type de parcours: "Voyageur" ou "Ménage"
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
    type: str = "Voyageur"  # Type de parcours: "Voyageur" ou "Ménage"
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
    log_success("Client OpenAI initialisé avec succès")
except Exception as e:
    log_error(f"Erreur critique lors de l'initialisation du client OpenAI: {e}")
    log_error(f"Clé API disponible: {'Oui' if OPENAI_API_KEY else 'Non'}")
    log_error(f"Longueur clé: {len(OPENAI_API_KEY) if OPENAI_API_KEY else 0}")
    try:
        # Fallback - essayer sans aucune configuration spéciale
        import openai
        openai.api_key = OPENAI_API_KEY
        client = openai.OpenAI()
        log_success("Client OpenAI initialisé avec fallback")
    except Exception as e2:
        log_error(f"Erreur aussi avec fallback: {e2}")
    client = None

# Charger les templates de vérification des pièces
def load_room_templates(parcours_type: str = "Voyageur"):
    """
    Charger les templates de vérification depuis variables d'environnement ou fichier JSON selon le type de parcours

    Args:
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        dict: Templates de vérification des pièces
    """
    try:
        # Normaliser le type de parcours
        parcours_type = parcours_type.strip() if parcours_type else "Voyageur"

        # Déterminer le suffixe du fichier selon le type
        if parcours_type.lower() == "ménage":
            file_suffix = "-menage"
            env_var_name = "ROOM_TEMPLATES_CONFIG_MENAGE"
        else:  # Par défaut: Voyageur
            file_suffix = "-voyageur"
            env_var_name = "ROOM_TEMPLATES_CONFIG_VOYAGEUR"

        logger.info(f"🔧 Chargement des templates de vérification pour le parcours: {parcours_type}")

        # 🔥 PRIORITÉ 1: Variable d'environnement Railway (production)
        room_templates_env = os.environ.get(env_var_name)
        if room_templates_env:
            try:
                logger.info(f"📡 Chargement des templates depuis la variable d'environnement {env_var_name}")
                return json.loads(room_templates_env)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Erreur lors du parsing JSON de {env_var_name}: {e}")

        # 🔥 PRIORITÉ 2: Fichier local (développement/fallback)
        possible_paths = [
            f"room_classfication/room-verification-templates{file_suffix}.json",
            f"room-verification-templates{file_suffix}.json",
            os.path.join(os.path.dirname(__file__), "room_classfication", f"room-verification-templates{file_suffix}.json")
        ]

        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"📁 Chargement des templates depuis le fichier: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)

        # 🔥 PRIORITÉ 3: Configuration par défaut
        logger.warning(f"⚠️ Aucun template trouvé pour {parcours_type}, utilisation de la configuration par défaut")
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

# Charger les templates au démarrage (par défaut: Voyageur)
ROOM_TEMPLATES = load_room_templates("Voyageur")

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

def build_dynamic_prompt(input_data: InputData, parcours_type: str = "Voyageur") -> str:
    """
    Construire un prompt dynamique basé sur les critères spécifiques de la pièce

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        str: Prompt dynamique construit
    """
    try:
        # 📋 Construction du prompt avec données injectées
        logger.info(f"🔧 Prompt pour {input_data.nom} (parcours: {parcours_type}): {len(input_data.elements_critiques)} critiques, {len(input_data.points_ignorables)} ignorables, {len(input_data.defauts_frequents)} défauts")

        # Charger la configuration des prompts selon le type de parcours
        prompts_config = load_prompts_config(parcours_type)
        analyze_main_config = prompts_config.get("prompts", {}).get("analyze_main", {})
        
        # Préparer les variables pour les templates
        # 🔥 AMÉLIORATION: Formater les listes avec des puces pour une meilleure lisibilité
        elements_critiques_formatted = '\n'.join(f"• {element}" for element in input_data.elements_critiques) if input_data.elements_critiques else "Aucun élément critique spécifique configuré"
        points_ignorables_formatted = '\n'.join(f"• {point}" for point in input_data.points_ignorables) if input_data.points_ignorables else "Aucun point ignorable spécifique configuré"
        defauts_frequents_formatted = '\n'.join(f"• {defaut}" for defaut in input_data.defauts_frequents) if input_data.defauts_frequents else "Aucun défaut fréquent spécifique configuré"
        
        # 🗺️ MAPPING ÉTENDU: Couvrir toutes les variations possibles de noms de variables
        variables = {
            # Variables de base
            "commentaire_ia": input_data.commentaire_ia,
            "elements_critiques": elements_critiques_formatted,
            "points_ignorables": points_ignorables_formatted,
            "defauts_frequents": defauts_frequents_formatted,
            "piece_nom": input_data.nom,
            
            # Variations avec "_list"
            "elements_critiques_list": elements_critiques_formatted,
            "points_ignorables_list": points_ignorables_formatted,  
            "defauts_frequents_list": defauts_frequents_formatted,
            
            # Variations avec "_items"
            "elements_critiques_items": elements_critiques_formatted,
            "points_ignorables_items": points_ignorables_formatted,
            "defauts_frequents_items": defauts_frequents_formatted,
            
            # Variations en anglais
            "critical_elements": elements_critiques_formatted,
            "ignorable_points": points_ignorables_formatted,
            "frequent_defects": defauts_frequents_formatted,
            
            # Données brutes (listes non formatées) pour flexibilité
            "elements_critiques_raw": input_data.elements_critiques,
            "points_ignorables_raw": input_data.points_ignorables,
            "defauts_frequents_raw": input_data.defauts_frequents,
            
            # Métadonnées
            "nb_elements_critiques": len(input_data.elements_critiques),
            "nb_points_ignorables": len(input_data.points_ignorables),
            "nb_defauts_frequents": len(input_data.defauts_frequents),
            
            # ID et informations de contexte
            "piece_id": input_data.piece_id,
            "nom_piece": input_data.nom,
            "piece_name": input_data.nom
        }
        
        # Variables préparées pour injection
        
        # Utiliser la fonction standardisée pour construire le prompt
        full_prompt = build_full_prompt_from_config(analyze_main_config, variables)
        
        # Vérifier que le prompt n'est pas vide
        if full_prompt and len(full_prompt) > 100:
            logger.info(f"✅ Prompt construit: {len(full_prompt)} caractères")
            return full_prompt
        else:
            logger.warning("⚠️ Prompt vide, utilisation du fallback")
            raise ValueError("Prompt vide depuis la configuration")
    
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors du chargement de la config prompts: {e}")
        logger.warning("🔄 Utilisation du prompt de secours minimal")
        
        # Fallback minimal - uniquement en cas d'erreur critique
        return """Tu es un expert en inspection de propreté. Analyse les différences entre les photos d'entrée et de sortie.

INSTRUCTIONS :
1. Compare méticuleusement les photos d'entrée avec celles de sortie
2. Identifie les changements significatifs
3. Utilise des descriptions précises
4. Évalue la gravité (low/medium/high)

IMPORTANT :
- Si des instructions spéciales sont données, les respecter absolument
- Si des éléments critiques sont définis, les vérifier en priorité
- Si des points ignorables sont définis, ne jamais les signaler

RÉPONDS EN FORMAT JSON :
{
    "piece_id": "string",
    "nom_piece": "string", 
    "analyse_globale": {
        "status": "ok|attention|probleme",
        "score": 0-10,
        "temps_nettoyage_estime": "string",
        "commentaire_global": "string"
    },
    "preliminary_issues": [
        {
            "description": "string",
            "category": "cleanliness|damage|positioning|missing_item|added_item|image_quality|wrong_room",
            "severity": "low|medium|high",
            "confidence": 0-100
        }
    ]
}"""

# 🚀 FALLBACK SYSTEM VERSION
FALLBACK_SYSTEM_VERSION = "v1.0.0-data-uri-fallback"
logger.info(f"🚀 Système de fallback Data URI chargé: {FALLBACK_SYSTEM_VERSION}")

def convert_url_to_data_uri(url: str) -> Optional[str]:
    """
    Convertit une URL d'image en data URI base64
    Utilisé comme fallback quand OpenAI ne peut pas télécharger l'URL

    Args:
        url: URL de l'image à convertir

    Returns:
        Data URI base64 ou None si échec
    """
    try:
        logger.info(f"🔄 Conversion URL → Data URI: {url}")

        # Télécharger l'image
        image_data, detected_format = ImageConverter.download_image(url)

        if not image_data:
            logger.error(f"❌ Échec téléchargement pour conversion data URI: {url}")
            return None

        # Convertir en JPEG pour optimiser la taille
        jpeg_data = ImageConverter.convert_image_to_jpeg_for_ai(image_data, max_quality=True)

        # Créer la data URI
        data_uri = ImageConverter.upload_to_temp_service(jpeg_data, 'jpeg')

        logger.info(f"✅ Conversion réussie: {len(data_uri)} caractères")
        return data_uri

    except Exception as e:
        logger.error(f"❌ Erreur conversion URL → Data URI pour {url}: {e}")
        return None

def convert_message_urls_to_data_uris(user_message: dict) -> dict:
    """
    Convertit toutes les URLs d'images dans un message en data URIs
    Utilisé comme fallback quand OpenAI ne peut pas télécharger les URLs

    Args:
        user_message: Message utilisateur avec des image_url

    Returns:
        Message modifié avec data URIs
    """
    try:
        logger.info("🔄 Conversion de toutes les URLs en Data URIs...")

        converted_count = 0
        failed_count = 0

        # Parcourir le contenu du message
        for content_item in user_message.get("content", []):
            if content_item.get("type") == "image_url":
                original_url = content_item["image_url"]["url"]

                # Ne convertir que si ce n'est pas déjà une data URI
                if not original_url.startswith("data:"):
                    logger.info(f"🔄 Conversion de: {original_url[:100]}...")

                    data_uri = convert_url_to_data_uri(original_url)

                    if data_uri:
                        content_item["image_url"]["url"] = data_uri
                        converted_count += 1
                        logger.info(f"✅ URL convertie en Data URI")
                    else:
                        failed_count += 1
                        logger.warning(f"⚠️ Échec conversion, URL conservée")

        logger.info(f"📊 Conversion terminée: {converted_count} réussies, {failed_count} échecs")
        return user_message

    except Exception as e:
        logger.error(f"❌ Erreur lors de la conversion des URLs: {e}")
        return user_message

def analyze_images(input_data: InputData, parcours_type: str = "Voyageur") -> AnalyseResponse:
    """
    Analyser les images d'entrée et de sortie et retourner une réponse structurée.

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        AnalyseResponse: Résultat de l'analyse
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
            # 🔧 NORMALISER L'URL JUSTE AVANT ENVOI À OPENAI
            normalized_photo_url = normalize_url(photo['url'])
            logger.info(f"🔍 ANALYSE CHECKIN - URL avant normalisation: '{photo['url']}'")
            logger.info(f"🔍 ANALYSE CHECKIN - URL après normalisation: '{normalized_photo_url}'")

            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_checkin.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": normalized_photo_url,  # ✅ Utiliser l'URL normalisée
                        "detail": "high"
                    }
                })
                logger.info(f"✅ ANALYSE CHECKIN - Image ajoutée au payload OpenAI: {normalized_photo_url}")
            else:
                logger.warning(f"⚠️ ANALYSE CHECKIN - Image invalide ignorée: {normalized_photo_url}")

        # Filtrer et ajouter seulement les photos de sortie valides
        valid_checkout = []
        for photo in processed_checkout:
            # 🔧 NORMALISER L'URL JUSTE AVANT ENVOI À OPENAI
            normalized_photo_url = normalize_url(photo['url'])
            logger.info(f"🔍 ANALYSE CHECKOUT - URL avant normalisation: '{photo['url']}'")
            logger.info(f"🔍 ANALYSE CHECKOUT - URL après normalisation: '{normalized_photo_url}'")

            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_checkout.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": normalized_photo_url,  # ✅ Utiliser l'URL normalisée
                        "detail": "high"
                    }
                })
                logger.info(f"✅ ANALYSE CHECKOUT - Image ajoutée au payload OpenAI: {normalized_photo_url}")
            else:
                logger.warning(f"⚠️ ANALYSE CHECKOUT - Image invalide ignorée: {normalized_photo_url}")
        
        logger.info(f"📷 Images valides envoyées à OpenAI: {len(valid_checkin)} checkin + {len(valid_checkout)} checkout (sur {len(processed_checkin)}+{len(processed_checkout)} traitées)")
        
        # Si aucune image valide, ajouter une note
        if len(valid_checkin) == 0 and len(valid_checkout) == 0:
            user_message["content"].append({
                "type": "text",
                "text": "⚠️ Aucune image disponible - Fournir une analyse générique basée sur le type de pièce uniquement."
            })

        # Construire le prompt dynamique avec le type de parcours
        dynamic_prompt = build_dynamic_prompt(input_data, parcours_type)

        # 🔍 PAYLOAD OPENAI - ANALYSE PRINCIPALE STRUCTURÉ
        logger.info(f"")
        logger.info(f"🔬 ╔══════════════════════════════════════════════════════════════════════════════╗")
        logger.info(f"🔬 ║                     PAYLOAD ENVOYÉ À OPENAI - ANALYSE                       ║")
        logger.info(f"🔬 ╚══════════════════════════════════════════════════════════════════════════════╝")
        logger.info(f"")
        
        logger.info(f"🔬 🤖 PARAMÈTRES DE L'APPEL:")
        logger.info(f"🔬    ├─ Modèle: gpt-4.1-2025-04-14")
        logger.info(f"🔬    ├─ Temperature: 0.2")
        logger.info(f"🔬    ├─ Max tokens: 16000")
        logger.info(f"🔬    └─ Response format: json_object")
        logger.info(f"")
        
        # Analyser le prompt pour identifier les sections injectées
        prompt_lines = dynamic_prompt.split('\n')
        total_lines = len(prompt_lines)
        
        logger.info(f"🔬 📋 PROMPT SYSTÈME (role: system):")
        logger.info(f"🔬    ├─ Longueur totale: {len(dynamic_prompt)} caractères")
        logger.info(f"🔬    ├─ Nombre de lignes: {total_lines}")
        logger.info(f"🔬    └─ Pièce analysée: {input_data.nom}")
        logger.info(f"")
        
        # Identifier et afficher les sections importantes du prompt
        logger.info(f"🔬 🎯 VARIABLES INJECTÉES DANS LE PROMPT:")
        logger.info(f"🔬    ├─ 🔍 Éléments critiques: {len(input_data.elements_critiques)} items")
        for i, element in enumerate(input_data.elements_critiques[:5]):  # Limiter à 5 pour la lisibilité
            prefix = "├─" if i < min(4, len(input_data.elements_critiques)-1) else "└─"
            logger.info(f"🔬    │   {prefix} • {element}")
        if len(input_data.elements_critiques) > 5:
            logger.info(f"🔬    │       ... et {len(input_data.elements_critiques)-5} autres")
        
        logger.info(f"🔬    ├─ 🚫 Points ignorables: {len(input_data.points_ignorables)} items")
        for i, point in enumerate(input_data.points_ignorables[:3]):  # Limiter à 3
            prefix = "├─" if i < min(2, len(input_data.points_ignorables)-1) else "└─"
            logger.info(f"🔬    │   {prefix} • {point}")
        if len(input_data.points_ignorables) > 3:
            logger.info(f"🔬    │       ... et {len(input_data.points_ignorables)-3} autres")
        
        logger.info(f"🔬    ├─ ⚠️ Défauts fréquents: {len(input_data.defauts_frequents)} items")
        for i, defaut in enumerate(input_data.defauts_frequents[:3]):  # Limiter à 3
            prefix = "├─" if i < min(2, len(input_data.defauts_frequents)-1) else "└─"
            logger.info(f"🔬    │   {prefix} • {defaut}")
        if len(input_data.defauts_frequents) > 3:
            logger.info(f"🔬    │       ... et {len(input_data.defauts_frequents)-3} autres")
        
        if input_data.commentaire_ia and input_data.commentaire_ia.strip():
            logger.info(f"🔬    └─ 🤖 Instructions spéciales: '{input_data.commentaire_ia}'")
        else:
            logger.info(f"🔬    └─ 🤖 Instructions spéciales: Aucune")
        logger.info(f"")
        
        # Afficher les premières lignes du prompt pour vérification
        logger.info(f"🔬 📄 APERÇU DU PROMPT SYSTÈME (50 premières lignes):")
        for i, line in enumerate(prompt_lines[:50]):
            if line.strip():  # Ignorer les lignes vides
                logger.info(f"🔬    {i+1:2d}│ {line}")
        if total_lines > 50:
            logger.info(f"🔬      │ ... ({total_lines - 50} lignes supplémentaires)")
        logger.info(f"")
        
        # Message utilisateur structuré
        total_images = len([c for c in user_message['content'] if c['type'] == 'image_url'])
        total_text_items = len([c for c in user_message['content'] if c['type'] == 'text'])
        
        logger.info(f"🔬 💬 MESSAGE UTILISATEUR (role: user):")
        logger.info(f"🔬    ├─ Éléments texte: {total_text_items}")
        logger.info(f"🔬    └─ Images: {total_images} ({len(valid_checkin)} checkin + {len(valid_checkout)} checkout)")
        logger.info(f"")
        
        # Détail du contenu utilisateur
        text_counter = 0
        image_counter = 0
        for content_item in user_message['content']:
            if content_item['type'] == 'text':
                text_counter += 1
                text_content = content_item['text']
                if len(text_content) > 150:
                    text_preview = text_content[:150] + "..."
                else:
                    text_preview = text_content
                logger.info(f"🔬    📝 TEXTE {text_counter}: {text_preview}")
            elif content_item['type'] == 'image_url':
                image_counter += 1
                image_url = content_item['image_url']['url']
                image_detail = content_item['image_url'].get('detail', 'default')
                # Extraire le nom de fichier de l'URL
                filename = image_url.split('/')[-1][:30] if '/' in image_url else image_url[:30]
                logger.info(f"🔬    🖼️ IMAGE {image_counter}: {filename}... (detail: {image_detail})")
        
        logger.info(f"")
        logger.info(f"🔬 ✅ RÉSUMÉ FINAL:")
        logger.info(f"🔬    ├─ Prompt système: {len(dynamic_prompt)} caractères ({total_lines} lignes)")
        logger.info(f"🔬    ├─ Variables injectées: {len(input_data.elements_critiques) + len(input_data.points_ignorables) + len(input_data.defauts_frequents)} au total")
        logger.info(f"🔬    ├─ Images analysées: {total_images} ({len(valid_checkin)} checkin + {len(valid_checkout)} checkout)")
        logger.info(f"🔬    └─ Pièce: {input_data.nom} (ID: {input_data.piece_id})")
        logger.info(f"")
        logger.info(f"🔬 ╚══════════════════════════════════════════════════════════════════════════════╝")
        logger.info(f"")

        # 🔗 ENVOI PARALLÈLE DU PAYLOAD VERS BUBBLE (pour debug)
        async def send_payload_to_bubble():
            """Envoyer le payload complet vers Bubble en parallèle"""
            try:
                bubble_endpoint = "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/iatest"
                
                # Préparer le payload exact envoyé à OpenAI
                openai_payload = {
                    "model": "gpt-4.1-2025-04-14",
                    "messages": [
                        {
                            "role": "system",
                            "content": dynamic_prompt
                        },
                        user_message
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                    "max_tokens": 16000
                }
                
                # Payload enrichi pour Bubble avec métadonnées
                bubble_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "piece_id": input_data.piece_id,
                    "piece_nom": input_data.nom,
                    "endpoint_source": "/analyze-with-classification",
                    "operation_type": "analysis",
                    "openai_payload": openai_payload,
                    "metadata": {
                        "elements_critiques_count": len(input_data.elements_critiques),
                        "points_ignorables_count": len(input_data.points_ignorables),
                        "defauts_frequents_count": len(input_data.defauts_frequents),
                        "images_count": len([c for c in user_message['content'] if c['type'] == 'image_url']),
                        "prompt_length": len(dynamic_prompt),
                        "has_commentaire_ia": bool(input_data.commentaire_ia and input_data.commentaire_ia.strip())
                    },
                    "variables_injectees": {
                        "elements_critiques": input_data.elements_critiques,
                        "points_ignorables": input_data.points_ignorables,
                        "defauts_frequents": input_data.defauts_frequents,
                        "commentaire_ia": input_data.commentaire_ia
                    }
                }
                
                logger.info(f"🔗 Envoi payload vers Bubble: {bubble_endpoint}")
                
                # Configuration du timeout et des headers
                timeout = aiohttp.ClientTimeout(total=10)  # 10 secondes max pour ne pas bloquer
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'CheckEasy-API-V5-Debug'
                }
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        bubble_endpoint,
                        json=bubble_payload,
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            response_text = await response.text()
                            logger.info(f"✅ Payload envoyé à Bubble avec succès: {response_text[:100]}...")
                        else:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Bubble réponse non-200 ({response.status}): {error_text[:100]}...")
                            
            except asyncio.TimeoutError:
                logger.warning("⚠️ Timeout lors de l'envoi vers Bubble (analyse continue)")
            except Exception as e:
                logger.warning(f"⚠️ Erreur envoi vers Bubble: {e} (analyse continue)")
        
        # Lancer l'envoi vers Bubble en arrière-plan (non bloquant)
        asyncio.create_task(send_payload_to_bubble())

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
                temperature=0,  # 🔧 Changé de 0.2 à 0 pour plus de déterminisme
                max_tokens=16000
                #temperature=1,
                #max_completion_tokens=16000
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de l'analyse: {error_str}")

            # 🔍 DEBUG: Vérifier le contenu de error_str
            error_str_lower = error_str.lower()
            logger.info(f"🔍 DEBUG - error_str_lower contient 'timeout while downloading': {'timeout while downloading' in error_str_lower}")
            logger.info(f"🔍 DEBUG - error_str_lower contient 'error while downloading': {'error while downloading' in error_str_lower}")
            logger.info(f"🔍 DEBUG - error_str_lower contient 'invalid_image_url': {'invalid_image_url' in error_str_lower}")

            # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
            if any(keyword in error_str_lower for keyword in [
                "error while downloading",
                "timeout while downloading",
                "invalid_image_url",
                "failed to download"
            ]):
                logger.warning("⚠️ Erreur de téléchargement d'image détectée, tentative avec Data URIs")

                try:
                    # Convertir toutes les URLs en data URIs
                    user_message_with_data_uris = convert_message_urls_to_data_uris(user_message.copy())

                    # Compter les images converties
                    data_uri_count = sum(
                        1 for c in user_message_with_data_uris.get("content", [])
                        if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                    )

                    logger.info(f"🔄 Retry avec {data_uri_count} images en Data URI")

                    # Réessayer avec les data URIs
                    response = client.chat.completions.create(
                        model="gpt-4.1-2025-04-14",
                        messages=[
                            {
                                "role": "system",
                                "content": dynamic_prompt
                            },
                            user_message_with_data_uris
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        max_tokens=16000
                    )
                    logger.info("✅ Analyse réussie avec Data URIs (fallback téléchargement)")

                except Exception as data_uri_error:
                    logger.error(f"❌ Échec du fallback Data URI: {data_uri_error}")

                    # Si le fallback Data URI échoue aussi, passer au fallback sans images
                    logger.warning("⚠️ Tentative finale sans images")

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
                    except Exception as final_error:
                        logger.error(f"❌ Échec de tous les fallbacks: {final_error}")
                        return AnalyseResponse(
                            piece_id=input_data.piece_id,
                            nom_piece=input_data.nom,
                            analyse_globale=AnalyseGlobale(
                                status="attention",
                                score=5.0,
                                temps_nettoyage_estime="Non estimable",
                                commentaire_global="Analyse impossible : erreur technique"
                            ),
                            preliminary_issues=[
                                Probleme(
                                    description="Erreur technique lors de l'analyse",
                                    category="image_quality",
                                    severity="medium",
                                    confidence=100
                                )
                            ]
                        )

            # 🔄 FALLBACK 2: Erreurs de format d'image → Sans images
            elif "invalid_image_format" in error_str or "unsupported image" in error_str:
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
                                description="Erreur technique lors de l'analyse",
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

        # 🛡️ VALIDATION ET CORRECTION DU FORMAT DE RÉPONSE
        try:
            response_content = response.choices[0].message.content.strip()
            logger.info(f"📄 Réponse IA reçue: {len(response_content)} caractères")
            
            # Tenter de parser le JSON
            try:
                response_json = json.loads(response_content)
                logger.info("✅ JSON parsé avec succès")
            except json.JSONDecodeError as json_error:
                logger.error(f"❌ Erreur parsing JSON: {json_error}")
                logger.error(f"   📄 Contenu: {response_content}")
                raise ValueError(f"Réponse IA invalide: JSON malformé")

            # 🔍 DEBUG CRITIQUE: Logger la réponse BRUTE de l'IA AVANT validation
            preliminary_issues_count = len(response_json.get("preliminary_issues", []))
            logger.info(f"🔍 DEBUG - Réponse BRUTE de l'IA: {preliminary_issues_count} issues détectées")
            if preliminary_issues_count > 0:
                logger.info(f"🔍 DEBUG - Premières issues brutes: {json.dumps(response_json.get('preliminary_issues', [])[:3], indent=2, ensure_ascii=False)}")
            else:
                logger.warning(f"⚠️ DEBUG - L'IA n'a détecté AUCUNE ISSUE dans sa réponse brute !")

            # 🔍 VÉRIFICATION DU FORMAT - Détecter les formats incorrects
            required_fields = ["piece_id", "nom_piece", "analyse_globale", "preliminary_issues"]
            missing_fields = []
            
            for field in required_fields:
                if field not in response_json:
                    missing_fields.append(field)
            
            # 🚨 DÉTECTION ET CORRECTION DES FORMATS INCORRECTS
            if missing_fields:
                logger.error(f"❌ FORMAT INCORRECT détecté!")
                logger.error(f"   📋 Champs manquants: {missing_fields}")
                logger.error(f"   📄 Clés présentes: {list(response_json.keys())}")
                logger.error(f"⚠️ DEBUG - FALLBACK DÉCLENCHÉ : preliminary_issues sera FORCÉ À [] !")

                # Tenter de récupérer les données dans des structures non-standard
                corrected_response = {
                    "piece_id": input_data.piece_id,
                    "nom_piece": input_data.nom,
                    "analyse_globale": {
                        "status": "attention",
                        "score": 5.0,
                        "temps_nettoyage_estime": "15 minutes",
                        "commentaire_global": "Analyse partielle - format de réponse IA non standard détecté"
                    },
                    "preliminary_issues": []
                }
                
                # Essayer de récupérer des données pertinentes
                if isinstance(response_json, dict):
                    # Chercher des indices dans la réponse malformée
                    for key, value in response_json.items():
                        if isinstance(value, dict):
                            # Essayer d'extraire des informations utiles
                            if "score" in str(value).lower():
                                try:
                                    # Extraire un score si possible
                                    import re
                                    score_match = re.search(r'score["\s:]*(\d+(?:\.\d+)?)', str(value), re.IGNORECASE)
                                    if score_match:
                                        corrected_response["analyse_globale"]["score"] = float(score_match.group(1))
                                except:
                                    pass
                            
                            if "problème" in str(value).lower() or "issue" in str(value).lower():
                                corrected_response["preliminary_issues"].append({
                                    "description": f"Analyse récupérée: {str(value)[:200]}",
                                    "category": "cleanliness",
                                    "severity": "medium", 
                                    "confidence": 70
                                })
                
                logger.warning(f"🔧 CORRECTION appliquée: Format standardisé forcé")
                response_json = corrected_response
            
            # Valider que analyse_globale a la bonne structure
            if "analyse_globale" in response_json:
                analyse_globale = response_json["analyse_globale"]
                if not isinstance(analyse_globale, dict):
                    logger.error("❌ analyse_globale n'est pas un dictionnaire")
                    response_json["analyse_globale"] = {
                        "status": "attention",
                        "score": 5.0,
                        "temps_nettoyage_estime": "Non estimable",
                        "commentaire_global": "Format d'analyse corrigé automatiquement"
                    }
                else:
                    # Vérifier et corriger les champs requis
                    if "status" not in analyse_globale:
                        analyse_globale["status"] = "attention"
                    if "score" not in analyse_globale:
                        analyse_globale["score"] = 5.0
                    if "temps_nettoyage_estime" not in analyse_globale:
                        analyse_globale["temps_nettoyage_estime"] = "Non estimé"
                    if "commentaire_global" not in analyse_globale:
                        analyse_globale["commentaire_global"] = "Analyse technique complétée"
            
            # Valider et corriger preliminary_issues
            if "preliminary_issues" not in response_json or not isinstance(response_json["preliminary_issues"], list):
                logger.warning("⚠️ DEBUG - preliminary_issues manquant ou invalide, FORCÉ À [] !")
                logger.warning(f"   Type reçu: {type(response_json.get('preliminary_issues'))}")
                response_json["preliminary_issues"] = []
            else:
                logger.info(f"✅ DEBUG - preliminary_issues valide: {len(response_json['preliminary_issues'])} issues conservées")
            
            # Valider piece_id et nom_piece
            if "piece_id" not in response_json:
                response_json["piece_id"] = input_data.piece_id
            if "nom_piece" not in response_json:
                response_json["nom_piece"] = input_data.nom
            
            logger.info("✅ Format validé et corrigé si nécessaire")
            
            # Convertir en JSON standardisé pour Pydantic
            standardized_json = json.dumps(response_json)
            
        except Exception as validation_error:
            logger.error(f"❌ Erreur lors de la validation: {validation_error}")
            # Fallback complet
            standardized_json = json.dumps({
                "piece_id": input_data.piece_id,
                "nom_piece": input_data.nom,
                "analyse_globale": {
                    "status": "attention",
                    "score": 5.0,
                    "temps_nettoyage_estime": "Non estimable",
                    "commentaire_global": "Erreur de validation - analyse de secours appliquée"
                },
                "preliminary_issues": []
            })
            logger.warning("🔧 Fallback JSON appliqué")

        # Parser la réponse avec Pydantic
        try:
            return AnalyseResponse.model_validate_json(standardized_json)
        except Exception as pydantic_error:
            logger.error(f"❌ Erreur Pydantic finale: {pydantic_error}")
            logger.error(f"   📄 JSON standardisé: {standardized_json}")
            
            # Fallback ultime
            return AnalyseResponse(
                piece_id=input_data.piece_id,
                nom_piece=input_data.nom,
                analyse_globale=AnalyseGlobale(
                    status="attention",
                    score=5.0,
                    temps_nettoyage_estime="Non estimable",
                    commentaire_global="Erreur de format - analyse de secours"
                ),
                preliminary_issues=[]
            )

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
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        return analyze_images(input_data, parcours_type)
    except Exception as e:
        logger.error(f"Erreur lors de la requête: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def classify_room_type(input_data: RoomClassificationInput, parcours_type: str = "Voyageur") -> RoomClassificationResponse:
    """
    Classifier le type de pièce à partir des images et retourner les critères de vérification

    Args:
        input_data: Données d'entrée pour la classification
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        RoomClassificationResponse: Résultat de la classification avec critères
    """
    try:
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible dans classify_room_type")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible - Client non initialisé")

        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(parcours_type)

        # Créer le prompt de classification depuis la config JSON
        try:
            prompts_config = load_prompts_config(parcours_type)
            classify_room_config = prompts_config.get("prompts", {}).get("classify_room", {})

            # Préparer les variables pour le template
            room_types_list = list(room_templates["room_types"].keys())
            room_descriptions = []
            for room_key, room_info in room_templates["room_types"].items():
                room_descriptions.append(f"- {room_key}: {room_info['name']} {room_info['icon']}")
            
            variables = {
                "room_types_list": ', '.join(room_types_list),
                "room_descriptions_list": '\n'.join(room_descriptions)
            }
            
            # Utiliser la fonction standardisée
            classification_prompt = build_full_prompt_from_config(classify_room_config, variables)
            
            if not classification_prompt or len(classification_prompt) < 100:
                raise ValueError("Prompt de classification vide")
                
        except Exception as config_error:
            logger.warning(f"⚠️ Erreur config classification: {config_error}, utilisation fallback")
            # Fallback minimal
            classification_prompt = f"""Tu es un expert en classification d'espaces intérieurs.
Analyse les images et détermine le type de pièce.

Types disponibles: {', '.join(room_types_list)}

RÉPONDS EN JSON:
{{
    "room_type": "type_de_piece",
    "confidence": 0-100
}}"""

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
            # 🔧 NORMALISER L'URL JUSTE AVANT ENVOI À OPENAI
            normalized_photo_url = normalize_url(photo['url'])
            logger.info(f"🔍 CLASSIFICATION - URL avant normalisation: '{photo['url']}'")
            logger.info(f"🔍 CLASSIFICATION - URL après normalisation: '{normalized_photo_url}'")

            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_images.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": normalized_photo_url,  # ✅ Utiliser l'URL normalisée
                        "detail": "high"
                    }
                })
                logger.info(f"✅ CLASSIFICATION - Image ajoutée au payload OpenAI: {normalized_photo_url}")
            else:
                logger.warning(f"⚠️ CLASSIFICATION - Image invalide ignorée: {normalized_photo_url}")
        
        logger.info(f"📷 Images valides envoyées à OpenAI: {len(valid_images)}/{len(all_pictures_processed)}")
        
        # Si aucune image valide, ajouter une note et adapter le prompt
        if len(valid_images) == 0:
            user_message["content"].append({
                "type": "text",
                "text": f"⚠️ Aucune image disponible - Classification basée uniquement sur le nom de la pièce: '{input_data.nom}'. Si le nom n'est pas fourni ou peu informatif, utiliser 'autre' avec une confiance faible."
            })
        
        # 🔍 PAYLOAD OPENAI - CLASSIFICATION
        logger.info(f"🤖 ═══ PAYLOAD CLASSIFICATION → OPENAI ═══")
        prompt_text = next((c['text'] for c in user_message['content'] if c['type'] == 'text'), "Aucun prompt")
        logger.info(f"🤖 PROMPT: {prompt_text[:200]}...")
        logger.info(f"🤖 IMAGES: {len([c for c in user_message['content'] if c['type'] == 'image_url'])} images")
        logger.info(f"🤖 ════════════════════════════════════════")

        # 🔗 ENVOI PARALLÈLE DU PAYLOAD DE CLASSIFICATION VERS BUBBLE 
        async def send_classification_payload_to_bubble():
            """Envoyer le payload de classification vers Bubble en parallèle"""
            try:
                bubble_endpoint = "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/iatest"
                
                # Extraire le texte du prompt de classification
                classification_text = ""
                for content in user_message['content']:
                    if content['type'] == 'text':
                        classification_text = content['text']
                        break
                
                # Préparer le payload exact envoyé à OpenAI pour la classification
                openai_payload = {
                    "model": "gpt-4o",
                    "messages": [user_message],
                    "max_tokens": 200,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }
                
                # Payload enrichi pour Bubble avec métadonnées de classification
                bubble_payload = {
                    "timestamp": datetime.now().isoformat(),
                    "piece_id": input_data.piece_id,
                    "piece_nom": input_data.nom,
                    "endpoint_source": "/classify-room",
                    "operation_type": "classification",
                    "openai_payload": openai_payload,
                    "metadata": {
                        "images_count": len([c for c in user_message['content'] if c['type'] == 'image_url']),
                        "prompt_type": "classification",
                        "room_types_available": list(room_templates["room_types"].keys()),
                        "classification_prompt_length": len(classification_text),
                        "classification_prompt_preview": classification_text[:200] + "..." if len(classification_text) > 200 else classification_text
                    },
                    "room_templates_context": {
                        "available_room_types": list(room_templates["room_types"].keys()),
                        "total_room_templates": len(room_templates["room_types"])
                    }
                }
                
                logger.info(f"🔗 Envoi payload CLASSIFICATION vers Bubble: {bubble_endpoint}")
                
                # Configuration du timeout et des headers
                timeout = aiohttp.ClientTimeout(total=8)  # 8 secondes pour classification
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'CheckEasy-API-V5-Classification-Debug'
                }
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        bubble_endpoint,
                        json=bubble_payload,
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            response_text = await response.text()
                            logger.info(f"✅ Payload CLASSIFICATION envoyé à Bubble: {response_text[:100]}...")
                        else:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Bubble CLASSIFICATION réponse non-200 ({response.status}): {error_text[:100]}...")
                            
            except asyncio.TimeoutError:
                logger.warning("⚠️ Timeout lors de l'envoi CLASSIFICATION vers Bubble (classification continue)")
            except Exception as e:
                logger.warning(f"⚠️ Erreur envoi CLASSIFICATION vers Bubble: {e} (classification continue)")
        
        # Lancer l'envoi vers Bubble en arrière-plan (non bloquant)
        asyncio.create_task(send_classification_payload_to_bubble())

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

            # 🔍 DEBUG: Vérifier le contenu de error_str
            error_str_lower = error_str.lower()
            logger.info(f"🔍 DEBUG - error_str_lower contient 'timeout while downloading': {'timeout while downloading' in error_str_lower}")
            logger.info(f"🔍 DEBUG - error_str_lower contient 'error while downloading': {'error while downloading' in error_str_lower}")
            logger.info(f"🔍 DEBUG - error_str_lower contient 'invalid_image_url': {'invalid_image_url' in error_str_lower}")

            # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
            if any(keyword in error_str_lower for keyword in [
                "error while downloading",
                "timeout while downloading",
                "invalid_image_url",
                "failed to download"
            ]):
                logger.warning("⚠️ Erreur de téléchargement d'image détectée, tentative avec Data URIs")

                try:
                    # Convertir toutes les URLs en data URIs
                    user_message_with_data_uris = convert_message_urls_to_data_uris(user_message.copy())

                    # Compter les images converties
                    data_uri_count = sum(
                        1 for c in user_message_with_data_uris.get("content", [])
                        if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                    )

                    logger.info(f"🔄 Retry classification avec {data_uri_count} images en Data URI")

                    # Réessayer avec les data URIs
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[user_message_with_data_uris],
                        max_tokens=200,
                        temperature=0.1,
                        response_format={"type": "json_object"}
                    )
                    logger.info("✅ Classification réussie avec Data URIs (fallback téléchargement)")

                except Exception as data_uri_error:
                    logger.error(f"❌ Échec du fallback Data URI: {data_uri_error}")

                    # Si le fallback Data URI échoue aussi, passer au fallback sans images
                    logger.warning("⚠️ Tentative finale sans images")

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
                        response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[fallback_message],
                            max_tokens=200,
                            temperature=0.1,
                            response_format={"type": "json_object"}
                        )
                        logger.info("✅ Classification réussie en mode fallback (sans images)")
                    except Exception as final_error:
                        logger.error(f"❌ Échec de tous les fallbacks: {final_error}")
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

            # 🔄 FALLBACK 2: Erreurs de format d'image → Sans images
            elif "invalid_image_format" in error_str or "unsupported image" in error_str:
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
        
        # Extraire les résultats
        detected_room_type = classification_result.get("room_type", "autre")
        confidence = classification_result.get("confidence", 50)
        
        # Si confiance = 0, l'ajuster à 10 minimum pour éviter les problèmes
        if confidence == 0:
            confidence = 10
            logger.info(f"📊 Confiance ajustée de 0 à {confidence} pour éviter une valeur nulle")
        
        # 🗺️ ÉTAPE DE MAPPING - Convertir les variations vers les types valides
        original_detected_type = detected_room_type
        detected_room_type = map_room_type_to_valid(detected_room_type)

        # Vérifier que le type mappé existe dans nos templates
        if detected_room_type not in room_templates["room_types"]:
            logger.warning(f"⚠️ Type '{detected_room_type}' (mappé depuis '{original_detected_type}') non reconnu, utilisation de 'autre'")
            detected_room_type = "autre"
            confidence = max(confidence - 20, 10)  # Réduire la confiance
        else:
            if original_detected_type != detected_room_type:
                logger.info(f"✅ Mapping réussi: '{original_detected_type}' → '{detected_room_type}' reconnu")
            else:
                logger.info(f"✅ Type de pièce '{detected_room_type}' reconnu directement")

        # Récupérer les informations du template
        room_info = room_templates["room_types"][detected_room_type]
        
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
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        result = classify_room_type(input_data, parcours_type)
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
    issues: List[Probleme]  # Issues générales + issues d'étapes (fusionnées)

def analyze_with_auto_classification(input_data: InputData, parcours_type: str = "Voyageur") -> CombinedAnalysisResponse:
    """
    Effectuer d'abord la classification, puis l'analyse avec injection des critères automatiques

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        CombinedAnalysisResponse: Résultat combiné de la classification et de l'analyse
    """
    try:
        # ÉTAPE 1: Classification de la pièce
        logger.info(f"🔍 ÉTAPE 1 - Classification automatique pour la pièce {input_data.piece_id} (parcours: {parcours_type})")

        # Convertir InputData en RoomClassificationInput
        classification_input = RoomClassificationInput(
            piece_id=input_data.piece_id,
            nom=input_data.nom,
            type=parcours_type,
            checkin_pictures=input_data.checkin_pictures,
            checkout_pictures=input_data.checkout_pictures
        )

        # Effectuer la classification avec le type de parcours
        classification_result = classify_room_type(classification_input, parcours_type)
        
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

        analysis_result = analyze_images(enhanced_input_data, parcours_type)

        logger.info(f"✅ Analyse terminée: Score {analysis_result.analyse_globale.score}/10, {len(analysis_result.preliminary_issues)} problèmes détectés")

        # 🔍 DEBUG: Logger les issues détectées
        if analysis_result.preliminary_issues:
            logger.info(f"🔍 DEBUG - Issues détectées par l'IA:")
            for idx, issue in enumerate(analysis_result.preliminary_issues):
                logger.info(f"   [{idx+1}] {issue.description} ({issue.category}, {issue.severity}, {issue.confidence}%)")
        else:
            logger.warning(f"⚠️ DEBUG - AUCUNE ISSUE DÉTECTÉE par l'IA pour la pièce {input_data.piece_id}")

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
        logger.info(f"🔍 DEBUG - CombinedAnalysisResponse créé avec {len(combined_result.issues)} issues")
        
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
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        result = analyze_with_auto_classification(input_data, parcours_type)
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
    type: str = "Voyageur"  # Type de parcours: "Voyageur" ou "Ménage"
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
                
                # Construire le prompt spécifique pour l'étape depuis la config JSON
                try:
                    prompts_config = load_prompts_config()
                    analyze_etapes_config = prompts_config.get("prompts", {}).get("analyze_etapes", {})
                    
                    # Préparer les variables pour le template
                    variables = {
                        "task_name": etape.task_name,
                        "consigne": etape.consigne,
                        "etape_id": etape.etape_id
                    }
                    
                    # Utiliser la fonction standardisée
                    etape_prompt = build_full_prompt_from_config(analyze_etapes_config, variables)
                    
                    if not etape_prompt or len(etape_prompt) < 100:
                        raise ValueError("Prompt d'étape vide")
                        
                except Exception as config_error:
                    logger.warning(f"⚠️ Erreur config étape: {config_error}, utilisation fallback")
                    # Fallback minimal
                    etape_prompt = f"""Tu es un expert en vérification de tâches ménagères.
Analyse si la consigne "{etape.consigne}" a été correctement exécutée.

Compare les photos avant/après et réponds en JSON:
{{
    "etape_id": "{etape.etape_id}",
    "issues": []
}}"""

                # Récupérer les URLs traitées (peuvent être None si invalides)
                checking_url = etape_data['checking_picture']
                checkout_url = etape_data['checkout_picture']

                # 🔧 NORMALISER LES URLs JUSTE AVANT ENVOI À OPENAI
                if checking_url is not None and isinstance(checking_url, str):
                    checking_url_normalized = normalize_url(checking_url)
                    logger.info(f"🔍 ÉTAPE CHECKING - URL avant normalisation: '{checking_url}'")
                    logger.info(f"🔍 ÉTAPE CHECKING - URL après normalisation: '{checking_url_normalized}'")
                    checking_url = checking_url_normalized

                if checkout_url is not None and isinstance(checkout_url, str):
                    checkout_url_normalized = normalize_url(checkout_url)
                    logger.info(f"🔍 ÉTAPE CHECKOUT - URL avant normalisation: '{checkout_url}'")
                    logger.info(f"🔍 ÉTAPE CHECKOUT - URL après normalisation: '{checkout_url_normalized}'")
                    checkout_url = checkout_url_normalized

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
                    logger.info(f"✅ ÉTAPE CHECKING - Image ajoutée au payload OpenAI: {checking_url}")
                    user_content.extend([
                        {
                            "type": "text",
                            "text": "Photo AVANT (checking_picture):"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": checking_url,  # ✅ Utiliser l'URL normalisée
                                "detail": "high"
                            }
                        }
                    ])
                else:
                    logger.warning(f"⚠️ ÉTAPE CHECKING - Image invalide ignorée")
                    user_content.append({
                        "type": "text",
                        "text": "Photo AVANT: Image non conforme ou indisponible"
                    })

                if checkout_usable:
                    logger.info(f"✅ ÉTAPE CHECKOUT - Image ajoutée au payload OpenAI: {checkout_url}")
                    user_content.extend([
                        {
                            "type": "text",
                            "text": "Photo APRÈS (checkout_picture):"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": checkout_url,  # ✅ Utiliser l'URL normalisée
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

                    # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
                    if any(keyword in error_str.lower() for keyword in [
                        "error while downloading",
                        "timeout while downloading",
                        "invalid_image_url",
                        "failed to download"
                    ]):
                        logger.warning(f"⚠️ Erreur de téléchargement d'image détectée pour l'étape {etape.etape_id}, tentative avec Data URIs")

                        try:
                            # Convertir toutes les URLs en data URIs
                            user_message_with_data_uris = convert_message_urls_to_data_uris(user_message.copy())

                            # Compter les images converties
                            data_uri_count = sum(
                                1 for c in user_message_with_data_uris.get("content", [])
                                if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                            )

                            logger.info(f"🔄 Retry étape {etape.etape_id} avec {data_uri_count} images en Data URI")

                            # Réessayer avec les data URIs
                            response = client.chat.completions.create(
                                model="gpt-4.1-2025-04-14",
                                messages=[
                                    {
                                        "role": "system",
                                        "content": etape_prompt
                                    },
                                    user_message_with_data_uris
                                ],
                                response_format={"type": "json_object"},
                                temperature=0.2,
                                max_tokens=16000
                            )
                            logger.info(f"✅ Analyse de l'étape {etape.etape_id} réussie avec Data URIs (fallback téléchargement)")

                        except Exception as data_uri_error:
                            logger.error(f"❌ Échec du fallback Data URI pour l'étape {etape.etape_id}: {data_uri_error}")

                            # Si le fallback Data URI échoue aussi, passer au fallback sans images
                            logger.warning(f"⚠️ Tentative finale sans images pour l'étape {etape.etape_id}")

                            fallback_message = {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Analyse de l'étape '{etape.task_name}' avec consigne: '{etape.consigne}'. Les images sont indisponibles. Fournir une réponse JSON générique indiquant un problème d'image."
                                    }
                                ]
                            }

                            try:
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
                            except Exception as final_error:
                                logger.error(f"❌ Échec de tous les fallbacks pour l'étape {etape.etape_id}: {final_error}")
                                all_issues.append(EtapeIssue(
                                    etape_id=etape.etape_id,
                                    description=f"Impossibilité d'analyser l'étape '{etape.task_name}' - erreur technique",
                                    category="image_quality",
                                    severity="medium",
                                    confidence=100
                                ))
                                logger.info(f"⚠️ Problème générique ajouté pour l'étape {etape.etape_id}")
                                continue  # Passer à l'étape suivante

                    # 🔄 FALLBACK 2: Erreurs de format d'image → Sans images
                    elif "invalid_image_format" in error_str or "unsupported image" in error_str:
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
    score: float = Field(ge=1, le=5, description="Note globale de 1 à 5 (décimales autorisées)")
    label: str = Field(description="Label textuel (EXCELLENT, TRÈS BON, BON, MOYEN, MÉDIOCRE)")
    description: str = Field(description="Description détaillée de l'état général")
    
    @field_validator('score', mode='before')
    @classmethod
    def validate_score(cls, v):
        """Convertit automatiquement du texte ou autres types en float"""
        if isinstance(v, str):
            # Nettoyer le texte et convertir en float
            v_clean = v.strip().replace(',', '.')  # Remplacer virgule par point
            try:
                return float(v_clean)
            except ValueError:
                raise ValueError(f"Impossible de convertir '{v}' en score numérique")
        elif isinstance(v, (int, float)):
            return float(v)
        else:
            raise ValueError(f"Type de score non supporté: {type(v)}")

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


# ═══════════════════════════════════════════════════════════════
# SYSTÈME DE NOTATION À SCORE PONDÉRÉ (APPROCHE 2)
# ═══════════════════════════════════════════════════════════════

def calculate_weighted_severity_score(
    pieces_analysis: List[CombinedAnalysisResponse],
    general_issues_count: int,
    etapes_issues_count: int
) -> dict:
    """
    Calcule le score de gravité avec moyenne pondérée par pièce

    SOLUTION RETENUE : Score moyen par pièce avec pondération par type

    Avantages :
    - Équitable : Même qualité par pièce = même note (quelle que soit la taille)
    - Juste : Tient compte de l'importance des pièces (cuisine > entrée)
    - Flexible : Facile d'ajuster les poids d'importance via scoring-config.json
    - Déterministe et traçable

    Returns:
        dict: {
            "weighted_average_score": float,
            "total_weight": float,
            "final_grade": float,
            "label": str,
            "room_scores": list,
            "summary": dict
        }
    """

    # ═══════════════════════════════════════════════════════════
    # CHARGEMENT DE LA CONFIGURATION DYNAMIQUE
    # ═══════════════════════════════════════════════════════════

    logger.info("")
    logger.info("═" * 80)
    logger.info("🧮 CALCUL DU SCORE ALGORITHMIQUE (APPROCHE 2 - MOYENNE PONDÉRÉE)")
    logger.info("═" * 80)

    # 🔍 DEBUG: Logger ce que la fonction reçoit
    logger.info(f"🔍 DEBUG - calculate_weighted_severity_score reçoit:")
    logger.info(f"   - {len(pieces_analysis)} pièces")
    logger.info(f"   - {general_issues_count} issues générales (paramètre)")
    logger.info(f"   - {etapes_issues_count} issues d'étapes (paramètre)")
    total_issues_in_pieces = sum(len(p.issues) for p in pieces_analysis)
    logger.info(f"   - {total_issues_in_pieces} issues TOTALES dans les objets pieces_analysis (générales + étapes fusionnées)")
    for piece in pieces_analysis:
        logger.info(f"      Pièce {piece.piece_id}: {len(piece.issues)} issues totales")

    config = load_scoring_config()
    scoring_config = config.get("scoring_system", {})

    # Extraire les paramètres de configuration
    SEVERITY_BASE_SCORE = scoring_config.get("severity_base_score", {"low": 1, "medium": 3, "high": 10})
    CATEGORY_MULTIPLIER = scoring_config.get("category_multiplier", {
        "damage": 2.0, "cleanliness": 1.5, "missing_item": 1.3,
        "positioning": 0.5, "added_item": 0.4, "image_quality": 0.2, "wrong_room": 0.3
    })
    ROOM_IMPORTANCE_WEIGHT = scoring_config.get("room_importance_weight", {
        "cuisine": 2.0, "salle_de_bain": 1.8, "salle_de_bain_et_toilettes": 1.8,
        "salle_d_eau": 1.7, "salle_d_eau_et_wc": 1.7, "wc": 1.5,
        "salon": 1.2, "chambre": 1.0, "bureau": 1.0, "entree": 0.8, "exterieur": 0.6
    })
    ETAPE_REDUCTION_FACTOR = scoring_config.get("etape_reduction_factor", {}).get("value", 0.6)
    CONFIDENCE_THRESHOLD = scoring_config.get("confidence_threshold", {}).get("value", 90)

    # ═══════════════════════════════════════════════════════════
    # CALCUL DU SCORE PAR PIÈCE
    # ═══════════════════════════════════════════════════════════

    room_scores = []
    total_weight = 0
    weighted_sum = 0

    logger.info(f"")
    logger.info(f"🔢 CALCUL DU SCORE MOYEN PONDÉRÉ PAR PIÈCE")
    logger.info(f"   📊 Nombre de pièces à analyser : {len(pieces_analysis)}")
    logger.info(f"   🎯 Seuil de confiance : {CONFIDENCE_THRESHOLD}%")
    logger.info(f"")

    for idx, piece in enumerate(pieces_analysis, 1):
        room_type = piece.room_classification.room_type
        room_weight = ROOM_IMPORTANCE_WEIGHT.get(room_type, 1.0)

        # Calculer le score de cette pièce uniquement
        piece_score = 0
        piece_issues_details = []

        # Traiter TOUTES les issues (générales + étapes fusionnées)
        if hasattr(piece, 'issues') and piece.issues:
            for issue in piece.issues:
                if issue.confidence >= CONFIDENCE_THRESHOLD:
                    base_score = SEVERITY_BASE_SCORE.get(issue.severity, 1)
                    category_mult = CATEGORY_MULTIPLIER.get(issue.category, 1.0)

                    # Détecter si c'est une issue d'étape (description commence par "[ÉTAPE]")
                    is_etape_issue = issue.description.startswith("[ÉTAPE]")

                    # Appliquer le facteur de réduction pour les issues d'étapes
                    if is_etape_issue:
                        issue_score = base_score * category_mult * ETAPE_REDUCTION_FACTOR
                    else:
                        issue_score = base_score * category_mult

                    piece_score += issue_score

                    piece_issues_details.append({
                        "description": issue.description,
                        "category": issue.category,
                        "severity": issue.severity,
                        "score": round(issue_score, 2),
                        "is_etape": is_etape_issue
                    })

        # Ajouter au calcul de la moyenne pondérée
        weighted_score = piece_score * room_weight
        weighted_sum += weighted_score
        total_weight += room_weight

        room_scores.append({
            "piece_id": piece.piece_id,
            "room_type": room_type,
            "score": round(piece_score, 2),
            "weight": room_weight,
            "weighted_score": round(weighted_score, 2),
            "num_issues": len(piece_issues_details),
            "issues_details": piece_issues_details
        })

        logger.info(
            f"   [{idx}] {room_type} (poids {room_weight}) : "
            f"{len(piece_issues_details)} issue(s), "
            f"Score {piece_score:.2f} × {room_weight} = {weighted_score:.2f}"
        )

    # ═══════════════════════════════════════════════════════════
    # CALCUL DE LA MOYENNE PONDÉRÉE
    # ═══════════════════════════════════════════════════════════

    if total_weight > 0:
        weighted_average_score = weighted_sum / total_weight
    else:
        weighted_average_score = 0

    logger.info(f"")
    logger.info(f"📊 RÉSULTAT DU CALCUL :")
    logger.info(f"   📈 Somme pondérée : {weighted_sum:.2f}")
    logger.info(f"   ⚖️  Poids total : {total_weight:.2f}")
    logger.info(f"   📉 Moyenne pondérée : {weighted_average_score:.2f}")

    # ═══════════════════════════════════════════════════════════
    # CONVERSION EN NOTE /5
    # ═══════════════════════════════════════════════════════════

    final_grade, label = convert_weighted_average_to_grade(weighted_average_score, config)

    logger.info(f"   🏆 Note finale : {final_grade}/5")
    logger.info(f"   🏷️  Label : {label}")

    # ═══════════════════════════════════════════════════════════
    # RÉSUMÉ
    # ═══════════════════════════════════════════════════════════

    summary = {
        "total_issues_analyzed": sum(r["num_issues"] for r in room_scores),
        "num_pieces": len(pieces_analysis),
        "severity_breakdown": {"high": 0, "medium": 0, "low": 0},
        "category_breakdown": {},
        "room_breakdown": {}
    }

    # Compter par sévérité et catégorie
    for room in room_scores:
        for issue in room["issues_details"]:
            summary["severity_breakdown"][issue["severity"]] += 1
            cat = issue["category"]
            summary["category_breakdown"][cat] = summary["category_breakdown"].get(cat, 0) + 1

        room_type = room["room_type"]
        summary["room_breakdown"][room_type] = summary["room_breakdown"].get(room_type, 0) + room["num_issues"]

    return {
        "weighted_average_score": round(weighted_average_score, 2),
        "total_weight": round(total_weight, 2),
        "final_grade": final_grade,
        "label": label,
        "room_scores": room_scores,
        "summary": summary
    }


def convert_weighted_average_to_grade(weighted_average_score: float, config: dict) -> tuple:
    """
    Convertit le score moyen pondéré en note /5 selon les seuils configurés

    Args:
        weighted_average_score: Score moyen pondéré calculé
        config: Configuration du scoring

    Returns:
        tuple: (grade, label)
    """
    thresholds = config.get("scoring_system", {}).get("grade_thresholds", {}).get("thresholds", [])

    # Trier les seuils par max_score croissant
    sorted_thresholds = sorted(thresholds, key=lambda x: x["max_score"])

    # Trouver le seuil correspondant
    for threshold in sorted_thresholds:
        if weighted_average_score <= threshold["max_score"]:
            return (threshold["grade"], threshold["label"])

    # Par défaut, retourner la note la plus basse
    return (1.0, "CRITIQUE")


def generate_logement_enrichment(logement_id: str, pieces_analysis: List[CombinedAnalysisResponse], total_issues: int, general_issues: int, etapes_issues: int) -> LogementAnalysisEnrichment:
    """
    Générer une synthèse globale et des recommandations pour le logement

    VERSION AVEC SYSTÈME DE NOTATION ALGORITHMIQUE (APPROCHE 2)
    - Le score est calculé de manière déterministe via calculate_weighted_severity_score()
    - L'IA génère uniquement le summary et les recommendations
    - Plus de variabilité, plus de traçabilité, plus d'équité
    """
    try:
        # 🛡️ LOGS D'ENTRÉE DÉTAILLÉS
        logger.info(f"🚀 DÉBUT generate_logement_enrichment pour logement {logement_id}")
        logger.info(f"   📊 Paramètres reçus:")
        logger.info(f"   - total_issues: {total_issues}")
        logger.info(f"   - general_issues: {general_issues}")
        logger.info(f"   - etapes_issues: {etapes_issues}")
        logger.info(f"   - pieces_analysis: {len(pieces_analysis)} pièces")

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 0 : CALCUL DU SCORE ALGORITHMIQUE (NOUVEAU)
        # ═══════════════════════════════════════════════════════════

        logger.info(f"")
        logger.info(f"🎯 ÉTAPE 0 - CALCUL DU SCORE ALGORITHMIQUE")
        logger.info(f"   📊 Utilisation du système de notation à score pondéré (APPROCHE 2)")

        score_result = calculate_weighted_severity_score(
            pieces_analysis=pieces_analysis,
            general_issues_count=general_issues,
            etapes_issues_count=etapes_issues
        )

        algorithmic_score = score_result["final_grade"]
        algorithmic_label = score_result["label"]
        weighted_average = score_result["weighted_average_score"]

        logger.info(f"")
        logger.info(f"✅ SCORE ALGORITHMIQUE CALCULÉ :")
        logger.info(f"   🏆 Note finale : {algorithmic_score}/5")
        logger.info(f"   🏷️  Label : {algorithmic_label}")
        logger.info(f"   📊 Score moyen pondéré : {weighted_average:.2f}")
        logger.info(f"   📈 Nombre de pièces : {score_result['summary']['num_pieces']}")
        logger.info(f"   📋 Issues analysées : {score_result['summary']['total_issues_analyzed']}")
        logger.info(f"")
        
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible pour l'enrichissement")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible")

        # 🔍 ÉTAPE 1: Créer un résumé structuré des problèmes détectés
        logger.info(f"🔍 ÉTAPE 1 - Création du résumé structuré des problèmes")
        issues_summary = []
        pieces_avec_problemes = 0
        
        for i, piece in enumerate(pieces_analysis):
            piece_issues = []
            
            # ✅ Vérification de la structure de la pièce
            if not hasattr(piece, 'issues'):
                logger.warning(f"⚠️ Pièce {piece.piece_id} sans attribut 'issues'")
                continue
                
            if piece.issues is None:
                logger.warning(f"⚠️ piece.issues est None pour {piece.piece_id}")
                piece.issues = []
            
            # Filtrer les issues avec confiance >= 90%
            issues_filtrees = 0
            for issue in piece.issues:
                if hasattr(issue, 'confidence') and issue.confidence >= 90:
                    piece_issues.append({
                        "description": issue.description,
                        "category": issue.category,
                        "severity": issue.severity,
                        "confidence": issue.confidence
                    })
                else:
                    issues_filtrees += 1
            
            if issues_filtrees > 0:
                logger.info(f"   🔽 Pièce {piece.piece_id}: {issues_filtrees} issues filtrées (confiance < 90%)")
            
            # Ajouter à issues_summary seulement si il y a des problèmes qualifiés
            if piece_issues:
                pieces_avec_problemes += 1
                issues_summary.append({
                    "piece_name": piece.nom_piece,
                    "piece_id": piece.piece_id,
                    "room_type": piece.room_classification.room_type,
                    "global_score": piece.analyse_globale.score,
                    "global_status": piece.analyse_globale.status,
                    "issues": piece_issues
                })
                logger.info(f"   📋 Pièce {i+1} ({piece.piece_id}): {len(piece_issues)} issues qualifiées ajoutées")
            else:
                logger.info(f"   ✅ Pièce {i+1} ({piece.piece_id}): Aucune issue qualifiée")

        logger.info(f"✅ Résumé créé: {pieces_avec_problemes}/{len(pieces_analysis)} pièces avec problèmes qualifiés")
        logger.info(f"ℹ️ L'IA évaluera la note globale selon son ressenti général, indépendamment du comptage d'issues")
        
        # 🔍 ÉTAPE 2: Construire le prompt pour la synthèse globale
        logger.info(f"🔍 ÉTAPE 2 - Construction du prompt de synthèse")
        
        try:
            prompts_config = load_prompts_config()
            synthesis_global_config = prompts_config.get("prompts", {}).get("synthesis_global", {})
            
            # Préparer les variables pour le template
            variables = {
                "logement_id": logement_id,
                "total_issues": total_issues,
                "general_issues": general_issues,
                "etapes_issues": etapes_issues,
                "issues_summary": json.dumps(issues_summary, indent=2, ensure_ascii=False)
            }
            
            logger.info(f"   📋 Variables préparées pour le template:")
            logger.info(f"   - logement_id: {logement_id}")
            logger.info(f"   - total_issues: {total_issues}")
            logger.info(f"   - issues_summary: {len(issues_summary)} pièces")
            
            # Utiliser la fonction standardisée
            synthesis_prompt = build_full_prompt_from_config(synthesis_global_config, variables)
            
            if not synthesis_prompt or len(synthesis_prompt) < 200:
                raise ValueError("Prompt de synthèse vide")
            
            logger.info(f"✅ Prompt construit: {len(synthesis_prompt)} caractères")
                
        except Exception as config_error:
            logger.warning(f"⚠️ Erreur config synthèse: {config_error}, utilisation fallback")
            # Fallback minimal
            synthesis_prompt = f"""Tu es un expert en gestion immobilière.
Analyse les problèmes détectés dans le logement {logement_id}.

Évalue l'état général selon ton ressenti et attribue une note de 1 à 5 (décimales autorisées):
- 5.0: EXCELLENT (état irréprochable)
- 4.0-4.9: TRÈS BON (détails mineurs)
- 3.0-3.9: BON (défauts légers)
- 2.0-2.9: MOYEN (défauts notables)
- 1.0-1.9: CRITIQUE (problèmes majeurs)

Génère une synthèse en JSON:
{{
    "summary": {{
        "missing_items": ["Liste ou 'Aucun objet manquant constaté'"],
        "damages": ["Liste ou 'Aucun dégât constaté'"],
        "cleanliness_issues": ["Liste ou 'Aucun problème de propreté majeur détecté'"],
        "layout_problems": ["Liste ou 'Aucun problème d'agencement constaté'"]
    }},
    "recommendations": ["5 recommandations concrètes"],
    "global_score": {{
        "score": [choisir de 1.0 à 5.0 selon ton évaluation, décimales autorisées],
        "label": "[EXCELLENT/TRÈS BON/BON/MOYEN/CRITIQUE]",
        "description": "Description de l'état général et justification de la note"
    }}
}}"""
            logger.info(f"✅ Prompt fallback utilisé: {len(synthesis_prompt)} caractères")

        # 🔍 ÉTAPE 3: Faire l'appel API pour la synthèse
        logger.info(f"🔍 ÉTAPE 3 - Appel à l'IA de synthèse (OpenAI)")
        
        try:
            logger.info(f"   🤖 Modèle: gpt-4.1-2025-04-14")
            logger.info(f"   🌡️ Température: 0.3")
            logger.info(f"   📏 Max tokens: 8000")
            
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
            
            logger.info(f"✅ Réponse OpenAI reçue avec succès")
            
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de l'enrichissement du logement {logement_id}: {error_str}")
            
            # En cas d'erreur OpenAI, retourner une erreur plutôt qu'un score arbitraire
            logger.error("❌ Impossible de générer l'enrichissement sans l'IA")
            raise HTTPException(
                status_code=503, 
                detail="Service d'enrichissement temporairement indisponible - L'IA n'a pas pu générer la synthèse globale"
            )
        
        # 🔍 ÉTAPE 4: Parser et valider la réponse
        logger.info(f"🔍 ÉTAPE 4 - Parsing et validation de la réponse IA")
        
        response_content = response.choices[0].message.content.strip()
        logger.info(f"   📄 Longueur réponse: {len(response_content)} caractères")
        
        # Valider que c'est du JSON valide
        try:
            enrichment_data = json.loads(response_content)
            logger.info(f"✅ JSON parsé avec succès")
        except json.JSONDecodeError as json_error:
            logger.error(f"❌ Erreur parsing JSON: {json_error}")
            logger.error(f"   📄 Contenu reçu: {response_content[:500]}...")
            raise ValueError(f"Réponse IA invalide: {json_error}")
        
        # Valider les champs requis
        required_fields = ["summary", "recommendations", "global_score"]
        for field in required_fields:
            if field not in enrichment_data:
                logger.error(f"❌ Champ manquant dans la réponse: {field}")
                raise ValueError(f"Champ requis manquant: {field}")
        
        # ═══════════════════════════════════════════════════════════
        # UTILISATION DU SCORE ALGORITHMIQUE (au lieu du score IA)
        # ═══════════════════════════════════════════════════════════

        # L'IA peut retourner un global_score, mais on l'ignore et on utilise le score algorithmique
        if "global_score" in enrichment_data:
            ia_score = enrichment_data["global_score"].get("score", "N/A")
            logger.info(f"   ℹ️  Score IA reçu (ignoré) : {ia_score}/5")
            logger.info(f"   ✅ Score algorithmique utilisé : {algorithmic_score}/5")

        # Créer la description du score
        score_description = (
            f"Score calculé algorithmiquement : {weighted_average:.2f} points "
            f"(moyenne pondérée sur {score_result['summary']['num_pieces']} pièces). "
            f"{score_result['summary']['total_issues_analyzed']} issues analysées "
            f"(H:{score_result['summary']['severity_breakdown']['high']}, "
            f"M:{score_result['summary']['severity_breakdown']['medium']}, "
            f"L:{score_result['summary']['severity_breakdown']['low']})."
        )

        # Valider et créer l'objet LogementAnalysisEnrichment avec le score algorithmique
        try:
            enrichment = LogementAnalysisEnrichment(
                summary=LogementSummary(**enrichment_data["summary"]),
                recommendations=enrichment_data["recommendations"],
                global_score=GlobalScore(
                    score=algorithmic_score,
                    label=algorithmic_label,
                    description=score_description
                )
            )
            logger.info(f"✅ Objet LogementAnalysisEnrichment créé avec succès")
            logger.info(f"   🎯 Score final : {algorithmic_score}/5 ({algorithmic_label})")
        except Exception as validation_error:
            logger.error(f"❌ Erreur validation Pydantic: {validation_error}")
            raise ValueError(f"Données invalides: {validation_error}")
        
        logger.info(f"✅ Synthèse globale générée: Note {enrichment.global_score.score}/5 ({enrichment.global_score.label})")
        logger.info(f"   📋 {len(enrichment.recommendations)} recommandations formulées")
        logger.info(f"🎉 FIN generate_logement_enrichment - SUCCÈS")
        
        return enrichment
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération de l'enrichissement: {str(e)}")
        logger.error(f"   📊 Paramètres: logement_id={logement_id}, total_issues={total_issues}")
        
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
        logger.info(f"🎉 FIN generate_logement_enrichment - FALLBACK")
        return fallback_enrichment

# ═══════════════════════════════════════════════════════════════
# 🚀 FONCTIONS ASYNC POUR PARALLÉLISATION
# ═══════════════════════════════════════════════════════════════

async def analyze_single_piece_async(piece: PieceWithEtapes, parcours_type: str = "Voyageur") -> CombinedAnalysisResponse:
    """
    Analyse asynchrone d'une seule pièce avec classification automatique
    Version async de la logique dans analyze_complete_logement

    Args:
        piece: Données de la pièce à analyser
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        CombinedAnalysisResponse: Résultat de l'analyse combinée
    """
    try:
        logger.info(f"🔍 [ASYNC] Analyse de la pièce {piece.piece_id}: {piece.nom} (parcours: {parcours_type})")

        # Filtrer les images invalides avant l'analyse
        valid_checkin_pictures = []
        for pic in piece.checkin_pictures:
            logger.info(f"🔍 Traitement image checkin - URL originale: '{pic.url}'")
            normalized_url = normalize_url(pic.url)
            logger.info(f"🔍 Traitement image checkin - URL normalisée: '{normalized_url}'")

            if is_valid_image_url(normalized_url):
                from pydantic import BaseModel
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkin_pictures.append(normalized_pic)
                logger.info(f"✅ Image checkin valide ajoutée: {normalized_url}")
            else:
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {pic.url}")
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {normalized_url}")

        valid_checkout_pictures = []
        for pic in piece.checkout_pictures:
            logger.info(f"🔍 Traitement image checkout - URL originale: '{pic.url}'")
            normalized_url = normalize_url(pic.url)
            logger.info(f"🔍 Traitement image checkout - URL normalisée: '{normalized_url}'")

            if is_valid_image_url(normalized_url):
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkout_pictures.append(normalized_pic)
                logger.info(f"✅ Image checkout valide ajoutée: {normalized_url}")
            else:
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {pic.url}")
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {normalized_url}")

        logger.info(f"📷 Images valides pour pièce {piece.piece_id}: {len(valid_checkin_pictures)} checkin + {len(valid_checkout_pictures)} checkout")

        # Convertir PieceWithEtapes en InputData pour l'analyse générale avec images filtrées
        input_data_piece = InputData(
            piece_id=piece.piece_id,
            nom=piece.nom,
            commentaire_ia=piece.commentaire_ia,
            checkin_pictures=valid_checkin_pictures,
            checkout_pictures=valid_checkout_pictures,
            etapes=[],
            elements_critiques=[],
            points_ignorables=[],
            defauts_frequents=[]
        )

        # Effectuer l'analyse avec classification automatique (fonction synchrone)
        # Note: analyze_with_auto_classification est synchrone, on l'appelle normalement
        piece_analysis = analyze_with_auto_classification(input_data_piece, parcours_type)

        logger.info(f"✅ [ASYNC] Pièce {piece.piece_id} analysée: {len(piece_analysis.issues)} issues générales détectées")
        return piece_analysis

    except Exception as e:
        logger.error(f"❌ [ASYNC] Erreur lors de l'analyse de la pièce {piece.piece_id}: {str(e)}")
        raise


async def analyze_single_etape_async(etape: Etape, etape_data: dict, piece_id: str) -> List[EtapeIssue]:
    """
    Analyse asynchrone d'une seule étape
    Extrait de la logique dans analyze_etapes
    """
    try:
        logger.info(f"🔍 [ASYNC] Analyse de l'étape {etape.etape_id}: {etape.task_name}")

        # Construire le prompt spécifique pour l'étape depuis la config JSON
        prompts_config = load_prompts_config()
        analyze_etapes_config = prompts_config.get("prompts", {}).get("analyze_etapes", {})

        # Préparer les variables pour le template
        variables = {
            "task_name": etape.task_name,
            "consigne": etape.consigne,
            "etape_id": etape.etape_id
        }

        # Construire le prompt système
        system_prompt = build_prompt_from_config(analyze_etapes_config, variables)

        # Message utilisateur
        user_message_config = prompts_config.get("user_messages", {}).get("analyze_etapes_user", {})
        user_message_template = user_message_config.get("template", "Analyse cette étape: {task_name}")
        user_message = user_message_template.format(**variables)

        # Préparer les images
        messages_content = [{"type": "text", "text": user_message}]

        if etape_data.get("checking_picture_processed"):
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": etape_data["checking_picture_processed"]}
            })

        if etape_data.get("checkout_picture_processed"):
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": etape_data["checkout_picture_processed"]}
            })

        # Appel à l'API OpenAI (synchrone, mais dans un contexte async)
        response = client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": messages_content}
            ],
            response_format={"type": "json_object"},
            max_tokens=1000
        )

        # Parser la réponse
        response_text = response.choices[0].message.content
        response_data = json.loads(response_text)

        # Extraire les issues
        issues = []
        for issue_data in response_data.get("issues", []):
            if issue_data.get("confidence", 0) >= 90:
                issue = EtapeIssue(
                    etape_id=etape.etape_id,
                    description=issue_data.get("description", ""),
                    category=issue_data.get("category", "cleanliness"),
                    severity=issue_data.get("severity", "medium"),
                    confidence=issue_data.get("confidence", 90)
                )
                issues.append(issue)

        logger.info(f"✅ [ASYNC] Étape {etape.etape_id} analysée: {len(issues)} issues détectées")
        return issues

    except Exception as e:
        logger.error(f"❌ [ASYNC] Erreur lors de l'analyse de l'étape {etape.etape_id}: {str(e)}")
        return []


# ═══════════════════════════════════════════════════════════════
# 🔄 VERSION PARALLÉLISÉE DE analyze_complete_logement
# ═══════════════════════════════════════════════════════════════

async def analyze_complete_logement_parallel(input_data: EtapesAnalysisInput) -> CompleteAnalysisResponse:
    """
    Version PARALLÉLISÉE de analyze_complete_logement
    Utilise asyncio.gather() pour analyser toutes les pièces et étapes en parallèle

    Gain attendu: 70-80% de réduction du temps (80s → 14s pour 5 pièces)
    """
    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"

        logger.info(f"🚀 [PARALLEL] ANALYSE COMPLÈTE démarrée pour le logement {input_data.logement_id} (parcours: {parcours_type})")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 1: Analyse PARALLÈLE de toutes les pièces
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"📊 [PARALLEL] ÉTAPE 1 - Analyse parallèle de {len(input_data.pieces)} pièces")

        # Créer les tâches pour toutes les pièces avec le type de parcours
        piece_tasks = [analyze_single_piece_async(piece, parcours_type) for piece in input_data.pieces]

        # Lancer toutes les analyses EN PARALLÈLE
        pieces_analysis_results = await asyncio.gather(*piece_tasks, return_exceptions=True)

        # Filtrer les erreurs
        valid_pieces_analysis = []
        for i, result in enumerate(pieces_analysis_results):
            if isinstance(result, Exception):
                logger.error(f"❌ Erreur lors de l'analyse de la pièce {input_data.pieces[i].piece_id}: {result}")
            else:
                valid_pieces_analysis.append(result)

        pieces_analysis_results = valid_pieces_analysis
        logger.info(f"✅ [PARALLEL] {len(pieces_analysis_results)} pièces analysées avec succès")

        # 🔍 DEBUG: Logger les issues de chaque pièce
        for piece_result in pieces_analysis_results:
            logger.info(f"🔍 DEBUG - Pièce {piece_result.piece_id}: {len(piece_result.issues)} issues détectées")
            if piece_result.issues:
                for idx, issue in enumerate(piece_result.issues[:3]):  # Afficher max 3 issues
                    logger.info(f"      [{idx+1}] {issue.description[:50]}...")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 2: Analyse PARALLÈLE de toutes les étapes
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"🎯 [PARALLEL] ÉTAPE 2 - Analyse parallèle des étapes")

        # Créer un mapping etape_id -> piece_id
        etape_to_piece_mapping = {}
        all_etape_tasks = []

        for piece in input_data.pieces:
            # Traiter les images des étapes
            processed_etapes = process_etapes_images([etape.dict() for etape in piece.etapes])

            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]
                etape_to_piece_mapping[etape.etape_id] = piece.piece_id

                # Créer une tâche async pour cette étape
                task = analyze_single_etape_async(etape, etape_data, piece.piece_id)
                all_etape_tasks.append((etape.etape_id, task))

        # Lancer toutes les analyses d'étapes EN PARALLÈLE
        if all_etape_tasks:
            etape_results = await asyncio.gather(*[task for _, task in all_etape_tasks], return_exceptions=True)

            # Regrouper les issues d'étapes
            all_etape_issues = []
            for i, result in enumerate(etape_results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Erreur lors de l'analyse de l'étape: {result}")
                elif isinstance(result, list):
                    all_etape_issues.extend(result)

            logger.info(f"✅ [PARALLEL] {len(all_etape_issues)} issues d'étapes détectées")
        else:
            all_etape_issues = []

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 3: Regroupement des résultats (identique à la version séquentielle)
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"🔄 [PARALLEL] ÉTAPE 3 - Regroupement des résultats")

        # Grouper les issues d'étapes par piece_id
        etapes_issues_by_piece = {}
        for etape_issue in all_etape_issues:
            piece_id = etape_to_piece_mapping.get(etape_issue.etape_id)
            if piece_id:
                if piece_id not in etapes_issues_by_piece:
                    etapes_issues_by_piece[piece_id] = []

                probleme = Probleme(
                    description=f"[ÉTAPE] {etape_issue.description}",
                    category=etape_issue.category,
                    severity=etape_issue.severity,
                    confidence=etape_issue.confidence
                )
                etapes_issues_by_piece[piece_id].append(probleme)

        # Calcul des compteurs et reconstruction des objets avec issues fusionnées
        total_issues_count = 0
        general_issues_count = 0
        etapes_issues_count = len(all_etape_issues)

        # Reconstruire les objets CombinedAnalysisResponse avec TOUTES les issues fusionnées
        updated_pieces_analysis = []

        for piece_analysis in pieces_analysis_results:
            piece_id = piece_analysis.piece_id

            # Compter les issues générales
            general_issues_for_piece = len(piece_analysis.issues) if piece_analysis.issues else 0
            general_issues_count += general_issues_for_piece

            # Récupérer les issues d'étapes pour cette pièce
            etapes_issues_for_piece = etapes_issues_by_piece.get(piece_id, [])

            # FUSIONNER les issues générales + issues d'étapes dans un seul tableau
            all_issues_for_piece = list(piece_analysis.issues) + etapes_issues_for_piece

            # Créer un nouvel objet avec TOUTES les issues fusionnées
            updated_piece_analysis = CombinedAnalysisResponse(
                piece_id=piece_analysis.piece_id,
                nom_piece=piece_analysis.nom_piece,
                room_classification=piece_analysis.room_classification,
                analyse_globale=piece_analysis.analyse_globale,
                issues=all_issues_for_piece  # Issues générales + étapes fusionnées
            )

            updated_pieces_analysis.append(updated_piece_analysis)

            # Compter le total (issues générales + issues d'étapes)
            total_issues_count += len(all_issues_for_piece)

        # Remplacer la liste originale par la liste mise à jour
        pieces_analysis_results = updated_pieces_analysis

        logger.info(f"📊 [PARALLEL] Compteurs: {total_issues_count} total ({general_issues_count} générales + {etapes_issues_count} étapes)")

        # 🔍 DEBUG: Logger les issues après reconstruction
        logger.info(f"🔍 DEBUG - Après reconstruction des objets (issues fusionnées):")
        for piece_result in pieces_analysis_results:
            logger.info(f"   Pièce {piece_result.piece_id}: {len(piece_result.issues)} issues TOTALES (générales + étapes fusionnées)")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 4: Génération de la synthèse globale
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"🧠 [PARALLEL] ÉTAPE 4 - Génération de la synthèse globale")

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

        logger.info(f"🎉 [PARALLEL] ANALYSE COMPLÈTE terminée pour le logement {input_data.logement_id}")
        logger.info(f"📊 RÉSUMÉ FINAL: {total_issues_count} issues totales")
        logger.info(f"🏆 NOTE GLOBALE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")

        return complete_result

    except Exception as e:
        logger.error(f"❌ [PARALLEL] Erreur lors de l'analyse complète: {str(e)}")
        raise


# ═══════════════════════════════════════════════════════════════
# 📌 VERSION ORIGINALE (SÉQUENTIELLE) - CONSERVÉE POUR COMPATIBILITÉ
# ═══════════════════════════════════════════════════════════════

def analyze_complete_logement(input_data: EtapesAnalysisInput) -> CompleteAnalysisResponse:
    """
    Analyse complète d'un logement : classification + analyse générale + analyse des étapes
    VERSION SÉQUENTIELLE (originale)
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
                # 🔍 DEBUG: Logger l'URL originale
                logger.info(f"🔍 Traitement image checkin - URL originale: '{pic.url}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.info(f"🔍 Traitement image checkin - URL normalisée: '{normalized_url}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    from pydantic import BaseModel
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkin_pictures.append(normalized_pic)
                    logger.info(f"✅ Image checkin valide ajoutée: {normalized_url}")
                else:
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {pic.url}")
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {normalized_url}")

            valid_checkout_pictures = []
            for pic in piece.checkout_pictures:
                # 🔍 DEBUG: Logger l'URL originale
                logger.info(f"🔍 Traitement image checkout - URL originale: '{pic.url}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.info(f"🔍 Traitement image checkout - URL normalisée: '{normalized_url}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkout_pictures.append(normalized_pic)
                    logger.info(f"✅ Image checkout valide ajoutée: {normalized_url}")
                else:
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {pic.url}")
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {normalized_url}")
            
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
        
        # 🛡️ VÉRIFICATIONS SCRUPULEUSES AVANT CALCUL
        if not pieces_analysis_results:
            logger.error("❌ ERREUR CRITIQUE: pieces_analysis_results est vide!")
            raise ValueError("Aucune analyse de pièce disponible pour le calcul des issues")
        
        if not etapes_analysis:
            logger.error("❌ ERREUR CRITIQUE: etapes_analysis est None!")
            raise ValueError("Analyse des étapes manquante")

        logger.info(f"✅ Vérifications préliminaires: {len(pieces_analysis_results)} pièces + {len(etapes_analysis.preliminary_issues)} issues d'étapes")
        
        total_issues_count = 0
        general_issues_count = 0
        etapes_issues_count = len(etapes_analysis.preliminary_issues)
        
        # 🔍 LOGS DÉTAILLÉS POUR CHAQUE PIÈCE
        for i, piece_analysis in enumerate(pieces_analysis_results):
            piece_id = piece_analysis.piece_id
            
            # ✅ Vérifier que piece_analysis.issues existe et est une liste
            if not hasattr(piece_analysis, 'issues'):
                logger.error(f"❌ ERREUR CRITIQUE: piece_analysis.issues manquant pour pièce {piece_id}")
                raise ValueError(f"Attribut 'issues' manquant pour la pièce {piece_id}")
            
            if piece_analysis.issues is None:
                logger.warning(f"⚠️ piece_analysis.issues est None pour pièce {piece_id}, initialisation avec liste vide")
                piece_analysis.issues = []
            
            # Compter les issues générales AVANT ajout des étapes
            issues_avant_etapes = len(piece_analysis.issues)
            general_issues_count += issues_avant_etapes
            
            logger.info(f"📊 Pièce {i+1}/{len(pieces_analysis_results)} ({piece_id}): {issues_avant_etapes} issues générales")
            
            # Ajouter les issues d'étapes à cette pièce si elle en a
            if piece_id in etapes_issues_by_piece:
                issues_etapes_ajoutees = len(etapes_issues_by_piece[piece_id])
                piece_analysis.issues.extend(etapes_issues_by_piece[piece_id])
                logger.info(f"   🔗 Ajouté {issues_etapes_ajoutees} issues d'étapes à la pièce {piece_id}")
            else:
                logger.info(f"   ℹ️ Aucune issue d'étape pour la pièce {piece_id}")
            
            # Compter le total des issues APRÈS ajout des étapes
            issues_apres_etapes = len(piece_analysis.issues)
            total_issues_count += issues_apres_etapes
            
            logger.info(f"   📈 Total final pour pièce {piece_id}: {issues_apres_etapes} issues")

        # 🛡️ VÉRIFICATIONS FINALES AVANT TRANSMISSION
        logger.info(f"📊 ÉTAPE 4 - Compilation et vérifications des résultats finaux")
        
        # Calculs de vérification
        verification_total = general_issues_count + etapes_issues_count
        
        logger.info(f"🔍 VÉRIFICATIONS COMPTEURS:")
        logger.info(f"   📋 Issues générales: {general_issues_count}")
        logger.info(f"   🎯 Issues d'étapes: {etapes_issues_count}")
        logger.info(f"   📊 Total calculé: {total_issues_count}")
        logger.info(f"   🧮 Vérification: {general_issues_count} + {etapes_issues_count} = {verification_total}")
        
        # ⚠️ ALERTE si les compteurs ne correspondent pas
        if total_issues_count != verification_total:
            logger.warning(f"⚠️ ATTENTION: Différence de comptage détectée!")
            logger.warning(f"   Total calculé: {total_issues_count}")
            logger.warning(f"   Somme attendue: {verification_total}")
            # On continue mais on log l'anomalie
        
        # 🚨 VÉRIFICATION CRITIQUE: Si des issues sont visibles mais total_issues_count = 0
        if total_issues_count == 0:
            logger.warning("🚨 ALERTE CRITIQUE: total_issues_count = 0")
            
            # Vérifier s'il y a vraiment des issues dans les pièces
            issues_reelles = 0
            for piece in pieces_analysis_results:
                if hasattr(piece, 'issues') and piece.issues:
                    issues_reelles += len(piece.issues)
            
            if issues_reelles > 0:
                logger.error(f"❌ ERREUR MAJEURE: {issues_reelles} issues détectées mais total_issues_count = 0!")
                logger.error("❌ Cela va causer une note erronée de 5/5!")
                # Corriger le compteur
                total_issues_count = issues_reelles
                logger.info(f"🔧 Correction appliquée: total_issues_count = {total_issues_count}")
            else:
                logger.info("✅ Confirmation: Aucune issue réelle détectée")

        # 🛡️ VALIDATION DES DONNÉES AVANT TRANSMISSION À L'IA
        logger.info(f"🧠 ÉTAPE 5 - Génération de la synthèse globale via IA")
        
        # Vérifier que nous avons des données valides
        if not pieces_analysis_results:
            logger.error("❌ ERREUR: Aucune analyse de pièce pour la synthèse!")
            raise ValueError("Impossible de générer la synthèse sans données d'analyse")
        
        # Vérifier que logement_id est valide
        if not input_data.logement_id or input_data.logement_id.strip() == "":
            logger.error("❌ ERREUR: logement_id vide!")
            raise ValueError("logement_id manquant pour la synthèse")
        
        # 📊 LOG FINAL AVANT TRANSMISSION
        logger.info(f"🚀 TRANSMISSION À L'IA DE SYNTHÈSE:")
        logger.info(f"   🏠 Logement ID: {input_data.logement_id}")
        logger.info(f"   🏘️ Nombre de pièces: {len(pieces_analysis_results)}")
        logger.info(f"   📊 Total issues: {total_issues_count}")
        logger.info(f"   📋 Issues générales: {general_issues_count}")
        logger.info(f"   🎯 Issues étapes: {etapes_issues_count}")
        
        # ✅ APPEL SÉCURISÉ À L'IA DE SYNTHÈSE
        try:
            analysis_enrichment = generate_logement_enrichment(
                logement_id=input_data.logement_id,
                pieces_analysis=pieces_analysis_results,
                total_issues=total_issues_count,
                general_issues=general_issues_count,
                etapes_issues=etapes_issues_count
            )
            
            # 🛡️ VÉRIFICATION DE LA RÉPONSE
            if not analysis_enrichment:
                logger.error("❌ ERREUR: generate_logement_enrichment a retourné None!")
                raise ValueError("Échec de génération de l'enrichissement")
            
            if not hasattr(analysis_enrichment, 'global_score'):
                logger.error("❌ ERREUR: Pas de global_score dans l'enrichissement!")
                raise ValueError("global_score manquant dans la réponse d'enrichissement")
            
            # ✅ ACCEPTATION DU SCORE DE L'IA BASÉ SUR SON RESSENTI GÉNÉRAL
            note_finale = analysis_enrichment.global_score.score
            logger.info(f"🎯 Score basé sur le ressenti de l'IA: {note_finale}/5 ({analysis_enrichment.global_score.label})")
            
            logger.info(f"✅ Enrichissement généré avec succès")
            logger.info(f"   🏆 Note finale: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")
            
        except Exception as enrichment_error:
            logger.error(f"❌ ERREUR LORS DE L'ENRICHISSEMENT: {enrichment_error}")
            logger.error(f"   📊 Données transmises: logement_id={input_data.logement_id}, total_issues={total_issues_count}")
            raise enrichment_error
        
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
        logger.info(f"📊 RÉSUMÉ FINAL: {total_issues_count} issues totales ({general_issues_count} générales + {etapes_issues_count} étapes)")
        logger.info(f"🏆 NOTE GLOBALE VALIDÉE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")
        
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
        # 1. Effectuer l'analyse complète PARALLÉLISÉE ⚡
        logger.info(f"⚡ Utilisation de la version PARALLÉLISÉE pour gain de performance")
        result = await analyze_complete_logement_parallel(input_data)
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

def save_room_templates(templates_data, parcours_type: str = "Voyageur"):
    """Sauvegarder les templates dans le fichier JSON et variables d'environnement Railway selon le type de parcours"""
    success_local = False
    success_env = False

    # Déterminer le suffixe du fichier selon le type
    if parcours_type.lower() == "ménage":
        file_suffix = "-menage"
        env_var_name = "ROOM_TEMPLATES_CONFIG_MENAGE"
    else:  # Par défaut: Voyageur
        file_suffix = "-voyageur"
        env_var_name = "ROOM_TEMPLATES_CONFIG_VOYAGEUR"

    try:
        # 🔥 SAUVEGARDE 1: Fichier local (pour développement)
        possible_paths = [
            f"room_classfication/room-verification-templates{file_suffix}.json",
            f"room-verification-templates{file_suffix}.json",
            os.path.join(os.path.dirname(__file__), "room_classfication", f"room-verification-templates{file_suffix}.json")
        ]

        target_path = None
        for path in possible_paths:
            if os.path.exists(path):
                target_path = path
                break

        if not target_path:
            # Créer le répertoire si nécessaire
            os.makedirs("room_classfication", exist_ok=True)
            target_path = f"room_classfication/room-verification-templates{file_suffix}.json"

        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Templates {parcours_type} sauvegardés dans le fichier: {target_path}")
        success_local = True

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde fichier local ({parcours_type}): {e}")

    try:
        # 🔥 SAUVEGARDE 2: Variable d'environnement (pour Railway production)
        templates_json = json.dumps(templates_data, ensure_ascii=False, separators=(',', ':'))

        # Note: En production Railway, cette mise à jour nécessitera un redémarrage
        # Pour une vraie persistence, il faudrait utiliser l'API Railway ou une DB
        os.environ[env_var_name] = templates_json

        logger.info(f"✅ Templates {parcours_type} mis à jour dans les variables d'environnement ({env_var_name})")
        success_env = True

        # 🔥 IMPORTANT: Informer l'utilisateur pour Railway
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            logger.warning(f"⚠️ RAILWAY: Les modifications {parcours_type} seront perdues au prochain déploiement!")
            logger.warning(f"💡 Utilisez l'interface d'admin Railway pour définir {env_var_name} de façon permanente")

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde variable d'environnement ({parcours_type}): {e}")

    # Logs de vérification
    if success_local or success_env:
        logger.info(f"🔥 Templates {parcours_type} mis à jour - Modifications IMMÉDIATEMENT effectives!")

        if "room_types" in templates_data:
            for room_key, room_info in templates_data["room_types"].items():
                points_ignorables = room_info.get("verifications", {}).get("points_ignorables", [])
                logger.info(f"   📝 {room_key}: {len(points_ignorables)} points ignorables en mémoire")

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
async def get_all_room_templates(type: str = "Voyageur"):
    """Récupérer tous les types de pièces configurés selon le type de parcours"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)
        return {
            "success": True,
            "room_types": room_templates.get("room_types", {}),
            "parcours_type": type
        }
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des templates ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/room-templates/export/railway-env")
async def export_templates_for_railway(type: str = "Voyageur"):
    """🚀 Exporter la configuration actuelle pour Railway (variable d'environnement)"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)
        env_var_value = json.dumps(room_templates, ensure_ascii=False, separators=(',', ':'))

        # Déterminer le nom de la variable selon le type
        var_name = f"ROOM_TEMPLATES_CONFIG_{type.upper()}" if type.lower() == "ménage" else f"ROOM_TEMPLATES_CONFIG_{type.upper()}"

        if env_var_value:
            return {
                "success": True,
                "message": f"Configuration exportée pour Railway (parcours {type})",
                "instructions": [
                    "1. Copiez la valeur 'env_var_value' ci-dessous",
                    "2. Allez dans Railway Dashboard > Variables",
                    f"3. Créez/modifiez la variable: {var_name}",
                    "4. Collez la valeur et sauvegardez",
                    "5. Railway redémarrera automatiquement avec la nouvelle config"
                ],
                "variable_name": var_name,
                "env_var_value": env_var_value,
                "railway_command": f"railway variables set {var_name}='{env_var_value}'",
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de l'export")
    except Exception as e:
        logger.error(f"Erreur lors de l'export Railway ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/room-templates/{room_type_key}")
async def get_room_template(room_type_key: str, type: str = "Voyageur"):
    """Récupérer un type de pièce spécifique selon le type de parcours"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)
        room_types = room_templates.get("room_types", {})

        if room_type_key not in room_types:
            raise HTTPException(status_code=404, detail="Type de pièce non trouvé")

        return {
            "success": True,
            "room_type_key": room_type_key,
            "room_type": room_types[room_type_key],
            "parcours_type": type
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du template {room_type_key} ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/room-templates")
async def create_room_template(room_data: RoomTypeCreate, type: str = "Voyageur"):
    """Créer un nouveau type de pièce selon le type de parcours"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)

        # Vérifier si la clé existe déjà
        room_types = room_templates.get("room_types", {})
        if room_data.room_type_key in room_types:
            raise HTTPException(status_code=400, detail="Ce type de pièce existe déjà")

        # Ajouter le nouveau type
        if "room_types" not in room_templates:
            room_templates["room_types"] = {}

        room_templates["room_types"][room_data.room_type_key] = {
            "name": room_data.name,
            "icon": room_data.icon,
            "verifications": room_data.verifications.dict()
        }

        # Sauvegarder dans le fichier
        if save_room_templates(room_templates, type):
            return {
                "success": True,
                "message": f"Type de pièce créé avec succès (parcours {type})",
                "room_type_key": room_data.room_type_key,
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création du template ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/room-templates/{room_type_key}")
async def update_room_template(room_type_key: str, room_data: RoomTypeUpdate, type: str = "Voyageur"):
    """Mettre à jour un type de pièce existant selon le type de parcours"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)
        room_types = room_templates.get("room_types", {})

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
        if save_room_templates(room_templates, type):
            return {
                "success": True,
                "message": f"Type de pièce mis à jour avec succès (parcours {type})",
                "room_type": room_types[room_type_key],
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du template {room_type_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/room-templates/{room_type_key}")
async def delete_room_template(room_type_key: str, type: str = "Voyageur"):
    """Supprimer un type de pièce selon le type de parcours"""
    try:
        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(type)
        room_types = room_templates.get("room_types", {})

        if room_type_key not in room_types:
            raise HTTPException(status_code=404, detail="Type de pièce non trouvé")

        # Supprimer le type de pièce
        deleted_room = room_types.pop(room_type_key)

        # Sauvegarder dans le fichier
        if save_room_templates(room_templates, type):
            return {
                "success": True,
                "message": f"Type de pièce supprimé avec succès (parcours {type})",
                "deleted_room": deleted_room,
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du template {room_type_key} ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/room-templates/reload")
async def reload_room_templates():
    """🔄 Recharger manuellement les templates depuis le fichier ou les variables d'environnement"""
    try:
        global ROOM_TEMPLATES
        
        logger.info("🔄 Rechargement manuel des templates demandé")
        
        # Recharger depuis les sources (env vars ou fichier)
        new_templates = load_room_templates()
        
        # Mettre à jour la variable globale
        ROOM_TEMPLATES = new_templates
        
        logger.info("✅ Templates rechargés avec succès en mémoire")
        
        # Logs de vérification
        room_count = len(ROOM_TEMPLATES.get("room_types", {}))
        total_ignorables = 0
        
        for room_key, room_info in ROOM_TEMPLATES.get("room_types", {}).items():
            points_ignorables = room_info.get("verifications", {}).get("points_ignorables", [])
            total_ignorables += len(points_ignorables)
            logger.info(f"   📝 {room_key}: {len(points_ignorables)} points ignorables")
        
        return {
            "success": True,
            "message": "Templates rechargés avec succès",
            "room_types_count": room_count,
            "total_points_ignorables": total_ignorables,
            "details": {
                room_key: {
                    "name": room_info.get("name", ""),
                    "points_ignorables_count": len(room_info.get("verifications", {}).get("points_ignorables", []))
                }
                for room_key, room_info in ROOM_TEMPLATES.get("room_types", {}).items()
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du rechargement des templates: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors du rechargement: {str(e)}")

@app.get("/room-templates/debug")
async def debug_room_templates():
    """🔍 Debug - Afficher l'état actuel des templates en mémoire"""
    try:
        global ROOM_TEMPLATES
        
        return {
            "success": True,
            "message": "État actuel des templates en mémoire",
            "templates_in_memory": ROOM_TEMPLATES,
            "room_types_count": len(ROOM_TEMPLATES.get("room_types", {})),
            "memory_address": id(ROOM_TEMPLATES),
            "summary": {
                room_key: {
                    "name": room_info.get("name", ""),
                    "elements_critiques_count": len(room_info.get("verifications", {}).get("elements_critiques", [])),
                    "points_ignorables_count": len(room_info.get("verifications", {}).get("points_ignorables", [])),
                    "defauts_frequents_count": len(room_info.get("verifications", {}).get("defauts_frequents", [])),
                    "points_ignorables": room_info.get("verifications", {}).get("points_ignorables", [])
                }
                for room_key, room_info in ROOM_TEMPLATES.get("room_types", {}).items()
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du debug des templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# 🔧 ENDPOINTS GESTION DES PROMPTS
# ═══════════════════════════════════════════════════════════════

# Modèles pour la gestion des prompts
class PromptSection(BaseModel):
    content: str

class PromptData(BaseModel):
    name: str
    description: str
    endpoint: str
    variables: List[str]
    sections: dict

class UserMessage(BaseModel):
    name: str
    description: str
    endpoint: str
    template: str
    variables: List[str]

class PromptsConfig(BaseModel):
    version: str
    last_updated: str
    description: str
    prompts: dict
    user_messages: dict

class PromptPreviewRequest(BaseModel):
    prompt_key: str
    variables: dict = {}
    is_user_message: bool = False

def load_prompts_config(parcours_type: str = "Voyageur"):
    """
    Charger la configuration des prompts depuis le fichier JSON selon le type de parcours

    Args:
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        dict: Configuration des prompts
    """
    try:
        # Normaliser le type de parcours
        parcours_type = parcours_type.strip() if parcours_type else "Voyageur"

        # Déterminer le suffixe du fichier selon le type
        if parcours_type.lower() == "ménage":
            file_suffix = "-menage"
            env_var_name = "PROMPTS_CONFIG_MENAGE"
        else:  # Par défaut: Voyageur
            file_suffix = "-voyageur"
            env_var_name = "PROMPTS_CONFIG_VOYAGEUR"

        logger.info(f"🔧 Chargement de la config prompts pour le parcours: {parcours_type}")

        # 🔥 PRIORITÉ 1: Variable d'environnement Railway (production)
        prompts_config_env = os.environ.get(env_var_name)
        if prompts_config_env:
            try:
                logger.info(f"📡 Chargement de la config prompts depuis la variable d'environnement {env_var_name}")
                return json.loads(prompts_config_env)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Erreur lors du parsing JSON de {env_var_name}: {e}")

        # 🔥 PRIORITÉ 2: Fichier local (développement/fallback)
        possible_paths = [
            f"front/prompts-config{file_suffix}.json",
            f"prompts-config{file_suffix}.json",
            os.path.join(os.path.dirname(__file__), "front", f"prompts-config{file_suffix}.json")
        ]

        for path in possible_paths:
            if os.path.exists(path):
                logger.info(f"📁 Chargement de la config prompts depuis le fichier: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)

        # 🔥 PRIORITÉ 3: Configuration par défaut
        logger.warning(f"⚠️ Aucune config prompts trouvée pour {parcours_type}, utilisation de la configuration par défaut")
        return get_default_prompts_config()

    except Exception as e:
        logger.error(f"❌ Erreur critique lors du chargement de la config prompts: {e}")
        return get_default_prompts_config()

def get_default_prompts_config():
    """Retourner la configuration par défaut des prompts"""
    return {
        "version": "1.0.0",
        "last_updated": "2025-01-16",
        "description": "Configuration des prompts pour CheckEasy API V5",
        "prompts": {
            "analyze_main": {
                "name": "Analyse Principale des Pièces",
                "description": "Prompt principal pour l'analyse comparative des images de pièces",
                "endpoint": "/analyze, /analyze-with-classification, /analyze-complete",
                "variables": ["commentaire_ia", "elements_critiques", "points_ignorables", "defauts_frequents", "piece_nom"],
                "sections": {
                    "reset_header": "🔄 RESET COMPLET - NOUVELLE ANALYSE INDÉPENDANTE 🔄",
                    "role_definition": "Tu es un expert en inspection de propreté avec une grande expérience dans le nettoyage professionnel.",
                    "instructions_analyse": """INSTRUCTIONS D'ANALYSE :
0. Filtre absolu — {points_ignorables}  
   Ignore totalement (JSON + texte) tout élément appartenant à la liste, même sous
   forme de synonyme ou variante (sing./plur., abréviation, etc.).

1. Focus — {elements_critiques}
   Concentre-toi particulièrement sur ces éléments critiques spécifiques à cette pièce.

2. Défauts fréquents — {defauts_frequents}
   Sois vigilant sur ces problèmes récurrents identifiés pour ce type de pièce.

3. Instructions spéciales : {commentaire_ia}""",
                    "criteres_severite": """CRITÈRES DE SÉVÉRITÉ :
- LOW : Rapide à nettoyer (< 2 min)
  Exemple : miettes isolées sur plan de travail, un coussin déplacé, micro-rayure superficielle, chaise déplacée

- MEDIUM : Nécessite une attention particulière (2-10 min) 
  Exemple : taches sur surface, objet manquant, désordre visible, problème d'hygiène modéré

- HIGH : Problème majeur nécessitant intervention (>10 min)
  Exemple : dégât important, casse, moisissure, saleté incrustée, dysfonctionnement""",
                    "format_descriptions": "Décris le problème, sa localisation précise et son état (sec, gras, etc.).\nEx. : « Taches de café séchées sur le plan de travail à droite de l'évier ».",
                    "regles_fondamentales": "",
                    "format_reponse": """RÉPONDS UNIQUEMENT EN FORMAT JSON ; AVANT de construire chaque objet `preliminary_issues`, vérifie que l'anomalie **n'appartient pas** à {points_ignorables} de la pièce courante.   Si c'est le cas, **l'exclure totalement** du JSON final.

Format JSON attendu :
{
  "piece_id": "{piece_id}",
  "nom_piece": "{piece_nom}",
  "analyse_globale": {
    "status": "ok|attention|probleme",
    "score": 0.0-10.0,
    "temps_nettoyage_estime": "X minutes",
    "commentaire_global": "Description humaine"
  },
  "preliminary_issues": [
    {
      "description": "Description précise",
      "category": "missing_item|damage|cleanliness|positioning|added_item|image_quality|wrong_room",
      "severity": "low|medium|high",
      "confidence": 0-100
    }
  ]
}"""
                }
            },
            "synthesis_global": {
                "name": "Synthèse Globale Logement",
                "description": "Prompt pour la synthèse et enrichissement global d'un logement",
                "endpoint": "/analyze-complete",
                "variables": ["logement_id", "total_issues", "general_issues", "etapes_issues", "issues_summary"],
                "sections": {
                    "role_definition": "Tu es un expert en gestion immobilière et analyse de logements.",
                    "task_definition": """MISSION : Analyser les résultats d'inspection du logement {logement_id} et créer une synthèse globale.

DONNÉES D'ENTRÉE :
- Total des problèmes détectés : {total_issues}
- Issues générales : {general_issues}  
- Issues d'étapes : {etapes_issues}
- Résumé détaillé : {issues_summary}

CALCUL DU SCORE (1-5) :
- 5 (EXCELLENT) : 0 problème ou défauts très mineurs
- 4 (TRÈS BON) : 1-2 problèmes mineurs sans impact majeur
- 3 (BON) : 3-5 problèmes modérés nécessitant attention
- 2 (MOYEN) : 6-10 problèmes ou plusieurs problèmes graves
- 1 (MÉDIOCRE) : Plus de 10 problèmes ou défauts critiques

LABELS CORRESPONDANTS :
Score 5 → "EXCELLENT", Score 4 → "TRÈS BON", Score 3 → "BON", Score 2 → "MOYEN", Score 1 → "MÉDIOCRE""",
                    "output_format": """GÉNÈRE UNE SYNTHÈSE EN JSON :
{
    "summary": {
        "missing_items": ["Liste des objets manquants reformulés en phrases claires OU 'Aucun objet manquant constaté' si vide"],
        "damages": ["Liste des dégâts et éléments abîmés OU 'Aucun dégât constaté' si vide"],
        "cleanliness_issues": ["Liste des problèmes de propreté OU 'Aucun problème de propreté majeur détecté' si vide"],
        "layout_problems": ["Liste des problèmes d'agencement OU 'Aucun problème d'agencement constaté' si vide"]
    },
    "recommendations": ["5 recommandations concrètes et priorisées"],
    "global_score": {
        "score": "CALCULER_SELON_ETAT_REEL",
        "label": "CALCULER_SELON_SCORE",
        "description": "Évaluer l'état réel et justifier la note attribuée"
    }
}"""
                }
            },
            "analyze_etapes": {
                "name": "Analyse des Étapes",
                "description": "Prompt pour l'analyse des étapes individuelles",
                "endpoint": "/analyze-etapes",
                "variables": ["task_name", "consigne", "etape_id"],
                "sections": {
                    "role_definition": "Tu es un expert en vérification de tâches ménagères.",
                    "task_definition": """MISSION : Analyser si la consigne "{consigne}" a été correctement exécutée pour l'étape "{task_name}".

ID ÉTAPE : {etape_id}""",
                    "output_format": """Compare les photos avant/après et retourne uniquement :
{
    "etape_id": "{etape_id}",
    "issues": [
        {
            "description": "Description du problème si la consigne n'est pas respectée",
            "category": "missing_item|damage|cleanliness|positioning|added_item|image_quality|wrong_room",
            "severity": "low|medium|high",
            "confidence": 0-100
        }
    ]
}"""
                }
            }
        },
        "user_messages": {
            "analyze_main_user": {
                "name": "Message Utilisateur - Analyse Principal",
                "description": "Message envoyé par l'utilisateur pour l'analyse des images",
                "endpoint": "/analyze",
                "template": "Analyse les différences entre ces photos d'entrée et de sortie d'une {piece_nom}. Fournis une réponse JSON structurée.",
                "variables": ["piece_nom"]
            }
        }
    }

def save_prompts_config(config_data, parcours_type: str = "Voyageur"):
    """Sauvegarder la configuration des prompts selon le type de parcours"""
    success_local = False
    success_env = False

    # Déterminer le suffixe du fichier selon le type
    if parcours_type.lower() == "ménage":
        file_suffix = "-menage"
        env_var_name = "PROMPTS_CONFIG_MENAGE"
    else:  # Par défaut: Voyageur
        file_suffix = "-voyageur"
        env_var_name = "PROMPTS_CONFIG_VOYAGEUR"

    try:
        # 🔥 SAUVEGARDE 1: Fichier local (pour développement)
        possible_paths = [
            f"front/prompts-config{file_suffix}.json",
            f"prompts-config{file_suffix}.json",
            os.path.join(os.path.dirname(__file__), "front", f"prompts-config{file_suffix}.json")
        ]

        target_path = None
        for path in possible_paths:
            if os.path.exists(path):
                target_path = path
                break

        if not target_path:
            # Créer le répertoire si nécessaire
            os.makedirs("front", exist_ok=True)
            target_path = f"front/prompts-config{file_suffix}.json"

        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Config prompts {parcours_type} sauvegardée dans le fichier: {target_path}")
        success_local = True

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde fichier local prompts ({parcours_type}): {e}")

    try:
        # 🔥 SAUVEGARDE 2: Variable d'environnement (pour Railway production)
        config_json = json.dumps(config_data, ensure_ascii=False, separators=(',', ':'))

        # Note: En production Railway, cette mise à jour nécessitera un redémarrage
        os.environ[env_var_name] = config_json

        logger.info(f"✅ Config prompts {parcours_type} mise à jour dans les variables d'environnement ({env_var_name})")
        success_env = True

        # 🔥 IMPORTANT: Informer l'utilisateur pour Railway
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            logger.warning(f"⚠️ RAILWAY: Les modifications {parcours_type} seront perdues au prochain déploiement!")
            logger.warning(f"💡 Utilisez l'interface d'admin Railway pour définir {env_var_name} de façon permanente")

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde variable d'environnement prompts ({parcours_type}): {e}")

    # Succès si au moins une méthode a fonctionné
    return success_local or success_env

@app.get("/prompts")
async def get_prompts_config(type: str = "Voyageur"):
    """Récupérer la configuration complète des prompts selon le type de parcours"""
    try:
        config = load_prompts_config(type)
        return {
            "success": True,
            "config": config,
            "parcours_type": type
        }
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la config prompts ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/prompts")
async def update_prompts_config(config: PromptsConfig):
    """Sauvegarder la configuration complète des prompts"""
    try:
        # Ajouter le timestamp de mise à jour
        config_dict = config.dict()
        config_dict["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        
        if save_prompts_config(config_dict):
            return {
                "success": True,
                "message": "Configuration des prompts sauvegardée avec succès",
                "last_updated": config_dict["last_updated"]
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la config prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/prompts/{prompt_key}")
async def get_prompt(prompt_key: str):
    """Récupérer un prompt spécifique"""
    try:
        config = load_prompts_config()
        
        if prompt_key in config.get("prompts", {}):
            return {
                "success": True,
                "prompt": config["prompts"][prompt_key]
            }
        elif prompt_key in config.get("user_messages", {}):
            return {
                "success": True,
                "user_message": config["user_messages"][prompt_key]
            }
        else:
            raise HTTPException(status_code=404, detail="Prompt non trouvé")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/prompts/{prompt_key}")
async def update_prompt(prompt_key: str, prompt_data: dict):
    """Mettre à jour un prompt spécifique"""
    try:
        config = load_prompts_config()
        
        if prompt_key in config.get("prompts", {}):
            config["prompts"][prompt_key] = prompt_data
        elif prompt_key in config.get("user_messages", {}):
            config["user_messages"][prompt_key] = prompt_data
        else:
            raise HTTPException(status_code=404, detail="Prompt non trouvé")
        
        config["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        
        if save_prompts_config(config):
            return {
                "success": True,
                "message": f"Prompt {prompt_key} mis à jour avec succès",
                "last_updated": config["last_updated"]
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/prompts/preview")
async def preview_prompt(request: PromptPreviewRequest):
    """Prévisualiser un prompt avec des variables d'exemple"""
    try:
        config = load_prompts_config()
        
        if request.is_user_message:
            # Message utilisateur
            message_key = request.prompt_key.replace('user_message.', '')
            if message_key not in config.get("user_messages", {}):
                raise HTTPException(status_code=404, detail="Message utilisateur non trouvé")
            
            message = config["user_messages"][message_key]
            template = message.get("template", "")
            generated_prompt = replace_variables_in_template(template, request.variables)
        else:
            # Prompt système
            if request.prompt_key not in config.get("prompts", {}):
                raise HTTPException(status_code=404, detail="Prompt non trouvé")
            
            prompt = config["prompts"][request.prompt_key]
            generated_prompt = build_full_prompt_from_config(prompt, request.variables)
        
        return {
            "success": True,
            "generated_prompt": generated_prompt,
            "variables_used": request.variables
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la prévisualisation du prompt {request.prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def replace_variables_in_template(template: str, variables: dict) -> str:
    """Remplacer les variables dans un template - VERSION SIMPLIFIÉE FIABLE"""
    result = template
    variables_replacees = 0
    
    for key, value in variables.items():
        placeholder = f"{{{key}}}"
        
        if placeholder in result:
            # Variable trouvée dans le template
            if isinstance(value, list):
                # Pour les listes, joindre avec des retours à la ligne avec des puces
                replacement_text = '\n'.join(f"• {str(item)}" for item in value) if value else "Aucun élément configuré"
            else:
                replacement_text = str(value)
            
            result = result.replace(placeholder, replacement_text)
            variables_replacees += 1
    
    logger.info(f"🔧 Variables remplacées: {variables_replacees}/{len(variables)}")
    
    return result

def build_full_prompt_from_config(prompt_config: dict, variables: dict) -> str:
    """Construire un prompt complet à partir de la configuration"""
    full_prompt = ""
    
    sections = prompt_config.get("sections", {})
    
    for section_key, content in sections.items():
        # 🔥 CORRECTION CRITIQUE: Remplacer les variables dans TOUTES les sections
        # Pas seulement celles qui finissent par '_template'
        section_content = replace_variables_in_template(content, variables)
        full_prompt += section_content + "\n\n"
    
    # Si aucune section trouvée, essayer de traiter la config comme un template simple
    if not sections and isinstance(prompt_config, dict):
        # Essayer de traiter toute la config comme du contenu
        if 'content' in prompt_config:
            full_prompt = replace_variables_in_template(prompt_config['content'], variables)
        elif 'template' in prompt_config:
            full_prompt = replace_variables_in_template(prompt_config['template'], variables)
        else:
            # Essayer de traiter la config entière comme un string
            config_str = str(prompt_config)
            full_prompt = replace_variables_in_template(config_str, variables)
    
    final_prompt = full_prompt.strip()
    
    # Vérification finale des variables non remplacées
    import re
    variables_restantes = re.findall(r'\{[^}]+\}', final_prompt)
    if variables_restantes:
        logger.error(f"🏗️ Variables non remplacées: {variables_restantes}")
    
    logger.info(f"🏗️ Prompt construit: {len(final_prompt)} caractères, {len(sections)} sections")
    
    return final_prompt

@app.get("/prompts/export/railway-env")
async def export_prompts_for_railway():
    """🚀 Exporter la configuration actuelle des prompts pour Railway (variable d'environnement)"""
    try:
        config = load_prompts_config()
        env_var_value = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
        
        return {
            "success": True,
            "message": "Configuration exportée pour Railway",
            "instructions": [
                "1. Copiez la valeur 'env_var_value' ci-dessous",
                "2. Allez dans Railway Dashboard > Variables",
                "3. Créez/modifiez la variable: PROMPTS_CONFIG",
                "4. Collez la valeur et sauvegardez",
                "5. Railway redémarrera automatiquement avec la nouvelle config"
            ],
            "variable_name": "PROMPTS_CONFIG",
            "env_var_value": env_var_value,
            "railway_command": f"railway variables set PROMPTS_CONFIG='{env_var_value}'"
        }
    except Exception as e:
        logger.error(f"Erreur lors de l'export Railway des prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Servir l'interface de gestion des prompts
@app.get("/prompts-admin")
async def serve_prompts_admin():
    """Servir l'interface d'administration pour gérer les prompts"""
    return FileResponse("front/index.html")

# Servir les fichiers statiques de l'interface prompts
app.mount("/front", StaticFiles(directory="front"), name="front")

# ═══════════════════════════════════════════════════════════════
# INTERFACE D'ADMINISTRATION DU SYSTÈME DE NOTATION
# ═══════════════════════════════════════════════════════════════

@app.get("/scoring-config")
async def serve_scoring_admin():
    """Servir l'interface d'administration pour gérer le système de notation"""
    try:
        # Charger la configuration actuelle
        config = load_scoring_config()

        # Rendre le template avec la configuration
        with open("templates/scoring-admin.html", "r", encoding="utf-8") as f:
            template_content = f.read()

        # Injecter la configuration dans le template
        import json
        config_json = json.dumps(config)
        template_content = template_content.replace("{{ config_json | safe }}", config_json)

        return HTMLResponse(content=template_content)
    except Exception as e:
        logger.error(f"Erreur lors du chargement de l'interface scoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scoring-config/save")
async def save_scoring_config_endpoint(request: Request):
    """Sauvegarder la configuration du système de notation"""
    try:
        # Récupérer les données JSON
        new_config = await request.json()

        # Créer un backup avant modification
        import shutil
        from datetime import datetime
        backup_path = f"front/scoring-config.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if os.path.exists("front/scoring-config.json"):
            shutil.copy("front/scoring-config.json", backup_path)
            logger.info(f"✅ Backup créé : {backup_path}")

        # Sauvegarder la nouvelle configuration
        with open("front/scoring-config.json", "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)

        logger.info("✅ Configuration du scoring sauvegardée avec succès")
        logger.info(f"📊 Dernière mise à jour : {new_config.get('last_updated', 'N/A')}")

        return {"success": True, "message": "Configuration sauvegardée avec succès"}
    except Exception as e:
        logger.error(f"❌ Erreur lors de la sauvegarde de la configuration scoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scoring-config/reset")
async def reset_scoring_config_endpoint():
    """Réinitialiser la configuration du système de notation aux valeurs par défaut"""
    try:
        # Valeurs par défaut
        default_config = {
            "version": "1.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "description": "Configuration du système de notation à score pondéré (APPROCHE 2) - CheckEasy API V5",
            "scoring_system": {
                "severity_base_score": {
                    "description": "Score de base selon la sévérité de l'issue",
                    "low": 1,
                    "medium": 3,
                    "high": 10
                },
                "category_multiplier": {
                    "description": "Multiplicateur selon la catégorie d'issue",
                    "damage": 2.0,
                    "cleanliness": 1.5,
                    "missing_item": 1.3,
                    "positioning": 0.5,
                    "added_item": 0.4,
                    "image_quality": 0.2,
                    "wrong_room": 0.3
                },
                "room_importance_weight": {
                    "description": "Poids d'importance par type de pièce (pour la moyenne pondérée)",
                    "cuisine": 2.0,
                    "salle_de_bain": 1.8,
                    "salle_de_bain_et_toilettes": 1.8,
                    "salle_d_eau": 1.7,
                    "salle_d_eau_et_wc": 1.7,
                    "wc": 1.5,
                    "salon": 1.2,
                    "chambre": 1.0,
                    "bureau": 1.0,
                    "entree": 0.8,
                    "exterieur": 0.6
                },
                "etape_reduction_factor": {
                    "description": "Facteur de réduction pour les issues d'étapes (0.6 = réduction de 40%)",
                    "value": 0.6
                },
                "grade_thresholds": {
                    "description": "Seuils de conversion du score moyen pondéré en note /5",
                    "thresholds": [
                        {"grade": 5.0, "label": "EXCELLENT", "max_score": 0, "description": "Aucune issue détectée"},
                        {"grade": 4.8, "label": "EXCELLENT", "max_score": 1.5, "description": "Quelques détails très mineurs"},
                        {"grade": 4.5, "label": "TRÈS BON", "max_score": 3.0, "description": "Quelques détails mineurs par pièce"},
                        {"grade": 4.0, "label": "BON", "max_score": 5.0, "description": "Quelques problèmes par pièce"},
                        {"grade": 3.5, "label": "CORRECT", "max_score": 8.0, "description": "Plusieurs problèmes par pièce"},
                        {"grade": 3.0, "label": "MOYEN", "max_score": 12.0, "description": "Nombreux problèmes par pièce"},
                        {"grade": 2.5, "label": "PASSABLE", "max_score": 18.0, "description": "Problèmes importants"},
                        {"grade": 2.0, "label": "INSUFFISANT", "max_score": 25.0, "description": "Problèmes graves"},
                        {"grade": 1.5, "label": "MAUVAIS", "max_score": 35.0, "description": "Problèmes très graves"},
                        {"grade": 1.0, "label": "CRITIQUE", "max_score": 999999, "description": "Problèmes critiques généralisés"}
                    ]
                },
                "confidence_threshold": {
                    "description": "Seuil de confiance minimum pour qu'une issue soit prise en compte dans le calcul",
                    "value": 90
                }
            },
            "metadata": {
                "created_by": "CheckEasy Admin",
                "notes": "Cette configuration permet d'ajuster finement le système de notation sans modifier le code Python. Toute modification est appliquée immédiatement."
            }
        }

        # Créer un backup avant réinitialisation
        import shutil
        backup_path = f"front/scoring-config.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if os.path.exists("front/scoring-config.json"):
            shutil.copy("front/scoring-config.json", backup_path)
            logger.info(f"✅ Backup créé avant réinitialisation : {backup_path}")

        # Sauvegarder la configuration par défaut
        with open("front/scoring-config.json", "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        logger.info("✅ Configuration du scoring réinitialisée aux valeurs par défaut")

        return {"success": True, "message": "Configuration réinitialisée", "config": default_config}
    except Exception as e:
        logger.error(f"❌ Erreur lors de la réinitialisation de la configuration scoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def load_scoring_config() -> dict:
    """
    Charger la configuration du système de notation depuis le fichier JSON

    Returns:
        dict: Configuration du scoring
    """
    try:
        config_path = "front/scoring-config.json"

        if not os.path.exists(config_path):
            logger.warning(f"⚠️ Fichier de configuration scoring non trouvé : {config_path}")
            logger.info("📝 Création du fichier avec les valeurs par défaut...")

            # Créer le fichier avec les valeurs par défaut
            default_config = {
                "version": "1.0.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "description": "Configuration du système de notation à score pondéré (APPROCHE 2) - CheckEasy API V5",
                "scoring_system": {
                    "severity_base_score": {
                        "description": "Score de base selon la sévérité de l'issue",
                        "low": 1,
                        "medium": 3,
                        "high": 10
                    },
                    "category_multiplier": {
                        "description": "Multiplicateur selon la catégorie d'issue",
                        "damage": 2.0,
                        "cleanliness": 1.5,
                        "missing_item": 1.3,
                        "positioning": 0.5,
                        "added_item": 0.4,
                        "image_quality": 0.2,
                        "wrong_room": 0.3
                    },
                    "room_importance_weight": {
                        "description": "Poids d'importance par type de pièce (pour la moyenne pondérée)",
                        "cuisine": 2.0,
                        "salle_de_bain": 1.8,
                        "salle_de_bain_et_toilettes": 1.8,
                        "salle_d_eau": 1.7,
                        "salle_d_eau_et_wc": 1.7,
                        "wc": 1.5,
                        "salon": 1.2,
                        "chambre": 1.0,
                        "bureau": 1.0,
                        "entree": 0.8,
                        "exterieur": 0.6
                    },
                    "etape_reduction_factor": {
                        "description": "Facteur de réduction pour les issues d'étapes (0.6 = réduction de 40%)",
                        "value": 0.6
                    },
                    "grade_thresholds": {
                        "description": "Seuils de conversion du score moyen pondéré en note /5",
                        "thresholds": [
                            {"grade": 5.0, "label": "EXCELLENT", "max_score": 0, "description": "Aucune issue détectée"},
                            {"grade": 4.8, "label": "EXCELLENT", "max_score": 1.5, "description": "Quelques détails très mineurs"},
                            {"grade": 4.5, "label": "TRÈS BON", "max_score": 3.0, "description": "Quelques détails mineurs par pièce"},
                            {"grade": 4.0, "label": "BON", "max_score": 5.0, "description": "Quelques problèmes par pièce"},
                            {"grade": 3.5, "label": "CORRECT", "max_score": 8.0, "description": "Plusieurs problèmes par pièce"},
                            {"grade": 3.0, "label": "MOYEN", "max_score": 12.0, "description": "Nombreux problèmes par pièce"},
                            {"grade": 2.5, "label": "PASSABLE", "max_score": 18.0, "description": "Problèmes importants"},
                            {"grade": 2.0, "label": "INSUFFISANT", "max_score": 25.0, "description": "Problèmes graves"},
                            {"grade": 1.5, "label": "MAUVAIS", "max_score": 35.0, "description": "Problèmes très graves"},
                            {"grade": 1.0, "label": "CRITIQUE", "max_score": 999999, "description": "Problèmes critiques généralisés"}
                        ]
                    },
                    "confidence_threshold": {
                        "description": "Seuil de confiance minimum pour qu'une issue soit prise en compte dans le calcul",
                        "value": 90
                    }
                },
                "metadata": {
                    "created_by": "CheckEasy Admin",
                    "notes": "Cette configuration permet d'ajuster finement le système de notation sans modifier le code Python. Toute modification est appliquée immédiatement."
                }
            }

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)

            return default_config

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        logger.info(f"✅ Configuration scoring chargée depuis {config_path}")
        return config

    except Exception as e:
        logger.error(f"❌ Erreur lors du chargement de la configuration scoring: {e}")
        # Retourner une configuration par défaut en cas d'erreur
        return {
            "scoring_system": {
                "severity_base_score": {"low": 1, "medium": 3, "high": 10},
                "category_multiplier": {
                    "damage": 2.0, "cleanliness": 1.5, "missing_item": 1.3,
                    "positioning": 0.5, "added_item": 0.4, "image_quality": 0.2, "wrong_room": 0.3
                },
                "room_importance_weight": {
                    "cuisine": 2.0, "salle_de_bain": 1.8, "salle_de_bain_et_toilettes": 1.8,
                    "salle_d_eau": 1.7, "salle_d_eau_et_wc": 1.7, "wc": 1.5,
                    "salon": 1.2, "chambre": 1.0, "bureau": 1.0, "entree": 0.8, "exterieur": 0.6
                },
                "etape_reduction_factor": {"value": 0.6},
                "grade_thresholds": {
                    "thresholds": [
                        {"grade": 5.0, "label": "EXCELLENT", "max_score": 0},
                        {"grade": 4.8, "label": "EXCELLENT", "max_score": 1.5},
                        {"grade": 4.5, "label": "TRÈS BON", "max_score": 3.0},
                        {"grade": 4.0, "label": "BON", "max_score": 5.0},
                        {"grade": 3.5, "label": "CORRECT", "max_score": 8.0},
                        {"grade": 3.0, "label": "MOYEN", "max_score": 12.0},
                        {"grade": 2.5, "label": "PASSABLE", "max_score": 18.0},
                        {"grade": 2.0, "label": "INSUFFISANT", "max_score": 25.0},
                        {"grade": 1.5, "label": "MAUVAIS", "max_score": 35.0},
                        {"grade": 1.0, "label": "CRITIQUE", "max_score": 999999}
                    ]
                },
                "confidence_threshold": {"value": 90}
            }
        }

# ═══════════════════════════════════════════════════════════════

def map_room_type_to_valid(detected_type: str) -> str:
    """
    Mapper les variations de types de pièces vers les types valides
    
    Args:
        detected_type: Le type détecté par l'IA (peut être non standard)
        
    Returns:
        str: Le type valide correspondant
    """
    # Normaliser : minuscules et enlever les espaces
    normalized = detected_type.lower().strip()
    
    # 🗺️ MAPPING DES VARIATIONS COURANTES
    mapping = {
        # Variations salle de bain
        "salle_de_bain_avec_wc": "salle_de_bain_et_toilettes",  # Redirige vers le nouveau type
        "salle_de_bain_wc": "salle_de_bain_et_toilettes",
        "sdb": "salle_de_bain",
        "bathroom": "salle_de_bain",
        
        # Variations WC
        "toilettes": "wc",
        "toilet": "wc",
        "wc_separe": "wc",
        "wc_separé": "wc",
        
        # Variations cuisine
        "kitchen": "cuisine",
        "kitchenette": "cuisine",
        "coin_cuisine": "cuisine",
        
        # Variations salon
        "living": "salon",
        "living_room": "salon",
        "sejour": "salon",
        "séjour": "salon",
        "salle_a_manger": "salon",
        "salle_à_manger": "salon",
        
        # Variations chambre
        "bedroom": "chambre",
        "chambre_a_coucher": "chambre",
        "chambre_à_coucher": "chambre",
        "chambre_principale": "chambre",
        "chambre_parentale": "chambre",
        
        # Variations bureau
        "office": "bureau",
        "study": "bureau",
        "bureau_domicile": "bureau",
        
        # Variations entrée
        "entree_principale": "entree",
        "entrée": "entree",
        "entrée_principale": "entree",
        "hall": "entree",
        "couloir": "entree",
        "corridor": "entree",
        
        # Variations balcon
        "terrasse": "balcon",
        "terrace": "balcon",
        "loggia": "balcon",
        "veranda": "balcon",
        "véranda": "balcon",
        
        # Autres variations courantes
        "piece": "autre",
        "pièce": "autre",
        "room": "autre",
        "space": "autre",
        "espace": "autre",
        "inconnu": "autre",
        "unknown": "autre"
    }
    
    # Chercher d'abord une correspondance exacte
    if normalized in mapping:
        mapped_type = mapping[normalized]
        logger.info(f"🗺️ Type mappé: '{detected_type}' → '{mapped_type}'")
        return mapped_type
    
    # Si pas de mapping direct, chercher des mots-clés
    for variant, valid_type in mapping.items():
        if variant in normalized or normalized in variant:
            logger.info(f"🗺️ Type mappé par mots-clés: '{detected_type}' → '{valid_type}'")
            return valid_type
    
    # Si aucun mapping trouvé, retourner le type original
    logger.info(f"🗺️ Aucun mapping trouvé pour '{detected_type}', utilisation directe")
    return normalized

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 