from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
import logging
import logging.config
import sys
import json
import os
import threading
from openai import OpenAI, AsyncOpenAI
import asyncio
import aiohttp
import nest_asyncio
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

# 🔧 FIX WINDOWS: Forcer SelectorEventLoop pour compatibilité aiodns
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 🔧 Permettre les boucles asyncio imbriquées (nécessaire pour compatibilité)
# Note: DOUBLE_PASS est désactivé mais nest_asyncio reste pour éviter les conflits
nest_asyncio.apply()
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from image_converter import (
    process_pictures_list,
    process_etapes_images,
    is_valid_image_url,
    normalize_url,
    create_placeholder_image_url,
    ImageConverter
)
from datetime import datetime
import re
from tqdm import tqdm
import uuid

# Import du gestionnaire de logs
from logs_viewer.logs_manager import logs_manager

# 🚀 CONFIGURATION LOGGING OPTIMISÉE RAILWAY
class RailwayJSONFormatter(logging.Formatter):
    """
    Formatter JSON optimisé pour Railway qui produit des logs structurés
    sans caractères spéciaux qui causent des problèmes d'interprétation
    """
    
    def format(self, record):
        # Créer un objet de log structuré
        from datetime import datetime
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        log_obj = {
            "timestamp": timestamp,
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

    # 🔧 Support LOG_LEVEL via variable d'environnement (défaut: INFO)
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
        log_level = 'INFO'

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
                    "level": log_level
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
                    "level": log_level,
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

# ========== AFFICHAGE AMÉLIORÉ DES LOGS (UNIQUEMENT EN LOCAL) ==========
# Détecter si on est en local (pas sur Railway)
is_local = not any([
    os.environ.get('RAILWAY_ENVIRONMENT'),
    os.environ.get('RAILWAY_PUBLIC_DOMAIN'),
    os.environ.get('RAILWAY_SERVICE_NAME'),
])

if is_local:
    # Activer l'affichage amélioré uniquement en local
    try:
        from enable_pretty_logs import enable_pretty_logs
        enable_pretty_logs()
    except ImportError:
        logger.warning("⚠️ Module enable_pretty_logs non trouvé - affichage standard utilisé")
# ========================================================================

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
    score: float = Field(ge=1, le=5, description="Note algorithmique de 1 à 5 (calculée automatiquement)")
    temps_nettoyage_estime: str
    commentaire_global: str = Field(description="Résumé humain de l'état général de la pièce, incluant propreté et agencement")

class Probleme(BaseModel):
    description: str
    category: Literal["missing_item", "damage", "cleanliness", "positioning", "added_item", "image_quality", "wrong_room", "etape_non_validee"]
    severity: Literal["low", "medium", "high"]
    confidence: int = Field(ge=0, le=100)
    etape_id: Optional[str] = None  # ID de l'étape si l'issue provient d'une étape

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
    is_valid_room: bool  # True si les photos montrent un intérieur de logement, False sinon
    validation_message: str  # Message explicatif si is_valid_room = False
    verifications: RoomVerifications

# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR LE SYSTÈME DOUBLE-PASS (Inventaire + Vérification)
# ═══════════════════════════════════════════════════════════════

class InventoryObject(BaseModel):
    """Un objet détecté dans l'inventaire"""
    object_id: str = Field(description="ID unique de l'objet (ex: obj_001)")
    name: str = Field(description="Nom de l'objet (ex: 'Lampe de chevet')")
    location: str = Field(description="Localisation précise (ex: 'Sur la table de nuit à gauche du lit')")
    description: str = Field(description="Description visuelle (ex: 'Lampe blanche avec abat-jour beige')")
    category: str = Field(description="Catégorie: furniture, decoration, electronic, textile, accessory, appliance")
    importance: str = Field(description="Importance: essential, important, decorative")

class InventoryExtractionResponse(BaseModel):
    """Réponse de l'extraction d'inventaire"""
    piece_id: str
    total_objects: int
    objects: List[InventoryObject]

class ObjectVerificationResult(BaseModel):
    """Résultat de vérification d'un objet"""
    object_id: str
    name: str
    location: str
    status: str = Field(description="present, missing, moved, damaged")
    confidence: int = Field(ge=0, le=100)
    details: str = Field(description="Détails de la vérification")

class InventoryVerificationResponse(BaseModel):
    """Réponse de la vérification d'inventaire"""
    piece_id: str
    total_checked: int
    missing_objects: List[ObjectVerificationResult]
    moved_objects: List[ObjectVerificationResult]
    present_objects: List[ObjectVerificationResult]

# ═══════════════════════════════════════════════════════════════

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
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates-static", StaticFiles(directory="templates"), name="templates-static")

@app.get("/admin")
async def serve_admin_interface():
    """Servir l'interface d'administration pour gérer les room templates"""
    return FileResponse("templates/admin.html")

@app.get("/tester")
async def serve_api_tester():
    """Servir l'interface de test avancée de l'API"""
    return FileResponse("templates/api-tester.html")

@app.get("/parcourtest.json")
async def get_parcourtest_json():
    """Servir le fichier parcourtest.json pour l'interface de test"""
    return FileResponse("parcourtest.json")

# Client OpenAI global
import os

# Charger les variables d'environnement depuis .env si le fichier existe
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ Fichier .env chargé avec succès")
except ImportError:
    logger.warning("⚠️ Module python-dotenv non installé - utilisation des variables d'environnement système uniquement")
except Exception as e:
    logger.warning(f"⚠️ Erreur lors du chargement du fichier .env: {e}")

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

# Initialiser le client Async pour la parallélisation
try:
    async_client = AsyncOpenAI()
    log_success("Client AsyncOpenAI initialisé avec succès")
except Exception as e:
    log_warning(f"Impossible d'initialiser AsyncOpenAI: {e}")
    async_client = None
    client = None

# ═══════════════════════════════════════════════════════════════════════════════
# 🚀 CONFIGURATION MODÈLE OPENAI (depuis variable d'environnement Railway)
# ═══════════════════════════════════════════════════════════════════════════════
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.2-2025-12-11")
logger.debug("")
logger.debug("=" * 100)
logger.debug("🤖🤖🤖  CONFIGURATION MODÈLE OPENAI  🤖🤖🤖")
logger.debug("=" * 100)
logger.debug(f"📌 MODÈLE UTILISÉ: {OPENAI_MODEL}")
logger.debug(f"📌 SOURCE: {'Variable OPENAI_MODEL' if os.environ.get('OPENAI_MODEL') else 'Valeur par défaut'}")
logger.debug("=" * 100)
logger.debug("")

def call_openai_responses(
    system_prompt: str,
    user_input: str = None,
    user_images: list = None,
    json_response: bool = True,
    max_tokens: int = 16000
) -> dict:
    """
    🚀 Fonction centralisée pour appeler l'API OpenAI Responses
    
    Utilise la nouvelle API Responses (/v1/responses) au lieu de Chat Completions.
    Le modèle est lu depuis la variable d'environnement OPENAI_MODEL.
    
    Args:
        system_prompt: Le prompt système (instructions)
        user_input: Le texte de l'utilisateur (optionnel)
        user_images: Liste d'URLs d'images à analyser (optionnel)
        json_response: Si True, demande une réponse JSON structurée
        max_tokens: Nombre maximum de tokens de réponse
    
    Returns:
        dict: La réponse parsée (JSON si json_response=True, sinon texte brut)
    """
    global OPENAI_MODEL
    
    try:
        # 🟢🟢🟢 LOG APPEL API - TRÈS VISIBLE 🟢🟢🟢
        logger.debug("")
        logger.debug("=" * 100)
        logger.debug("🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵")
        logger.debug("🤖🤖🤖  APPEL API OPENAI RESPONSES  🤖🤖🤖")
        logger.debug("🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵🔵")
        logger.debug("=" * 100)
        logger.debug(f"📌 MODÈLE: {OPENAI_MODEL}")
        logger.debug(f"📌 JSON RESPONSE: {json_response}")
        logger.debug(f"📌 MAX TOKENS: {max_tokens}")
        logger.debug(f"📌 IMAGES: {len(user_images) if user_images else 0}")
        logger.debug(f"📌 LONGUEUR SYSTEM PROMPT: {len(system_prompt)} caractères")
        logger.debug(f"📌 LONGUEUR USER INPUT: {len(user_input) if user_input else 0} caractères")
        logger.debug("=" * 100)
        
        # Construire l'input pour l'API Responses
        input_content = []
        
        # Ajouter le prompt système comme contexte
        input_content.append({
            "role": "system",
            "content": system_prompt
        })
        
        # Construire le message utilisateur
        user_message_content = []
        
        # Ajouter le texte utilisateur si présent
        if user_input:
            user_message_content.append({
                "type": "input_text",
                "text": user_input
            })
        
        # Ajouter les images si présentes
        if user_images:
            for img_url in user_images:
                if img_url and isinstance(img_url, str):
                    user_message_content.append({
                        "type": "input_image",
                        "image_url": img_url
                    })
        
        # Ajouter le message utilisateur
        if user_message_content:
            input_content.append({
                "role": "user",
                "content": user_message_content
            })
        
        # Configuration de la réponse
        response_config = {
            "model": OPENAI_MODEL,
            "input": input_content
        }
        
        # Ajouter le format JSON si demandé
        if json_response:
            response_config["text"] = {
                "format": {
                    "type": "json_object"
                }
            }
        
        # Ajouter max_tokens si spécifié
        if max_tokens:
            response_config["max_output_tokens"] = max_tokens
        
        logger.debug(f"📤 Envoi de la requête à OpenAI Responses API...")
        
        # Appel à l'API Responses
        response = client.responses.create(**response_config)
        
        # Extraire le contenu de la réponse
        response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
        
        logger.debug(f"✅ Réponse reçue: {len(response_text)} caractères")
        
        # Parser en JSON si demandé
        if json_response:
            try:
                result = json.loads(response_text)
                logger.info("✅ JSON parsé avec succès")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"❌ Erreur parsing JSON: {e}")
                logger.error(f"   Contenu: {response_text[:500]}...")
                raise ValueError(f"Réponse non-JSON valide: {e}")
        else:
            return {"text": response_text}
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'appel OpenAI Responses API: {e}")
        raise

async def call_openai_responses_async(
    system_prompt: str,
    user_input: str = None,
    user_images: list = None,
    json_response: bool = True,
    max_tokens: int = 16000
) -> dict:
    """
    🚀 Version asynchrone de call_openai_responses
    """
    global OPENAI_MODEL, async_client

    if async_client is None:
        # Fallback sur la version synchrone
        return call_openai_responses(system_prompt, user_input, user_images, json_response, max_tokens)

    try:
        logger.debug(f"📤 Appel async à OpenAI Responses API (modèle: {OPENAI_MODEL})...")

        # Construire l'input
        input_content = []
        input_content.append({"role": "system", "content": system_prompt})

        user_message_content = []
        if user_input:
            user_message_content.append({"type": "input_text", "text": user_input})
        if user_images:
            for img_url in user_images:
                if img_url:
                    user_message_content.append({"type": "input_image", "image_url": img_url})

        if user_message_content:
            input_content.append({"role": "user", "content": user_message_content})

        response_config = {
            "model": OPENAI_MODEL,
            "input": input_content
        }

        if json_response:
            response_config["text"] = {"format": {"type": "json_object"}}
        if max_tokens:
            response_config["max_output_tokens"] = max_tokens

        response = await async_client.responses.create(**response_config)

        response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)

        if json_response:
            return json.loads(response_text)
        return {"text": response_text}

    except Exception as e:
        logger.error(f"❌ Erreur async OpenAI Responses API: {e}")
        raise


def convert_chat_messages_to_responses_input(messages: list) -> list:
    """
    🔄 Convertit les messages du format Chat Completions vers le format Responses

    Chat Completions format:
    [
        {"role": "system", "content": "..."},
        {"role": "user", "content": [...]}
    ]

    Responses format:
    [
        {"role": "system", "content": "..."},
        {"role": "user", "content": [{"type": "input_text", "text": "..."}, {"type": "input_image", "image_url": "..."}]}
    ]

    Args:
        messages: Liste de messages au format Chat Completions

    Returns:
        list: Messages convertis au format Responses
    """
    converted = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            # Le système reste identique
            converted.append({"role": "system", "content": content})

        elif role == "user":
            # Convertir le contenu utilisateur
            if isinstance(content, str):
                # Texte simple
                converted.append({
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}]
                })
            elif isinstance(content, list):
                # Contenu multimodal (texte + images)
                user_content = []
                for item in content:
                    if item.get("type") == "text":
                        user_content.append({"type": "input_text", "text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url", "")
                        if image_url:
                            user_content.append({"type": "input_image", "image_url": image_url})

                if user_content:
                    converted.append({"role": "user", "content": user_content})

    return converted


def extract_usage_tokens(response) -> dict:
    """
    🔄 Extrait les tokens d'usage de manière compatible avec Responses API

    Responses API utilise:
    - input_tokens au lieu de prompt_tokens
    - output_tokens au lieu de completion_tokens

    Args:
        response: Réponse de l'API OpenAI

    Returns:
        dict: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    """
    if not hasattr(response, 'usage'):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    usage = response.usage

    # Responses API format
    if hasattr(usage, 'input_tokens'):
        return {
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens
        }

    # Chat Completions API format (fallback)
    if hasattr(usage, 'prompt_tokens'):
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens
        }

    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


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

        logger.info(f"🔧 Chargement des templates de vérification pour le parcours: {parcours_type} (suffixe: {file_suffix})")

        # 🔥 PRIORITÉ 1: Variable d'environnement Railway (production)
        room_templates_env = os.environ.get(env_var_name)
        if room_templates_env:
            try:
                logger.debug(f"📡 Chargement des templates depuis la variable d'environnement {env_var_name}")
                templates = json.loads(room_templates_env)
                logger.debug(f"✅ Templates {parcours_type} chargés depuis variable d'environnement ({len(templates.get('room_types', {}))} types de pièces)")
                return templates
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
                logger.debug(f"📁 Chargement des templates depuis le fichier: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    templates = json.load(f)
                logger.debug(f"✅ Templates {parcours_type} chargés depuis fichier ({len(templates.get('room_types', {}))} types de pièces)")
                # Log des points_ignorables pour la chambre (debug)
                if 'chambre' in templates.get('room_types', {}):
                    chambre_ignorables = templates['room_types']['chambre']['verifications'].get('points_ignorables', [])
                    logger.info(f"🛏️ Chambre - Points ignorables ({len(chambre_ignorables)}): {chambre_ignorables}")
                return templates

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
    # 🔥 PRIORITÉ 1: Variable VERSION (Railway custom - source de vérité)
    version = os.environ.get('VERSION', '').lower()
    if version == 'live':
        logger.info("🚀 Environnement détecté: PRODUCTION (via VERSION=live)")
        return "production"
    elif version == 'test':
        logger.info("🔧 Environnement détecté: STAGING (via VERSION=test)")
        return "staging"

    # Méthode 2: Variable d'environnement explicite ENVIRONMENT
    env = os.environ.get('ENVIRONMENT', '').lower()
    if env in ['staging', 'stage', 'test']:
        logger.info("🔧 Environnement détecté: STAGING (via ENVIRONMENT)")
        return "staging"
    elif env in ['production', 'prod', 'live']:
        logger.info("🚀 Environnement détecté: PRODUCTION (via ENVIRONMENT)")
        return "production"

    # Méthode 3: Variable Railway RAILWAY_ENVIRONMENT
    railway_env = os.environ.get('RAILWAY_ENVIRONMENT', '').lower()
    if railway_env == 'production':
        logger.info("🚀 Environnement détecté: PRODUCTION (via RAILWAY_ENVIRONMENT)")
        return "production"

    # Méthode 4: URL de l'application RAILWAY_PUBLIC_DOMAIN
    railway_public_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if 'staging' in railway_public_domain.lower():
        logger.info("🔧 Environnement détecté: STAGING (via RAILWAY_PUBLIC_DOMAIN)")
        return "staging"
    elif railway_public_domain and 'staging' not in railway_public_domain.lower():
        logger.info("🚀 Environnement détecté: PRODUCTION (via RAILWAY_PUBLIC_DOMAIN)")
        return "production"

    # Méthode 5: Nom du service Railway RAILWAY_SERVICE_NAME
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

def get_webhook_url_individual_report(environment: str) -> str:
    """
    Retourne l'URL du webhook individual-report selon l'environnement

    Ce webhook reçoit le payload au format individual-report-data-model.json
    pour la page de rapport détaillé.

    Args:
        environment: "staging" ou "production"

    Returns:
        str: URL du webhook Bubble pour le rapport individuel
    """
    if environment == "production":
        return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/individual-report-webhook"
    else:  # staging par défaut
        return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/individual-report-webhook"

def get_bubble_debug_endpoint(environment: str) -> str:
    """
    Retourne l'URL du endpoint de debug Bubble selon l'environnement

    Args:
        environment: "staging" ou "production"

    Returns:
        str: URL du endpoint debug Bubble (iatest)
    """
    if environment == "production":
        return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/iatest"
    else:  # staging par défaut
        return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/iatest"

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
        logger.debug(f"📤 Envoi webhook vers: {webhook_url}")
        
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
                    logger.debug(f"✅ Webhook envoyé avec succès (200): {response_text[:200]}...")
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
            logger.debug(f"✅ Prompt construit: {len(full_prompt)} caractères")
            
            # 🟢🟢🟢 DEBUG PROMPT FINAL CONSTRUIT - TRÈS VISIBLE 🟢🟢🟢
            logger.debug("")
            logger.debug("=" * 100)
            logger.debug("🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢")
            logger.debug("🔵🔵🔵  PROMPT FINAL ENVOYÉ À OPENAI (après injection variables)  🔵🔵🔵")
            logger.debug("🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢🟢")
            logger.debug("=" * 100)
            logger.debug(f"📊 LONGUEUR TOTALE: {len(full_prompt)} caractères")
            logger.debug(f"📊 NOMBRE DE LIGNES: {len(full_prompt.split(chr(10)))}")
            logger.debug(f"🧳 TYPE PARCOURS: {parcours_type}")
            logger.debug(f"🏠 PIÈCE: {input_data.nom}")
            logger.debug("-" * 100)
            logger.debug("📜 CONTENU COMPLET DU PROMPT FINAL:")
            logger.debug("-" * 100)
            
            # Afficher le prompt ligne par ligne
            prompt_lines = full_prompt.split('\n')
            for i, line in enumerate(prompt_lines):
                logger.debug(f"   {i+1:4d} | {line}")
            
            logger.debug("-" * 100)
            logger.debug("=" * 100)
            logger.debug("🟢🟢🟢  FIN PROMPT FINAL  🟢🟢🟢")
            logger.debug("=" * 100)
            logger.debug("")
            # 🟢🟢🟢 FIN DEBUG PROMPT FINAL 🟢🟢🟢
            
            return full_prompt
        else:
            logger.warning("⚠️ Prompt vide, utilisation du fallback")
            raise ValueError("Prompt vide depuis la configuration")
    
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors du chargement de la config prompts: {e}")
        logger.warning("🔄 Utilisation du prompt de secours minimal")
        
        # Fallback minimal - uniquement en cas d'erreur critique
        return """Tu es un expert en inspection de propreté. Compare les PHOTOS DE RÉFÉRENCE avec les PHOTOS DE SORTIE.

🚨 RÈGLE ABSOLUE - ORDRE DES IMAGES:
📷 Les PREMIÈRES images = PHOTOS DE RÉFÉRENCE = État ATTENDU/IDÉAL (comment ça DOIT être)
📷 Les DERNIÈRES images = PHOTOS DE SORTIE = État ACTUEL (comment c'EST maintenant)

⚠️ UN PROBLÈME = quelque chose qui est DIFFÉRENT (en pire) sur les PHOTOS DE SORTIE par rapport aux PHOTOS DE RÉFÉRENCE
⚠️ Si un objet est PRÉSENT sur la RÉFÉRENCE mais ABSENT sur la SORTIE → PROBLÈME (objet manquant)
⚠️ Si un objet est ABSENT sur la RÉFÉRENCE mais PRÉSENT sur la SORTIE → PAS un problème (sauf si c'est un déchet)

INSTRUCTIONS :
1. D'ABORD analyse les PHOTOS DE RÉFÉRENCE - mémorise l'état idéal
2. ENSUITE analyse les PHOTOS DE SORTIE - compare avec la référence
3. Identifie ce qui MANQUE, ce qui est ENDOMMAGÉ, ce qui est SALE par rapport à la référence
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
logger.debug(f"🚀 Système de fallback Data URI chargé: {FALLBACK_SYSTEM_VERSION}")

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
        # Télécharger l'image
        image_data, detected_format = ImageConverter.download_image(url)

        if not image_data:
            return None

        # Convertir en JPEG pour optimiser la taille
        jpeg_data = ImageConverter.convert_image_to_jpeg_for_ai(image_data, max_quality=True)

        # Créer la data URI
        data_uri = ImageConverter.upload_to_temp_service(jpeg_data, 'jpeg')

        return data_uri

    except Exception as e:
        logger.debug(f"Échec conversion URL → Data URI: {url[:50]}...")
        return None

# 🚀 CACHE GLOBAL pour les conversions Data URI (évite de reconvertir les mêmes URLs)
_data_uri_cache = {}
_data_uri_cache_lock = threading.Lock()

def clear_data_uri_cache():
    """Nettoie le cache des conversions Data URI"""
    global _data_uri_cache
    with _data_uri_cache_lock:
        _data_uri_cache.clear()

def get_data_uri_cache_stats():
    """Retourne les statistiques du cache Data URI"""
    with _data_uri_cache_lock:
        return {
            "size": len(_data_uri_cache),
            "urls": list(_data_uri_cache.keys())[:10]  # Premières 10 URLs pour debug
        }

def convert_message_urls_to_data_uris(user_message: dict) -> dict:
    """
    Convertit toutes les URLs d'images dans un message en data URIs (VERSION SÉQUENTIELLE)
    Utilisé comme fallback quand OpenAI ne peut pas télécharger les URLs

    Args:
        user_message: Message utilisateur avec des image_url

    Returns:
        Message modifié avec data URIs
    """
    try:
        converted_count = 0
        failed_count = 0
        cached_count = 0

        for content_item in user_message.get("content", []):
            if content_item.get("type") == "image_url":
                original_url = content_item["image_url"]["url"]
                if not original_url.startswith("data:"):
                    with _data_uri_cache_lock:
                        if original_url in _data_uri_cache:
                            content_item["image_url"]["url"] = _data_uri_cache[original_url]
                            cached_count += 1
                            continue

                    data_uri = convert_url_to_data_uri(original_url)
                    if data_uri:
                        content_item["image_url"]["url"] = data_uri
                        with _data_uri_cache_lock:
                            _data_uri_cache[original_url] = data_uri
                        converted_count += 1
                    else:
                        failed_count += 1

        return user_message

    except Exception as e:
        logger.error(f"❌ Erreur conversion URLs: {e}")
        return user_message

async def convert_message_urls_to_data_uris_parallel(user_message: dict) -> dict:
    """
    🚀 VERSION PARALLÉLISÉE - Convertit toutes les URLs d'images en data URIs en parallèle
    Beaucoup plus rapide que la version séquentielle pour plusieurs images

    Args:
        user_message: Message utilisateur avec des image_url

    Returns:
        Message modifié avec data URIs
    """
    try:
        urls_to_convert = []
        content_items = []
        cached_count = 0

        for content_item in user_message.get("content", []):
            if content_item.get("type") == "image_url":
                original_url = content_item["image_url"]["url"]
                if not original_url.startswith("data:"):
                    with _data_uri_cache_lock:
                        if original_url in _data_uri_cache:
                            content_item["image_url"]["url"] = _data_uri_cache[original_url]
                            cached_count += 1
                            continue
                    urls_to_convert.append(original_url)
                    content_items.append(content_item)

        if not urls_to_convert:
            return user_message

        loop = asyncio.get_running_loop()
        conversion_tasks = [
            loop.run_in_executor(None, convert_url_to_data_uri, url)
            for url in urls_to_convert
        ]
        data_uris = await asyncio.gather(*conversion_tasks, return_exceptions=True)

        converted_count = 0
        failed_count = 0
        for url, content_item, data_uri in zip(urls_to_convert, content_items, data_uris):
            if isinstance(data_uri, Exception):
                failed_count += 1
            elif data_uri:
                content_item["image_url"]["url"] = data_uri
                with _data_uri_cache_lock:
                    _data_uri_cache[url] = data_uri
                converted_count += 1
            else:
                failed_count += 1

        return user_message

    except Exception as e:
        logger.error(f"❌ Erreur conversion parallèle: {e}")
        return user_message


def convert_message_urls_to_data_uris_sync(user_message: dict) -> dict:
    """
    🔄 VERSION SYNCHRONE - Convertit toutes les URLs d'images en data URIs
    Utilisée dans les fallbacks quand asyncio.run() n'est pas disponible (thread pool)

    Args:
        user_message: Message utilisateur avec des image_url

    Returns:
        Message modifié avec data URIs
    """
    try:
        converted_count = 0
        failed_count = 0
        cached_count = 0

        for content_item in user_message.get("content", []):
            if content_item.get("type") == "image_url":
                original_url = content_item["image_url"]["url"]
                if not original_url.startswith("data:"):
                    # Vérifier le cache
                    with _data_uri_cache_lock:
                        if original_url in _data_uri_cache:
                            content_item["image_url"]["url"] = _data_uri_cache[original_url]
                            cached_count += 1
                            continue

                    # Convertir (synchrone)
                    data_uri = convert_url_to_data_uri(original_url)
                    if data_uri:
                        content_item["image_url"]["url"] = data_uri
                        with _data_uri_cache_lock:
                            _data_uri_cache[original_url] = data_uri
                        converted_count += 1
                    else:
                        failed_count += 1

        logger.debug(f"🔄 Conversion sync: {converted_count} converties, {cached_count} cached, {failed_count} échouées")
        return user_message

    except Exception as e:
        logger.error(f"❌ Erreur conversion sync: {e}")
        return user_message


def analyze_images(input_data: InputData, parcours_type: str = "Voyageur", request_id: str = None) -> AnalyseResponse:
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

        # 🔄 TRAITEMENT DES IMAGES
        processed_checkin = process_pictures_list([pic.model_dump() for pic in input_data.checkin_pictures])
        processed_checkout = process_pictures_list([pic.model_dump() for pic in input_data.checkout_pictures])

        # Préparer le message avec les images valides uniquement
        user_message = {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Compare les PHOTOS DE RÉFÉRENCE (état attendu) avec les PHOTOS DE SORTIE (état actuel) de cette {input_data.nom}. Identifie ce qui manque, ce qui est endommagé, ou ce qui n'est pas conforme à la référence. Fournis une réponse JSON structurée.",
                    "reasoning": {
                        "effort": "high"
                    }
                },
            ]
        }

        # 📸 ÉTAPE 1: Ajouter les PHOTOS DE RÉFÉRENCE avec label explicite
        valid_checkin = []
        checkin_urls = []
        for photo in processed_checkin:
            normalized_photo_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_checkin.append(photo)
                checkin_urls.append(normalized_photo_url)

        # Ajouter le label AVANT les photos de référence
        if checkin_urls:
            user_message["content"].append({
                "type": "text",
                "text": f"📷 ═══ PHOTOS DE RÉFÉRENCE ({len(checkin_urls)} images) ═══\n⬇️ Ces images montrent l'ÉTAT ATTENDU - Comment le logement DOIT être:"
            })
            for i, url in enumerate(checkin_urls, 1):
                user_message["content"].append({
                    "type": "text",
                    "text": f"[RÉFÉRENCE {i}/{len(checkin_urls)}]"
                })
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": url, "detail": "high"}
                })

        # 📸 ÉTAPE 2: Ajouter les PHOTOS DE SORTIE avec label explicite
        valid_checkout = []
        checkout_urls = []
        for photo in processed_checkout:
            normalized_photo_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_checkout.append(photo)
                checkout_urls.append(normalized_photo_url)

        # Ajouter le label AVANT les photos de sortie
        if checkout_urls:
            user_message["content"].append({
                "type": "text",
                "text": f"📷 ═══ PHOTOS DE SORTIE ({len(checkout_urls)} images) ═══\n⬇️ Ces images montrent l'ÉTAT ACTUEL - Comment le logement EST maintenant:"
            })
            for i, url in enumerate(checkout_urls, 1):
                user_message["content"].append({
                    "type": "text",
                    "text": f"[SORTIE {i}/{len(checkout_urls)}]"
                })
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": url, "detail": "high"}
                })
        
        # Si aucune image valide, ajouter une note
        if len(valid_checkin) == 0 and len(valid_checkout) == 0:
            user_message["content"].append({
                "type": "text",
                "text": "⚠️ Aucune image disponible - Fournir une analyse générique basée sur le type de pièce uniquement."
            })

        # Construire le prompt dynamique avec le type de parcours
        dynamic_prompt = build_dynamic_prompt(input_data, parcours_type)

        # Compter les images pour le log résumé
        total_images = len([c for c in user_message['content'] if c['type'] == 'image_url'])

        # 🔗 ENVOI PARALLÈLE DU PAYLOAD VERS BUBBLE (pour debug)
        async def send_payload_to_bubble():
            """Envoyer le payload complet vers Bubble en parallèle"""
            try:
                # Détecter l'environnement et utiliser le bon endpoint
                current_environment = detect_environment()
                bubble_endpoint = get_bubble_debug_endpoint(current_environment)

                # Préparer le payload exact envoyé à OpenAI
                openai_payload = {
                    "model": OPENAI_MODEL,
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
                
                logger.debug(f"🔗 Envoi payload vers Bubble: {bubble_endpoint}")
                
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
                            logger.debug(f"✅ Payload envoyé à Bubble avec succès: {response_text[:100]}...")
                        else:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Bubble réponse non-200 ({response.status}): {error_text[:100]}...")
                            
            except asyncio.TimeoutError:
                logger.warning("⚠️ Timeout lors de l'envoi vers Bubble (analyse continue)")
            except Exception as e:
                logger.warning(f"⚠️ Erreur envoi vers Bubble: {e} (analyse continue)")
        
        # Lancer l'envoi vers Bubble en arrière-plan (non bloquant)
        # 🔒 Vérifier qu'un event loop est disponible avant de créer la tâche
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_payload_to_bubble())
        except RuntimeError:
            # Pas d'event loop (exécution dans un thread pool) - skip l'envoi Bubble
            logger.debug("⏭️ Skip envoi Bubble (pas d'event loop - exécution parallèle)")

        # 📝 LOG DES PROMPTS POUR LE SYSTÈME DE LOGS
        if request_id:
            logs_manager.add_prompt_log(
                request_id=request_id,
                prompt_type="System",
                prompt_content=dynamic_prompt,
                model=OPENAI_MODEL
            )

            # Log du message utilisateur (contient les images)
            user_message_text = ""
            if isinstance(user_message.get("content"), list):
                for content_item in user_message["content"]:
                    if content_item.get("type") == "text":
                        user_message_text += content_item.get("text", "")
                    elif content_item.get("type") == "image_url":
                        user_message_text += f"[IMAGE: {content_item['image_url'].get('url', 'N/A')[:100]}...]"
            else:
                user_message_text = str(user_message.get("content", ""))

            logs_manager.add_prompt_log(
                request_id=request_id,
                prompt_type="User",
                prompt_content=user_message_text,
                model=OPENAI_MODEL
            )

        # Faire l'appel API avec response_format et gestion d'erreurs robuste
        try:
            # 🚀 MIGRATION vers Responses API avec gpt-5.2-2025-12-11
            messages = [
                {
                    "role": "system",
                    "content": dynamic_prompt
                },
                user_message
            ]
            input_content = convert_chat_messages_to_responses_input(messages)

            response = client.responses.create(
                model=OPENAI_MODEL,
                input=input_content,
                text={"format": {"type": "json_object"}},
                max_output_tokens=20000,
                reasoning={"effort": "high"}
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de l'analyse: {error_str}")

            # 🔍 DEBUG: Vérifier le contenu de error_str
            error_str_lower = error_str.lower()
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'timeout while downloading': {'timeout while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'error while downloading': {'error while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'invalid_image_url': {'invalid_image_url' in error_str_lower}")

            # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
            if any(keyword in error_str_lower for keyword in [
                "error while downloading",
                "timeout while downloading",
                "invalid_image_url",
                "failed to download"
            ]):
                logger.warning("⚠️ Erreur de téléchargement d'image détectée, tentative avec Data URIs")

                try:
                    # 🔄 Convertir toutes les URLs en data URIs (version sync pour compatibilité thread pool)
                    user_message_with_data_uris = convert_message_urls_to_data_uris_sync(user_message.copy())

                    # Compter les images converties
                    data_uri_count = sum(
                        1 for c in user_message_with_data_uris.get("content", [])
                        if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                    )

                    logger.debug(f"🔄 Retry avec {data_uri_count} images en Data URI")

                    # Réessayer avec les data URIs
                    # 🚀 MIGRATION vers Responses API
                    messages = [
                        {
                            "role": "system",
                            "content": dynamic_prompt
                        },
                        user_message_with_data_uris
                    ]
                    input_content = convert_chat_messages_to_responses_input(messages)

                    response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=20000,
                        reasoning={"effort": "high"}
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
                        # 🚀 MIGRATION vers Responses API
                        messages = [
                            {
                                "role": "system",
                                "content": dynamic_prompt
                            },
                            fallback_message
                        ]
                        input_content = convert_chat_messages_to_responses_input(messages)

                        response = client.responses.create(
                            model=OPENAI_MODEL,
                            input=input_content,
                            text={"format": {"type": "json_object"}},
                            max_output_tokens=20000,
                            reasoning={"effort": "high"}
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
                                    severity="high",
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
                    # 🚀 MIGRATION vers Responses API
                    messages = [
                        {
                            "role": "system",
                            "content": dynamic_prompt
                        },
                        fallback_message
                    ]
                    input_content = convert_chat_messages_to_responses_input(messages)

                    response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=20000,
                        reasoning={"effort": "high"}
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
                                severity="high",
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
            # 🚀 MIGRATION: Extraction depuis Responses API
            response_content = response.output_text.strip() if hasattr(response, 'output_text') else str(response.output[0].content[0].text).strip()
            logger.info(f"📄 Réponse IA reçue: {len(response_content)} caractères")

            # 📝 LOG DE LA RÉPONSE POUR LE SYSTÈME DE LOGS
            if request_id:
                logs_manager.add_response_log(
                    request_id=request_id,
                    response_type="Analysis",
                    response_content=response_content,
                    model=OPENAI_MODEL,
                    tokens_used=extract_usage_tokens(response)
                )

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
            logger.debug(f"🔍 DEBUG - Réponse BRUTE de l'IA: {preliminary_issues_count} issues détectées")
            if preliminary_issues_count > 0:
                logger.debug(f"🔍 DEBUG - Premières issues brutes: {json.dumps(response_json.get('preliminary_issues', [])[:3], indent=2, ensure_ascii=False)}")
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
                logger.debug(f"✅ DEBUG - preliminary_issues valide: {len(response_json['preliminary_issues'])} issues conservées")
            
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


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTÈME DOUBLE-PASS : EXTRACTION D'INVENTAIRE + VÉRIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

INVENTORY_EXTRACTION_PROMPT = """🔍 PHASE 1 : EXTRACTION D'INVENTAIRE

Tu es un expert en inventaire visuel. Ta SEULE mission est d'identifier et lister TOUS les objets visibles sur les photos de RÉFÉRENCE (checkin).

⚠️ RÈGLES ABSOLUES :
1. Liste UNIQUEMENT les objets clairement visibles
2. Sois EXHAUSTIF - ne manque aucun objet
3. Donne une localisation PRÉCISE pour chaque objet
4. Catégorise chaque objet correctement

📦 CATÉGORIES D'OBJETS :
- furniture : meubles (lit, table, chaise, armoire, canapé...)
- decoration : décoration (cadre, vase, sculpture, plante, miroir...)
- electronic : électronique (TV, télécommande, lampe, réveil...)
- textile : textiles (coussin, couverture, rideau, tapis...)
- accessory : accessoires (poubelle, panier, porte-manteau...)
- appliance : électroménager (micro-ondes, bouilloire, grille-pain...)

🎯 IMPORTANCE :
- essential : objets fonctionnels indispensables (lit, frigo, TV, lampes...)
- important : objets utiles au quotidien (télécommande, miroir, poubelle...)
- decorative : objets purement décoratifs (vase, cadre, sculpture...)

📋 FORMAT DE RÉPONSE JSON :
{
    "piece_id": "ID_PIECE",
    "total_objects": NOMBRE,
    "objects": [
        {
            "object_id": "obj_001",
            "name": "Nom de l'objet",
            "location": "Localisation précise dans la pièce",
            "description": "Description visuelle détaillée",
            "category": "furniture|decoration|electronic|textile|accessory|appliance",
            "importance": "essential|important|decorative"
        }
    ]
}

🚫 NE PAS inclure :
- Les éléments fixes (murs, portes, fenêtres, prises)
- Les objets trop petits pour être vérifiés (stylos, clés...)
- Les consommables (papier toilette, savon...)
"""

INVENTORY_VERIFICATION_PROMPT = """🔎 PHASE 2 : VÉRIFICATION D'INVENTAIRE

Tu es un expert en vérification d'inventaire. Ta mission est de vérifier la PRÉSENCE de chaque objet de l'inventaire sur les photos de SORTIE (checkout).

📋 INVENTAIRE À VÉRIFIER :
{inventory_list}

⚠️ RÈGLES DE VÉRIFICATION :
1. Pour CHAQUE objet de l'inventaire, cherche-le sur TOUTES les photos de sortie
2. Vérifie sa présence à la localisation indiquée OU ailleurs dans la pièce
3. Si l'objet n'apparaît sur AUCUNE photo de sortie → status = "missing"
4. Si l'objet a changé de place → status = "moved"
5. Si l'objet est visiblement endommagé → status = "damaged"
6. Si l'objet est bien présent → status = "present"

🎯 SEUIL DE CONFIANCE :
- 95-100% : Certitude absolue (objet clairement visible ou clairement absent)
- 85-94% : Haute confiance (identification quasi certaine)
- 70-84% : Confiance moyenne (quelques doutes)
- <70% : Ne pas remonter (trop incertain)

📋 FORMAT DE RÉPONSE JSON :
{
    "piece_id": "ID_PIECE",
    "total_checked": NOMBRE,
    "missing_objects": [
        {
            "object_id": "obj_XXX",
            "name": "Nom",
            "location": "Dernière localisation connue",
            "status": "missing",
            "confidence": 95,
            "details": "Non visible sur aucune des X photos de sortie"
        }
    ],
    "moved_objects": [...],
    "present_objects": [...]
}

🚨 IMPORTANT : Sois TRÈS RIGOUREUX. Un objet est "missing" UNIQUEMENT s'il n'apparaît sur AUCUNE photo de sortie, même partiellement.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTÈME MULTI-MODÈLES OPENROUTER - CONSENSUS VOTING (5 modèles)
# ═══════════════════════════════════════════════════════════════════════════════

OPENROUTER_API_KEY = "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"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# 5 modèles de vision économiques pour le consensus
VISION_MODELS = [
    {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku", "weight": 1.2},  # Claude - prioritaire
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "weight": 1.0},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "weight": 1.0},
    {"id": "amazon/nova-2-lite-v1", "name": "Amazon Nova 2 Lite", "weight": 0.9},
    # ❌ Mistral Large 3 supprimé: ne supporte que 8 images max
]

MINIMUM_MODELS_FOR_CONSENSUS = 3  # Minimum 3 modèles doivent répondre
CONSENSUS_THRESHOLD = 2  # 2/4 pour valider une détection (assouplissement pour meilleure détection)

# 🔴 DÉSACTIVATION TEMPORAIRE DU SYSTÈME DOUBLE-PASS (OpenRouter)
# Mettre à True pour réactiver le système d'inventaire/vérification des objets manquants
DOUBLE_PASS_ENABLED = False


def call_openrouter_vision(
    model_id: str,
    system_prompt: str,
    user_content: list,
    model_name: str = ""
) -> dict:
    """
    Appeler un modèle de vision via OpenRouter API (synchrone avec requests)

    Args:
        model_id: ID du modèle OpenRouter (ex: "anthropic/claude-3-haiku")
        system_prompt: Prompt système
        user_content: Liste de contenu (texte + images)
        model_name: Nom du modèle pour les logs

    Returns:
        dict: {"success": bool, "model": str, "response": dict ou None, "error": str ou None}
    """
    import requests as req  # Utiliser requests au lieu de aiohttp (plus fiable)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://checkeasy.io",
        "X-Title": "CheckEasy Double-Pass"
    }

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": 8000
    }

    try:
        response = req.post(
            OPENROUTER_API_URL,
            headers=headers,
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            result = response.json()

            # 🆕 Supporter les deux formats de réponse OpenRouter
            content = None

            # Format 1: OpenAI-compatible (choices[].message.content)
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0].get("message", {}).get("content", "")

            # Format 2: Nouveau format OpenRouter (output[].content[].text)
            elif "output" in result and len(result["output"]) > 0:
                output_item = result["output"][0]
                if "content" in output_item and len(output_item["content"]) > 0:
                    content = output_item["content"][0].get("text", "")

            if content:
                try:
                    # 🆕 Nettoyer le contenu: supprimer les backticks markdown et texte avant JSON
                    cleaned_content = content.strip()

                    # Supprimer les backticks markdown
                    if cleaned_content.startswith("```"):
                        cleaned_content = cleaned_content.lstrip("`").lstrip("json").lstrip("`").strip()
                    if cleaned_content.endswith("```"):
                        cleaned_content = cleaned_content.rstrip("`").strip()

                    # 🆕 Supprimer le texte avant le JSON (chercher le premier "{")
                    json_start = cleaned_content.find("{")
                    if json_start > 0:
                        cleaned_content = cleaned_content[json_start:]

                    # 🆕 Supprimer le texte après le JSON (chercher le dernier "}")
                    json_end = cleaned_content.rfind("}")
                    if json_end >= 0:
                        cleaned_content = cleaned_content[:json_end + 1]

                    parsed = json.loads(cleaned_content)
                    logger.debug(f"✅ [OPENROUTER] {model_name} répondu avec succès")
                    return {"success": True, "model": model_id, "response": parsed, "error": None}
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ [OPENROUTER] {model_name} JSON invalide: {e}")
                    logger.warning(f"   Contenu brut: {content[:200]}...")
                    return {"success": False, "model": model_id, "response": None, "error": f"JSON invalide: {e}"}
            else:
                logger.warning(f"⚠️ [OPENROUTER] {model_name} réponse vide ou format inconnu")
                logger.warning(f"   Réponse brute: {str(result)[:300]}...")
                return {"success": False, "model": model_id, "response": None, "error": "Réponse vide"}
        else:
            error_text = response.text
            logger.warning(f"⚠️ [OPENROUTER] {model_name} erreur HTTP {response.status_code}: {error_text[:200]}")
            return {"success": False, "model": model_id, "response": None, "error": f"HTTP {response.status_code}"}

    except req.exceptions.Timeout:
        logger.warning(f"⚠️ [OPENROUTER] {model_name} timeout (120s)")
        return {"success": False, "model": model_id, "response": None, "error": "Timeout"}
    except Exception as e:
        logger.error(f"❌ [OPENROUTER] {model_name} erreur: {e}")
        return {"success": False, "model": model_id, "response": None, "error": str(e)}


def call_multi_models_parallel(
    system_prompt: str,
    user_content: list,
    phase_name: str = "Double-Pass"
) -> list:
    """
    Appeler les 5 modèles de vision en parallèle via OpenRouter (utilise ThreadPool)

    Args:
        system_prompt: Prompt système commun
        user_content: Liste de contenu (texte + images)
        phase_name: Nom de la phase pour les logs

    Returns:
        list: Liste des réponses réussies [{"model": str, "response": dict}, ...]
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError

    logger.debug(f"")
    logger.debug(f"      🔄 [MULTI-MODEL] {phase_name}")
    logger.debug(f"      📊 Appel parallèle de {len(VISION_MODELS)} modèles:")
    for model in VISION_MODELS:
        logger.debug(f"         • {model['name']} (poids: {model['weight']})")
    logger.debug(f"      ⏳ Attente des réponses (timeout: 120s par modèle)...")

    # Exécuter les appels en parallèle avec ThreadPoolExecutor
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                call_openrouter_vision,
                model["id"],
                system_prompt,
                user_content,
                model["name"]
            ): model for model in VISION_MODELS
        }

        for future in as_completed(futures, timeout=150):  # 150s timeout total
            model = futures[future]
            try:
                result = future.result(timeout=120)  # 120s timeout par modèle
                results.append((model, result))
            except FutureTimeoutError:
                logger.warning(f"         ⏱️ [MULTI-MODEL] {model['name']} TIMEOUT (120s)")
                results.append((model, {"success": False, "error": "Timeout (120s)"}))
            except Exception as e:
                logger.warning(f"         ❌ [MULTI-MODEL] {model['name']} exception: {e}")
                results.append((model, {"success": False, "error": str(e)}))

    # Filtrer les réponses réussies
    successful_responses = []
    logger.debug(f"      📋 Résultats:")
    for model, result in results:
        if result.get("success"):
            successful_responses.append({
                "model": result["model"],
                "model_name": model["name"],
                "weight": model["weight"],
                "response": result["response"]
            })
            logger.debug(f"         ✅ {model['name']}: OK")
        else:
            logger.warning(f"         ❌ {model['name']}: {result.get('error', 'Erreur inconnue')}")

    logger.debug(f"      ✅ {len(successful_responses)}/{len(VISION_MODELS)} modèles ont répondu avec succès")
    logger.debug(f"")
    return successful_responses


def aggregate_inventory_responses(responses: list, piece_id: str) -> InventoryExtractionResponse:
    """
    Agréger les réponses d'inventaire de plusieurs modèles (PHASE 1)

    Utilise un système de vote pondéré pour déterminer quels objets inclure.
    Un objet est inclus s'il est détecté par au moins 3 modèles sur 5.

    Args:
        responses: Liste des réponses des modèles
        piece_id: ID de la pièce

    Returns:
        InventoryExtractionResponse agrégée
    """
    logger.debug(f"      🔀 [AGGREGATE] Début agrégation...")

    if not responses:
        logger.warning("      ⚠️ [AGGREGATE] Aucune réponse à agréger")
        return InventoryExtractionResponse(piece_id=piece_id, total_objects=0, objects=[])

    logger.debug(f"      🔀 [AGGREGATE] Agrégation de {len(responses)} réponses d'inventaire...")

    # 🆕 DEBUG: Afficher ce que chaque modèle a retourné
    logger.debug(f"      📋 Détail des réponses:")
    for resp in responses:
        model_name = resp.get("model_name", "Unknown")
        raw_response = resp.get("response", {})
        objects = raw_response.get("objects", [])
        logger.debug(f"         📊 {model_name}: {len(objects)} objets détectés")
        if len(objects) > 0:
            obj_names = [obj.get('name', 'N/A') for obj in objects[:3]]
            logger.debug(f"            ✅ Exemples: {obj_names}")
        else:
            logger.warning(f"            ⚠️ Aucun objet détecté")

    # Collecter tous les objets avec leur fréquence de détection
    object_votes = {}  # clé: nom_objet_normalisé -> {count, weight_sum, best_description}

    logger.debug(f"      🔄 Collecte des votes...")
    try:
        for resp in responses:
            model_weight = resp.get("weight", 1.0)
            objects = resp.get("response", {}).get("objects", [])
            logger.debug(f"         Processing {len(objects)} objects from model...")

            for obj in objects:
                # Normaliser le nom pour le regroupement
                name = obj.get("name", "").lower().strip()
                if not name:
                    continue

                # Clé de regroupement (nom + localisation approximative)
                location = obj.get("location", "").lower().strip()
                key = f"{name}|{location[:30]}"  # Limiter la location pour le regroupement

                if key not in object_votes:
                    object_votes[key] = {
                        "count": 0,
                        "weight_sum": 0.0,
                        "examples": [],
                        "name": obj.get("name", ""),
                        "location": obj.get("location", ""),
                        "category": obj.get("category", "accessory"),
                        "importance": obj.get("importance", "decorative")
                    }

                object_votes[key]["count"] += 1
                object_votes[key]["weight_sum"] += model_weight
                object_votes[key]["examples"].append(obj)

        logger.debug(f"      ✅ Collecte terminée: {len(object_votes)} objets candidats")
    except Exception as e:
        logger.error(f"      ❌ Erreur lors de la collecte des votes: {e}")
        raise

    # Filtrer par consensus (au moins 3 détections ou poids suffisant)
    consensus_objects = []
    obj_counter = 1

    logger.debug(f"      🔍 Filtrage par consensus (seuil: {CONSENSUS_THRESHOLD}/5)...")
    try:
        for key, data in object_votes.items():
            # Consensus: détecté par au moins 3 modèles OU poids pondéré >= 2.5
            if data["count"] >= CONSENSUS_THRESHOLD or data["weight_sum"] >= 2.5:
                # Prendre la meilleure description (la plus longue)
                best_example = max(data["examples"], key=lambda x: len(x.get("description", "")))

                consensus_objects.append(InventoryObject(
                    object_id=f"obj_{obj_counter:03d}",
                    name=best_example.get("name", data["name"]),
                    location=best_example.get("location", data["location"]),
                    description=best_example.get("description", ""),
                    category=best_example.get("category", data["category"]),
                    importance=best_example.get("importance", data["importance"])
                ))
                obj_counter += 1
                logger.debug(f"         ✓ {data['name']} (votes: {data['count']}/5, poids: {data['weight_sum']:.1f})")

        logger.debug(f"      ✅ [AGGREGATE] {len(consensus_objects)} objets validés par consensus sur {len(object_votes)} candidats")
    except Exception as e:
        logger.error(f"      ❌ Erreur lors du filtrage par consensus: {e}")
        raise

    return InventoryExtractionResponse(
        piece_id=piece_id,
        total_objects=len(consensus_objects),
        objects=consensus_objects
    )


def aggregate_verification_responses(
    responses: list,
    piece_id: str,
    inventory: InventoryExtractionResponse
) -> InventoryVerificationResponse:
    """
    Agréger les réponses de vérification de plusieurs modèles (PHASE 2)

    Utilise un système de vote pour déterminer le statut de chaque objet.
    Un objet est considéré manquant/déplacé si au moins 3 modèles sur 5 le détectent ainsi.

    Args:
        responses: Liste des réponses des modèles
        piece_id: ID de la pièce
        inventory: Inventaire de référence (PHASE 1)

    Returns:
        InventoryVerificationResponse agrégée
    """
    if not responses:
        logger.warning("⚠️ [AGGREGATE] Aucune réponse de vérification à agréger")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[]
        )

    logger.debug(f"🔀 [AGGREGATE] Agrégation de {len(responses)} réponses de vérification...")

    # Collecter les votes pour chaque objet de l'inventaire
    object_status_votes = {}  # object_id -> {missing: count, moved: count, present: count, details: []}

    for resp in responses:
        model_weight = resp.get("weight", 1.0)

        # Traiter les objets manquants
        for obj in resp.get("response", {}).get("missing_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["missing"] += model_weight
            object_status_votes[obj_id]["details"].append(obj.get("details", ""))

        # Traiter les objets déplacés
        for obj in resp.get("response", {}).get("moved_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["moved"] += model_weight
            object_status_votes[obj_id]["details"].append(obj.get("details", ""))

        # Traiter les objets présents
        for obj in resp.get("response", {}).get("present_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["present"] += model_weight

    # Déterminer le statut final par consensus
    missing_objects = []
    moved_objects = []
    present_objects = []

    for obj_id, votes in object_status_votes.items():
        # Trouver le statut majoritaire
        max_votes = max(votes["missing"], votes["moved"], votes["present"])

        # Confidence basée sur le consensus
        total_votes = votes["missing"] + votes["moved"] + votes["present"]
        confidence = int((max_votes / total_votes) * 100) if total_votes > 0 else 50

        # Meilleur détail (le plus long)
        best_detail = max(votes["details"], key=len) if votes["details"] else ""

        result = ObjectVerificationResult(
            object_id=obj_id,
            name=votes["name"],
            location=votes["location"],
            status="unknown",
            confidence=confidence,
            details=best_detail
        )

        # Seuil de consensus: au moins 3 votes pondérés
        if votes["missing"] >= CONSENSUS_THRESHOLD and votes["missing"] == max_votes:
            result.status = "missing"
            if confidence >= 70:  # Seuil de confiance minimum
                missing_objects.append(result)
                logger.debug(f"   ❌ MANQUANT: {votes['name']} (votes: {votes['missing']:.1f}, conf: {confidence}%)")
        elif votes["moved"] >= CONSENSUS_THRESHOLD and votes["moved"] == max_votes:
            result.status = "moved"
            if confidence >= 70:
                moved_objects.append(result)
                logger.debug(f"   🔄 DÉPLACÉ: {votes['name']} (votes: {votes['moved']:.1f}, conf: {confidence}%)")
        else:
            result.status = "present"
            present_objects.append(result)

    logger.debug(f"✅ [AGGREGATE] Résultat: {len(missing_objects)} manquants, {len(moved_objects)} déplacés, {len(present_objects)} présents")

    return InventoryVerificationResponse(
        piece_id=piece_id,
        total_checked=len(object_status_votes),
        missing_objects=missing_objects,
        moved_objects=moved_objects,
        present_objects=present_objects
    )


# ═══════════════════════════════════════════════════════════════════════════════
# FIN SYSTÈME MULTI-MODÈLES OPENROUTER
# ═══════════════════════════════════════════════════════════════════════════════


def extract_inventory_from_images(piece_id: str, nom_piece: str, checkin_pictures: List[Picture]) -> InventoryExtractionResponse:
    """
    PHASE 1 : Extraire l'inventaire complet des objets visibles sur les photos checkin

    🆕 MULTI-MODÈLES: Utilise 5 modèles de vision via OpenRouter pour un consensus robuste
    """
    logger.debug(f"")
    logger.debug(f"{'='*80}")
    logger.debug(f"📦 PHASE 1 - EXTRACTION INVENTAIRE")
    logger.debug(f"{'='*80}")
    logger.debug(f"   📍 Pièce: {nom_piece} (ID: {piece_id})")
    logger.debug(f"   📸 Photos de référence: {len(checkin_pictures)}")
    logger.debug(f"   🔄 Mode MULTI-MODÈLES activé ({len(VISION_MODELS)} modèles)")
    logger.debug(f"   🎯 Seuil consensus: {CONSENSUS_THRESHOLD}/5 modèles")

    # 🔄 CONVERSION DES IMAGES - Utiliser le système de conversion existant
    logger.debug(f"   [ÉTAPE 1.1] 🔄 Conversion des images checkin pour compatibilité...")
    processed_pictures = process_pictures_list([pic.model_dump() for pic in checkin_pictures])
    logger.debug(f"   [ÉTAPE 1.1] ✅ {len(processed_pictures)}/{len(checkin_pictures)} images converties avec succès")

    if not processed_pictures:
        logger.error(f"   [ÉTAPE 1.1] ❌ Aucune image valide après conversion pour {piece_id}")
        return InventoryExtractionResponse(piece_id=piece_id, total_objects=0, objects=[])

    # 🆕 LIMITATION: Mistral supporte max 8 images
    MAX_IMAGES_FOR_MODELS = 8
    if len(processed_pictures) > MAX_IMAGES_FOR_MODELS:
        logger.warning(f"   [ÉTAPE 1.1] ⚠️ {len(processed_pictures)} images détectées, limitation à {MAX_IMAGES_FOR_MODELS} pour compatibilité Mistral")
        processed_pictures = processed_pictures[:MAX_IMAGES_FOR_MODELS]
        logger.debug(f"   [ÉTAPE 1.1] ✅ Limitation appliquée: {len(processed_pictures)} images utilisées")

    # Construire le message avec les images CONVERTIES
    user_content = [{"type": "text", "text": f"Pièce: {nom_piece} (ID: {piece_id})\n\nAnalyse les photos de RÉFÉRENCE suivantes et liste TOUS les objets visibles:"}]

    for processed_pic in processed_pictures:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": processed_pic["url"], "detail": "high"}
        })

    try:
        # 🆕 APPEL MULTI-MODÈLES EN PARALLÈLE (synchrone avec ThreadPool)
        logger.debug(f"   [ÉTAPE 1.2] 🔄 Appel parallèle des 5 modèles OpenRouter...")
        responses = call_multi_models_parallel(
            system_prompt=INVENTORY_EXTRACTION_PROMPT,
            user_content=user_content,
            phase_name="PHASE 1 - Inventaire"
        )
        logger.debug(f"   [ÉTAPE 1.2] ✅ {len(responses)}/5 modèles ont répondu avec succès")

        # Vérifier le minimum de réponses
        if len(responses) < MINIMUM_MODELS_FOR_CONSENSUS:
            logger.error(f"   [ÉTAPE 1.2] ❌ Seulement {len(responses)} modèles ont répondu (minimum: {MINIMUM_MODELS_FOR_CONSENSUS})")
            # Fallback vers OpenAI si pas assez de réponses
            logger.warning(f"   [ÉTAPE 1.2] 🔄 Fallback vers OpenAI GPT-4.1...")
            return _extract_inventory_fallback_openai(piece_id, nom_piece, user_content)

        # 🆕 AGRÉGATION PAR CONSENSUS
        logger.debug(f"   [ÉTAPE 1.3] 🔀 Agrégation des réponses par consensus...")
        result = aggregate_inventory_responses(responses, piece_id)
        logger.debug(f"   [ÉTAPE 1.3] ✅ Agrégation terminée: {result.total_objects} objets validés par consensus")
        logger.debug(f"")
        logger.debug(f"{'='*80}")
        logger.debug(f"✅ PHASE 1 TERMINÉE - {result.total_objects} objets inventoriés")
        logger.debug(f"{'='*80}")
        logger.debug(f"")

        return result

    except Exception as e:
        logger.error(f"   [ÉTAPE 1.X] ❌ Erreur extraction inventaire multi-modèles: {e}")
        # Fallback vers OpenAI
        logger.warning(f"   [ÉTAPE 1.X] 🔄 Fallback vers OpenAI GPT-4.1...")
        return _extract_inventory_fallback_openai(piece_id, nom_piece, user_content)


def _extract_inventory_fallback_openai(piece_id: str, nom_piece: str, user_content: list) -> InventoryExtractionResponse:
    """
    Fallback vers OpenAI si le système multi-modèles échoue
    """
    if client is None:
        logger.error("❌ Client OpenAI non disponible pour fallback")
        return InventoryExtractionResponse(piece_id=piece_id, total_objects=0, objects=[])

    try:
        # 🚀 MIGRATION vers Responses API
        messages = [
            {"role": "system", "content": INVENTORY_EXTRACTION_PROMPT},
            {"role": "user", "content": user_content}
        ]
        input_content = convert_chat_messages_to_responses_input(messages)

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=input_content,
            text={"format": {"type": "json_object"}},
            max_output_tokens=10000,
            reasoning={"effort": "medium"}
        )

        response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
        response_json = json.loads(response_text)

        # Parser les objets
        objects = []
        for obj in response_json.get("objects", []):
            try:
                objects.append(InventoryObject(
                    object_id=obj.get("object_id", f"obj_{len(objects)+1:03d}"),
                    name=obj.get("name", "Objet inconnu"),
                    location=obj.get("location", "Non spécifié"),
                    description=obj.get("description", ""),
                    category=obj.get("category", "accessory"),
                    importance=obj.get("importance", "decorative")
                ))
            except Exception as e:
                logger.warning(f"⚠️ Objet invalide ignoré: {e}")

        logger.debug(f"✅ PHASE 1 terminée (FALLBACK OpenAI): {len(objects)} objets inventoriés")

        return InventoryExtractionResponse(
            piece_id=piece_id,
            total_objects=len(objects),
            objects=objects
        )

    except Exception as e:
        logger.error(f"❌ Erreur fallback OpenAI: {e}")
        return InventoryExtractionResponse(piece_id=piece_id, total_objects=0, objects=[])


def verify_inventory_on_checkout(
    piece_id: str,
    inventory: InventoryExtractionResponse,
    checkout_pictures: List[Picture]
) -> InventoryVerificationResponse:
    """
    PHASE 2 : Vérifier chaque objet de l'inventaire sur les photos de sortie

    🆕 MULTI-MODÈLES: Utilise 5 modèles de vision via OpenRouter pour un consensus robuste
    """
    logger.debug(f"")
    logger.debug(f"{'='*80}")
    logger.debug(f"🔎 PHASE 2 - VÉRIFICATION INVENTAIRE")
    logger.debug(f"{'='*80}")
    logger.debug(f"   📍 Pièce ID: {piece_id}")
    logger.debug(f"   📦 Objets à vérifier: {inventory.total_objects}")
    logger.debug(f"   📸 Photos de sortie: {len(checkout_pictures)}")
    logger.debug(f"   🔄 Mode MULTI-MODÈLES activé ({len(VISION_MODELS)} modèles)")
    logger.debug(f"   🎯 Seuil consensus: {CONSENSUS_THRESHOLD}/5 modèles")

    if inventory.total_objects == 0:
        logger.warning(f"   ⚠️ Aucun objet à vérifier (inventaire vide)")
        logger.debug(f"{'='*80}")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[]
        )

    # 🔄 CONVERSION DES IMAGES - Utiliser le système de conversion existant
    logger.debug(f"   🔄 Conversion des images checkout pour compatibilité...")
    processed_pictures = process_pictures_list([pic.model_dump() for pic in checkout_pictures])
    logger.debug(f"   ✅ {len(processed_pictures)} images converties avec succès")

    if not processed_pictures:
        logger.warning(f"⚠️ Aucune image checkout valide après conversion pour {piece_id}")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[]
        )

    # Construire la liste d'inventaire formatée
    inventory_list = "\n".join([
        f"- [{obj.object_id}] {obj.name} | Localisation: {obj.location} | {obj.importance.upper()}"
        for obj in inventory.objects
    ])

    system_prompt = INVENTORY_VERIFICATION_PROMPT.replace("{inventory_list}", inventory_list)

    # Construire le message avec les images de sortie CONVERTIES
    user_content = [{"type": "text", "text": f"Pièce ID: {piece_id}\n\nVérifie la présence de chaque objet de l'inventaire sur ces photos de SORTIE:"}]

    for processed_pic in processed_pictures:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": processed_pic["url"], "detail": "high"}
        })

    try:
        # 🆕 APPEL MULTI-MODÈLES EN PARALLÈLE (synchrone avec ThreadPool)
        logger.debug(f"   [ÉTAPE 2.1] 🔄 Appel parallèle des 5 modèles OpenRouter...")
        responses = call_multi_models_parallel(
            system_prompt=system_prompt,
            user_content=user_content,
            phase_name="PHASE 2 - Vérification"
        )
        logger.debug(f"   [ÉTAPE 2.1] ✅ {len(responses)}/5 modèles ont répondu avec succès")

        # Vérifier le minimum de réponses
        if len(responses) < MINIMUM_MODELS_FOR_CONSENSUS:
            logger.error(f"   [ÉTAPE 2.1] ❌ Seulement {len(responses)} modèles ont répondu (minimum: {MINIMUM_MODELS_FOR_CONSENSUS})")
            # Fallback vers OpenAI si pas assez de réponses
            logger.warning(f"   [ÉTAPE 2.1] 🔄 Fallback vers OpenAI GPT-4.1...")
            return _verify_inventory_fallback_openai(piece_id, inventory, system_prompt, user_content)

        # 🆕 AGRÉGATION PAR CONSENSUS
        logger.debug(f"   [ÉTAPE 2.2] 🔀 Agrégation des réponses par consensus...")
        result = aggregate_verification_responses(responses, piece_id, inventory)
        logger.debug(f"   [ÉTAPE 2.2] ✅ Agrégation terminée:")
        logger.debug(f"      - Objets manquants: {len(result.missing_objects)}")
        logger.debug(f"      - Objets déplacés: {len(result.moved_objects)}")
        logger.debug(f"      - Objets présents: {len(result.present_objects)}")
        logger.debug(f"")
        logger.debug(f"{'='*80}")
        logger.debug(f"✅ PHASE 2 TERMINÉE - {len(result.missing_objects)} manquants détectés")
        logger.debug(f"{'='*80}")
        logger.debug(f"")

        return result

    except Exception as e:
        logger.error(f"   [ÉTAPE 2.X] ❌ Erreur vérification inventaire multi-modèles: {e}")
        # Fallback vers OpenAI
        logger.warning(f"   [ÉTAPE 2.X] 🔄 Fallback vers OpenAI GPT-4.1...")
        return _verify_inventory_fallback_openai(piece_id, inventory, system_prompt, user_content)


def _verify_inventory_fallback_openai(
    piece_id: str,
    inventory: InventoryExtractionResponse,
    system_prompt: str,
    user_content: list
) -> InventoryVerificationResponse:
    """
    Fallback vers OpenAI si le système multi-modèles échoue
    """
    if client is None:
        logger.error("❌ Client OpenAI non disponible pour fallback")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[]
        )

    try:
        # 🚀 MIGRATION vers Responses API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        input_content = convert_chat_messages_to_responses_input(messages)

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=input_content,
            text={"format": {"type": "json_object"}},
            max_output_tokens=10000,
            reasoning={"effort": "medium"}
        )

        response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
        response_json = json.loads(response_text)

        # Parser les résultats
        missing = []
        moved = []
        present = []

        for obj in response_json.get("missing_objects", []):
            if obj.get("confidence", 0) >= 85:
                missing.append(ObjectVerificationResult(
                    object_id=obj.get("object_id", ""),
                    name=obj.get("name", ""),
                    location=obj.get("location", ""),
                    status="missing",
                    confidence=obj.get("confidence", 90),
                    details=obj.get("details", "")
                ))

        for obj in response_json.get("moved_objects", []):
            if obj.get("confidence", 0) >= 85:
                moved.append(ObjectVerificationResult(
                    object_id=obj.get("object_id", ""),
                    name=obj.get("name", ""),
                    location=obj.get("location", ""),
                    status="moved",
                    confidence=obj.get("confidence", 90),
                    details=obj.get("details", "")
                ))

        for obj in response_json.get("present_objects", []):
            present.append(ObjectVerificationResult(
                object_id=obj.get("object_id", ""),
                name=obj.get("name", ""),
                location=obj.get("location", ""),
                status="present",
                confidence=obj.get("confidence", 95),
                details=obj.get("details", "Présent")
            ))

        logger.debug(f"✅ PHASE 2 terminée (FALLBACK OpenAI): {len(missing)} manquants, {len(moved)} déplacés")

        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=inventory.total_objects,
            missing_objects=missing,
            moved_objects=moved,
            present_objects=present
        )

    except Exception as e:
        logger.error(f"❌ Erreur fallback OpenAI: {e}")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[]
        )


def convert_inventory_to_issues(verification: InventoryVerificationResponse) -> List[Probleme]:
    """
    Convertir les résultats de vérification d'inventaire en issues standard
    """
    issues = []

    # Objets manquants → missing_item
    for obj in verification.missing_objects:
        # Déterminer la sévérité selon l'importance de l'objet
        severity = "high" if "essential" in obj.details.lower() or obj.confidence >= 95 else "medium"

        issues.append(Probleme(
            description=f"Objet manquant: {obj.name} - {obj.location}. {obj.details}",
            category="missing_item",
            severity=severity,
            confidence=obj.confidence
        ))

    # Objets déplacés → positioning (sévérité basse)
    for obj in verification.moved_objects:
        issues.append(Probleme(
            description=f"Objet déplacé: {obj.name} - {obj.details}",
            category="positioning",
            severity="low",
            confidence=obj.confidence
        ))

    logger.debug(f"🔄 Conversion: {len(issues)} issues générées depuis l'inventaire")
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# FIN SYSTÈME DOUBLE-PASS
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/extract-inventory", response_model=InventoryExtractionResponse)
async def extract_inventory_endpoint(input_data: RoomClassificationInput):
    """
    PHASE 1 du système Double-Pass : Extraire l'inventaire des objets visibles

    Analyse les photos checkin et retourne une liste structurée de tous les objets détectés.
    """
    logger.debug(f"📦 API /extract-inventory - Pièce: {input_data.nom} ({input_data.piece_id})")

    return extract_inventory_from_images(
        piece_id=input_data.piece_id,
        nom_piece=input_data.nom,
        checkin_pictures=input_data.checkin_pictures
    )


class VerifyInventoryInput(BaseModel):
    piece_id: str
    inventory: InventoryExtractionResponse
    checkout_pictures: List[Picture]


@app.post("/verify-inventory", response_model=InventoryVerificationResponse)
async def verify_inventory_endpoint(input_data: VerifyInventoryInput):
    """
    PHASE 2 du système Double-Pass : Vérifier les objets sur les photos de sortie

    Prend l'inventaire extrait en Phase 1 et vérifie chaque objet sur les photos checkout.
    """
    logger.debug(f"🔎 API /verify-inventory - {input_data.inventory.total_objects} objets à vérifier")

    return verify_inventory_on_checkout(
        piece_id=input_data.piece_id,
        inventory=input_data.inventory,
        checkout_pictures=input_data.checkout_pictures
    )


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
    # 🔍 TRACKING DES LOGS EN TEMPS RÉEL
    request_id = str(uuid.uuid4())
    logs_manager.start_request(
        request_id=request_id,
        endpoint="/analyze",
        data={"piece_id": input_data.piece_id, "nom": input_data.nom}
    )

    # Ajouter une étape pour l'analyse
    step_id = logs_manager.add_step(
        request_id=request_id,
        step_name=f"Analyse de {input_data.nom}",
        step_type="analyze",
        metadata={"piece_id": input_data.piece_id}
    )

    logs_manager.add_log(
        request_id=request_id,
        level="INFO",
        message=f"🔍 Démarrage de l'analyse pour {input_data.nom}"
    )

    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"

        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"📋 Type de parcours: {parcours_type}"
        )

        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"🖼️ Images: {len(input_data.checkin_pictures)} checkin, {len(input_data.checkout_pictures)} checkout"
        )

        # Capturer les informations de prompt avant l'analyse
        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"📋 Critères: {len(input_data.elements_critiques)} critiques, {len(input_data.points_ignorables)} ignorables, {len(input_data.defauts_frequents)} défauts"
        )

        result = analyze_images(input_data, parcours_type, request_id=request_id)

        # Marquer l'étape comme terminée avec succès
        logs_manager.complete_step(
            request_id=request_id,
            step_id=step_id,
            status="success",
            result={"issues_count": len(result.preliminary_issues)}
        )

        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"✅ Analyse terminée: {len(result.preliminary_issues)} issues détectées"
        )

        # Marquer la requête comme terminée
        logs_manager.complete_request(
            request_id=request_id,
            status="success"
        )

        return result

    except Exception as e:
        logger.error(f"Erreur lors de la requête: {str(e)}")

        # Marquer l'étape comme échouée
        logs_manager.complete_step(
            request_id=request_id,
            step_id=step_id,
            status="error"
        )

        logs_manager.add_log(
            request_id=request_id,
            level="ERROR",
            message=f"❌ Erreur: {str(e)}"
        )

        # Marquer la requête comme échouée
        logs_manager.complete_request(
            request_id=request_id,
            status="error"
        )

        raise HTTPException(status_code=500, detail=str(e))

def verify_checkin_checkout_coherence(
    checkin_pictures: List[Picture],
    checkout_pictures: List[Picture],
    piece_id: str,
    parcours_type: str = "Voyageur"
) -> dict:
    """
    Vérifie la cohérence entre les photos checkin et checkout.
    Détecte si les photos montrent des pièces différentes.

    Args:
        checkin_pictures: Photos AVANT (état de référence)
        checkout_pictures: Photos APRÈS (état final)
        piece_id: ID de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        dict: {
            "is_coherent": bool,  # True si les photos montrent la même pièce
            "checkin_room_type": str,  # Type détecté pour checkin
            "checkout_room_type": str,  # Type détecté pour checkout
            "message": str  # Message explicatif
        }
    """
    try:
        # Si pas de checkout_pictures, considérer comme cohérent
        if not checkout_pictures or len(checkout_pictures) == 0:
            logger.debug(f"🔍 [COHERENCE] Pas de checkout_pictures → Cohérence OK (pas de comparaison possible)")
            return {
                "is_coherent": True,
                "checkin_room_type": "unknown",
                "checkout_room_type": "none",
                "message": "Pas de photos checkout à comparer"
            }

        # Si pas de checkin_pictures, considérer comme cohérent
        if not checkin_pictures or len(checkin_pictures) == 0:
            logger.debug(f"🔍 [COHERENCE] Pas de checkin_pictures → Cohérence OK (pas de comparaison possible)")
            return {
                "is_coherent": True,
                "checkin_room_type": "none",
                "checkout_room_type": "unknown",
                "message": "Pas de photos checkin à comparer"
            }

        logger.info(f"🔍 [COHERENCE] Vérification cohérence checkin/checkout pour pièce {piece_id}")

        # Charger les templates selon le type de parcours
        room_templates = load_room_templates(parcours_type)

        # Créer le prompt de classification
        prompts_config = load_prompts_config(parcours_type)
        classify_room_config = prompts_config.get("prompts", {}).get("classify_room", {})

        room_types_list = list(room_templates["room_types"].keys())
        room_descriptions = []
        for room_key, room_info in room_templates["room_types"].items():
            room_descriptions.append(f"- {room_key}: {room_info['name']} {room_info['icon']}")

        variables = {
            "room_types_list": ', '.join(room_types_list),
            "room_descriptions_list": '\n'.join(room_descriptions)
        }

        classification_prompt = build_full_prompt_from_config(classify_room_config, variables)

        # 1️⃣ CLASSIFIER LES CHECKIN PICTURES
        logger.debug(f"🔍 [COHERENCE] Étape 1/2 - Classification des CHECKIN pictures...")
        checkin_pictures_raw = [pic.model_dump() for pic in checkin_pictures]
        checkin_processed = process_pictures_list(checkin_pictures_raw)

        checkin_user_message = {
            "role": "user",
            "content": [{"type": "text", "text": classification_prompt}]
        }

        for photo in checkin_processed:
            normalized_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_url) and not normalized_url.startswith('data:image/gif;base64,R0lGOD'):
                checkin_user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": normalized_url, "detail": "high"}
                })

        # Appel OpenAI pour checkin
        checkin_response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[checkin_user_message],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_completion_tokens=500
        )

        checkin_result = json.loads(checkin_response.choices[0].message.content)
        checkin_room_type = checkin_result.get("room_type", "autre")
        logger.debug(f"✅ [COHERENCE] Checkin classifié comme: {checkin_room_type}")

        # 2️⃣ CLASSIFIER LES CHECKOUT PICTURES
        logger.debug(f"🔍 [COHERENCE] Étape 2/2 - Classification des CHECKOUT pictures...")
        checkout_pictures_raw = [pic.model_dump() for pic in checkout_pictures]
        checkout_processed = process_pictures_list(checkout_pictures_raw)

        checkout_user_message = {
            "role": "user",
            "content": [{"type": "text", "text": classification_prompt}]
        }

        for photo in checkout_processed:
            normalized_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_url) and not normalized_url.startswith('data:image/gif;base64,R0lGOD'):
                checkout_user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": normalized_url, "detail": "high"}
                })

        # Appel OpenAI pour checkout
        checkout_response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[checkout_user_message],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_completion_tokens=500
        )

        checkout_result = json.loads(checkout_response.choices[0].message.content)
        checkout_room_type = checkout_result.get("room_type", "autre")
        logger.debug(f"✅ [COHERENCE] Checkout classifié comme: {checkout_room_type}")

        # 3️⃣ COMPARER LES DEUX CLASSIFICATIONS
        # Définir les groupes de pièces compatibles (ex: salon/cuisine ouverte = même pièce)
        COMPATIBLE_ROOMS = {
            # Pièces de vie ouvertes
            "salon": ["cuisine", "salon_cuisine", "sejour"],
            "cuisine": ["salon", "salon_cuisine", "sejour"],
            "salon_cuisine": ["salon", "cuisine", "sejour"],
            "sejour": ["salon", "cuisine", "salon_cuisine"],
            # Chambres / Bureaux
            "chambre": ["bureau"],
            "bureau": ["chambre"],
            # Salles de bain / Salles d'eau (toutes compatibles entre elles - angle de vue peut masquer WC)
            "salle_de_bain": ["salle_d_eau", "salle_de_bain_et_toilettes", "salle_d_eau_et_wc"],
            "salle_d_eau": ["salle_de_bain", "salle_de_bain_et_toilettes", "salle_d_eau_et_wc"],
            "salle_de_bain_et_toilettes": ["salle_de_bain", "salle_d_eau", "salle_d_eau_et_wc"],
            "salle_d_eau_et_wc": ["salle_de_bain", "salle_d_eau", "salle_de_bain_et_toilettes"],
        }

        # Considérer comme incohérent si les types sont différents ET ne sont pas "autre" ET pas compatibles
        is_coherent = True
        message = "Photos cohérentes"

        if checkin_room_type != checkout_room_type:
            # Vérifier si les types sont compatibles (ex: salon et cuisine ouverte)
            compatible_types = COMPATIBLE_ROOMS.get(checkin_room_type, [])

            if checkout_room_type in compatible_types:
                # ✅ Types différents mais compatibles (ex: salon/cuisine ouverte)
                is_coherent = True
                message = f"Types compatibles: {checkin_room_type} et {checkout_room_type} (pièce ouverte)"
                logger.info(f"✅ [COHERENCE] Types différents mais COMPATIBLES: {checkin_room_type} / {checkout_room_type}")
                logger.info(f"✅ [COHERENCE] Interprété comme une pièce de vie ouverte (salon/cuisine)")
            elif checkin_room_type == "autre" or checkout_room_type == "autre":
                # Si l'un des deux est "autre", tolérer (classification incertaine)
                logger.debug(f"🔍 [COHERENCE] Types différents mais l'un est 'autre' → Toléré (checkin={checkin_room_type}, checkout={checkout_room_type})")
            else:
                is_coherent = False
                message = f"Incohérence détectée: checkin={checkin_room_type}, checkout={checkout_room_type}"
                logger.warning(f"⚠️ [COHERENCE] ═══════════════════════════════════════")
                logger.warning(f"⚠️ [COHERENCE] INCOHÉRENCE DÉTECTÉE!")
                logger.warning(f"⚠️ [COHERENCE] Pièce ID: {piece_id}")
                logger.warning(f"⚠️ [COHERENCE] Checkin photos → {checkin_room_type}")
                logger.warning(f"⚠️ [COHERENCE] Checkout photos → {checkout_room_type}")
                logger.warning(f"⚠️ [COHERENCE] Les photos ne montrent PAS la même pièce!")
                logger.warning(f"⚠️ [COHERENCE] ═══════════════════════════════════════")

        return {
            "is_coherent": is_coherent,
            "checkin_room_type": checkin_room_type,
            "checkout_room_type": checkout_room_type,
            "message": message
        }

    except Exception as e:
        logger.error(f"❌ [COHERENCE] Erreur lors de la vérification: {e}")
        # En cas d'erreur, considérer comme cohérent pour ne pas bloquer
        return {
            "is_coherent": True,
            "checkin_room_type": "error",
            "checkout_room_type": "error",
            "message": f"Erreur lors de la vérification: {str(e)}"
        }

def classify_room_type(input_data: RoomClassificationInput, parcours_type: str = "Voyageur", request_id: str = None) -> RoomClassificationResponse:
    """
    Classifier le type de pièce à partir des images et retourner les critères de vérification

    Args:
        input_data: Données d'entrée pour la classification
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")
        request_id: ID de la requête pour le tracking des logs

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
        logger.debug(f"🖼️ Traitement des images pour classification de la pièce {input_data.piece_id}")

        # 🎯 IMPORTANT: Utiliser UNIQUEMENT les checkin_pictures (photos AVANT) pour la classification
        # Les photos AVANT représentent l'état de référence de la pièce, sans désordre ou objets manquants
        logger.debug(f"📸 Classification basée UNIQUEMENT sur les checkin_pictures (photos AVANT)")
        checkin_pictures_raw = [pic.model_dump() for pic in input_data.checkin_pictures]
        all_pictures_processed = process_pictures_list(checkin_pictures_raw)

        logger.debug(f"✅ Traitement terminé: {len(all_pictures_processed)} images checkin pour classification")

        # 🔍 VÉRIFICATION DE COHÉRENCE CHECKIN/CHECKOUT
        # Vérifier si les photos checkin et checkout montrent la même pièce
        coherence_check = verify_checkin_checkout_coherence(
            checkin_pictures=input_data.checkin_pictures,
            checkout_pictures=input_data.checkout_pictures,
            piece_id=input_data.piece_id,
            parcours_type=parcours_type
        )

        # Si incohérence détectée, retourner immédiatement une erreur wrong_room
        if not coherence_check["is_coherent"]:
            logger.error(f"🚫 INCOHÉRENCE DÉTECTÉE entre checkin et checkout!")
            logger.error(f"   📸 Checkin classifié comme: {coherence_check['checkin_room_type']}")
            logger.error(f"   📸 Checkout classifié comme: {coherence_check['checkout_room_type']}")
            logger.error(f"   ⚠️ Les photos ne montrent pas la même pièce!")

            # Retourner une réponse wrong_room
            return RoomClassificationResponse(
                piece_id=input_data.piece_id,
                room_type="wrong_room",
                room_name="Photos incohérentes",
                room_icon="⚠️",
                confidence=95,
                is_valid_room=False,
                validation_message=f"Les photos checkin et checkout montrent des pièces différentes: {coherence_check['checkin_room_type']} vs {coherence_check['checkout_room_type']}",
                verifications=RoomVerifications(
                    elements_critiques=["Vérifier que les photos correspondent à la même pièce"],
                    points_ignorables=[],
                    defauts_frequents=["Photos de pièces différentes"]
                )
            )
        else:
            logger.debug(f"✅ [COHERENCE] Photos checkin/checkout cohérentes: {coherence_check['message']}")

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
            logger.debug(f"🔍 URL avant normalisation: '{photo['url']}'")
            logger.debug(f"�� URL après normalisation: '{normalized_photo_url}'")

            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_images.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": normalized_photo_url,  # ✅ Utiliser l'URL normalisée
                        "detail": "high"
                    }
                })
                logger.debug(f"✅ CLASSIFICATION - Image ajoutée au payload OpenAI: {normalized_photo_url}")
            else:
                logger.warning(f"⚠️ CLASSIFICATION - Image invalide ignorée: {normalized_photo_url}")
        
        logger.debug(f"📷 Images valides envoyées à OpenAI: {len(valid_images)}/{len(all_pictures_processed)}")
        
        # Si aucune image valide, ajouter une note et adapter le prompt
        if len(valid_images) == 0:
            user_message["content"].append({
                "type": "text",
                "text": f"⚠️ Aucune image disponible - Classification basée uniquement sur le nom de la pièce: '{input_data.nom}'. Si le nom n'est pas fourni ou peu informatif, utiliser 'autre' avec une confiance faible."
            })
        
        # 🔍 PAYLOAD OPENAI - CLASSIFICATION
        logger.debug(f"🤖 ═══ PAYLOAD CLASSIFICATION → OPENAI ═══")
        prompt_text = next((c['text'] for c in user_message['content'] if c['type'] == 'text'), "Aucun prompt")
        logger.debug(f"🤖 PROMPT: {prompt_text[:200]}...")
        logger.debug(f"🤖 IMAGES: {len([c for c in user_message['content'] if c['type'] == 'image_url'])} images")
        logger.debug(f"🤖 ════════════════════════════════════════")

        # 🔗 ENVOI PARALLÈLE DU PAYLOAD DE CLASSIFICATION VERS BUBBLE
        async def send_classification_payload_to_bubble():
            """Envoyer le payload de classification vers Bubble en parallèle"""
            try:
                # Détecter l'environnement et utiliser le bon endpoint
                current_environment = detect_environment()
                bubble_endpoint = get_bubble_debug_endpoint(current_environment)

                # Extraire le texte du prompt de classification
                classification_text = ""
                for content in user_message['content']:
                    if content['type'] == 'text':
                        classification_text = content['text']
                        break
                
                # Préparer le payload exact envoyé à OpenAI pour la classification
                openai_payload = {
                    "model": OPENAI_MODEL,
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
                
                logger.debug(f"🔗 Envoi payload CLASSIFICATION vers Bubble: {bubble_endpoint}")
                
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
                            logger.debug(f"✅ Payload CLASSIFICATION envoyé à Bubble: {response_text[:100]}...")
                        else:
                            error_text = await response.text()
                            logger.warning(f"⚠️ Bubble CLASSIFICATION réponse non-200 ({response.status}): {error_text[:100]}...")
                            
            except asyncio.TimeoutError:
                logger.warning("⚠️ Timeout lors de l'envoi CLASSIFICATION vers Bubble (classification continue)")
            except Exception as e:
                logger.warning(f"⚠️ Erreur envoi CLASSIFICATION vers Bubble: {e} (classification continue)")
        
        # Lancer l'envoi vers Bubble en arrière-plan (non bloquant)
        # 🔒 Vérifier qu'un event loop est disponible avant de créer la tâche
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(send_classification_payload_to_bubble())
        except RuntimeError:
            # Pas d'event loop (exécution dans un thread pool) - skip l'envoi Bubble
            logger.debug("⏭️ Skip envoi Bubble classification (pas d'event loop - exécution parallèle)")

        # 📝 LOG DES PROMPTS POUR LE SYSTÈME DE LOGS (Classification)
        if request_id:
            # Extraire le texte du prompt
            user_text = ""
            for content in user_message['content']:
                if content['type'] == 'text':
                    user_text = content['text']
                    break

            logs_manager.add_prompt_log(
                request_id=request_id,
                prompt_type="Classification",
                prompt_content=user_text,
                model=OPENAI_MODEL
            )

        # Appel à l'API OpenAI avec gestion d'erreurs robuste
        try:
            # 🚀 MIGRATION vers Responses API
            input_content = convert_chat_messages_to_responses_input([user_message])

            response = client.responses.create(
                model=OPENAI_MODEL,
                input=input_content,
                text={"format": {"type": "json_object"}},
                max_output_tokens=1000,
                reasoning={"effort": "low"}
            )
        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ Erreur OpenAI lors de la classification: {error_str}")

            # 🔍 DEBUG: Vérifier le contenu de error_str
            error_str_lower = error_str.lower()
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'timeout while downloading': {'timeout while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'error while downloading': {'error while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'invalid_image_url': {'invalid_image_url' in error_str_lower}")

            # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
            if any(keyword in error_str_lower for keyword in [
                "error while downloading",
                "timeout while downloading",
                "invalid_image_url",
                "failed to download"
            ]):
                logger.warning("⚠️ Erreur de téléchargement d'image détectée, tentative avec Data URIs")

                try:
                    # 🔄 Convertir toutes les URLs en data URIs (version sync pour compatibilité thread pool)
                    user_message_with_data_uris = convert_message_urls_to_data_uris_sync(user_message.copy())

                    # Compter les images converties
                    data_uri_count = sum(
                        1 for c in user_message_with_data_uris.get("content", [])
                        if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                    )

                    logger.debug(f"🔄 Retry classification avec {data_uri_count} images en Data URI")

                    # Réessayer avec les data URIs
                    # 🚀 MIGRATION vers Responses API
                    input_content = convert_chat_messages_to_responses_input([user_message_with_data_uris])

                    response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=1000,
                        reasoning={"effort": "low"}
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
                        # 🚀 MIGRATION vers Responses API
                        input_content = convert_chat_messages_to_responses_input([fallback_message])

                        response = client.responses.create(
                            model=OPENAI_MODEL,
                            input=input_content,
                            text={"format": {"type": "json_object"}},
                            max_output_tokens=1000,
                            reasoning={"effort": "low"}
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
                            is_valid_room=True,
                            validation_message="Classification par défaut (erreur technique)",
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
                    # 🚀 MIGRATION vers Responses API
                    input_content = convert_chat_messages_to_responses_input([fallback_message])

                    response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=1000,
                        reasoning={"effort": "low"}
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
                        is_valid_room=True,
                        validation_message="Classification par défaut (erreur technique)",
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
        # 🚀 MIGRATION: Extraction depuis Responses API
        response_content = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
        if response_content is None:
            logger.error("❌ Réponse OpenAI vide")
            raise ValueError("Réponse OpenAI vide")

        response_content = response_content.strip()
        logger.info(f"📄 Réponse brute de classification (longueur: {len(response_content)} caractères)")
        logger.info(f"📄 Contenu: {response_content[:500]}...")  # Afficher les 500 premiers caractères

        # 📝 LOG DE LA RÉPONSE POUR LE SYSTÈME DE LOGS (Classification)
        if request_id:
            logs_manager.add_response_log(
                request_id=request_id,
                response_type="Classification",
                response_content=response_content,
                model=OPENAI_MODEL,
                tokens_used=extract_usage_tokens(response)
            )

        # 🔧 NETTOYAGE ROBUSTE DU JSON
        # GPT-5 mini peut retourner du texte avant/après le JSON
        try:
            # Essayer de trouver le JSON entre accolades
            start_idx = response_content.find('{')
            end_idx = response_content.rfind('}')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_content = response_content[start_idx:end_idx+1]
                logger.debug(f"✂️ JSON extrait (de position {start_idx} à {end_idx})")
                classification_result = json.loads(json_content)
            else:
                logger.warning("⚠️ Pas d'accolades trouvées, tentative de parsing direct")
                classification_result = json.loads(response_content)
        except json.JSONDecodeError as json_err:
            logger.error(f"❌ Erreur parsing JSON après nettoyage: {json_err}")
            logger.error(f"📄 Contenu complet reçu: {response_content}")
            raise  # Re-lever l'exception pour être capturée par le bloc except principal

        # Extraire les résultats
        detected_room_type = classification_result.get("room_type", "autre")
        confidence = classification_result.get("confidence", 50)
        is_valid_room = classification_result.get("is_valid_room", True)  # Par défaut True pour rétrocompatibilité
        validation_message = classification_result.get("validation_message", "Photos valides")

        # 🚨 VALIDATION DES PHOTOS - Si photos invalides, forcer wrong_room
        if not is_valid_room:
            logger.warning(f"⚠️ PHOTOS INVALIDES DÉTECTÉES: {validation_message}")
            logger.warning(f"🚫 Les photos ne montrent pas un intérieur de logement - Classification forcée à 'wrong_room'")
            detected_room_type = "wrong_room"
            confidence = 95

        # Si confiance = 0, l'ajuster à 10 minimum pour éviter les problèmes
        if confidence == 0:
            confidence = 10
            logger.debug(f"📊 Confiance ajustée de 0 à {confidence} pour éviter une valeur nulle")

        # 🗺️ ÉTAPE DE MAPPING - Convertir les variations vers les types valides (sauf si wrong_room)
        original_detected_type = detected_room_type
        if detected_room_type != "wrong_room":
            detected_room_type = map_room_type_to_valid(detected_room_type)

            # Vérifier que le type mappé existe dans nos templates
            if detected_room_type not in room_templates["room_types"]:
                logger.warning(f"⚠️ Type '{detected_room_type}' (mappé depuis '{original_detected_type}') non reconnu, utilisation de 'autre'")
                detected_room_type = "autre"
                confidence = max(confidence - 20, 10)  # Réduire la confiance
            else:
                if original_detected_type != detected_room_type:
                    logger.debug(f"✅ Mapping réussi: '{original_detected_type}' → '{detected_room_type}' reconnu")
                else:
                    logger.debug(f"✅ Type de pièce '{detected_room_type}' reconnu directement")

        # Récupérer les informations du template (ou valeurs par défaut pour wrong_room)
        if detected_room_type == "wrong_room":
            room_info = {
                "name": "Photos invalides",
                "icon": "⚠️",
                "verifications": {
                    "elements_critiques": ["Photos montrant l'intérieur du logement"],
                    "points_ignorables": [],
                    "defauts_frequents": ["Photos hors sujet", "Photos floues", "Photos non pertinentes"]
                }
            }
        else:
            room_info = room_templates["room_types"][detected_room_type]

        # Créer la réponse
        return RoomClassificationResponse(
            piece_id=input_data.piece_id,
            room_type=detected_room_type,
            room_name=room_info["name"],
            room_icon=room_info["icon"],
            confidence=confidence,
            is_valid_room=is_valid_room,
            validation_message=validation_message,
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
            is_valid_room=True,
            validation_message="Classification par défaut (erreur de parsing JSON)",
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
            is_valid_room=True,
            validation_message="Classification par défaut (erreur générale)",
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
    # 🔍 TRACKING DES LOGS EN TEMPS RÉEL
    request_id = str(uuid.uuid4())
    logs_manager.start_request(
        request_id=request_id,
        endpoint="/classify-room",
        data={"piece_id": input_data.piece_id}
    )

    logger.info(f"Classification démarrée pour la pièce {input_data.piece_id}")

    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        result = classify_room_type(input_data, parcours_type, request_id=request_id)
        logger.info(f"Classification terminée pour la pièce {input_data.piece_id}: {result.room_type} (confiance: {result.confidence}%)")

        logs_manager.complete_request(
            request_id=request_id,
            status="success"
        )

        return result
    except Exception as e:
        logger.error(f"Erreur dans l'endpoint classify-room: {str(e)}")

        logs_manager.complete_request(
            request_id=request_id,
            status="error"
        )

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

def analyze_with_auto_classification(input_data: InputData, parcours_type: str = "Voyageur", request_id: str = None) -> CombinedAnalysisResponse:
    """
    Effectuer d'abord la classification, puis l'analyse avec injection des critères automatiques

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")
        request_id: ID de la requête pour le tracking des logs

    Returns:
        CombinedAnalysisResponse: Résultat combiné de la classification et de l'analyse
    """
    try:
        # ÉTAPE 1: Classification de la pièce
        logger.debug(f"🔍 ÉTAPE 1 - Classification automatique pour la pièce {input_data.piece_id} (parcours: {parcours_type})")

        # Convertir InputData en RoomClassificationInput
        classification_input = RoomClassificationInput(
            piece_id=input_data.piece_id,
            nom=input_data.nom,
            type=parcours_type,
            checkin_pictures=input_data.checkin_pictures,
            checkout_pictures=input_data.checkout_pictures
        )

        # Effectuer la classification avec le type de parcours
        classification_result = classify_room_type(classification_input, parcours_type, request_id=request_id)
        
        logger.debug(f"✅ Classification terminée: {classification_result.room_type} ({classification_result.confidence}%)")
        logger.info(f"📝 Nom détecté: {classification_result.room_name} {classification_result.room_icon}")
        logger.debug(f"🔍 Validation photos: is_valid_room={classification_result.is_valid_room}, message={classification_result.validation_message}")

        # 🚨 VÉRIFICATION: Si photos invalides, créer une issue critique
        if not classification_result.is_valid_room:
            logger.error(f"🚫 PHOTOS INVALIDES DÉTECTÉES - Création d'une issue critique 'wrong_room'")
            logger.warning(f"⚠️ BLOCAGE TOTAL: Aucune autre analyse (propreté, dégradation, etc.) ne sera effectuée")
            logger.warning(f"⚠️ Raison: {classification_result.validation_message}")

            # Créer une issue wrong_room avec sévérité high
            wrong_room_issue = Probleme(
                description=f"Photos invalides: {classification_result.validation_message}",
                category="wrong_room",
                severity="high",
                confidence=95
            )

            # Retourner directement un résultat avec cette issue critique
            # ⚠️ IMPORTANT: On retourne ICI sans faire d'autres analyses
            return CombinedAnalysisResponse(
                piece_id=input_data.piece_id,
                nom_piece=f"{classification_result.room_name} {classification_result.room_icon}",
                room_classification=classification_result,
                analyse_globale=AnalyseGlobale(
                    status="probleme",
                    score=1.0,
                    temps_nettoyage_estime="Non applicable",
                    commentaire_global="Les photos fournies ne montrent pas un intérieur de logement identifiable. Veuillez soumettre des photos valides."
                ),
                issues=[wrong_room_issue]
            )

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
        logger.debug(f"📌 INJECTION DES CRITÈRES:")
        logger.debug(f"   🔍 Éléments critiques injectés ({len(enhanced_input_data.elements_critiques)}): {enhanced_input_data.elements_critiques}")
        logger.debug(f"   ➖ Points ignorables injectés ({len(enhanced_input_data.points_ignorables)}): {enhanced_input_data.points_ignorables}")
        logger.debug(f"   ⚠️ Défauts fréquents injectés ({len(enhanced_input_data.defauts_frequents)}): {enhanced_input_data.defauts_frequents}")
        
        # ÉTAPE 3: Analyse avec les critères injectés
        logger.debug(f"🔬 ÉTAPE 3 - Analyse détaillée avec critères spécifiques au type '{classification_result.room_type}'")

        analysis_result = analyze_images(enhanced_input_data, parcours_type, request_id=request_id)

        logger.debug(f"✅ Analyse IA terminée: {len(analysis_result.preliminary_issues)} problèmes détectés (score sera calculé algorithmiquement)")

        # 🔍 DEBUG: Logger les issues détectées
        if analysis_result.preliminary_issues:
            logger.debug(f"🔍 DEBUG - Issues détectées par l'IA:")
            for idx, issue in enumerate(analysis_result.preliminary_issues):
                logger.debug(f"   [{idx+1}] {issue.description} ({issue.category}, {issue.severity}, {issue.confidence}%)")
        else:
            logger.warning(f"⚠️ DEBUG - AUCUNE ISSUE DÉTECTÉE par l'IA pour la pièce {input_data.piece_id}")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 3.5: SYSTÈME DOUBLE-PASS POUR OBJETS MANQUANTS
        # 🔴 DÉSACTIVÉ TEMPORAIREMENT (DOUBLE_PASS_ENABLED = False)
        # ═══════════════════════════════════════════════════════════════
        if DOUBLE_PASS_ENABLED:
            logger.debug(f"📦 ÉTAPE 3.5 - DOUBLE-PASS: Vérification renforcée des objets manquants")

            try:
                # PHASE 1: Extraction de l'inventaire depuis les photos checkin
                inventory = extract_inventory_from_images(
                    piece_id=input_data.piece_id,
                    nom_piece=f"{classification_result.room_name}",
                    checkin_pictures=input_data.checkin_pictures
                )

                if inventory.total_objects > 0:
                    logger.debug(f"📦 PHASE 1 OK: {inventory.total_objects} objets inventoriés")

                    # PHASE 2: Vérification sur les photos checkout
                    verification = verify_inventory_on_checkout(
                        piece_id=input_data.piece_id,
                        inventory=inventory,
                        checkout_pictures=input_data.checkout_pictures
                    )

                    logger.debug(f"🔎 PHASE 2 OK: {len(verification.missing_objects)} manquants, {len(verification.moved_objects)} déplacés")

                    # Convertir en issues et fusionner avec les issues existantes
                    inventory_issues = convert_inventory_to_issues(verification)

                    if inventory_issues:
                        # Éviter les doublons: vérifier si l'objet n'est pas déjà signalé
                        existing_descriptions = {issue.description.lower() for issue in analysis_result.preliminary_issues}

                        new_issues = []
                        for inv_issue in inventory_issues:
                            # Vérifier si un issue similaire existe déjà
                            is_duplicate = any(
                                inv_issue.description.lower().split(':')[1].strip().split(' - ')[0] in existing_desc
                                for existing_desc in existing_descriptions
                                if ':' in inv_issue.description
                            )

                            if not is_duplicate:
                                new_issues.append(inv_issue)
                                logger.debug(f"   ➕ Nouvel objet manquant détecté: {inv_issue.description}")

                        # Ajouter les nouvelles issues
                        analysis_result.preliminary_issues.extend(new_issues)
                        logger.debug(f"✅ DOUBLE-PASS: {len(new_issues)} issues ajoutées (total: {len(analysis_result.preliminary_issues)})")
                else:
                    logger.debug(f"📦 PHASE 1: Aucun objet inventorié (pièce peut-être vide ou photos insuffisantes)")

            except Exception as dp_error:
                logger.warning(f"⚠️ DOUBLE-PASS: Erreur non bloquante - {dp_error}")
                # Le double-pass est optionnel, on continue sans lui en cas d'erreur
        else:
            logger.debug(f"📦 ÉTAPE 3.5 - DOUBLE-PASS: ⏸️ DÉSACTIVÉ (DOUBLE_PASS_ENABLED = False)")

        # ═══════════════════════════════════════════════════════════════
        # FIN DOUBLE-PASS
        # ═══════════════════════════════════════════════════════════════

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 3.9: CALCUL DU SCORE ALGORITHMIQUE
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🧮 ÉTAPE 3.9 - Calcul du score algorithmique pour la pièce")

        # Calculer le score algorithmique basé sur les issues détectées
        algorithmic_score_result = calculate_room_algorithmic_score(
            issues=analysis_result.preliminary_issues,
            parcours_type=parcours_type
        )

        # Remplacer le score IA par le score algorithmique
        analysis_result.analyse_globale.score = algorithmic_score_result["note_sur_5"]

        logger.debug(f"✅ Score algorithmique appliqué: {algorithmic_score_result['note_sur_5']}/5 ({algorithmic_score_result['label']})")
        logger.debug(f"   📊 Détails: {algorithmic_score_result['issues_count']} issues, {algorithmic_score_result['total_penalty']} pénalités")

        # ÉTAPE 4: Combinaison des résultats
        logger.debug(f"🔄 ÉTAPE 4 - Combinaison des résultats de classification et d'analyse")

        combined_result = CombinedAnalysisResponse(
            piece_id=input_data.piece_id,
            nom_piece=f"{classification_result.room_name} {classification_result.room_icon}",
            room_classification=classification_result,
            analyse_globale=analysis_result.analyse_globale,
            issues=analysis_result.preliminary_issues
        )

        logger.debug(f"🎉 Analyse combinée terminée avec succès pour la pièce {input_data.piece_id}")
        logger.debug(f"🔍 DEBUG - CombinedAnalysisResponse créé avec {len(combined_result.issues)} issues")
        
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
    logger.debug(f"🚀 Analyse combinée démarrée pour la pièce {input_data.piece_id}")

    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        result = analyze_with_auto_classification(input_data, parcours_type)
        logger.debug(f"🎯 Analyse combinée terminée pour la pièce {input_data.piece_id}")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-with-classification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════
# NOUVEAUX MODÈLES POUR LE RAPPORT INDIVIDUAL-REPORT
# ═══════════════════════════════════════════════════════════════

class ChecklistItem(BaseModel):
    """Item de la checklist finale"""
    id: str
    text: str
    completed: bool
    icon: str
    photo: Optional[str] = None

class UserReport(BaseModel):
    """Signalement manuel effectué par l'opérateur"""
    id: str
    piece_id: str
    titre: str
    description: str
    severite: Literal["basse", "moyenne", "haute"]
    photo: Optional[str] = None
    date_signalement: str  # Format ISO 8601

# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR L'ANALYSE DES ÉTAPES (ENRICHIS)
# ═══════════════════════════════════════════════════════════════

class Etape(BaseModel):
    """Étape/tâche à effectuer avec métadonnées de validation"""
    etape_id: str
    task_name: str
    consigne: str
    checking_picture: str
    checkout_picture: Optional[str] = None  # Optional: tasks without photo don't need AI analysis
    # 🆕 Métadonnées de validation de tâche (Phase 3)
    tache_approuvee: Optional[bool] = None
    tache_date_validation: Optional[str] = None  # Format ISO 8601
    tache_commentaire: Optional[str] = None

class PieceWithEtapes(BaseModel):
    """Pièce avec étapes et métadonnées de validation"""
    piece_id: str
    nom: str
    commentaire_ia: str = ""
    checkin_pictures: List[Picture]
    checkout_pictures: List[Picture]
    etapes: List[Etape]
    # 🆕 Métadonnées par pièce (Phase 3)
    photos_reference: Optional[List[str]] = None
    check_entree_conforme: Optional[bool] = None
    check_entree_date_validation: Optional[str] = None  # Format ISO 8601
    check_entree_photos_reprises: Optional[List[str]] = None
    check_sortie_valide: Optional[bool] = None
    check_sortie_date_validation: Optional[str] = None  # Format ISO 8601
    check_sortie_photos_non_conformes: Optional[List[str]] = None

class EtapesAnalysisInput(BaseModel):
    """
    Input enrichi pour l'analyse complète avec toutes les métadonnées nécessaires
    au rapport individual-report-data-model.json
    """
    # ✅ Champs existants
    logement_id: str
    rapport_id: str
    type: str = "Voyageur"  # Type de parcours: "Voyageur" ou "Ménage"
    pieces: List[PieceWithEtapes]

    # 🆕 PHASE 1: Métadonnées critiques (priorité haute)
    logement_adresse: Optional[str] = Field(None, alias='adresseLogement')
    logement_name: Optional[str] = Field(None, alias='logementName')
    date_debut: Optional[str] = None  # Format: "DD/MM/YY"
    date_fin: Optional[str] = None  # Format: "DD/MM/YY"
    operateur_nom: Optional[str] = None
    operateur_prenom: Optional[str] = Field(None, alias='operatorFirstName')
    operateur_nom_famille: Optional[str] = Field(None, alias='operatorLastName')
    operateur_telephone: Optional[str] = Field(None, alias='operatorPhone')
    etat_lieux_moment: Optional[Literal["sortie", "arrivee-sortie"]] = None

    # 🆕 PHASE 1: Informations voyageur (priorité haute)
    voyageur_nom: Optional[str] = None
    voyageur_email: Optional[str] = None
    voyageur_telephone: Optional[str] = None

    # 🆕 PHASE 2: Horaires des contrôles (priorité moyenne)
    heure_checkin_debut: Optional[str] = None  # Format: "HH:MM"
    heure_checkin_fin: Optional[str] = None  # Format: "HH:MM"
    heure_checkout_debut: Optional[str] = None  # Format: "HH:MM"
    heure_checkout_fin: Optional[str] = None  # Format: "HH:MM"

    # 🆕 PHASE 2: Signalements utilisateurs (priorité moyenne)
    signalements_utilisateur: Optional[List[UserReport]] = None

    # 🆕 PHASE 3: Checklist finale (priorité basse)
    checklist_finale: Optional[List[ChecklistItem]] = None

    model_config = {"populate_by_name": True}  # Permet d'utiliser les alias

    @field_validator('etat_lieux_moment', mode='before')
    @classmethod
    def normalize_etat_lieux_moment(cls, v):
        """Normalise les différentes valeurs possibles pour etat_lieux_moment"""
        if v is None:
            return v

        # Mapping des valeurs Bubble vers les valeurs attendues
        mapping = {
            "checkinandcheckout": "arrivee-sortie",
            "checkoutonly": "sortie",
            "arrivee-sortie": "arrivee-sortie",
            "sortie": "sortie",
            "checkout": "sortie",
        }

        # Normaliser en minuscules pour la recherche
        normalized = mapping.get(v.lower() if isinstance(v, str) else v)

        if normalized:
            return normalized

        # Si la valeur n'est pas dans le mapping, retourner telle quelle
        # (Pydantic lèvera une erreur de validation si ce n'est pas une valeur valide)
        return v

class EtapeIssue(BaseModel):
    etape_id: str
    description: str
    category: Literal["missing_item", "damage", "cleanliness", "positioning", "added_item", "image_quality", "wrong_room", "etape_non_validee"]
    severity: Literal["low", "medium", "high"]
    confidence: int = Field(ge=0, le=100)
    validation_status: Optional[Literal["VALIDÉ", "NON_VALIDÉ", "INCERTAIN"]] = None  # 🆕 Statut de validation de l'étape
    commentaire: Optional[str] = None  # 🆕 Commentaire explicatif

class EtapesAnalysisResponse(BaseModel):
    preliminary_issues: List[EtapeIssue]

def analyze_etapes(input_data: EtapesAnalysisInput, request_id: str = None) -> EtapesAnalysisResponse:
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
            logger.debug(f"🖼️ Traitement des images des étapes pour la pièce {piece.piece_id}")
            processed_etapes = process_etapes_images([etape.model_dump() for etape in piece.etapes])
            logger.debug(f"✅ {len(processed_etapes)} étapes traitées pour la pièce {piece.piece_id}")
            
            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]  # Garder l'objet original pour les autres propriétés

                # 🚫 RÈGLE: Exclure les tâches sans checkout_picture de l'analyse AI
                # Si checkout_picture est vide/null dans l'étape originale, ne pas analyser
                if not etape.checkout_picture or etape.checkout_picture.strip() == "":
                    logger.debug(f"⏭️ Étape {etape.etape_id} skippée: pas de checkout_picture requis (tâche sans photo)")
                    continue

                logger.debug(f"🔍 Analyse de l'étape {etape.etape_id}: {etape.task_name}")

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
                    logger.debug(f"🔍 URL avant normalisation: '{checking_url}'")
                    logger.debug(f"�� URL après normalisation: '{checking_url_normalized}'")
                    checking_url = checking_url_normalized

                if checkout_url is not None and isinstance(checkout_url, str):
                    checkout_url_normalized = normalize_url(checkout_url)
                    logger.debug(f"🔍 URL avant normalisation: '{checkout_url}'")
                    logger.debug(f"�� URL après normalisation: '{checkout_url_normalized}'")
                    checkout_url = checkout_url_normalized

                # Déterminer si les URLs sont utilisables (non None et non placeholders)
                checking_usable = checking_url is not None and not (isinstance(checking_url, str) and checking_url.startswith('data:image/gif;base64,R0lGOD'))
                checkout_usable = checkout_url is not None and not (isinstance(checkout_url, str) and checkout_url.startswith('data:image/gif;base64,R0lGOD'))

                logger.debug(f"🔍 Validation images pour étape {etape.etape_id}: checking_usable={checking_usable}, checkout_usable={checkout_usable}")

                # Construire le message en fonction des images disponibles
                user_content = [
                    {
                        "type": "text",
                        "text": f"Analyse cette étape selon la consigne : {etape.consigne}"
                    }
                ]

                # Ajouter images seulement si elles sont utilisables
                if checking_usable:
                    logger.debug(f"✅ ÉTAPE CHECKING - Image ajoutée au payload OpenAI: {checking_url}")
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
                    logger.debug(f"✅ ÉTAPE CHECKOUT - Image ajoutée au payload OpenAI: {checkout_url}")
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

                # 📝 LOG DES PROMPTS POUR LE SYSTÈME DE LOGS (Étapes)
                if request_id:
                    logs_manager.add_prompt_log(
                        request_id=request_id,
                        prompt_type=f"Étape: {etape.task_name}",
                        prompt_content=etape_prompt,
                        model=OPENAI_MODEL
                    )

                # Faire l'appel API avec gestion d'erreurs robuste
                try:
                    # 🚀 MIGRATION vers Responses API
                    messages = [
                        {
                            "role": "system",
                            "content": etape_prompt
                        },
                        user_message
                    ]
                    input_content = convert_chat_messages_to_responses_input(messages)

                    response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=20000,
                        reasoning={"effort": "high"}
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
                            # 🔄 Convertir toutes les URLs en data URIs (version sync pour compatibilité thread pool)
                            user_message_with_data_uris = convert_message_urls_to_data_uris_sync(user_message.copy())

                            # Compter les images converties
                            data_uri_count = sum(
                                1 for c in user_message_with_data_uris.get("content", [])
                                if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                            )

                            logger.debug(f"🔄 Retry étape {etape.etape_id} avec {data_uri_count} images en Data URI")

                            # Réessayer avec les data URIs
                            # 🚀 MIGRATION vers Responses API
                            messages = [
                                {
                                    "role": "system",
                                    "content": etape_prompt
                                },
                                user_message_with_data_uris
                            ]
                            input_content = convert_chat_messages_to_responses_input(messages)

                            response = client.responses.create(
                                model=OPENAI_MODEL,
                                input=input_content,
                                text={"format": {"type": "json_object"}},
                                max_output_tokens=20000,
                                reasoning={"effort": "high"}
                            )
                            logger.debug(f"✅ Analyse de l'étape {etape.etape_id} réussie avec Data URIs (fallback téléchargement)")

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
                                # 🚀 MIGRATION vers Responses API
                                messages = [
                                    {
                                        "role": "system",
                                        "content": etape_prompt
                                    },
                                    fallback_message
                                ]
                                input_content = convert_chat_messages_to_responses_input(messages)

                                response = client.responses.create(
                                    model=OPENAI_MODEL,
                                    input=input_content,
                                    text={"format": {"type": "json_object"}},
                                    max_output_tokens=20000,
                                    reasoning={"effort": "high"}
                                )
                                logger.debug(f"✅ Analyse de l'étape {etape.etape_id} réussie en mode fallback (sans images)")
                            except Exception as final_error:
                                logger.error(f"❌ Échec de tous les fallbacks pour l'étape {etape.etape_id}: {final_error}")
                                all_issues.append(EtapeIssue(
                                    etape_id=etape.etape_id,
                                    description=f"Impossibilité d'analyser l'étape '{etape.task_name}' - erreur technique",
                                    category="image_quality",
                                    severity="high",
                                    confidence=100
                                ))
                                logger.debug(f"⚠️ Problème générique ajouté pour l'étape {etape.etape_id}")
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
                            # 🚀 MIGRATION vers Responses API
                            messages = [
                                {
                                    "role": "system",
                                    "content": etape_prompt
                                },
                                fallback_message
                            ]
                            input_content = convert_chat_messages_to_responses_input(messages)

                            response = client.responses.create(
                                model=OPENAI_MODEL,
                                input=input_content,
                                text={"format": {"type": "json_object"}},
                                max_output_tokens=20000,
                                reasoning={"effort": "high"}
                            )
                            logger.debug(f"✅ Analyse de l'étape {etape.etape_id} réussie en mode fallback (sans images)")
                        except Exception as fallback_error:
                            logger.error(f"❌ Échec du fallback OpenAI pour l'étape {etape.etape_id}: {fallback_error}")
                            # Ajouter un problème générique pour cette étape
                            all_issues.append(EtapeIssue(
                                etape_id=etape.etape_id,
                                description=f"Impossibilité d'analyser l'étape '{etape.task_name}' - images en format non supporté",
                                category="image_quality",
                                severity="high",
                                confidence=100
                            ))
                            logger.debug(f"⚠️ Problème générique ajouté pour l'étape {etape.etape_id}")
                            continue  # Passer à l'étape suivante
                    else:
                        # Autres erreurs OpenAI - ajouter un problème générique
                        logger.error(f"❌ Erreur OpenAI non récupérable pour l'étape {etape.etape_id}: {error_str}")
                        all_issues.append(EtapeIssue(
                            etape_id=etape.etape_id,
                            description=f"Erreur technique lors de l'analyse de l'étape '{etape.task_name}'",
                            category="image_quality",
                            severity="high",
                            confidence=100
                        ))
                        continue  # Passer à l'étape suivante
                
                # Parser la réponse
                # 🚀 MIGRATION: Extraction depuis Responses API
                response_content = (response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)).strip()

                # 📝 LOG DE LA RÉPONSE POUR LE SYSTÈME DE LOGS (Étapes)
                if request_id:
                    logs_manager.add_response_log(
                        request_id=request_id,
                        response_type=f"Étape: {etape.task_name}",
                        response_content=response_content,
                        model=OPENAI_MODEL,
                        tokens_used=extract_usage_tokens(response)
                    )

                # 🔧 NETTOYAGE ROBUSTE DU JSON
                try:
                    # Essayer de trouver le JSON entre accolades
                    start_idx = response_content.find('{')
                    end_idx = response_content.rfind('}')

                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_content = response_content[start_idx:end_idx+1]
                        etape_result = json.loads(json_content)
                    else:
                        etape_result = json.loads(response_content)
                except json.JSONDecodeError as json_err:
                    logger.error(f"❌ Erreur parsing JSON pour étape {etape.etape_id}: {json_err}")
                    logger.error(f"📄 Contenu reçu: {response_content[:500]}...")
                    # Ajouter une issue d'erreur et continuer
                    all_issues.append(EtapeIssue(
                        etape_id=etape.etape_id,
                        description=f"Erreur de parsing JSON pour l'étape '{etape.task_name}'",
                        category="image_quality",
                        severity="high",
                        confidence=100
                    ))
                    continue  # Passer à l'étape suivante
                
                # 🆕 Extraire validation_status et commentaire
                validation_status = etape_result.get("validation_status")
                commentaire = etape_result.get("commentaire", "")

                logger.info(f"📋 Étape {etape.etape_id} - validation_status IA: {validation_status}")

                # Extraire les issues temporaires
                temp_issues = []
                if "issues" in etape_result and etape_result["issues"]:
                    for issue in etape_result["issues"]:
                        temp_issues.append({
                            "description": issue["description"],
                            "category": issue["category"],
                            "severity": issue["severity"],
                            "confidence": issue["confidence"]
                        })

                # ═══════════════════════════════════════════════════════════════
                # 🔄 APPLIQUER LA LOGIQUE EN 2 ÉTAPES (POST-TRAITEMENT)
                # ═══════════════════════════════════════════════════════════════
                has_checking = bool(etape_data.get("checking_picture_processed"))
                has_checkout = bool(etape_data.get("checkout_picture_processed"))

                validation_status, temp_issues, commentaire = apply_two_step_validation_logic_sync(
                    validation_status=validation_status,
                    issues=temp_issues,
                    has_checking=has_checking,
                    checking_picture_url=etape_data.get("checking_picture_processed", "") if has_checking else "",
                    checkout_picture_url=etape_data.get("checkout_picture_processed", "") if has_checkout else "",
                    etape_id=etape.etape_id,
                    task_name=etape.task_name,
                    commentaire=commentaire
                )

                # 🆕 FUSION DES ISSUES : Une seule issue par étape avec catégorie "etape_non_validee"
                if temp_issues:
                    # Fusionner toutes les descriptions en une seule
                    merged_descriptions = [issue["description"] for issue in temp_issues]
                    merged_description = ", ".join(merged_descriptions)

                    # Prendre la sévérité la plus haute
                    severity_order = {"high": 3, "medium": 2, "low": 1}
                    max_severity = max(temp_issues, key=lambda x: severity_order.get(x["severity"], 1))["severity"]

                    # Prendre la confiance moyenne
                    avg_confidence = sum(issue["confidence"] for issue in temp_issues) // len(temp_issues)

                    # Créer UNE SEULE issue fusionnée avec la catégorie "etape_non_validee"
                    all_issues.append(EtapeIssue(
                        etape_id=etape.etape_id,
                        description=merged_description,
                        category="etape_non_validee",
                        severity=max_severity,
                        confidence=avg_confidence,
                        validation_status=validation_status,
                        commentaire=commentaire
                    ))
                    logger.debug(f"   🔗 {len(temp_issues)} issues fusionnées en 1 pour l'étape {etape.etape_id}")
                else:
                    # 🆕 Si pas d'issues mais validation_status existe, créer une entrée de suivi
                    # ⚠️ SEULEMENT pour NON_VALIDÉ ou INCERTAIN (pas pour VALIDÉ qui ne doit pas impacter la note)
                    if validation_status and validation_status != "VALIDÉ":
                        # Récupérer confidence de manière sécurisée
                        confidence_value = 100
                        if isinstance(etape_result, dict):
                            confidence_value = etape_result.get("confidence", 100)

                        # Pour NON_VALIDÉ ou INCERTAIN sans issues détaillées
                        all_issues.append(EtapeIssue(
                            etape_id=etape.etape_id,
                            description=commentaire if commentaire else f"Étape {validation_status.lower()}",
                            category="etape_non_validee",
                            severity="low" if validation_status == "INCERTAIN" else "medium",
                            confidence=confidence_value,
                            validation_status=validation_status,
                            commentaire=commentaire
                        ))

                logger.info(f"✅ Analyse terminée pour l'étape {etape.etape_id}: validation_status FINAL={validation_status}, {len(temp_issues)} problèmes détectés")

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
    logger.debug(f"🚀 Analyse des étapes démarrée pour le logement {input_data.logement_id}")
    
    try:
        result = analyze_etapes(input_data)
        total_issues = len(result.preliminary_issues)
        logger.debug(f"🎯 Analyse des étapes terminée pour le logement {input_data.logement_id}: {total_issues} problèmes détectés")
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
    score_explanation: Optional[str] = Field(default=None, description="Explication claire et compréhensible du calcul de la note")
    
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
    logement_name: Optional[str] = None  # Nom du logement (ajouté pour identification)
    rapport_id: str
    pieces_analysis: List[CombinedAnalysisResponse]  # Résultats de l'analyse avec classification pour chaque pièce
    total_issues_count: int
    etapes_issues_count: int
    general_issues_count: int
    # Enrichissement avec synthèse globale
    analysis_enrichment: LogementAnalysisEnrichment


# ═══════════════════════════════════════════════════════════════
# TRANSFORMATION VERS INDIVIDUAL-REPORT-DATA-MODEL
# ═══════════════════════════════════════════════════════════════

def calculate_category_scores(pieces_analysis: List[CombinedAnalysisResponse]) -> dict:
    """
    Calcule les scores par catégorie basés sur les issues détectées

    Catégories :
    - presenceObjets : missing_item
    - etatObjets : damage
    - proprete : cleanliness
    - agencement : positioning

    Returns:
        dict: Scores /5 pour chaque catégorie
    """

    # Pondération par sévérité (même système que calculate_weighted_severity_score)
    SEVERITY_WEIGHT = {
        "low": 1,
        "medium": 3,
        "high": 10
    }

    # Accumulateurs par catégorie
    category_scores = {
        "presenceObjets": {"total_weight": 0, "count": 0},  # missing_item
        "etatObjets": {"total_weight": 0, "count": 0},      # damage
        "proprete": {"total_weight": 0, "count": 0},        # cleanliness
        "agencement": {"total_weight": 0, "count": 0}       # positioning
    }

    # Parcourir toutes les issues de toutes les pièces
    for piece in pieces_analysis:
        for issue in piece.issues:
            severity_weight = SEVERITY_WEIGHT.get(issue.severity, 1)

            # Mapper les catégories d'issues aux sous-notes
            if issue.category == "missing_item":
                category_scores["presenceObjets"]["total_weight"] += severity_weight
                category_scores["presenceObjets"]["count"] += 1
            elif issue.category == "damage":
                category_scores["etatObjets"]["total_weight"] += severity_weight
                category_scores["etatObjets"]["count"] += 1
            elif issue.category == "cleanliness":
                category_scores["proprete"]["total_weight"] += severity_weight
                category_scores["proprete"]["count"] += 1
            elif issue.category == "positioning":
                category_scores["agencement"]["total_weight"] += severity_weight
                category_scores["agencement"]["count"] += 1

    # Convertir les poids en scores /5
    # Logique : Score parfait = 5.0, on soustrait selon la gravité
    # Formule : 5.0 - (total_weight / max(1, count)) * facteur_reduction
    final_scores = {}

    for category, data in category_scores.items():
        if data["count"] == 0:
            # Aucune issue dans cette catégorie = score parfait
            final_scores[category] = 5.0
        else:
            # Calculer la pénalité moyenne par issue
            avg_weight = data["total_weight"] / data["count"]

            # Convertir en score /5
            # low (1) → -0.2, medium (3) → -0.6, high (10) → -2.0
            penalty = avg_weight * 0.2 * data["count"]
            score = max(1.0, 5.0 - penalty)

            # Arrondir à 1 décimale
            final_scores[category] = round(score, 1)

    logger.debug(f"📊 Scores par catégorie calculés :")
    logger.debug(f"   - Présence objets : {final_scores['presenceObjets']}/5 ({category_scores['presenceObjets']['count']} issues)")
    logger.debug(f"   - État objets : {final_scores['etatObjets']}/5 ({category_scores['etatObjets']['count']} issues)")
    logger.debug(f"   - Propreté : {final_scores['proprete']}/5 ({category_scores['proprete']['count']} issues)")
    logger.debug(f"   - Agencement : {final_scores['agencement']}/5 ({category_scores['agencement']['count']} issues)")

    return final_scores

def transform_to_individual_report(
    analysis_response: CompleteAnalysisResponse,
    input_data: EtapesAnalysisInput
) -> dict:
    """
    Transforme CompleteAnalysisResponse + EtapesAnalysisInput enrichi
    vers le format individual-report-data-model.json

    Args:
        analysis_response: Résultat de l'analyse complète
        input_data: Données d'entrée enrichies avec métadonnées

    Returns:
        dict: Payload au format individual-report-data-model.json
    """

    # Helper: Mapper severity API -> severity UI
    def map_severity(api_severity: str) -> str:
        mapping = {
            "low": "faible",
            "medium": "moyenne",
            "high": "elevee"
        }
        return mapping.get(api_severity, "faible")

    # Helper: Récupérer l'URL de la photo pour un problème
    def get_photo_url_for_issue(issue, piece_input: PieceWithEtapes) -> Optional[str]:
        """
        Récupère l'URL de la photo associée à un problème.

        Logique:
        - Si le problème a un etapeId: utiliser la photo checkout de l'étape
        - Sinon: utiliser la première photo de sortie de la pièce

        Args:
            issue: L'issue/problème détecté
            piece_input: Les données d'entrée de la pièce

        Returns:
            str ou None: URL de la photo ou None si aucune photo disponible
        """
        # CAS 1: Problème lié à une étape spécifique
        if hasattr(issue, 'etape_id') and issue.etape_id:
            # Chercher l'étape correspondante
            for etape in piece_input.etapes:
                if etape.etape_id == issue.etape_id:
                    # Priorité 1: checkout_picture (photo de vérification)
                    if etape.checkout_picture:
                        return etape.checkout_picture
                    # Priorité 2: checking_picture (photo de référence) en fallback
                    if etape.checking_picture:
                        return etape.checking_picture
                    break
            # Si l'étape n'a pas de photo, retourner None
            return None

        # CAS 2: Problème général (pas d'etapeId)
        # Utiliser la première photo de sortie de la pièce
        if piece_input.checkout_pictures and len(piece_input.checkout_pictures) > 0:
            return piece_input.checkout_pictures[0].url

        # Aucune photo disponible
        return None

    # Helper: Mapper category API -> titre UI
    def map_category_to_title(category: str) -> str:
        mapping = {
            "missing_item": "Objets manquants",
            "added_item": "Objets ajoutés",
            "damage": "Dégradation",
            "cleanliness": "Propreté",
            "positioning": "Agencement",
            "image_quality": "Qualité image",
            "wrong_room": "Mauvaise pièce"
        }
        return mapping.get(category, "Autre")

    # Helper: Calculer le statut d'une pièce
    def calculate_room_status(issues_count: int, severity_counts: dict) -> str:
        if issues_count == 0:
            return "ok"
        elif severity_counts.get("high", 0) > 0 or severity_counts.get("medium", 0) > 2:
            return "probleme"
        else:
            return "attention"

    # Helper: Obtenir l'icône d'une pièce
    def get_room_icon(room_name: str) -> str:
        icons = {
            "salon": "🛋️",
            "cuisine": "🍳",
            "chambre": "🛏️",
            "salle_de_bain": "🚿",
            "salle d'eau": "🚿",
            "terrasse": "🌿",
            "balcon": "🌿",
            "entree": "🚪",
            "couloir": "🚪"
        }
        return icons.get(room_name.lower(), "🏠")

    # Helper: Compter les issues par catégorie et sévérité
    def count_issues_by_category(issues: List) -> dict:
        counts = {
            "missing_item": 0,
            "added_item": 0,
            "positioning": 0,
            "cleanliness": {"high": 0, "medium": 0, "low": 0},
            "damage": {"high": 0, "medium": 0, "low": 0},
            "image_quality": 0,
            "wrong_room": 0
        }

        for issue in issues:
            category = issue.category
            severity = issue.severity

            if category in ["cleanliness", "damage"]:
                counts[category][severity] += 1
            elif category in counts:
                counts[category] += 1

        return counts

    # ═══════════════════════════════════════════════════════════════
    # 1. REPORT METADATA
    # ═══════════════════════════════════════════════════════════════

    now = datetime.now()
    report_metadata = {
        "id": input_data.rapport_id,
        "logement": input_data.logement_adresse or "Adresse non renseignée",
        "logementName": input_data.logement_name or "",  # Nom du logement
        "dateDebut": input_data.date_debut or "",
        "dateFin": input_data.date_fin or "",
        "statut": "Terminé",
        "parcours": f"État des lieux {input_data.type.lower()}",
        "typeParcours": input_data.type.lower(),
        "etatLieuxMoment": input_data.etat_lieux_moment or "sortie",
        "operateur": input_data.operateur_nom or "Non renseigné",
        "etat": analysis_response.analysis_enrichment.global_score.score,
        "dateGeneration": now.strftime("%d/%m/%Y"),
        "heureGeneration": now.strftime("%H:%M")
    }

    # ═══════════════════════════════════════════════════════════════
    # 2. SYNTHESE SECTION
    # ═══════════════════════════════════════════════════════════════

    # Calculer les scores par catégorie
    category_scores = calculate_category_scores(analysis_response.pieces_analysis)

    # Agréger les remarques par catégorie
    objets_manquants = []
    degradations = []
    proprete_agencement = []
    signalements = []

    for piece in analysis_response.pieces_analysis:
        for issue in piece.issues:
            description = issue.description
            if issue.category == "missing_item":
                objets_manquants.append(description)
            elif issue.category == "damage":
                degradations.append(description)
            elif issue.category in ["cleanliness", "positioning"]:
                proprete_agencement.append(description)

    # Ajouter les signalements utilisateurs
    if input_data.signalements_utilisateur:
        for report in input_data.signalements_utilisateur:
            signalements.append(f"{report.titre} - {report.description}")

    synthese_section = {
        "logement": input_data.logement_adresse or "Adresse non renseignée",
        "voyageur": input_data.voyageur_nom or "Non renseigné",
        "email": input_data.voyageur_email or "",
        "telephone": input_data.voyageur_telephone or "",
        "dateDebut": input_data.date_debut or "",
        "dateFin": input_data.date_fin or "",
        "heureCheckin": input_data.heure_checkin_debut or "",
        "heureCheckout": input_data.heure_checkout_debut or "",
        "heureCheckinFin": input_data.heure_checkin_fin or "",
        "heureCheckoutFin": input_data.heure_checkout_fin or "",
        "noteGenerale": analysis_response.analysis_enrichment.global_score.score,
        "scoreLabel": analysis_response.analysis_enrichment.global_score.label,
        "scoreExplanation": analysis_response.analysis_enrichment.global_score.score_explanation or "",
        "sousNotes": {
            # Scores calculés par catégorie basés sur les issues détectées
            "presenceObjets": category_scores["presenceObjets"],
            "etatObjets": category_scores["etatObjets"],
            "proprete": category_scores["proprete"],
            "agencement": category_scores["agencement"]
        },
        "statut": "Terminé",
        "remarquesGenerales": {
            "objetsManquants": objets_manquants[:5],  # Limiter à 5
            "degradations": degradations[:5],
            "propreteAgencement": proprete_agencement[:5],
            "signalements": signalements
        }
    }

    # ═══════════════════════════════════════════════════════════════
    # 3. REMARQUES GENERALES SECTION
    # ═══════════════════════════════════════════════════════════════

    # Compter tous les issues
    all_issues = []
    for piece in analysis_response.pieces_analysis:
        all_issues.extend(piece.issues)

    total_counts = count_issues_by_category(all_issues)

    # Détecter les alertes
    has_wrong_room = total_counts["wrong_room"] > 0
    has_image_quality = total_counts["image_quality"] > 0
    wrong_room_rooms = []
    image_quality_rooms = []

    for piece in analysis_response.pieces_analysis:
        piece_issues = count_issues_by_category(piece.issues)
        if piece_issues["wrong_room"] > 0:
            wrong_room_rooms.append(piece.room_classification.room_name)
        if piece_issues["image_quality"] > 0:
            image_quality_rooms.append(piece.room_classification.room_name)

    # Créer les highlights (faits saillants)
    highlights = []

    # Ajouter les tâches non validées
    for piece_input in input_data.pieces:
        for etape in piece_input.etapes:
            if etape.tache_approuvee is False:
                piece_name = piece_input.nom.capitalize()
                highlights.append(f"Tâche non validée : {etape.task_name} — {piece_name}")

    # Ajouter les issues importantes
    for piece in analysis_response.pieces_analysis:
        piece_name = piece.room_classification.room_name
        for issue in piece.issues[:2]:  # Limiter à 2 par pièce
            category_title = map_category_to_title(issue.category)
            highlights.append(f"{category_title} : {issue.description} — {piece_name}")

    # Limiter à 6 highlights
    highlights = highlights[:6]

    # Créer la liste des pièces avec résumé
    rooms_summary = []
    for i, piece in enumerate(analysis_response.pieces_analysis):
        piece_issues = count_issues_by_category(piece.issues)
        piece_name = piece.room_classification.room_name

        rooms_summary.append({
            "name": piece_name,
            "icon": get_room_icon(piece_name),
            "status": calculate_room_status(len(piece.issues), piece_issues),
            "issues_summary": piece_issues,
            "flags": (
                ["wrong_room"] if piece_issues["wrong_room"] > 0 else []
            ) + (
                ["qualité"] if piece_issues["image_quality"] > 0 else []
            ),
            "link": f"/rapport/{input_data.rapport_id}/piece/{piece.piece_id}"
        })

    # Traiter les signalements utilisateurs
    user_reports_list = []
    if input_data.signalements_utilisateur:
        for report in input_data.signalements_utilisateur:
            # Trouver le nom de la pièce
            piece_name = "Non spécifié"
            for piece_input in input_data.pieces:
                if piece_input.piece_id == report.piece_id:
                    piece_name = piece_input.nom.capitalize()
                    break

            user_reports_list.append({
                "text": report.titre,
                "status": "confirmé",  # Par défaut, à améliorer avec logique de vérification
                "room": piece_name
            })

    # Compter les photos
    total_checkin_photos = sum(len(p.checkin_pictures) for p in input_data.pieces)
    total_checkout_photos = sum(len(p.checkout_pictures) for p in input_data.pieces)

    remarques_generales_section = {
        "scope": "logement",
        "meta": {
            "logementId": input_data.logement_adresse or input_data.logement_id,
            "rapportId": input_data.rapport_id,
            "dateGeneration": now.strftime("%d/%m/%Y"),
            "heureGeneration": now.strftime("%H:%M"),
            "photosCheckin": total_checkin_photos,
            "photosCheckout": total_checkout_photos
        },
        "counts": total_counts,
        "alerts": {
            "wrong_room": has_wrong_room,
            "image_quality": has_image_quality,
            "wrong_room_rooms": wrong_room_rooms,
            "image_quality_rooms": image_quality_rooms
        },
        "highlights": highlights,
        "user_reports": user_reports_list,
        "rooms": rooms_summary
    }

    # ═══════════════════════════════════════════════════════════════
    # 4. DETAIL PAR PIECE SECTION
    # ═══════════════════════════════════════════════════════════════

    detail_par_piece_section = []

    for piece_analysis in analysis_response.pieces_analysis:
        # Trouver les données d'entrée correspondantes
        piece_input = next(
            (p for p in input_data.pieces if p.piece_id == piece_analysis.piece_id),
            None
        )

        if not piece_input:
            continue

        piece_name = piece_analysis.room_classification.room_name
        piece_icon = get_room_icon(piece_name)

        # Photos de référence
        # Si photos_reference est null ou vide, utiliser les checkin_pictures comme fallback
        photos_reference = piece_input.photos_reference or []
        if not photos_reference:
            photos_reference = [pic.url for pic in piece_input.checkin_pictures]

        # Check d'entrée
        check_entree = {
            "estConforme": piece_input.check_entree_conforme if piece_input.check_entree_conforme is not None else True,
            "dateHeureValidation": piece_input.check_entree_date_validation or "",
            "photosReprises": piece_input.check_entree_photos_reprises or []
        }

        # Check de sortie
        photos_sortie = [pic.url for pic in piece_input.checkout_pictures]
        check_sortie = {
            "estValide": piece_input.check_sortie_valide if piece_input.check_sortie_valide is not None else True,
            "dateHeureValidation": piece_input.check_sortie_date_validation or "",
            "photosSortie": photos_sortie,
            "photosNonConformes": piece_input.check_sortie_photos_non_conformes or []
        }

        # ═══════════════════════════════════════════════════════════════
        # 🆕 ÉTAPE 1: Créer un mapping etape_id → validation_status depuis les issues IA
        # ═══════════════════════════════════════════════════════════════
        etape_validation_status_map = {}
        for issue in piece_analysis.issues:
            if hasattr(issue, 'etape_id') and issue.etape_id and hasattr(issue, 'validation_status') and issue.validation_status:
                # Garder le statut le plus restrictif si plusieurs issues pour la même étape
                current_status = etape_validation_status_map.get(issue.etape_id)
                if current_status is None:
                    etape_validation_status_map[issue.etape_id] = issue.validation_status
                elif current_status == "VALIDÉ" and issue.validation_status in ["NON_VALIDÉ", "INCERTAIN"]:
                    etape_validation_status_map[issue.etape_id] = issue.validation_status
                elif current_status == "INCERTAIN" and issue.validation_status == "NON_VALIDÉ":
                    etape_validation_status_map[issue.etape_id] = issue.validation_status

        # ═══════════════════════════════════════════════════════════════
        # 🆕 ÉTAPE 2: Construire tachesValidees avec estApprouve basé sur validation_status IA
        # ═══════════════════════════════════════════════════════════════
        taches_validees = []
        for etape in piece_input.etapes:
            # Récupérer le validation_status de l'IA pour cette étape
            ia_validation_status = etape_validation_status_map.get(etape.etape_id)

            # Déterminer estApprouve selon la logique suivante :
            # 1. Si PAS d'analyse IA (ia_validation_status absent) → utiliser tache_approuvee tel quel (ou True par défaut)
            # 2. Si analyse IA disponible → utiliser le statut IA (sauf si surcharge manuelle explicite)

            if ia_validation_status is None:
                # Pas d'analyse IA → respecter la valeur manuelle ou True par défaut
                est_approuve = etape.tache_approuvee if etape.tache_approuvee is not None else True
            else:
                # Analyse IA disponible
                if etape.tache_approuvee is not None:
                    # Surcharge manuelle explicite → prioritaire
                    est_approuve = etape.tache_approuvee
                else:
                    # Utiliser le statut IA
                    est_approuve = (ia_validation_status == "VALIDÉ")

            taches_validees.append({
                "etapeId": etape.etape_id,
                "nom": etape.task_name,
                "consigne": etape.consigne,  # ✅ Consigne/instruction de la tâche
                "checkingPicture": etape.checking_picture,  # ✅ Photo de référence (checkin)
                "checkoutPicture": etape.checkout_picture,  # ✅ Photo de validation (checkout)
                "estApprouve": est_approuve,
                "dateHeureValidation": etape.tache_date_validation or "",
                "commentaire": etape.tache_commentaire,
                "validationStatusIA": ia_validation_status  # Statut IA pour référence
            })

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 3: Construire la liste des problèmes détectés par l'IA
        # ═══════════════════════════════════════════════════════════════
        problemes = []
        for idx, issue in enumerate(piece_analysis.issues):
            category_title = map_category_to_title(issue.category)
            probleme_dict = {
                "id": f"p{idx+1}",
                "titre": f"{category_title} : {issue.description[:50]}...",
                "description": issue.description,
                "severite": map_severity(issue.severity),
                "detectionIA": True,
                "consignesIA": [],
                "estFaux": False
            }

            # ✅ Ajouter etapeId si l'issue provient d'une étape
            if hasattr(issue, 'etape_id') and issue.etape_id:
                probleme_dict["etapeId"] = issue.etape_id

            # 🆕 Ajouter validation_status si disponible
            if hasattr(issue, 'validation_status') and issue.validation_status:
                probleme_dict["validationStatus"] = issue.validation_status

            # 🆕 Ajouter commentaireIA si disponible
            if hasattr(issue, 'commentaire') and issue.commentaire:
                probleme_dict["commentaireIA"] = issue.commentaire

            # 📸 NOUVEAU: Ajouter photoUrl pour chaque problème
            photo_url = get_photo_url_for_issue(issue, piece_input)
            probleme_dict["photoUrl"] = photo_url

            problemes.append(probleme_dict)

        # Consignes IA (extraites du commentaire global)
        consignes_ia = []
        if piece_analysis.analyse_globale and piece_analysis.analyse_globale.commentaire_global:
            # Extraire des consignes du commentaire
            commentaire = piece_analysis.analyse_globale.commentaire_global
            if "surveiller" in commentaire.lower():
                consignes_ia.append(f"Surveiller {piece_name}")
            if "vérifier" in commentaire.lower():
                consignes_ia.append(f"Vérifier l'état de {piece_name}")

        # Résumé de la pièce
        resume = piece_analysis.analyse_globale.commentaire_global if piece_analysis.analyse_globale else ""

        # Note de la pièce (base IA)
        note_base = piece_analysis.analyse_globale.score if piece_analysis.analyse_globale else 3

        # ═══════════════════════════════════════════════════════════════
        # 🆕 CALCUL DU MALUS BASÉ SUR LES ISSUES D'ÉTAPES
        # ═══════════════════════════════════════════════════════════════

        # Déterminer si c'est un parcours Ménage (plus sévère) ou Voyageur
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        is_menage = parcours_type.lower() == "ménage" or parcours_type.lower() == "menage"

        # Barème différencié : Ménage = +50% plus sévère
        if is_menage:
            # Ménage : travail professionnel attendu, on est strict
            MALUS_HIGH = 1.2       # Issue grave = -1.2 point
            MALUS_MEDIUM = 0.6     # Issue modérée = -0.6 point
            MALUS_LOW = 0.25       # Issue légère = -0.25 point
            MALUS_NON_VALIDE = 0.8 # Étape non validée sans détail = -0.8
            MALUS_SIGNALEMENT = 0.4  # Par signalement
            MALUS_MAX = 3.5        # Plafond plus haut
        else:
            # Voyageur : plus tolérant
            MALUS_HIGH = 0.8       # Issue grave = -0.8 point
            MALUS_MEDIUM = 0.4     # Issue modérée = -0.4 point
            MALUS_LOW = 0.15       # Issue légère = -0.15 point
            MALUS_NON_VALIDE = 0.5 # Étape non validée sans détail = -0.5
            MALUS_SIGNALEMENT = 0.3  # Par signalement
            MALUS_MAX = 3.0        # Plafond

        # Récupérer les issues d'étapes pour cette pièce depuis piece_analysis
        issues_etapes_piece = []
        if hasattr(piece_analysis, 'issues') and piece_analysis.issues:
            for issue in piece_analysis.issues:
                # Les issues d'étapes ont un etape_id ou validation_status
                if hasattr(issue, 'etape_id') and issue.etape_id:
                    issues_etapes_piece.append(issue)
                elif hasattr(issue, 'validation_status') and issue.validation_status:
                    issues_etapes_piece.append(issue)

        # Calculer le malus basé sur la sévérité des issues d'étapes
        malus_issues_etapes = 0.0
        issues_high = 0
        issues_medium = 0
        issues_low = 0

        for issue in issues_etapes_piece:
            # Ignorer les étapes VALIDÉES (ne doivent pas impacter la note)
            if hasattr(issue, 'validation_status') and issue.validation_status == "VALIDÉ":
                continue

            severity = issue.severity if hasattr(issue, 'severity') else "low"
            if severity == "high":
                malus_issues_etapes += MALUS_HIGH
                issues_high += 1
            elif severity == "medium":
                malus_issues_etapes += MALUS_MEDIUM
                issues_medium += 1
            else:  # low (INCERTAIN)
                malus_issues_etapes += MALUS_LOW
                issues_low += 1

        # Compter les étapes NON_VALIDÉ/INCERTAIN depuis le mapping IA
        etapes_non_validees = sum(1 for status in etape_validation_status_map.values() if status == "NON_VALIDÉ")

        # Malus additionnel si des étapes NON_VALIDÉ sans issues détaillées
        if etapes_non_validees > 0 and issues_high == 0 and issues_medium == 0:
            malus_issues_etapes += etapes_non_validees * MALUS_NON_VALIDE

        # Compter les signalements utilisateurs pour cette pièce
        signalements_piece = 0
        if input_data.signalements_utilisateur:
            signalements_piece = sum(1 for s in input_data.signalements_utilisateur if s.piece_id == piece_input.piece_id)

        # Malus pour signalements (plafonné à 1.5 point max)
        malus_signalements = min(signalements_piece * MALUS_SIGNALEMENT, 1.5)

        # Malus total (plafonné selon le parcours)
        malus_total = min(malus_issues_etapes + malus_signalements, MALUS_MAX)

        # Appliquer le malus (minimum 1.0 pour garder une note)
        note = max(1.0, note_base - malus_total)

        # Log détaillé si malus appliqué
        if malus_total > 0:
            details = []
            if issues_high > 0:
                details.append(f"{issues_high} grave(s)")
            if issues_medium > 0:
                details.append(f"{issues_medium} modérée(s)")
            if issues_low > 0:
                details.append(f"{issues_low} légère(s)")
            if signalements_piece > 0:
                details.append(f"{signalements_piece} signalement(s)")
            mode = "MÉNAGE" if is_menage else "VOYAGEUR"
            logger.info(f"📉 [{mode}] Pièce {piece_name}: {note_base:.1f} → {note:.1f} (-{malus_total:.1f}: {', '.join(details)})")

        detail_par_piece_section.append({
            "id": piece_input.piece_id,
            "nom": piece_name,
            "pieceIcon": piece_icon,
            "note": note,
            "resume": resume,
            "photosReference": photos_reference,
            "checkEntree": check_entree,
            "checkSortie": check_sortie,
            "tachesValidees": taches_validees,
            "problemes": problemes,
            "consignesIA": consignes_ia
        })

    # ═══════════════════════════════════════════════════════════════
    # 5. CHECK FINAL SECTION
    # ═══════════════════════════════════════════════════════════════

    check_final_section = []
    if input_data.checklist_finale:
        for item in input_data.checklist_finale:
            check_final_section.append({
                "id": item.id,
                "text": item.text,
                "completed": item.completed,
                "icon": item.icon,
                "photo": item.photo
            })

    # ═══════════════════════════════════════════════════════════════
    # 6. SUGGESTIONS IA SECTION
    # ═══════════════════════════════════════════════════════════════

    suggestions_ia_section = []

    # Utiliser les recommandations de l'enrichissement
    if analysis_response.analysis_enrichment.recommendations:
        for idx, recommendation in enumerate(analysis_response.analysis_enrichment.recommendations):
            # Déterminer la priorité basée sur l'ordre
            if idx == 0:
                priorite = "haute"
            elif idx < 3:
                priorite = "moyenne"
            else:
                priorite = "basse"

            suggestions_ia_section.append({
                "titre": recommendation[:80],  # Titre court
                "description": recommendation,
                "priorite": priorite
            })

    # ═══════════════════════════════════════════════════════════════
    # 7. UI LABELS (STATIQUES)
    # ═══════════════════════════════════════════════════════════════

    ui_labels = {
        "header": {
            "title": "Rapport Check Easy",
            "closeButton": "Fermer"
        },
        "syntheseSection": {
            "title": "Synthèse",
            "voyageurTitle": "Voyageur",
            "checkEntreeTitle": "Check d'entrée",
            "checkSortieTitle": "Check de sortie",
            "noteGeneraleTitle": "Note Générale",
            "presenceObjetsLabel": "Présence des objets",
            "etatObjetsLabel": "État des objets",
            "propreteLabel": "Propreté",
            "agencementLabel": "Agencement",
            "debutLabel": "Début",
            "finLabel": "Fin"
        },
        "remarquesGeneralesSection": {
            "title": "Remarques Générales",
            "alerteTitle": "Problèmes d'analyse photos",
            "photosNonConformesLabel": "Photos non conformes",
            "qualiteInsuffisanteLabel": "Qualité insuffisante",
            "faitsSaillantsTitle": "Faits important analysés par l'IA",
            "signalementsUtilisateursTitle": "Signalements utilisateurs",
            "aTraiterLabel": "À traiter",
            "resoluLabel": "Résolu"
        },
        "detailParPieceSection": {
            "title": "Détail par Pièce",
            "photosReferenceLabel": "Voir les {count} photo(s) de référence",
            "etatLieuxEntreeLabel": "État des lieux d'entrée",
            "etatLieuxSortieLabel": "État des lieux de sortie",
            "conformeLabel": "Conforme aux photos de référence",
            "nonConformeLabel": "Non conforme aux photos de référence",
            "valideLabel": "Validé",
            "nonValideLabel": "Non validé",
            "tachesRealisees": "Tâches réalisées",
            "commentaireGlobalLabel": "Commentaire global",
            "faitsSignalesIATitle": "Faits signalés par l'IA",
            "consignesIATitle": "Consignes pour l'IA",
            "aIgnorerLabel": "À ignorer",
            "aSurveillerLabel": "À surveiller en priorité",
            "ajouterButton": "Ajouter",
            "modifierButton": "Modifier",
            "supprimerButton": "Supprimer",
            "creerSignalementButton": "Créer un signalement",
            "ajouterConsigneIAButton": "Ajouter aux consignes IA",
            "marquerCommeFauxButton": "Marquer comme faux"
        },
        "checkFinalSection": {
            "title": "Check final"
        },
        "suggestionsIASection": {
            "title": "Suggestions de l'IA"
        },
        "badges": {
            "tacheNonRealisee": "{count} tâche(s) non réalisée(s)",
            "faitSignale": "{count} fait(s) signalé(s) par l'IA",
            "signalementCree": "Signalement créé",
            "consigneIAAjoutee": "Consigne IA ajoutée",
            "marqueCommeFaux": "Marqué comme faux"
        },
        "severite": {
            "faible": "Faible",
            "moyenne": "Moyenne",
            "elevee": "Élevée"
        },
        "status": {
            "ok": "OK",
            "attention": "Attention",
            "probleme": "Problème",
            "termine": "Terminé",
            "expire": "Expiré",
            "enCours": "En cours"
        },
        "typeParcours": {
            "voyageur": "Voyageur",
            "menage": "Ménage"
        },
        "etatLieuxMoment": {
            "sortie": "Sortie uniquement",
            "arriveeSortie": "Arrivée + Sortie"
        }
    }

    # ═══════════════════════════════════════════════════════════════
    # RETOUR DU PAYLOAD COMPLET
    # ═══════════════════════════════════════════════════════════════

    return {
        "reportMetadata": report_metadata,
        "syntheseSection": synthese_section,
        "remarquesGeneralesSection": remarques_generales_section,
        "detailParPieceSection": detail_par_piece_section,
        "checkFinalSection": check_final_section,
        "suggestionsIASection": suggestions_ia_section,
        "uiLabels": ui_labels
    }


# ═══════════════════════════════════════════════════════════════
# SYSTÈME DE NOTATION V2 - Note = 5 - Σ(pénalités)
# ═══════════════════════════════════════════════════════════════

def calculate_weighted_severity_score(
    pieces_analysis: List[CombinedAnalysisResponse],
    general_issues_count: int,
    etapes_issues_count: int,
    parcours_type: str = "Voyageur"
) -> dict:
    """
    Calcule le score global du logement.

    🆕 NOUVELLE LOGIQUE V2 : Moyenne pondérée des NOTES (pas des scores bruts)

    1. Chaque pièce a sa note calculée via: Note = 5 - Σ(pénalités)
    2. Le score global = moyenne pondérée des notes de chaque pièce
    3. Simple, prévisible, logique !

    Returns:
        dict: {
            "weighted_average_grade": float,  # Note moyenne pondérée
            "total_weight": float,
            "final_grade": float,
            "label": str,
            "room_scores": list,
            "summary": dict
        }
    """

    logger.debug("")
    logger.debug("═" * 80)
    logger.info("🧮 CALCUL DU SCORE GLOBAL V2 - Moyenne pondérée des NOTES")
    logger.debug("═" * 80)

    # Debug logging
    logger.debug(f"🔍 DEBUG - calculate_weighted_severity_score reçoit:")
    logger.debug(f"   - {len(pieces_analysis)} pièces")
    logger.debug(f"   - {general_issues_count} issues générales")
    logger.debug(f"   - {etapes_issues_count} issues d'étapes")

    config = load_scoring_config(parcours_type)
    scoring_config = config.get("scoring_system", {})

    logger.debug(f"📊 Configuration chargée pour: {parcours_type}")

    # Paramètres de configuration
    SEVERITY_PENALTY = scoring_config.get("severity_penalty", {"low": 0.1, "medium": 0.3, "high": 0.8})
    CATEGORY_MULTIPLIER = scoring_config.get("category_multiplier", {
        "damage": 1.5, "cleanliness": 1.0, "missing_item": 1.2,
        "positioning": 0.5, "added_item": 0.4, "image_quality": 0.3, "wrong_room": 2.0, "other": 1.0
    })
    ROOM_IMPORTANCE_WEIGHT = scoring_config.get("room_importance_weight", {
        "cuisine": 2.0, "salle_de_bain": 1.8, "salle_de_bain_et_toilettes": 1.8,
        "salle_d_eau": 1.7, "salle_d_eau_et_wc": 1.7, "wc": 1.5,
        "salon": 1.2, "salon_cuisine": 1.8, "chambre": 1.0, "bureau": 1.0, "entree": 0.8, "exterieur": 0.6,
        "cle": 0.8, "autre": 0.8
    })
    CONFIDENCE_THRESHOLD = scoring_config.get("confidence_threshold", {}).get("value", 90)
    MIN_GRADE = scoring_config.get("min_grade", {}).get("value", 1.0)
    MAX_GRADE = scoring_config.get("max_grade", {}).get("value", 5.0)

    # ═══════════════════════════════════════════════════════════
    # CALCUL DE LA NOTE PAR PIÈCE
    # ═══════════════════════════════════════════════════════════

    room_scores = []
    total_weight = 0
    weighted_grade_sum = 0

    logger.debug(f"")
    logger.debug(f"🔢 CALCUL DES NOTES PAR PIÈCE (Note = 5 - pénalités)")
    logger.debug(f"   📊 Nombre de pièces : {len(pieces_analysis)}")
    logger.debug(f"")

    for idx, piece in enumerate(pieces_analysis, 1):
        room_type = piece.room_classification.room_type
        room_weight = ROOM_IMPORTANCE_WEIGHT.get(room_type, 1.0)

        # Calculer la pénalité totale de cette pièce
        total_penalty = 0
        piece_issues_details = []

        if hasattr(piece, 'issues') and piece.issues:
            for issue in piece.issues:
                if issue.confidence >= CONFIDENCE_THRESHOLD:
                    # Ignorer les étapes VALIDÉES
                    if hasattr(issue, 'validation_status') and issue.validation_status == "VALIDÉ":
                        logger.debug(f"   ⏭️  Étape VALIDÉE ignorée: {issue.description[:50]}")
                        continue

                    # Calculer la pénalité
                    base_penalty = SEVERITY_PENALTY.get(issue.severity, 0.3)
                    category_mult = CATEGORY_MULTIPLIER.get(issue.category, 1.0)
                    issue_penalty = base_penalty * category_mult

                    total_penalty += issue_penalty

                    is_etape_issue = issue.description.startswith("[ÉTAPE]")

                    piece_issues_details.append({
                        "description": issue.description,
                        "category": issue.category,
                        "severity": issue.severity,
                        "penalty": round(issue_penalty, 2),
                        "is_etape": is_etape_issue
                    })

        # Calculer la note de la pièce : Note = MAX_GRADE - pénalité
        piece_grade = max(MIN_GRADE, MAX_GRADE - total_penalty)
        piece_grade = round(piece_grade, 1)

        # Moyenne pondérée des NOTES (pas des pénalités)
        weighted_grade = piece_grade * room_weight
        weighted_grade_sum += weighted_grade
        total_weight += room_weight

        room_scores.append({
            "piece_id": piece.piece_id,
            "room_type": room_type,
            "total_penalty": round(total_penalty, 2),
            "grade": piece_grade,
            "weight": room_weight,
            "weighted_grade": round(weighted_grade, 2),
            "num_issues": len(piece_issues_details),
            "issues_details": piece_issues_details
        })

        logger.info(
            f"   [{idx}] {room_type} (poids {room_weight}) : "
            f"{len(piece_issues_details)} issue(s), "
            f"Note: 5 - {total_penalty:.2f} = {piece_grade}/5"
        )

    # ═══════════════════════════════════════════════════════════
    # CALCUL DE LA MOYENNE PONDÉRÉE DES NOTES
    # ═══════════════════════════════════════════════════════════

    if total_weight > 0:
        final_grade = weighted_grade_sum / total_weight
    else:
        final_grade = MAX_GRADE  # Pas de pièce = note parfaite

    # Arrondir à 1 décimale
    final_grade = round(final_grade, 1)

    # S'assurer que la note est dans les limites
    final_grade = max(MIN_GRADE, min(MAX_GRADE, final_grade))

    # Obtenir le label
    label = get_label_for_grade(final_grade, config)

    logger.debug(f"")
    logger.debug(f"📊 RÉSULTAT GLOBAL :")
    logger.debug(f"   ⚖️  Somme pondérée des notes : {weighted_grade_sum:.2f}")
    logger.debug(f"   📏 Poids total : {total_weight:.2f}")
    logger.debug(f"   🏆 Note finale : {final_grade}/5 ({label})")

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

    for room in room_scores:
        for issue in room["issues_details"]:
            summary["severity_breakdown"][issue["severity"]] += 1
            cat = issue["category"]
            summary["category_breakdown"][cat] = summary["category_breakdown"].get(cat, 0) + 1

        room_type = room["room_type"]
        summary["room_breakdown"][room_type] = summary["room_breakdown"].get(room_type, 0) + room["num_issues"]

    return {
        "weighted_average_grade": final_grade,
        "total_weight": round(total_weight, 2),
        "final_grade": final_grade,
        "label": label,
        "room_scores": room_scores,
        "summary": summary
    }


def get_label_for_grade(grade: float, config: dict) -> str:
    """
    Retourne le label correspondant à une note.

    NOUVELLE LOGIQUE V2 : Utilise les plages de labels définies dans la config.

    Args:
        grade: Note sur 5
        config: Configuration du scoring

    Returns:
        str: Label (EXCELLENT, TRÈS BON, BON, etc.)
    """
    # Récupérer les plages de labels
    labels_config = config.get("labels", {})
    ranges = labels_config.get("ranges", [])

    # Fallback si pas de config labels
    if not ranges:
        if grade >= 4.5:
            return "EXCELLENT"
        elif grade >= 4.0:
            return "TRÈS BON"
        elif grade >= 3.5:
            return "BON"
        elif grade >= 3.0:
            return "CORRECT"
        elif grade >= 2.5:
            return "MOYEN"
        elif grade >= 2.0:
            return "PASSABLE"
        elif grade >= 1.5:
            return "INSUFFISANT"
        else:
            return "CRITIQUE"

    # Chercher dans les plages configurées
    for range_item in ranges:
        if range_item["min"] <= grade <= range_item["max"]:
            return range_item["label"]

    return "CRITIQUE"


def calculate_room_algorithmic_score(
    issues: List[Probleme],
    parcours_type: str = "Voyageur"
) -> dict:
    """
    Calcule le score algorithmique d'une pièce basé sur ses issues.

    🆕 NOUVELLE LOGIQUE V2 : Note = 5 - Σ(pénalité × multiplicateur)

    Simple, prévisible, pas de seuils arbitraires :
    - Chaque issue retire directement des points
    - HIGH retire plus que MEDIUM, MEDIUM plus que LOW
    - Les multiplicateurs de catégorie ajustent l'importance relative

    Args:
        issues: Liste des issues détectées dans la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        dict: {
            "total_penalty": float,   # Total des pénalités
            "note_sur_5": float,      # Note finale sur 5 (1.0 à 5.0)
            "label": str,             # Label (EXCELLENT, BON, PASSABLE, etc.)
            "issues_count": int,      # Nombre d'issues prises en compte
            "issues_details": list    # Détails des issues avec leur pénalité
        }
    """
    config = load_scoring_config(parcours_type)
    scoring_config = config.get("scoring_system", {})

    # 🆕 NOUVELLE CONFIG : severity_penalty (pénalités directes)
    SEVERITY_PENALTY = scoring_config.get("severity_penalty", {"low": 0.1, "medium": 0.3, "high": 0.8})
    CATEGORY_MULTIPLIER = scoring_config.get("category_multiplier", {
        "damage": 1.5, "cleanliness": 1.0, "missing_item": 1.2,
        "positioning": 0.5, "added_item": 0.4, "image_quality": 0.3, "wrong_room": 2.0, "other": 1.0
    })
    CONFIDENCE_THRESHOLD = scoring_config.get("confidence_threshold", {}).get("value", 90)

    # 🔍 DEBUG: Afficher les valeurs chargées
    logger.debug(f"🔧 calculate_room_algorithmic_score - Config chargée pour '{parcours_type}':")
    logger.debug(f"   SEVERITY_PENALTY: {SEVERITY_PENALTY}")
    logger.debug(f"   CATEGORY_MULTIPLIER: {CATEGORY_MULTIPLIER}")
    logger.debug(f"   CONFIDENCE_THRESHOLD: {CONFIDENCE_THRESHOLD}")
    logger.debug(f"   Nombre d'issues à traiter: {len(issues)}")
    MIN_GRADE = scoring_config.get("min_grade", {}).get("value", 1.0)
    MAX_GRADE = scoring_config.get("max_grade", {}).get("value", 5.0)

    # Calculer la somme des pénalités
    total_penalty = 0
    issues_details = []

    for issue in issues:
        if issue.confidence >= CONFIDENCE_THRESHOLD:
            # Ignorer les étapes VALIDÉES (ne doivent pas impacter la note)
            if hasattr(issue, 'validation_status') and issue.validation_status == "VALIDÉ":
                logger.debug(f"   ⏭️  Étape VALIDÉE ignorée: {issue.description[:50]}")
                continue

            # Récupérer la pénalité de base selon la sévérité
            base_penalty = SEVERITY_PENALTY.get(issue.severity, 0.3)

            # Récupérer le multiplicateur de catégorie
            category_mult = CATEGORY_MULTIPLIER.get(issue.category, 1.0)

            # Calculer la pénalité finale pour cette issue
            issue_penalty = base_penalty * category_mult

            total_penalty += issue_penalty

            # Détecter si c'est une issue d'étape
            is_etape_issue = issue.description.startswith("[ÉTAPE]")

            issues_details.append({
                "description": issue.description[:50] + "..." if len(issue.description) > 50 else issue.description,
                "category": issue.category,
                "severity": issue.severity,
                "penalty": round(issue_penalty, 2),
                "is_etape": is_etape_issue
            })

    # 🆕 NOUVELLE FORMULE : Note = MAX_GRADE - total_penalty
    # Avec un minimum de MIN_GRADE
    grade = max(MIN_GRADE, MAX_GRADE - total_penalty)

    # Arrondir à 1 décimale
    grade = round(grade, 1)

    # Obtenir le label correspondant
    label = get_label_for_grade(grade, config)

    logger.debug(f"   🧮 Score pièce: 5 - {total_penalty:.2f} = {grade}/5 ({label})")

    return {
        "total_penalty": round(total_penalty, 2),
        "note_sur_5": grade,
        "label": label,
        "issues_count": len(issues_details),
        "issues_details": issues_details
    }


def generate_logement_enrichment(logement_id: str, pieces_analysis: List[CombinedAnalysisResponse], total_issues: int, general_issues: int, etapes_issues: int, parcours_type: str = "Voyageur", request_id: str = None) -> LogementAnalysisEnrichment:
    """
    Générer une synthèse globale et des recommandations pour le logement

    VERSION AVEC SYSTÈME DE NOTATION ALGORITHMIQUE (APPROCHE 2)
    - Le score est calculé de manière déterministe via calculate_weighted_severity_score()
    - L'IA génère uniquement le summary et les recommendations
    - Plus de variabilité, plus de traçabilité, plus d'équité
    """
    try:
        # 🛡️ LOGS D'ENTRÉE DÉTAILLÉS
        logger.debug(f"🚀 DÉBUT generate_logement_enrichment pour logement {logement_id}")
        logger.debug(f"   📊 Paramètres reçus:")
        logger.debug(f"   - total_issues: {total_issues}")
        logger.debug(f"   - general_issues: {general_issues}")
        logger.debug(f"   - etapes_issues: {etapes_issues}")
        logger.debug(f"   - pieces_analysis: {len(pieces_analysis)} pièces")

        # ═══════════════════════════════════════════════════════════
        # ÉTAPE 0 : CALCUL DU SCORE ALGORITHMIQUE (NOUVEAU)
        # ═══════════════════════════════════════════════════════════

        logger.debug(f"")
        logger.debug(f"🎯 ÉTAPE 0 - CALCUL DU SCORE ALGORITHMIQUE")
        logger.debug(f"   📊 Utilisation du système de notation à score pondéré (APPROCHE 2)")

        score_result = calculate_weighted_severity_score(
            pieces_analysis=pieces_analysis,
            general_issues_count=general_issues,
            etapes_issues_count=etapes_issues,
            parcours_type=parcours_type
        )

        algorithmic_score = score_result["final_grade"]
        algorithmic_label = score_result["label"]
        weighted_average = score_result["weighted_average_score"]

        logger.debug(f"")
        logger.debug(f"✅ SCORE ALGORITHMIQUE CALCULÉ :")
        logger.debug(f"   🏆 Note finale : {algorithmic_score}/5")
        logger.debug(f"   🏷️  Label : {algorithmic_label}")
        logger.debug(f"   📊 Score moyen pondéré : {weighted_average:.2f}")
        logger.debug(f"   📈 Nombre de pièces : {score_result['summary']['num_pieces']}")
        logger.debug(f"   📋 Issues analysées : {score_result['summary']['total_issues_analyzed']}")
        logger.debug(f"")
        
        # Vérifier que le client OpenAI est disponible
        if client is None:
            logger.error("❌ Client OpenAI non disponible pour l'enrichissement")
            raise HTTPException(status_code=503, detail="Service OpenAI non disponible")

        # 🔍 ÉTAPE 1: Créer un résumé structuré des problèmes détectés
        logger.debug(f"🔍 ÉTAPE 1 - Création du résumé structuré des problèmes")
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
                logger.debug(f"   🔽 Pièce {piece.piece_id}: {issues_filtrees} issues filtrées (confiance < 90%)")
            
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
                logger.debug(f"   📋 Pièce {i+1} ({piece.piece_id}): {len(piece_issues)} issues qualifiées ajoutées")
            else:
                logger.debug(f"   ✅ Pièce {i+1} ({piece.piece_id}): Aucune issue qualifiée")

        logger.debug(f"✅ Résumé créé: {pieces_avec_problemes}/{len(pieces_analysis)} pièces avec problèmes qualifiés")
        logger.debug(f"ℹ️ L'IA évaluera la note globale selon son ressenti général, indépendamment du comptage d'issues")
        
        # 🔍 ÉTAPE 2: Construire le prompt pour la synthèse globale
        logger.debug(f"🔍 ÉTAPE 2 - Construction du prompt de synthèse")
        
        try:
            prompts_config = load_prompts_config(parcours_type)
            synthesis_global_config = prompts_config.get("prompts", {}).get("synthesis_global", {})
            
            # Préparer les variables pour le template
            variables = {
                "logement_id": logement_id,
                "total_issues": total_issues,
                "general_issues": general_issues,
                "etapes_issues": etapes_issues,
                "issues_summary": json.dumps(issues_summary, indent=2, ensure_ascii=False)
            }
            
            logger.debug(f"   📋 Variables préparées pour le template:")
            logger.debug(f"   - logement_id: {logement_id}")
            logger.debug(f"   - total_issues: {total_issues}")
            logger.debug(f"   - issues_summary: {len(issues_summary)} pièces")
            
            # Utiliser la fonction standardisée
            synthesis_prompt = build_full_prompt_from_config(synthesis_global_config, variables)
            
            if not synthesis_prompt or len(synthesis_prompt) < 200:
                raise ValueError("Prompt de synthèse vide")
            
            logger.debug(f"✅ Prompt construit: {len(synthesis_prompt)} caractères")

            # 🔍 LOG DÉTAILLÉ DU PROMPT POUR DEBUG
            logger.info(f"📋 PROMPT DE SYNTHÈSE (premiers 500 caractères):")
            logger.debug(synthesis_prompt[:500])
            logger.info(f"📋 PROMPT DE SYNTHÈSE (derniers 500 caractères):")
            logger.debug(synthesis_prompt[-500:])

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
            logger.debug(f"✅ Prompt fallback utilisé: {len(synthesis_prompt)} caractères")

        # 🔍 ÉTAPE 3: Faire l'appel API pour la synthèse
        logger.debug(f"🔍 ÉTAPE 3 - Appel à l'IA de synthèse (OpenAI)")

        try:
            logger.debug(f"   🤖 Modèle: {OPENAI_MODEL}")
            logger.debug(f"   🌡️ Température: 0.1")
            logger.debug(f"   📏 Max tokens: 16000")

            # 📝 LOG DU PROMPT DE SYNTHÈSE
            if request_id:
                logs_manager.add_prompt_log(
                    request_id=request_id,
                    prompt_type="Synthesis",
                    prompt_content=synthesis_prompt,
                    model=OPENAI_MODEL
                )

            # 🚀 MIGRATION vers Responses API
            messages = [
                {
                    "role": "system",
                    "content": synthesis_prompt
                },
                {
                    "role": "user",
                    "content": f"Génère la synthèse globale pour le logement {logement_id} basée sur les données d'inspection fournies."
                }
            ]
            input_content = convert_chat_messages_to_responses_input(messages)

            response = client.responses.create(
                model=OPENAI_MODEL,
                input=input_content,
                text={"format": {"type": "json_object"}},
                max_output_tokens=12000,
                reasoning={"effort": "medium"}
            )

            logger.debug(f"✅ Réponse OpenAI reçue avec succès")

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
        logger.debug(f"🔍 ÉTAPE 4 - Parsing et validation de la réponse IA")

        # 🚀 MIGRATION: Extraction depuis Responses API
        response_content = (response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)).strip()
        logger.debug(f"   📄 Longueur réponse: {len(response_content)} caractères")

        # 📝 LOG DE LA RÉPONSE DE SYNTHÈSE
        if request_id:
            logs_manager.add_response_log(
                request_id=request_id,
                response_type="Synthesis",
                response_content=response_content,
                model=OPENAI_MODEL,
                tokens_used=extract_usage_tokens(response)
            )

        # Valider que c'est du JSON valide
        try:
            enrichment_data = json.loads(response_content)
            logger.debug(f"✅ JSON parsé avec succès")
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
            logger.debug(f"   ℹ️  Score IA reçu (ignoré) : {ia_score}/5")
            logger.debug(f"   ✅ Score algorithmique utilisé : {algorithmic_score}/5")

        # Créer la description technique du score (pour les logs/debug)
        score_description = (
            f"Score calculé algorithmiquement : {weighted_average:.2f} points "
            f"(moyenne pondérée sur {score_result['summary']['num_pieces']} pièces). "
            f"{score_result['summary']['total_issues_analyzed']} issues analysées "
            f"(H:{score_result['summary']['severity_breakdown']['high']}, "
            f"M:{score_result['summary']['severity_breakdown']['medium']}, "
            f"L:{score_result['summary']['severity_breakdown']['low']})."
        )

        # ═══════════════════════════════════════════════════════════
        # 🆕 GÉNÉRATION DE L'EXPLICATION COMPRÉHENSIBLE
        # ═══════════════════════════════════════════════════════════
        severity_breakdown = score_result['summary']['severity_breakdown']
        num_pieces = score_result['summary']['num_pieces']
        total_issues = score_result['summary']['total_issues_analyzed']

        # Construire une explication en langage naturel
        if total_issues == 0:
            score_explanation = f"Aucun problème détecté sur les {num_pieces} pièces analysées. État impeccable !"
        else:
            # Décrire les issues par sévérité
            issues_parts = []
            if severity_breakdown['high'] > 0:
                issues_parts.append(f"{severity_breakdown['high']} problème{'s' if severity_breakdown['high'] > 1 else ''} important{'s' if severity_breakdown['high'] > 1 else ''}")
            if severity_breakdown['medium'] > 0:
                issues_parts.append(f"{severity_breakdown['medium']} problème{'s' if severity_breakdown['medium'] > 1 else ''} modéré{'s' if severity_breakdown['medium'] > 1 else ''}")
            if severity_breakdown['low'] > 0:
                issues_parts.append(f"{severity_breakdown['low']} détail{'s' if severity_breakdown['low'] > 1 else ''} mineur{'s' if severity_breakdown['low'] > 1 else ''}")

            issues_text = ", ".join(issues_parts) if issues_parts else "quelques observations"

            # Phrase d'introduction selon la note
            if algorithmic_score >= 4.5:
                intro = "Très bon état global."
            elif algorithmic_score >= 4.0:
                intro = "Bon état général avec quelques points à noter."
            elif algorithmic_score >= 3.5:
                intro = "État correct, plusieurs éléments à améliorer."
            elif algorithmic_score >= 3.0:
                intro = "État moyen, des améliorations sont nécessaires."
            else:
                intro = "État insuffisant, intervention requise."

            score_explanation = f"{intro} Sur {num_pieces} pièce{'s' if num_pieces > 1 else ''} analysée{'s' if num_pieces > 1 else ''}, nous avons relevé {issues_text}. La note reflète l'importance relative des pièces (cuisine et salle de bain comptent davantage)."

        logger.debug(f"   📝 Explication générée: {score_explanation[:100]}...")

        # Valider et créer l'objet LogementAnalysisEnrichment avec le score algorithmique
        try:
            enrichment = LogementAnalysisEnrichment(
                summary=LogementSummary(**enrichment_data["summary"]),
                recommendations=enrichment_data["recommendations"],
                global_score=GlobalScore(
                    score=algorithmic_score,
                    label=algorithmic_label,
                    description=score_description,
                    score_explanation=score_explanation
                )
            )
            logger.debug(f"✅ Objet LogementAnalysisEnrichment créé avec succès")
            logger.debug(f"   🎯 Score final : {algorithmic_score}/5 ({algorithmic_label})")
        except Exception as validation_error:
            logger.error(f"❌ Erreur validation Pydantic: {validation_error}")
            raise ValueError(f"Données invalides: {validation_error}")
        
        logger.debug(f"✅ Synthèse globale générée: Note {enrichment.global_score.score}/5 ({enrichment.global_score.label})")
        logger.debug(f"   📋 {len(enrichment.recommendations)} recommandations formulées")
        logger.debug(f"🎉 FIN generate_logement_enrichment - SUCCÈS")
        
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
        logger.debug(f"🎉 FIN generate_logement_enrichment - FALLBACK")
        return fallback_enrichment

# ═══════════════════════════════════════════════════════════════
# 🚀 FONCTIONS ASYNC POUR PARALLÉLISATION
# ═══════════════════════════════════════════════════════════════

# Import du système de parallélisation optimisé
try:
    from analysis_parallel_integration import get_parallel_executor
    PARALLEL_EXECUTOR_AVAILABLE = True
    logger.info("✅ Système de parallélisation optimisé chargé")
except ImportError as e:
    PARALLEL_EXECUTOR_AVAILABLE = False
    logger.warning(f"⚠️ Système de parallélisation optimisé non disponible: {e}")

async def analyze_single_piece_async(piece: PieceWithEtapes, parcours_type: str = "Voyageur", request_id: str = None) -> CombinedAnalysisResponse:
    """
    Analyse asynchrone d'une seule pièce avec classification automatique
    Version async de la logique dans analyze_complete_logement

    Args:
        piece: Données de la pièce à analyser
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")
        request_id: ID de la requête pour le tracking des logs

    Returns:
        CombinedAnalysisResponse: Résultat de l'analyse combinée
    """
    try:
        logger.debug(f"🔍 [ASYNC] Analyse de la pièce {piece.piece_id}: {piece.nom} (parcours: {parcours_type})")

        # Filtrer les images invalides avant l'analyse
        valid_checkin_pictures = []
        for pic in piece.checkin_pictures:
            logger.debug(f"🔍 Traitement image checkin - URL originale: '{pic.url}'")
            normalized_url = normalize_url(pic.url)
            logger.debug(f"🔍 Traitement image checkin - URL normalisée: '{normalized_url}'")

            if is_valid_image_url(normalized_url):
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkin_pictures.append(normalized_pic)
                logger.debug(f"✅ Image checkin valide ajoutée: {normalized_url}")
            else:
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {pic.url}")
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {normalized_url}")

        valid_checkout_pictures = []
        for pic in piece.checkout_pictures:
            logger.debug(f"🔍 Traitement image checkout - URL originale: '{pic.url}'")
            normalized_url = normalize_url(pic.url)
            logger.debug(f"🔍 Traitement image checkout - URL normalisée: '{normalized_url}'")

            if is_valid_image_url(normalized_url):
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkout_pictures.append(normalized_pic)
                logger.debug(f"✅ Image checkout valide ajoutée: {normalized_url}")
            else:
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {pic.url}")
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {normalized_url}")

        logger.debug(f"📷 Images valides pour pièce {piece.piece_id}: {len(valid_checkin_pictures)} checkin + {len(valid_checkout_pictures)} checkout")

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
        # 🚀 Utiliser run_in_executor pour exécuter dans un thread pool
        # Cela permet la VRAIE parallélisation des pièces via asyncio.gather()
        # Note: Les appels Bubble sont skippés dans ce mode (pas d'event loop dans le thread)
        loop = asyncio.get_running_loop()
        piece_analysis = await loop.run_in_executor(
            None,  # Utilise le ThreadPoolExecutor par défaut
            lambda: analyze_with_auto_classification(input_data_piece, parcours_type, request_id=request_id)
        )

        logger.debug(f"✅ [ASYNC] Pièce {piece.piece_id} analysée: {len(piece_analysis.issues)} issues générales détectées")

        # ═══════════════════════════════════════════════════════════════
        # DOUBLE-PASS: Vérification renforcée des objets manquants
        # 🔴 DÉSACTIVÉ TEMPORAIREMENT (DOUBLE_PASS_ENABLED = False)
        # ═══════════════════════════════════════════════════════════════
        if DOUBLE_PASS_ENABLED and len(valid_checkin_pictures) > 0 and len(valid_checkout_pictures) > 0:
            logger.debug(f"📦 [ASYNC] DOUBLE-PASS: Vérification renforcée des objets manquants pour {piece.nom}")

            try:
                # PHASE 1: Extraction de l'inventaire depuis les photos checkin
                inventory = extract_inventory_from_images(
                    piece_id=piece.piece_id,
                    nom_piece=piece_analysis.nom_piece,
                    checkin_pictures=valid_checkin_pictures
                )

                if inventory.total_objects > 0:
                    logger.debug(f"📦 [ASYNC] PHASE 1 OK: {inventory.total_objects} objets inventoriés")

                    # PHASE 2: Vérification sur les photos checkout
                    verification = verify_inventory_on_checkout(
                        piece_id=piece.piece_id,
                        inventory=inventory,
                        checkout_pictures=valid_checkout_pictures
                    )

                    logger.debug(f"🔎 [ASYNC] PHASE 2 OK: {len(verification.missing_objects)} manquants, {len(verification.moved_objects)} déplacés")

                    # Convertir en issues et fusionner avec les issues existantes
                    inventory_issues = convert_inventory_to_issues(verification)

                    if inventory_issues:
                        # Éviter les doublons: vérifier si l'objet n'est pas déjà signalé
                        existing_descriptions = {issue.description.lower() for issue in piece_analysis.issues}

                        new_issues = []
                        for inv_issue in inventory_issues:
                            # Vérifier si un issue similaire existe déjà
                            is_duplicate = any(
                                inv_issue.description.lower().split(':')[1].strip().split(' - ')[0] in existing_desc
                                for existing_desc in existing_descriptions
                                if ':' in inv_issue.description
                            )

                            if not is_duplicate:
                                new_issues.append(inv_issue)
                                logger.debug(f"   ➕ [ASYNC] Nouvel objet manquant détecté: {inv_issue.description}")

                        # Ajouter les nouvelles issues
                        piece_analysis.issues.extend(new_issues)
                        logger.debug(f"✅ [ASYNC] DOUBLE-PASS: {len(new_issues)} issues ajoutées (total: {len(piece_analysis.issues)})")
                else:
                    logger.debug(f"📦 [ASYNC] PHASE 1: Aucun objet inventorié (pièce peut-être vide ou photos insuffisantes)")

            except Exception as dp_error:
                logger.warning(f"⚠️ [ASYNC] DOUBLE-PASS: Erreur non bloquante - {dp_error}")
                # Le double-pass est optionnel, on continue sans lui en cas d'erreur
        elif not DOUBLE_PASS_ENABLED:
            logger.debug(f"📦 [ASYNC] DOUBLE-PASS: ⏸️ DÉSACTIVÉ (DOUBLE_PASS_ENABLED = False)")
        else:
            logger.debug(f"📦 [ASYNC] DOUBLE-PASS: Skippé (photos insuffisantes: {len(valid_checkin_pictures)} checkin, {len(valid_checkout_pictures)} checkout)")

        return piece_analysis

    except Exception as e:
        logger.error(f"❌ [ASYNC] Erreur lors de l'analyse de la pièce {piece.piece_id}: {str(e)}")
        raise


def apply_two_step_validation_logic_sync(
    validation_status: str,
    issues: list,
    has_checking: bool,
    checking_picture_url: str,
    checkout_picture_url: str,
    etape_id: str,
    task_name: str,
    commentaire: str
) -> tuple:
    """
    🔄 LOGIQUE EN 2 ÉTAPES - Post-traitement de la validation IA (VERSION SYNCHRONE)

    Identique à apply_two_step_validation_logic mais en version synchrone pour analyze_etapes
    """
    try:
        # ═══════════════════════════════════════════════════════════════
        # CAS 1 : VALIDÉ par l'IA → On garde VALIDÉ (ÉTAPE 1 réussie)
        # ═══════════════════════════════════════════════════════════════
        if validation_status == "VALIDÉ":
            logger.debug(f"✅ [2-STEP] Étape {etape_id}: VALIDÉ par IA (ÉTAPE 1 réussie) → Validation confirmée")
            return validation_status, issues, commentaire

        # ═══════════════════════════════════════════════════════════════
        # CAS 2 : NON_VALIDÉ ou INCERTAIN → Vérifier ÉTAPE 2
        # ═══════════════════════════════════════════════════════════════
        if validation_status in ["NON_VALIDÉ", "INCERTAIN"]:
            logger.debug(f"⚠️ [2-STEP] Étape {etape_id}: {validation_status} par IA (ÉTAPE 1 échouée) → Passage à ÉTAPE 2")

            # Si pas de checking_picture, on ne peut pas faire l'ÉTAPE 2
            if not has_checking or not checking_picture_url:
                logger.debug(f"⏭️ [2-STEP] Étape {etape_id}: Pas de checking_picture → Impossible de faire ÉTAPE 2 → Garder {validation_status}")
                return validation_status, issues, commentaire

            # ═══════════════════════════════════════════════════════════════
            # ÉTAPE 2 : Comparer checking vs checkout avec l'IA
            # ═══════════════════════════════════════════════════════════════
            logger.debug(f"🔍 [2-STEP] Étape {etape_id}: Comparaison checking vs checkout...")

            # Construire un prompt simple pour comparer les deux images
            comparison_prompt = f"""Tu es un expert en comparaison d'images.

🎯 OBJECTIF : Déterminer si deux photos montrent le MÊME ÉTAT ou un état DIFFÉRENT.

📸 CONTEXTE :
- Photo 1 (AVANT) : État initial
- Photo 2 (APRÈS) : État final
- Tâche : {task_name}

🔍 QUESTION :
Les deux photos montrent-elles le MÊME ÉTAT (équivalent) ou un état DIFFÉRENT (dégradé/amélioré) ?

⚠️ RÈGLES :
- Ignore les différences d'angle, de luminosité, de cadrage
- Concentre-toi sur l'ÉTAT RÉEL des éléments visibles
- Petites variations normales = MÊME ÉTAT
- Changement significatif = ÉTAT DIFFÉRENT

📋 RÉPONDS EN JSON :
{{
    "same_state": true/false,
    "confidence": 0-100,
    "explanation": "Explication courte"
}}

- same_state = true → Les deux photos montrent le même état (équivalent)
- same_state = false → Les deux photos montrent un état différent"""

            # 🚀 CONVERTIR les URLs en Data URI pour éviter les timeouts OpenAI
            checking_url_final = checking_picture_url
            checkout_url_final = checkout_picture_url

            if not checking_picture_url.startswith("data:"):
                with _data_uri_cache_lock:
                    if checking_picture_url in _data_uri_cache:
                        checking_url_final = _data_uri_cache[checking_picture_url]
                        logger.debug(f"🖼️ [2-STEP SYNC] checking_picture: cache hit")
                    else:
                        data_uri = convert_url_to_data_uri(checking_picture_url)
                        if data_uri:
                            _data_uri_cache[checking_picture_url] = data_uri
                            checking_url_final = data_uri
                            logger.debug(f"🖼️ [2-STEP SYNC] checking_picture: converti en Data URI")

            if not checkout_picture_url.startswith("data:"):
                with _data_uri_cache_lock:
                    if checkout_picture_url in _data_uri_cache:
                        checkout_url_final = _data_uri_cache[checkout_picture_url]
                        logger.debug(f"🖼️ [2-STEP SYNC] checkout_picture: cache hit")
                    else:
                        data_uri = convert_url_to_data_uri(checkout_picture_url)
                        if data_uri:
                            _data_uri_cache[checkout_picture_url] = data_uri
                            checkout_url_final = data_uri
                            logger.debug(f"🖼️ [2-STEP SYNC] checkout_picture: converti en Data URI")

            # Préparer le message avec les deux images (URLs converties en Data URI)
            comparison_content = [
                {"type": "text", "text": "Compare ces deux photos et détermine si elles montrent le même état :"},
                {"type": "image_url", "image_url": {"url": checking_url_final, "detail": "high"}},
                {"type": "image_url", "image_url": {"url": checkout_url_final, "detail": "high"}}
            ]

            comparison_messages = [
                {"role": "system", "content": comparison_prompt},
                {"role": "user", "content": comparison_content}
            ]

            try:
                # Appel à l'IA pour comparer les images (VERSION SYNCHRONE)
                input_content = convert_chat_messages_to_responses_input(comparison_messages)

                comparison_response = client.responses.create(
                    model=OPENAI_MODEL,
                    input=input_content,
                    text={"format": {"type": "json_object"}},
                    max_output_tokens=500,
                    temperature=0.1
                )

                # Parser la réponse
                comparison_text = comparison_response.output_text if hasattr(comparison_response, 'output_text') else str(comparison_response.output[0].content[0].text)

                # Extraire le JSON
                start_idx = comparison_text.find('{')
                end_idx = comparison_text.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_content = comparison_text[start_idx:end_idx+1]
                    comparison_data = json.loads(json_content)
                else:
                    comparison_data = json.loads(comparison_text)

                same_state = comparison_data.get("same_state", False)
                comparison_confidence = comparison_data.get("confidence", 0)
                explanation = comparison_data.get("explanation", "")

                logger.debug(f"🔍 [2-STEP] Étape {etape_id}: Comparaison terminée - same_state={same_state}, confidence={comparison_confidence}")
                logger.debug(f"💬 [2-STEP] Explication: {explanation}")

                # ═══════════════════════════════════════════════════════════════
                # DÉCISION FINALE basée sur la comparaison
                # ═══════════════════════════════════════════════════════════════
                if same_state and comparison_confidence >= 70:
                    # Les images sont similaires → FORCER VALIDÉ (état maintenu)
                    logger.info(f"✅ [2-STEP] Étape {etape_id}: Images similaires (confidence={comparison_confidence}) → FORCER VALIDÉ (état maintenu)")

                    new_commentaire = f"État maintenu par rapport à l'état initial (pas de dégradation). {explanation}"

                    # Supprimer les issues car on force VALIDÉ
                    return "VALIDÉ", [], new_commentaire
                else:
                    # Les images sont différentes → GARDER NON_VALIDÉ (dégradation)
                    logger.info(f"❌ [2-STEP] Étape {etape_id}: Images différentes (same_state={same_state}, confidence={comparison_confidence}) → GARDER {validation_status}")

                    # Enrichir le commentaire avec l'explication
                    if explanation:
                        enriched_commentaire = f"{commentaire}. Comparaison avec état initial: {explanation}"
                    else:
                        enriched_commentaire = commentaire

                    return validation_status, issues, enriched_commentaire

            except Exception as comparison_error:
                logger.error(f"❌ [2-STEP] Erreur lors de la comparaison d'images pour étape {etape_id}: {str(comparison_error)}")
                # En cas d'erreur, on garde le statut original
                return validation_status, issues, commentaire

        # ═══════════════════════════════════════════════════════════════
        # CAS 3 : Autre statut (ne devrait pas arriver)
        # ═══════════════════════════════════════════════════════════════
        logger.warning(f"⚠️ [2-STEP] Étape {etape_id}: Statut inconnu '{validation_status}' → Garder tel quel")
        return validation_status, issues, commentaire

    except Exception as e:
        logger.error(f"❌ [2-STEP] Erreur dans apply_two_step_validation_logic_sync pour étape {etape_id}: {str(e)}")
        # En cas d'erreur, on retourne les valeurs originales
        return validation_status, issues, commentaire


async def apply_two_step_validation_logic(
    validation_status: str,
    issues: list,
    has_checking: bool,
    checking_picture_url: str,
    checkout_picture_url: str,
    etape_id: str,
    task_name: str,
    commentaire: str
) -> tuple:
    """
    🔄 LOGIQUE EN 2 ÉTAPES - Post-traitement de la validation IA

    Cette fonction applique la logique de validation en 2 étapes APRÈS l'analyse IA
    pour garantir qu'elle soit toujours respectée, même si l'IA ne l'a pas bien comprise.

    ÉTAPE 1 : L'IA a vérifié si checkout répond à la consigne
        ✅ VALIDÉ → On garde VALIDÉ
        ❌ NON_VALIDÉ → On passe à l'ÉTAPE 2

    ÉTAPE 2 : Comparer checkout avec checking (si disponible)
        ✅ Images similaires → Forcer VALIDÉ (état maintenu)
        ❌ Images différentes → Garder NON_VALIDÉ (dégradation)

    Args:
        validation_status: Statut retourné par l'IA
        issues: Liste des issues détectées par l'IA
        has_checking: Si une photo checking est disponible
        checking_picture_url: URL de la photo checking
        checkout_picture_url: URL de la photo checkout
        etape_id: ID de l'étape
        task_name: Nom de la tâche
        commentaire: Commentaire de l'IA

    Returns:
        tuple: (validation_status_final, issues_final, commentaire_final)
    """
    try:
        # ═══════════════════════════════════════════════════════════════
        # CAS 1 : VALIDÉ par l'IA → On garde VALIDÉ (ÉTAPE 1 réussie)
        # ═══════════════════════════════════════════════════════════════
        if validation_status == "VALIDÉ":
            logger.debug(f"✅ [2-STEP] Étape {etape_id}: VALIDÉ par IA (ÉTAPE 1 réussie) → Validation confirmée")
            return validation_status, issues, commentaire

        # ═══════════════════════════════════════════════════════════════
        # CAS 2 : NON_VALIDÉ ou INCERTAIN → Vérifier ÉTAPE 2
        # ═══════════════════════════════════════════════════════════════
        if validation_status in ["NON_VALIDÉ", "INCERTAIN"]:
            logger.debug(f"⚠️ [2-STEP] Étape {etape_id}: {validation_status} par IA (ÉTAPE 1 échouée) → Passage à ÉTAPE 2")

            # Si pas de checking_picture, on ne peut pas faire l'ÉTAPE 2
            if not has_checking or not checking_picture_url:
                logger.debug(f"⏭️ [2-STEP] Étape {etape_id}: Pas de checking_picture → Impossible de faire ÉTAPE 2 → Garder {validation_status}")
                return validation_status, issues, commentaire

            # ═══════════════════════════════════════════════════════════════
            # ÉTAPE 2 : Comparer checking vs checkout avec l'IA
            # ═══════════════════════════════════════════════════════════════
            logger.debug(f"🔍 [2-STEP] Étape {etape_id}: Comparaison checking vs checkout...")

            # Construire un prompt simple pour comparer les deux images
            comparison_prompt = f"""Tu es un expert en comparaison d'images.

🎯 OBJECTIF : Déterminer si deux photos montrent le MÊME ÉTAT ou un état DIFFÉRENT.

📸 CONTEXTE :
- Photo 1 (AVANT) : État initial
- Photo 2 (APRÈS) : État final
- Tâche : {task_name}

🔍 QUESTION :
Les deux photos montrent-elles le MÊME ÉTAT (équivalent) ou un état DIFFÉRENT (dégradé/amélioré) ?

⚠️ RÈGLES :
- Ignore les différences d'angle, de luminosité, de cadrage
- Concentre-toi sur l'ÉTAT RÉEL des éléments visibles
- Petites variations normales = MÊME ÉTAT
- Changement significatif = ÉTAT DIFFÉRENT

📋 RÉPONDS EN JSON :
{{
    "same_state": true/false,
    "confidence": 0-100,
    "explanation": "Explication courte"
}}

- same_state = true → Les deux photos montrent le même état (équivalent)
- same_state = false → Les deux photos montrent un état différent"""

            # 🚀 CONVERTIR les URLs en Data URI pour éviter les timeouts OpenAI
            checking_url_final = checking_picture_url
            checkout_url_final = checkout_picture_url

            if not checking_picture_url.startswith("data:"):
                with _data_uri_cache_lock:
                    if checking_picture_url in _data_uri_cache:
                        checking_url_final = _data_uri_cache[checking_picture_url]
                        logger.debug(f"🖼️ [2-STEP ASYNC] checking_picture: cache hit")
                    else:
                        data_uri = convert_url_to_data_uri(checking_picture_url)
                        if data_uri:
                            _data_uri_cache[checking_picture_url] = data_uri
                            checking_url_final = data_uri
                            logger.debug(f"🖼️ [2-STEP ASYNC] checking_picture: converti en Data URI")

            if not checkout_picture_url.startswith("data:"):
                with _data_uri_cache_lock:
                    if checkout_picture_url in _data_uri_cache:
                        checkout_url_final = _data_uri_cache[checkout_picture_url]
                        logger.debug(f"🖼️ [2-STEP ASYNC] checkout_picture: cache hit")
                    else:
                        data_uri = convert_url_to_data_uri(checkout_picture_url)
                        if data_uri:
                            _data_uri_cache[checkout_picture_url] = data_uri
                            checkout_url_final = data_uri
                            logger.debug(f"🖼️ [2-STEP ASYNC] checkout_picture: converti en Data URI")

            # Préparer le message avec les deux images (URLs converties en Data URI)
            comparison_content = [
                {"type": "text", "text": "Compare ces deux photos et détermine si elles montrent le même état :"},
                {"type": "image_url", "image_url": {"url": checking_url_final, "detail": "high"}},
                {"type": "image_url", "image_url": {"url": checkout_url_final, "detail": "high"}}
            ]

            comparison_messages = [
                {"role": "system", "content": comparison_prompt},
                {"role": "user", "content": comparison_content}
            ]

            try:
                # Appel à l'IA pour comparer les images
                input_content = convert_chat_messages_to_responses_input(comparison_messages)

                if 'async_client' in globals() and async_client:
                    comparison_response = await async_client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=500,
                        temperature=0.1
                    )
                else:
                    comparison_response = client.responses.create(
                        model=OPENAI_MODEL,
                        input=input_content,
                        text={"format": {"type": "json_object"}},
                        max_output_tokens=500,
                        temperature=0.1
                    )

                # Parser la réponse
                comparison_text = comparison_response.output_text if hasattr(comparison_response, 'output_text') else str(comparison_response.output[0].content[0].text)

                # Extraire le JSON
                start_idx = comparison_text.find('{')
                end_idx = comparison_text.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_content = comparison_text[start_idx:end_idx+1]
                    comparison_data = json.loads(json_content)
                else:
                    comparison_data = json.loads(comparison_text)

                same_state = comparison_data.get("same_state", False)
                comparison_confidence = comparison_data.get("confidence", 0)
                explanation = comparison_data.get("explanation", "")

                logger.debug(f"🔍 [2-STEP] Étape {etape_id}: Comparaison terminée - same_state={same_state}, confidence={comparison_confidence}")
                logger.debug(f"💬 [2-STEP] Explication: {explanation}")

                # ═══════════════════════════════════════════════════════════════
                # DÉCISION FINALE basée sur la comparaison
                # ═══════════════════════════════════════════════════════════════
                if same_state and comparison_confidence >= 70:
                    # Les images sont similaires → FORCER VALIDÉ (état maintenu)
                    logger.info(f"✅ [2-STEP] Étape {etape_id}: Images similaires (confidence={comparison_confidence}) → FORCER VALIDÉ (état maintenu)")

                    new_commentaire = f"État maintenu par rapport à l'état initial (pas de dégradation). {explanation}"

                    # Supprimer les issues car on force VALIDÉ
                    return "VALIDÉ", [], new_commentaire
                else:
                    # Les images sont différentes → GARDER NON_VALIDÉ (dégradation)
                    logger.info(f"❌ [2-STEP] Étape {etape_id}: Images différentes (same_state={same_state}, confidence={comparison_confidence}) → GARDER {validation_status}")

                    # Enrichir le commentaire avec l'explication
                    if explanation:
                        enriched_commentaire = f"{commentaire}. Comparaison avec état initial: {explanation}"
                    else:
                        enriched_commentaire = commentaire

                    return validation_status, issues, enriched_commentaire

            except Exception as comparison_error:
                logger.error(f"❌ [2-STEP] Erreur lors de la comparaison d'images pour étape {etape_id}: {str(comparison_error)}")
                # En cas d'erreur, on garde le statut original
                return validation_status, issues, commentaire

        # ═══════════════════════════════════════════════════════════════
        # CAS 3 : Autre statut (ne devrait pas arriver)
        # ═══════════════════════════════════════════════════════════════
        logger.warning(f"⚠️ [2-STEP] Étape {etape_id}: Statut inconnu '{validation_status}' → Garder tel quel")
        return validation_status, issues, commentaire

    except Exception as e:
        logger.error(f"❌ [2-STEP] Erreur dans apply_two_step_validation_logic pour étape {etape_id}: {str(e)}")
        # En cas d'erreur, on retourne les valeurs originales
        return validation_status, issues, commentaire


async def analyze_single_etape_async(etape: Etape, etape_data: dict, piece_id: str, parcours_type: str = "Voyageur", request_id: str = None) -> List[EtapeIssue]:
    """
    Analyse asynchrone d'une seule étape
    Extrait de la logique dans analyze_etapes

    Args:
        etape: Données de l'étape
        etape_data: Données traitées de l'étape
        piece_id: ID de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")
        request_id: ID de la requête pour le tracking des logs
    """
    try:
        # 🚫 RÈGLE: Exclure les tâches sans checkout_picture de l'analyse AI
        # Si checkout_picture est vide/null dans l'étape originale, ne pas analyser
        if not etape.checkout_picture or etape.checkout_picture.strip() == "":
            logger.debug(f"⏭️ [ASYNC] Étape {etape.etape_id} skippée: pas de checkout_picture requis (tâche sans photo)")
            return []

        logger.debug(f"🔍 [ASYNC] Analyse de l'étape {etape.etape_id}: {etape.task_name}")

        # Construire le prompt spécifique pour l'étape depuis la config JSON
        prompts_config = load_prompts_config(parcours_type)
        analyze_etapes_config = prompts_config.get("prompts", {}).get("analyze_etapes", {})

        # Préparer les variables pour le template
        variables = {
            "task_name": etape.task_name,
            "consigne": etape.consigne,
            "etape_id": etape.etape_id
        }

        # Construire le prompt système
        system_prompt = build_full_prompt_from_config(analyze_etapes_config, variables)

        # 🔍 LOG DÉTAILLÉ DU PROMPT POUR DEBUG
        logger.info(f"📋 PROMPT ANALYZE_ETAPES (premiers 500 caractères):")
        logger.debug(system_prompt[:500])
        logger.info(f"📋 PROMPT ANALYZE_ETAPES (derniers 500 caractères):")
        logger.debug(system_prompt[-500:])

        # Message utilisateur
        user_message_config = prompts_config.get("user_messages", {}).get("analyze_etapes_user", {})
        user_message_template = user_message_config.get("template", "Analyse cette étape: {task_name}")
        user_message = user_message_template.format(**variables)

        # Préparer les images
        messages_content = [{"type": "text", "text": user_message}]

        has_checking = bool(etape_data.get("checking_picture_processed"))
        has_checkout = bool(etape_data.get("checkout_picture_processed"))

        # ⚠️ Si aucune photo n'est disponible, on ne peut pas analyser
        if not has_checking and not has_checkout:
            logger.warning(f"⚠️ [ASYNC] Étape {etape.etape_id} skippée: aucune photo disponible (checking={has_checking}, checkout={has_checkout})")
            return []

        if has_checking:
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": etape_data["checking_picture_processed"]}
            })
            logger.debug(f"   📸 Photo AVANT ajoutée pour étape {etape.etape_id}")

        if has_checkout:
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": etape_data["checkout_picture_processed"]}
            })
            logger.debug(f"   📸 Photo APRÈS ajoutée pour étape {etape.etape_id}")

        # 📝 LOG DU PROMPT D'ÉTAPE
        if request_id:
            logs_manager.add_prompt_log(
                request_id=request_id,
                prompt_type="Etape",
                prompt_content=system_prompt,
                model=OPENAI_MODEL
            )

        # Appel à l'API OpenAI (ASYNCHRONE pour vraie parallélisation)
        # Utiliser async_client s'il est disponible, sinon fallback sur client synchrone (bloquant)
        # 🚀 MIGRATION vers Responses API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": messages_content}
        ]
        input_content = convert_chat_messages_to_responses_input(messages)

        try:
            if 'async_client' in globals() and async_client:
                response = await async_client.responses.create(
                    model=OPENAI_MODEL,
                    input=input_content,
                    text={"format": {"type": "json_object"}},
                    max_output_tokens=1000,
                    temperature=0.2
                )
            else:
                logger.warning("⚠️ async_client non disponible, utilisation du client synchrone (lent)")
                response = client.responses.create(
                    model=OPENAI_MODEL,
                    input=input_content,
                    text={"format": {"type": "json_object"}},
                    max_output_tokens=1000,
                    temperature=0.2
                )

            # Parser la réponse
            # 🚀 MIGRATION: Extraction depuis Responses API
            response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)

        except Exception as openai_error:
            error_str = str(openai_error)
            logger.error(f"❌ [ASYNC] Erreur OpenAI lors de l'analyse de l'étape {etape.etape_id}: {error_str}")

            # 🔍 DEBUG: Vérifier le contenu de error_str
            error_str_lower = error_str.lower()
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'timeout while downloading': {'timeout while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'error while downloading': {'error while downloading' in error_str_lower}")
            logger.debug(f"🔍 DEBUG - error_str_lower contient 'invalid_image_url': {'invalid_image_url' in error_str_lower}")

            # 🔄 FALLBACK 1: Erreurs de téléchargement d'URL → Convertir en Data URI
            if any(keyword in error_str_lower for keyword in [
                "error while downloading",
                "timeout while downloading",
                "invalid_image_url",
                "failed to download"
            ]):
                logger.warning(f"⚠️ [ASYNC] Erreur de téléchargement d'image détectée pour l'étape {etape.etape_id}, tentative avec Data URIs PARALLÈLES")

                try:
                    # 🚀 Convertir toutes les URLs en data URIs EN PARALLÈLE (beaucoup plus rapide)
                    user_message_dict = {"role": "user", "content": messages_content}
                    user_message_with_data_uris = await convert_message_urls_to_data_uris_parallel(user_message_dict.copy())

                    # Compter les images converties
                    data_uri_count = sum(
                        1 for c in user_message_with_data_uris.get("content", [])
                        if c.get("type") == "image_url" and c["image_url"]["url"].startswith("data:")
                    )

                    logger.debug(f"🔄 [ASYNC] Retry étape {etape.etape_id} avec {data_uri_count} images en Data URI")

                    # Réessayer avec les data URIs
                    messages_retry = [
                        {"role": "system", "content": system_prompt},
                        user_message_with_data_uris
                    ]
                    input_content_retry = convert_chat_messages_to_responses_input(messages_retry)

                    if 'async_client' in globals() and async_client:
                        response = await async_client.responses.create(
                            model=OPENAI_MODEL,
                            input=input_content_retry,
                            text={"format": {"type": "json_object"}},
                            max_output_tokens=1000,
                            temperature=0.2
                        )
                    else:
                        response = client.responses.create(
                            model=OPENAI_MODEL,
                            input=input_content_retry,
                            text={"format": {"type": "json_object"}},
                            max_output_tokens=1000,
                            temperature=0.2
                        )

                    # Parser la réponse
                    response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
                    logger.info(f"✅ [ASYNC] Retry réussi avec Data URIs pour l'étape {etape.etape_id}")

                except Exception as retry_error:
                    logger.error(f"❌ [ASYNC] Échec du retry avec Data URIs pour l'étape {etape.etape_id}: {str(retry_error)}")
                    raise  # Re-raise pour être catchée par le except principal
            else:
                # Autre type d'erreur, re-raise
                raise

        # 📝 LOG DE LA RÉPONSE D'ÉTAPE
        if request_id:
            logs_manager.add_response_log(
                request_id=request_id,
                response_type="Etape",
                response_content=response_text,
                model=OPENAI_MODEL,
                tokens_used=extract_usage_tokens(response)
            )

        # 🔧 NETTOYAGE ROBUSTE DU JSON (même logique que pour la classification)
        try:
            # Essayer de trouver le JSON entre accolades
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')

            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_content = response_text[start_idx:end_idx+1]
                response_data = json.loads(json_content)
            else:
                response_data = json.loads(response_text)
        except json.JSONDecodeError as json_err:
            logger.error(f"❌ [ASYNC] Erreur parsing JSON pour étape {etape.etape_id}: {json_err}")
            logger.error(f"📄 Contenu reçu: {response_text[:500]}...")
            return []  # Retourner liste vide en cas d'erreur

        # 🆕 Extraire validation_status et commentaire
        validation_status = response_data.get("validation_status")
        commentaire = response_data.get("commentaire", "")

        logger.info(f"📋 [ASYNC] Étape {etape.etape_id} - validation_status IA: {validation_status}")

        # Extraire les issues temporaires (pour fusion ultérieure)
        temp_issues = []
        for issue_data in response_data.get("issues", []):
            temp_issues.append({
                "description": issue_data.get("description", ""),
                "category": issue_data.get("category", "cleanliness"),
                "severity": issue_data.get("severity", "medium"),
                "confidence": issue_data.get("confidence", 70)
            })

        # ═══════════════════════════════════════════════════════════════
        # 🔄 APPLIQUER LA LOGIQUE EN 2 ÉTAPES (POST-TRAITEMENT)
        # ═══════════════════════════════════════════════════════════════
        validation_status, temp_issues, commentaire = await apply_two_step_validation_logic(
            validation_status=validation_status,
            issues=temp_issues,
            has_checking=has_checking,
            checking_picture_url=etape_data.get("checking_picture_processed", "") if has_checking else "",
            checkout_picture_url=etape_data.get("checkout_picture_processed", "") if has_checkout else "",
            etape_id=etape.etape_id,
            task_name=etape.task_name,
            commentaire=commentaire
        )

        # 🆕 FUSION DES ISSUES : Une seule issue par étape avec catégorie "etape_non_validee"
        issues = []
        if temp_issues:
            # Fusionner toutes les descriptions en une seule
            merged_descriptions = [issue["description"] for issue in temp_issues]
            merged_description = ", ".join(merged_descriptions)

            # Prendre la sévérité la plus haute
            severity_order = {"high": 3, "medium": 2, "low": 1}
            max_severity = max(temp_issues, key=lambda x: severity_order.get(x["severity"], 1))["severity"]

            # Prendre la confiance moyenne
            avg_confidence = sum(issue["confidence"] for issue in temp_issues) // len(temp_issues)

            # Créer UNE SEULE issue fusionnée avec la catégorie "etape_non_validee"
            issues.append(EtapeIssue(
                etape_id=etape.etape_id,
                description=merged_description,
                category="etape_non_validee",
                severity=max_severity,
                confidence=avg_confidence,
                validation_status=validation_status,
                commentaire=commentaire
            ))
            logger.debug(f"   🔗 [ASYNC] {len(temp_issues)} issues fusionnées en 1 pour l'étape {etape.etape_id}")
        else:
            # 🆕 Si pas d'issues mais validation_status existe, créer une entrée de suivi
            # ⚠️ SEULEMENT pour NON_VALIDÉ ou INCERTAIN (pas pour VALIDÉ qui ne doit pas impacter la note)
            if validation_status and validation_status != "VALIDÉ":
                # Récupérer confidence de manière sécurisée
                confidence_value = 100
                if isinstance(response_data, dict):
                    confidence_value = response_data.get("confidence", 100)

                issues.append(EtapeIssue(
                    etape_id=etape.etape_id,
                    description=commentaire if commentaire else f"Étape {validation_status.lower()}",
                    category="etape_non_validee",
                    severity="low" if validation_status == "INCERTAIN" else "medium",
                    confidence=confidence_value,
                    validation_status=validation_status,
                    commentaire=commentaire
                ))

        logger.info(f"✅ [ASYNC] Étape {etape.etape_id} analysée: validation_status FINAL={validation_status}, {len(issues)} issue(s)")
        return issues

    except Exception as e:
        logger.error(f"❌ [ASYNC] Erreur lors de l'analyse de l'étape {etape.etape_id}: {str(e)}")
        import traceback
        logger.error(f"📄 Traceback complet:\n{traceback.format_exc()}")
        return []


# ═══════════════════════════════════════════════════════════════
# 🔄 VERSION PARALLÉLISÉE DE analyze_complete_logement
# ═══════════════════════════════════════════════════════════════

async def process_single_etape_image_task(etape: dict, index: int, total: int) -> dict:
    """
    Tâche unitaire pour traiter les images d'une étape en parallèle (via ThreadPool).
    Remplace le traitement séquentiel de process_etapes_images.
    """
    try:
        loop = asyncio.get_running_loop()

        etape_id = etape.get('etape_id')
        task_name = etape.get('task_name')
        consigne = etape.get('consigne')
        checking_picture = etape.get('checking_picture')
        checkout_picture = etape.get('checkout_picture')
        
        # logger.debug(f"🔄 [ASYNC-IMG] Traitement images étape {index+1}/{total} - ID: {etape_id}")

        converted_checking = None
        converted_checkout = None

        # 1. Traiter image CHECK-IN
        if checking_picture and checking_picture.strip():
            normalized_checking = normalize_url(checking_picture)
            if is_valid_image_url(normalized_checking):
                # Exécution dans un thread séparé pour ne pas bloquer la boucle
                converted_checking = await loop.run_in_executor(
                    None, 
                    ImageConverter.process_image_url, 
                    normalized_checking, 
                    False # use_placeholder_for_invalid=False
                )
            else:
                logger.warning(f"⚠️ checking_picture invalide pour étape {etape_id}")
        
        # 2. Traiter image CHECK-OUT
        if checkout_picture and checkout_picture.strip():
            normalized_checkout = normalize_url(checkout_picture)
            if is_valid_image_url(normalized_checkout):
                # Exécution dans un thread séparé
                converted_checkout = await loop.run_in_executor(
                    None, 
                    ImageConverter.process_image_url, 
                    normalized_checkout, 
                    False # use_placeholder_for_invalid=False
                )
            else:
                logger.warning(f"⚠️ checkout_picture invalide pour étape {etape_id}")
        
        return {
            'etape_id': etape_id,
            'task_name': task_name,
            'consigne': consigne,
            'checking_picture_processed': converted_checking,
            'checkout_picture_processed': converted_checkout
        }

    except Exception as e:
        logger.error(f"❌ Erreur async processing images etape {etape.get('etape_id')}: {e}")
        # Fallback placeholders
        return {
             'etape_id': etape.get('etape_id'),
             'task_name': etape.get('task_name'),
             'consigne': etape.get('consigne'),
             'checking_picture_processed': create_placeholder_image_url(),
             'checkout_picture_processed': create_placeholder_image_url()
        }

async def process_etapes_images_parallel(etapes_list: list) -> list:
    """
    Version parallélisée de process_etapes_images.
    Lance le traitement de toutes les images de toutes les étapes en parallèle.
    """
    if not etapes_list:
        return []
        
    start_time = datetime.now()
    logger.debug(f"🚀 [ASYNC-IMG] Démarrage traitement parallèle de {len(etapes_list)} étapes")
    
    tasks = []
    for i, etape in enumerate(etapes_list):
        tasks.append(process_single_etape_image_task(etape, i, len(etapes_list)))
    
    # Attendre que tout soit fini
    results = await asyncio.gather(*tasks)
    
    duration = (datetime.now() - start_time).total_seconds()
    logger.debug(f"✅ [ASYNC-IMG] Traitement terminé en {duration:.2f}s")
    
    return list(results)

async def analyze_complete_logement_parallel(input_data: EtapesAnalysisInput, request_id: str = None) -> CompleteAnalysisResponse:
    """
    Version PARALLÉLISÉE de analyze_complete_logement
    Utilise asyncio.gather() pour analyser toutes les pièces et étapes en parallèle

    Gain attendu: 70-80% de réduction du temps (80s → 14s pour 5 pièces)
    """
    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"

        logger.debug(f"🚀 [PARALLEL] ANALYSE COMPLÈTE démarrée pour le logement {input_data.logement_id} (parcours: {parcours_type})")

        if request_id:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"📊 Analyse parallèle de {len(input_data.pieces)} pièces"
            )

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 1: Analyse PARALLÈLE de toutes les pièces
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"📊 [PARALLEL] ÉTAPE 1 - Analyse parallèle de {len(input_data.pieces)} pièces")

        # Créer les tâches pour toutes les pièces avec le type de parcours
        piece_tasks = [analyze_single_piece_async(piece, parcours_type, request_id=request_id) for piece in input_data.pieces]

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
        logger.debug(f"✅ [PARALLEL] {len(pieces_analysis_results)} pièces analysées avec succès")

        # 🔍 DEBUG: Logger les issues de chaque pièce
        for piece_result in pieces_analysis_results:
            logger.debug(f"🔍 DEBUG - Pièce {piece_result.piece_id}: {len(piece_result.issues)} issues détectées")
            if piece_result.issues:
                for idx, issue in enumerate(piece_result.issues[:3]):  # Afficher max 3 issues
                    logger.debug(f"      [{idx+1}] {issue.description[:50]}...")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 2: Analyse PARALLÈLE de toutes les étapes
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🎯 [PARALLEL] ÉTAPE 2 - Analyse parallèle des étapes")

        # Créer un mapping etape_id -> piece_id
        etape_to_piece_mapping = {}
        all_etape_tasks = []

        for piece in input_data.pieces:
            # Traiter les images des étapes (ASYNC PARALLEL)
            processed_etapes = await process_etapes_images_parallel([etape.model_dump() for etape in piece.etapes])

            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]

                # 🚫 RÈGLE: Exclure les tâches sans checkout_picture de l'analyse AI
                # Si checkout_picture est vide/null dans l'étape originale, ne pas analyser
                if not etape.checkout_picture or etape.checkout_picture.strip() == "":
                    logger.debug(f"⏭️ [PARALLEL] Étape {etape.etape_id} skippée: pas de checkout_picture requis (tâche sans photo)")
                    continue

                etape_to_piece_mapping[etape.etape_id] = piece.piece_id

                # Créer une tâche async pour cette étape
                task = analyze_single_etape_async(etape, etape_data, piece.piece_id, parcours_type=parcours_type, request_id=request_id)
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

            logger.debug(f"✅ [PARALLEL] {len(all_etape_issues)} issues d'étapes détectées")
        else:
            all_etape_issues = []

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 3: Regroupement des résultats (identique à la version séquentielle)
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🔄 [PARALLEL] ÉTAPE 3 - Regroupement des résultats")

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
                    confidence=etape_issue.confidence,
                    etape_id=etape_issue.etape_id  # ✅ Ajouter l'etape_id
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

            # 🆕 RECALCULER LE SCORE DE LA PIÈCE avec TOUTES les issues (générales + étapes)
            recalculated_score = calculate_room_algorithmic_score(
                issues=all_issues_for_piece,
                parcours_type=parcours_type
            )

            # Créer une copie modifiée de l'analyse globale avec le nouveau score
            updated_analyse_globale = AnalyseGlobale(
                status=piece_analysis.analyse_globale.status,
                score=recalculated_score["note_sur_5"],
                temps_nettoyage_estime=piece_analysis.analyse_globale.temps_nettoyage_estime,
                commentaire_global=piece_analysis.analyse_globale.commentaire_global
            )

            logger.debug(f"   🧮 [PARALLEL] Pièce {piece_id}: Score recalculé {piece_analysis.analyse_globale.score} → {recalculated_score['note_sur_5']}/5 ({len(all_issues_for_piece)} issues)")

            # Créer un nouvel objet avec TOUTES les issues fusionnées ET le score recalculé
            updated_piece_analysis = CombinedAnalysisResponse(
                piece_id=piece_analysis.piece_id,
                nom_piece=piece_analysis.nom_piece,
                room_classification=piece_analysis.room_classification,
                analyse_globale=updated_analyse_globale,
                issues=all_issues_for_piece  # Issues générales + étapes fusionnées
            )

            updated_pieces_analysis.append(updated_piece_analysis)

            # Compter le total (issues générales + issues d'étapes)
            total_issues_count += len(all_issues_for_piece)

        # Remplacer la liste originale par la liste mise à jour
        pieces_analysis_results = updated_pieces_analysis

        logger.debug(f"📊 [PARALLEL] Compteurs: {total_issues_count} total ({general_issues_count} générales + {etapes_issues_count} étapes)")

        # 🔍 DEBUG: Logger les issues après reconstruction
        logger.debug(f"🔍 DEBUG - Après reconstruction des objets (issues fusionnées):")
        for piece_result in pieces_analysis_results:
            logger.debug(f"   Pièce {piece_result.piece_id}: {len(piece_result.issues)} issues TOTALES (générales + étapes fusionnées)")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 4: Génération de la synthèse globale
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🧠 [PARALLEL] ÉTAPE 4 - Génération de la synthèse globale")

        analysis_enrichment = generate_logement_enrichment(
            logement_id=input_data.logement_id,
            pieces_analysis=pieces_analysis_results,
            total_issues=total_issues_count,
            general_issues=general_issues_count,
            etapes_issues=etapes_issues_count,
            parcours_type=parcours_type,
            request_id=request_id
        )

        complete_result = CompleteAnalysisResponse(
            logement_id=input_data.logement_id,
            logement_name=input_data.logement_name,  # Nom du logement
            rapport_id=input_data.rapport_id,
            pieces_analysis=pieces_analysis_results,
            total_issues_count=total_issues_count,
            etapes_issues_count=etapes_issues_count,
            general_issues_count=general_issues_count,
            analysis_enrichment=analysis_enrichment
        )

        logger.debug(f"🎉 [PARALLEL] ANALYSE COMPLÈTE terminée pour le logement {input_data.logement_id}")
        logger.debug(f"📊 RÉSUMÉ FINAL: {total_issues_count} issues totales")
        logger.info(f"🏆 NOTE GLOBALE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")

        if request_id:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"✅ Analyse parallèle terminée: {total_issues_count} issues détectées"
            )

        return complete_result

    except Exception as e:
        logger.error(f"❌ [PARALLEL] Erreur lors de l'analyse complète: {str(e)}")
        raise


async def analyze_complete_logement_ultra_parallel(input_data: EtapesAnalysisInput, request_id: str = None) -> CompleteAnalysisResponse:
    """
    🚀 VERSION ULTRA-PARALLÉLISÉE avec système de cache avancé

    Utilise le ParallelProcessor pour une parallélisation maximale avec:
    - Cache thread-safe pour les résultats intermédiaires
    - Contrôle de concurrence optimisé (15+ workers simultanés)
    - Gestion d'erreurs robuste sans blocage
    - Compilation finale des résultats en cache

    Gain attendu: 80-90% de réduction du temps vs version séquentielle
    """
    if not PARALLEL_EXECUTOR_AVAILABLE:
        logger.warning("⚠️ Système ultra-parallèle non disponible, fallback sur version parallèle standard")
        return await analyze_complete_logement_parallel(input_data, request_id)

    try:
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"

        logger.debug(f"🚀🚀 [ULTRA-PARALLEL] ANALYSE COMPLÈTE pour logement {input_data.logement_id}")
        logger.debug(f"   📊 {len(input_data.pieces)} pièces à analyser")
        logger.debug(f"   ⚡ Mode: Ultra-parallélisation avec cache avancé")

        if request_id:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"🚀 Analyse ultra-parallèle de {len(input_data.pieces)} pièces"
            )

        # Obtenir l'exécuteur parallèle global (max 15 workers pour haute quota)
        executor = get_parallel_executor(max_workers=15)

        # ═══════════════════════════════════════════════════════════════
        # STAGE 1: Analyse ultra-parallèle de toutes les pièces
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"📊 [STAGE 1] Analyse ultra-parallèle de {len(input_data.pieces)} pièces")

        pieces_analysis_results = await executor.analyze_pieces_parallel(
            pieces=input_data.pieces,
            analyze_func=analyze_single_piece_async,
            parcours_type=parcours_type,
            request_id=request_id
        )

        logger.debug(f"✅ [STAGE 1] {len(pieces_analysis_results)} pièces analysées")

        # ═══════════════════════════════════════════════════════════════
        # STAGE 2: Traitement et analyse ultra-parallèle des étapes
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🎯 [STAGE 2] Traitement et analyse ultra-parallèle des étapes")

        # Préparer toutes les données d'étapes
        etape_to_piece_mapping = {}
        all_etapes_data = []

        for piece in input_data.pieces:
            # Traiter les images des étapes (parallèle)
            processed_etapes = await process_etapes_images_parallel([etape.model_dump() for etape in piece.etapes])

            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]

                # Skip étapes sans checkout_picture
                if not etape.checkout_picture or etape.checkout_picture.strip() == "":
                    logger.debug(f"⏭️ Étape {etape.etape_id} skippée: pas de checkout_picture")
                    continue

                etape_to_piece_mapping[etape.etape_id] = piece.piece_id

                all_etapes_data.append({
                    'etape': etape,
                    'etape_data': etape_data,
                    'piece_id': piece.piece_id
                })

        # Analyser toutes les étapes en ultra-parallèle
        if all_etapes_data:
            all_etape_issues = await executor.analyze_etapes_parallel(
                etapes_data=all_etapes_data,
                analyze_func=analyze_single_etape_async,
                parcours_type=parcours_type,
                request_id=request_id
            )
        else:
            all_etape_issues = []

        logger.debug(f"✅ [STAGE 2] {len(all_etape_issues)} issues d'étapes détectées")

        # ═══════════════════════════════════════════════════════════════
        # STAGE 3: Compilation des résultats (identique à version standard)
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🔄 [STAGE 3] Compilation des résultats")

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
                    confidence=etape_issue.confidence,
                    etape_id=etape_issue.etape_id
                )
                etapes_issues_by_piece[piece_id].append(probleme)

        # Calcul des compteurs
        total_issues_count = 0
        general_issues_count = 0
        etapes_issues_count = len(all_etape_issues)

        # Reconstruire les objets avec issues fusionnées
        updated_pieces_analysis = []

        for piece_analysis in pieces_analysis_results:
            piece_id = piece_analysis.piece_id

            # Compter les issues générales
            general_issues_for_piece = len(piece_analysis.issues) if piece_analysis.issues else 0
            general_issues_count += general_issues_for_piece

            # Récupérer les issues d'étapes
            etapes_issues_for_piece = etapes_issues_by_piece.get(piece_id, [])

            # Fusionner toutes les issues
            all_issues_for_piece = list(piece_analysis.issues) + etapes_issues_for_piece

            # 🆕 RECALCULER LE SCORE DE LA PIÈCE avec TOUTES les issues (générales + étapes)
            recalculated_score = calculate_room_algorithmic_score(
                issues=all_issues_for_piece,
                parcours_type=parcours_type
            )

            # Créer une copie modifiée de l'analyse globale avec le nouveau score
            updated_analyse_globale = AnalyseGlobale(
                status=piece_analysis.analyse_globale.status,
                score=recalculated_score["note_sur_5"],
                temps_nettoyage_estime=piece_analysis.analyse_globale.temps_nettoyage_estime,
                commentaire_global=piece_analysis.analyse_globale.commentaire_global
            )

            logger.debug(f"   🧮 [PARALLEL-ALT] Pièce {piece_id}: Score recalculé {piece_analysis.analyse_globale.score} → {recalculated_score['note_sur_5']}/5 ({len(all_issues_for_piece)} issues)")

            # Créer objet mis à jour avec score recalculé
            updated_piece_analysis = CombinedAnalysisResponse(
                piece_id=piece_analysis.piece_id,
                nom_piece=piece_analysis.nom_piece,
                room_classification=piece_analysis.room_classification,
                analyse_globale=updated_analyse_globale,
                issues=all_issues_for_piece
            )

            updated_pieces_analysis.append(updated_piece_analysis)
            total_issues_count += len(all_issues_for_piece)

        pieces_analysis_results = updated_pieces_analysis

        logger.debug(f"📊 [PARALLEL] Compteurs: {total_issues_count} total ({general_issues_count} générales + {etapes_issues_count} étapes)")

        # 🔍 DEBUG: Logger les issues après reconstruction
        logger.debug(f"🔍 DEBUG - Après reconstruction des objets (issues fusionnées):")
        for piece_result in pieces_analysis_results:
            logger.debug(f"   Pièce {piece_result.piece_id}: {len(piece_result.issues)} issues TOTALES (générales + étapes fusionnées)")

        # ═══════════════════════════════════════════════════════════════
        # ÉTAPE 4: Génération de la synthèse globale
        # ═══════════════════════════════════════════════════════════════
        logger.debug(f"🧠 [PARALLEL] ÉTAPE 4 - Génération de la synthèse globale")

        analysis_enrichment = generate_logement_enrichment(
            logement_id=input_data.logement_id,
            pieces_analysis=pieces_analysis_results,
            total_issues=total_issues_count,
            general_issues=general_issues_count,
            etapes_issues=etapes_issues_count,
            parcours_type=parcours_type,
            request_id=request_id
        )

        complete_result = CompleteAnalysisResponse(
            logement_id=input_data.logement_id,
            logement_name=input_data.logement_name,  # Nom du logement
            rapport_id=input_data.rapport_id,
            pieces_analysis=pieces_analysis_results,
            total_issues_count=total_issues_count,
            etapes_issues_count=etapes_issues_count,
            general_issues_count=general_issues_count,
            analysis_enrichment=analysis_enrichment
        )

        # Afficher les statistiques de performance
        perf_stats = executor.get_performance_stats()
        logger.debug(f"📊 [ULTRA-PARALLEL] Statistiques de performance:")
        logger.debug(f"   Cache: {perf_stats['cache_stats']}")
        logger.debug(f"   Workers: {perf_stats['config']['max_workers']}")

        logger.debug(f"🎉 [ULTRA-PARALLEL] ANALYSE COMPLÈTE terminée pour logement {input_data.logement_id}")
        logger.debug(f"📊 RÉSUMÉ: {total_issues_count} issues totales")
        logger.info(f"🏆 NOTE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")

        if request_id:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"✅ Analyse ultra-parallèle terminée: {total_issues_count} issues, cache={perf_stats['cache_stats']}"
            )

        return complete_result

    except Exception as e:
        logger.error(f"❌ [ULTRA-PARALLEL] Erreur: {str(e)}")
        if request_id:
            logs_manager.add_log(
                request_id=request_id,
                level="ERROR",
                message=f"❌ Erreur ultra-parallèle: {str(e)}"
            )
        raise


# ═══════════════════════════════════════════════════════════════
# 📌 VERSION ORIGINALE (SÉQUENTIELLE) - CONSERVÉE POUR COMPATIBILITÉ
# ═══════════════════════════════════════════════════════════════

def analyze_complete_logement(input_data: EtapesAnalysisInput, request_id: str = None) -> CompleteAnalysisResponse:
    """
    Analyse complète d'un logement : classification + analyse générale + analyse des étapes
    VERSION SÉQUENTIELLE (originale)
    """
    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"

        logger.debug(f"🚀 ANALYSE COMPLÈTE démarrée pour le logement {input_data.logement_id} (parcours: {parcours_type})")

        pieces_analysis_results = []

        # ÉTAPE 1: Analyse avec classification pour chaque pièce
        logger.debug(f"📊 ÉTAPE 1 - Analyse avec classification pour {len(input_data.pieces)} pièces")

        # Utiliser tqdm pour afficher la progression
        for piece in tqdm(input_data.pieces, desc="🏠 Analyse des pièces", unit="pièce", colour='green'):
            logger.debug(f"🔍 Analyse de la pièce {piece.piece_id}: {piece.nom}")
            
            # Filtrer les images invalides avant l'analyse
            valid_checkin_pictures = []
            for pic in piece.checkin_pictures:
                # 🔍 DEBUG: Logger l'URL originale
                logger.debug(f"🔍 Traitement image checkin - URL originale: '{pic.url}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.debug(f"🔍 Traitement image checkin - URL normalisée: '{normalized_url}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkin_pictures.append(normalized_pic)
                    logger.debug(f"✅ Image checkin valide ajoutée: {normalized_url}")
                else:
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {pic.url}")
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {normalized_url}")

            valid_checkout_pictures = []
            for pic in piece.checkout_pictures:
                # 🔍 DEBUG: Logger l'URL originale
                logger.debug(f"🔍 Traitement image checkout - URL originale: '{pic.url}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.debug(f"🔍 Traitement image checkout - URL normalisée: '{normalized_url}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkout_pictures.append(normalized_pic)
                    logger.debug(f"✅ Image checkout valide ajoutée: {normalized_url}")
                else:
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {pic.url}")
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {normalized_url}")
            
            logger.debug(f"📷 Images valides pour pièce {piece.piece_id}: {len(valid_checkin_pictures)} checkin + {len(valid_checkout_pictures)} checkout")
            
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
            
            logger.debug(f"✅ Pièce {piece.piece_id} analysée: {len(piece_analysis.issues)} issues générales détectées")
        
        # ÉTAPE 2: Analyser les étapes et créer un mapping etape_id -> piece_id
        logger.debug(f"🎯 ÉTAPE 2 - Analyse des étapes pour toutes les pièces")
        
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
                    confidence=etape_issue.confidence,
                    etape_id=etape_issue.etape_id  # ✅ Ajouter l'etape_id
                )
                etapes_issues_by_piece[piece_id].append(probleme)
        
        logger.debug(f"✅ Analyse des étapes terminée: {len(etapes_analysis.preliminary_issues)} issues d'étapes détectées")
        
        # ÉTAPE 3: Ajouter les issues d'étapes aux pièces correspondantes
        logger.debug(f"🔄 ÉTAPE 3 - Ajout des issues d'étapes aux pièces correspondantes")
        
        # 🛡️ VÉRIFICATIONS SCRUPULEUSES AVANT CALCUL
        if not pieces_analysis_results:
            logger.error("❌ ERREUR CRITIQUE: pieces_analysis_results est vide!")
            raise ValueError("Aucune analyse de pièce disponible pour le calcul des issues")
        
        if not etapes_analysis:
            logger.error("❌ ERREUR CRITIQUE: etapes_analysis est None!")
            raise ValueError("Analyse des étapes manquante")

        logger.debug(f"✅ Vérifications préliminaires: {len(pieces_analysis_results)} pièces + {len(etapes_analysis.preliminary_issues)} issues d'étapes")
        
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
            
            logger.debug(f"📊 Pièce {i+1}/{len(pieces_analysis_results)} ({piece_id}): {issues_avant_etapes} issues générales")
            
            # Ajouter les issues d'étapes à cette pièce si elle en a
            if piece_id in etapes_issues_by_piece:
                issues_etapes_ajoutees = len(etapes_issues_by_piece[piece_id])
                piece_analysis.issues.extend(etapes_issues_by_piece[piece_id])
                logger.debug(f"   🔗 Ajouté {issues_etapes_ajoutees} issues d'étapes à la pièce {piece_id}")
            else:
                logger.debug(f"   ℹ️ Aucune issue d'étape pour la pièce {piece_id}")
            
            # Compter le total des issues APRÈS ajout des étapes
            issues_apres_etapes = len(piece_analysis.issues)
            total_issues_count += issues_apres_etapes
            
            logger.debug(f"   📈 Total final pour pièce {piece_id}: {issues_apres_etapes} issues")

        # 🛡️ VÉRIFICATIONS FINALES AVANT TRANSMISSION
        logger.debug(f"📊 ÉTAPE 4 - Compilation et vérifications des résultats finaux")
        
        # Calculs de vérification
        verification_total = general_issues_count + etapes_issues_count
        
        logger.debug(f"🔍 VÉRIFICATIONS COMPTEURS:")
        logger.debug(f"   📋 Issues générales: {general_issues_count}")
        logger.debug(f"   🎯 Issues d'étapes: {etapes_issues_count}")
        logger.debug(f"   📊 Total calculé: {total_issues_count}")
        logger.debug(f"   🧮 Vérification: {general_issues_count} + {etapes_issues_count} = {verification_total}")
        
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
        logger.debug(f"🧠 ÉTAPE 5 - Génération de la synthèse globale via IA")
        
        # Vérifier que nous avons des données valides
        if not pieces_analysis_results:
            logger.error("❌ ERREUR: Aucune analyse de pièce pour la synthèse!")
            raise ValueError("Impossible de générer la synthèse sans données d'analyse")
        
        # Vérifier que logement_id est valide
        if not input_data.logement_id or input_data.logement_id.strip() == "":
            logger.error("❌ ERREUR: logement_id vide!")
            raise ValueError("logement_id manquant pour la synthèse")
        
        # 📊 LOG FINAL AVANT TRANSMISSION
        logger.debug(f"🚀 TRANSMISSION À L'IA DE SYNTHÈSE:")
        logger.debug(f"   🏠 Logement ID: {input_data.logement_id}")
        logger.debug(f"   🏘️ Nombre de pièces: {len(pieces_analysis_results)}")
        logger.debug(f"   📊 Total issues: {total_issues_count}")
        logger.debug(f"   📋 Issues générales: {general_issues_count}")
        logger.debug(f"   🎯 Issues étapes: {etapes_issues_count}")
        
        # ✅ APPEL SÉCURISÉ À L'IA DE SYNTHÈSE
        try:
            analysis_enrichment = generate_logement_enrichment(
                logement_id=input_data.logement_id,
                pieces_analysis=pieces_analysis_results,
                total_issues=total_issues_count,
                general_issues=general_issues_count,
                etapes_issues=etapes_issues_count,
                parcours_type=parcours_type,
                request_id=request_id
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
            logger.debug(f"🎯 Score basé sur le ressenti de l'IA: {note_finale}/5 ({analysis_enrichment.global_score.label})")
            
            logger.debug(f"✅ Enrichissement généré avec succès")
            logger.debug(f"   🏆 Note finale: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")
            
        except Exception as enrichment_error:
            logger.error(f"❌ ERREUR LORS DE L'ENRICHISSEMENT: {enrichment_error}")
            logger.error(f"   📊 Données transmises: logement_id={input_data.logement_id}, total_issues={total_issues_count}")
            raise enrichment_error
        
        complete_result = CompleteAnalysisResponse(
            logement_id=input_data.logement_id,
            logement_name=input_data.logement_name,  # Nom du logement
            rapport_id=input_data.rapport_id,
            pieces_analysis=pieces_analysis_results,
            total_issues_count=total_issues_count,
            etapes_issues_count=etapes_issues_count,
            general_issues_count=general_issues_count,
            analysis_enrichment=analysis_enrichment
        )
        
        logger.debug(f"🎉 ANALYSE COMPLÈTE terminée pour le logement {input_data.logement_id}")
        logger.debug(f"📊 RÉSUMÉ FINAL: {total_issues_count} issues totales ({general_issues_count} générales + {etapes_issues_count} étapes)")
        logger.info(f"🏆 NOTE GLOBALE VALIDÉE: {analysis_enrichment.global_score.score}/5 - {analysis_enrichment.global_score.label}")
        
        return complete_result
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'analyse complète: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'analyse complète: {str(e)}")

@app.post("/analyze-complete")
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
    # 🔍 TRACKING DES LOGS EN TEMPS RÉEL
    request_id = str(uuid.uuid4())
    logs_manager.start_request(
        request_id=request_id,
        endpoint="/analyze-complete",
        data={
            "logement_id": input_data.logement_id,
            "rapport_id": input_data.rapport_id,
            "pieces_count": len(input_data.pieces)
        }
    )

    # Récupérer le nom du logement pour les logs
    logement_display_name = input_data.logement_name or input_data.logement_adresse or input_data.logement_id

    logs_manager.add_log(
        request_id=request_id,
        level="INFO",
        message=f"🚀 Analyse complète démarrée pour le logement {input_data.logement_id}"
    )

    logger.warning(f"🏠 DÉBUT ANALYSE - Logement: {logement_display_name} (ID: {input_data.logement_id})")
    logger.debug(f"🚀 Analyse complète démarrée pour le logement {input_data.logement_id}")

    try:
        # 1. Effectuer l'analyse complète PARALLÉLISÉE ⚡
        step_analyze = logs_manager.add_step(
            request_id=request_id,
            step_name="Analyse complète parallélisée",
            step_type="analyze",
            metadata={"pieces_count": len(input_data.pieces)}
        )

        # Choisir la version de parallélisation selon disponibilité
        if PARALLEL_EXECUTOR_AVAILABLE:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"🚀 Utilisation de la version ULTRA-PARALLÉLISÉE avec cache avancé"
            )
            logger.debug(f"🚀 Utilisation de la version ULTRA-PARALLÉLISÉE avec cache avancé")
            result = await analyze_complete_logement_ultra_parallel(input_data, request_id=request_id)
        else:
            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"⚡ Utilisation de la version PARALLÉLISÉE standard"
            )
            logger.debug(f"⚡ Utilisation de la version PARALLÉLISÉE standard")
            result = await analyze_complete_logement_parallel(input_data, request_id=request_id)

        logs_manager.complete_step(
            request_id=request_id,
            step_id=step_analyze,
            status="success",
            result={
                "total_issues": result.total_issues_count,
                "general_issues": result.general_issues_count,
                "etapes_issues": result.etapes_issues_count
            }
        )
        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"🎯 Analyse complète terminée: {result.total_issues_count} issues totales"
        )

        logger.debug(f"🎯 Analyse complète terminée pour le logement {input_data.logement_id}")
        logger.debug(f"📊 Total: {result.total_issues_count} issues ({result.general_issues_count} générales + {result.etapes_issues_count} étapes)")

        # 1.5. Transformer vers le format individual-report-data-model.json (AVANT les webhooks)
        logger.debug(f"🔄 Transformation vers format individual-report pour logement {input_data.logement_id}")
        webhook_payload_individual = transform_to_individual_report(result, input_data)
        logger.debug(f"✅ Transformation terminée - Payload individual-report généré")

        # 2. Envoyer les DEUX webhooks de manière asynchrone (ne fait pas échouer la réponse)
        step_webhook = logs_manager.add_step(
            request_id=request_id,
            step_name="Envoi webhooks",
            step_type="synthesis",
            metadata={"webhook_count": 2}
        )

        try:
            # Détecter l'environnement
            environment = detect_environment()
            webhook_url_current = get_webhook_url(environment)
            webhook_url_individual = get_webhook_url_individual_report(environment)

            # Préparer le payload pour le webhook actuel (format CompleteAnalysisResponse)
            webhook_payload_current = result.model_dump()

            # Envoyer les deux webhooks EN PARALLÈLE pour optimiser les performances
            logger.debug(f"🔗 Envoi de 2 webhooks pour logement {input_data.logement_id} vers {environment}")
            logger.debug(f"   📤 Webhook 1 (actuel): {webhook_url_current}")
            logger.debug(f"   📤 Webhook 2 (individual-report): {webhook_url_individual}")

            # Utiliser asyncio.gather pour envoyer les deux webhooks simultanément
            webhook_results = await asyncio.gather(
                send_webhook(webhook_payload_current, webhook_url_current),
                send_webhook(webhook_payload_individual, webhook_url_individual),
                return_exceptions=True  # Ne pas faire échouer si un webhook échoue
            )

            # Analyser les résultats
            webhook_current_success = webhook_results[0] if not isinstance(webhook_results[0], Exception) else False
            webhook_individual_success = webhook_results[1] if not isinstance(webhook_results[1], Exception) else False

            # Logger les résultats
            if webhook_current_success:
                logger.debug(f"✅ Webhook actuel envoyé avec succès pour logement {input_data.logement_id}")
            else:
                logger.warning(f"⚠️ Échec webhook actuel pour logement {input_data.logement_id}")
                if isinstance(webhook_results[0], Exception):
                    logger.error(f"   Erreur: {webhook_results[0]}")

            if webhook_individual_success:
                logger.debug(f"✅ Webhook individual-report envoyé avec succès pour logement {input_data.logement_id}")
            else:
                logger.warning(f"⚠️ Échec webhook individual-report pour logement {input_data.logement_id}")
                if isinstance(webhook_results[1], Exception):
                    logger.error(f"   Erreur: {webhook_results[1]}")

            # Résumé
            success_count = sum([webhook_current_success, webhook_individual_success])
            logger.debug(f"📊 Résumé webhooks: {success_count}/2 envoyés avec succès")

            logs_manager.add_log(
                request_id=request_id,
                level="INFO",
                message=f"📊 Webhooks: {success_count}/2 envoyés avec succès"
            )

            logs_manager.complete_step(
                request_id=request_id,
                step_id=step_webhook,
                status="success" if success_count > 0 else "error",
                result={"success_count": success_count, "total": 2}
            )

        except Exception as webhook_error:
            # Les erreurs de webhook ne doivent jamais faire échouer l'analyse
            logger.error(f"❌ Erreur lors de l'envoi des webhooks pour logement {input_data.logement_id}: {webhook_error}")
            logger.info("ℹ️ L'analyse continue normalement malgré l'erreur webhook")

            logs_manager.add_log(
                request_id=request_id,
                level="ERROR",
                message=f"❌ Erreur webhooks: {str(webhook_error)}"
            )

            logs_manager.complete_step(
                request_id=request_id,
                step_id=step_webhook,
                status="error"
            )

        # 3. Retourner le rapport transformé au format individual-report (PAS le CompleteAnalysisResponse)
        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"✅ Analyse complète terminée avec succès - Retour du rapport transformé"
        )

        # Log de fin avec le nom du logement et la note
        try:
            final_score = result.analysis_enrichment.global_score.score
            final_label = result.analysis_enrichment.global_score.label
            logger.warning(f"✅ FIN ANALYSE - Logement: {logement_display_name} - Note: {final_score}/5 ({final_label})")
        except Exception:
            logger.warning(f"✅ FIN ANALYSE - Logement: {logement_display_name}")

        logs_manager.complete_request(
            request_id=request_id,
            status="success"
        )

        # 🔥 IMPORTANT: Retourner le rapport transformé, pas le CompleteAnalysisResponse
        return webhook_payload_individual

    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-complete: {str(e)}")

        logs_manager.add_log(
            request_id=request_id,
            level="ERROR",
            message=f"❌ Erreur: {str(e)}"
        )

        logs_manager.complete_request(
            request_id=request_id,
            status="error"
        )

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

# ═══════════════════════════════════════════════════════════════
# LOGS VIEWER - VISUALISATION EN TEMPS RÉEL
# ═══════════════════════════════════════════════════════════════

@app.get("/logs-viewer")
async def serve_logs_viewer():
    """Servir l'interface de visualisation des logs en temps réel"""
    import os
    file_path = os.path.join(os.path.dirname(__file__), "templates", "logs_viewer.html")
    if not os.path.exists(file_path):
        logger.error(f"❌ Fichier logs_viewer.html non trouvé à: {file_path}")
        raise HTTPException(status_code=404, detail="logs_viewer.html not found")
    return FileResponse(file_path)

@app.get("/api/logs/{request_id}")
async def get_logs(request_id: str):
    """Récupère les logs d'une requête (polling HTTP au lieu de WebSocket)"""
    all_requests = logs_manager.get_all_requests()

    if request_id not in all_requests:
        return {
            "status": "not_found",
            "message": f"Request {request_id} not found"
        }

    request_data = all_requests[request_id]
    return {
        "status": "ok",
        "request_id": request_id,
        "request": request_data,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/logs-debug")
async def get_logs_debug():
    """Endpoint de debug pour vérifier l'état du système de logs"""
    all_requests = logs_manager.get_all_requests()
    return {
        "status": "ok",
        "active_requests": len(logs_manager.active_requests),
        "completed_requests": len(logs_manager.completed_requests),
        "total_requests": len(all_requests),
        "requests_ids": list(all_requests.keys()),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/logs")
async def get_all_logs():
    """Récupère tous les logs (actifs + complétés) pour le polling"""
    all_requests = logs_manager.get_all_requests()
    return {
        "status": "ok",
        "requests": list(all_requests.values()),
        "count": len(all_requests),
        "active_count": len(logs_manager.active_requests),
        "completed_count": len(logs_manager.completed_requests),
        "timestamp": datetime.now().isoformat()
    }

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket pour diffuser les logs en temps réel"""
    try:
        await websocket.accept()
        logger.debug(f"✅ WebSocket accepté depuis {websocket.client}")
        await logs_manager.register_client(websocket)

        try:
            # Garder la connexion ouverte
            while True:
                # Attendre des messages du client (ping/pong)
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                    # On peut ignorer les messages du client pour l'instant
                except asyncio.TimeoutError:
                    # Envoyer un ping pour garder la connexion vivante
                    try:
                        await websocket.send_json({"type": "ping"})
                    except:
                        break
        except WebSocketDisconnect:
            logger.info(f"❌ WebSocket déconnecté")
            await logs_manager.unregister_client(websocket)
        except Exception as e:
            logger.error(f"Erreur WebSocket: {e}")
            await logs_manager.unregister_client(websocket)
    except Exception as e:
        logger.error(f"Erreur lors de l'acceptation WebSocket: {e}")

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

        logger.debug(f"✅ Templates {parcours_type} sauvegardés dans le fichier: {target_path}")
        success_local = True

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde fichier local ({parcours_type}): {e}")

    try:
        # 🔥 SAUVEGARDE 2: Variable d'environnement (pour Railway production)
        templates_json = json.dumps(templates_data, ensure_ascii=False, separators=(',', ':'))

        # Note: En production Railway, cette mise à jour nécessitera un redémarrage
        # Pour une vraie persistence, il faudrait utiliser l'API Railway ou une DB
        os.environ[env_var_name] = templates_json

        logger.debug(f"✅ Templates {parcours_type} mis à jour dans les variables d'environnement ({env_var_name})")
        success_env = True

        # 🔥 IMPORTANT: Informer l'utilisateur pour Railway
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            logger.warning(f"⚠️ RAILWAY: Les modifications {parcours_type} seront perdues au prochain déploiement!")
            logger.warning(f"💡 Utilisez l'interface d'admin Railway pour définir {env_var_name} de façon permanente")

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde variable d'environnement ({parcours_type}): {e}")

    # Logs de vérification
    if success_local or success_env:
        logger.debug(f"🔥 Templates {parcours_type} mis à jour - Modifications IMMÉDIATEMENT effectives!")

        if "room_types" in templates_data:
            for room_key, room_info in templates_data["room_types"].items():
                points_ignorables = room_info.get("verifications", {}).get("points_ignorables", [])
                logger.debug(f"   📝 {room_key}: {len(points_ignorables)} points ignorables en mémoire")

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
            "verifications": room_data.verifications.model_dump()
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
            room_types[room_type_key]["verifications"] = room_data.verifications.model_dump()

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
            logger.debug(f"   📝 {room_key}: {len(points_ignorables)} points ignorables")
        
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

        logger.info(f"🔧 Chargement de la config prompts pour le parcours: {parcours_type} (suffixe: {file_suffix})")

        # 🔥 PRIORITÉ 1: Variable d'environnement Railway (production)
        prompts_config_env = os.environ.get(env_var_name)
        if prompts_config_env:
            try:
                logger.debug(f"📡 Chargement de la config prompts depuis la variable d'environnement {env_var_name}")
                config = json.loads(prompts_config_env)
                logger.debug(f"✅ Config prompts {parcours_type} chargée depuis variable d'environnement")
                
                # 🔴🔴🔴 DEBUG PROMPTS LOADING FROM ENV - TRÈS VISIBLE 🔴🔴🔴
                logger.debug("")
                logger.debug("=" * 100)
                logger.debug("🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣")
                logger.debug("🟡🟡🟡  DEBUG CHARGEMENT PROMPTS DEPUIS RAILWAY ENV  🟡🟡🟡")
                logger.debug("🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣🟣")
                logger.debug("=" * 100)
                logger.debug(f"📂 SOURCE: VARIABLE D'ENVIRONNEMENT RAILWAY")
                logger.debug(f"🔑 VARIABLE: {env_var_name}")
                logger.debug(f"🧳 TYPE PARCOURS: {parcours_type}")
                logger.info(f"📅 VERSION: {config.get('version', 'N/A')}")
                logger.info(f"📅 DERNIÈRE MAJ: {config.get('last_updated', 'N/A')}")
                logger.info(f"📝 DESCRIPTION: {config.get('description', 'N/A')}")
                logger.debug("-" * 100)
                
                # Afficher le contenu du prompt analyze_main
                analyze_main = config.get('prompts', {}).get('analyze_main', {})
                if analyze_main:
                    logger.debug("🎯 PROMPT PRINCIPAL (analyze_main):")
                    logger.debug(f"   📌 Nom: {analyze_main.get('name', 'N/A')}")
                    logger.debug(f"   📌 Endpoint: {analyze_main.get('endpoint', 'N/A')}")
                    logger.debug(f"   📌 Variables: {analyze_main.get('variables', [])}")
                    logger.debug("-" * 100)
                    logger.debug("📜 CONTENU DES SECTIONS:")
                    
                    sections = analyze_main.get('sections', {})
                    for section_name, section_content in sections.items():
                        if section_content and len(str(section_content)) > 10:
                            logger.debug(f"")
                            logger.debug(f"   🔶 SECTION [{section_name}]:")
                            logger.debug(f"   {'─' * 80}")
                            content_lines = str(section_content).split('\n')
                            for i, line in enumerate(content_lines[:100]):
                                logger.debug(f"   {i+1:3d} | {line}")
                            if len(content_lines) > 100:
                                logger.debug(f"   ... [{len(content_lines) - 100} lignes supplémentaires tronquées]")
                            logger.debug(f"   {'─' * 80}")
                
                logger.debug("=" * 100)
                logger.debug("🟣🟣🟣  FIN DEBUG CHARGEMENT PROMPTS RAILWAY ENV  🟣🟣🟣")
                logger.debug("=" * 100)
                logger.debug("")
                # 🔴🔴🔴 FIN DEBUG 🔴🔴🔴
                
                return config
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
                logger.debug(f"📁 Chargement de la config prompts depuis le fichier: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.debug(f"✅ Config prompts {parcours_type} chargée depuis fichier: {config.get('description', 'N/A')}")
                
                # 🔴🔴🔴 DEBUG PROMPTS LOADING - TRÈS VISIBLE 🔴🔴🔴
                logger.debug("")
                logger.debug("=" * 100)
                logger.debug("🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴")
                logger.debug("🟡🟡🟡  DEBUG CHARGEMENT PROMPTS - CONTENU COMPLET  🟡🟡🟡")
                logger.debug("🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴🔴")
                logger.debug("=" * 100)
                logger.debug(f"📂 SOURCE: FICHIER LOCAL")
                logger.debug(f"📁 CHEMIN: {path}")
                logger.debug(f"🧳 TYPE PARCOURS: {parcours_type}")
                logger.info(f"📅 VERSION: {config.get('version', 'N/A')}")
                logger.info(f"📅 DERNIÈRE MAJ: {config.get('last_updated', 'N/A')}")
                logger.info(f"📝 DESCRIPTION: {config.get('description', 'N/A')}")
                logger.debug("-" * 100)
                
                # Afficher le contenu du prompt analyze_main (le plus important)
                analyze_main = config.get('prompts', {}).get('analyze_main', {})
                if analyze_main:
                    logger.debug("🎯 PROMPT PRINCIPAL (analyze_main):")
                    logger.debug(f"   📌 Nom: {analyze_main.get('name', 'N/A')}")
                    logger.debug(f"   📌 Endpoint: {analyze_main.get('endpoint', 'N/A')}")
                    logger.debug(f"   📌 Variables: {analyze_main.get('variables', [])}")
                    logger.debug("-" * 100)
                    logger.debug("📜 CONTENU DES SECTIONS:")
                    
                    sections = analyze_main.get('sections', {})
                    for section_name, section_content in sections.items():
                        if section_content and len(str(section_content)) > 10:  # Ignorer les sections vides
                            logger.debug(f"")
                            logger.debug(f"   🔶 SECTION [{section_name}]:")
                            logger.debug(f"   {'─' * 80}")
                            # Afficher le contenu ligne par ligne pour la lisibilité
                            content_lines = str(section_content).split('\n')
                            for i, line in enumerate(content_lines[:100]):  # Limiter à 100 lignes par section
                                logger.debug(f"   {i+1:3d} | {line}")
                            if len(content_lines) > 100:
                                logger.debug(f"   ... [{len(content_lines) - 100} lignes supplémentaires tronquées]")
                            logger.debug(f"   {'─' * 80}")
                
                logger.debug("=" * 100)
                logger.debug("🔴🔴🔴  FIN DEBUG CHARGEMENT PROMPTS  🔴🔴🔴")
                logger.debug("=" * 100)
                logger.debug("")
                # 🔴🔴🔴 FIN DEBUG 🔴🔴🔴
                
                return config

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
                "template": "Compare les PHOTOS DE RÉFÉRENCE (état attendu) avec les PHOTOS DE SORTIE (état actuel) de cette {piece_nom}. Identifie ce qui manque, ce qui est endommagé, ou ce qui n'est pas conforme à la référence. Fournis une réponse JSON structurée.",
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

        logger.debug(f"✅ Config prompts {parcours_type} sauvegardée dans le fichier: {target_path}")
        success_local = True

    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde fichier local prompts ({parcours_type}): {e}")

    try:
        # 🔥 SAUVEGARDE 2: Variable d'environnement (pour Railway production)
        config_json = json.dumps(config_data, ensure_ascii=False, separators=(',', ':'))

        # Note: En production Railway, cette mise à jour nécessitera un redémarrage
        os.environ[env_var_name] = config_json

        logger.debug(f"✅ Config prompts {parcours_type} mise à jour dans les variables d'environnement ({env_var_name})")
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
async def update_prompts_config(config: PromptsConfig, type: str = "Voyageur"):
    """Sauvegarder la configuration complète des prompts selon le type de parcours"""
    try:
        # Ajouter le timestamp de mise à jour
        config_dict = config.model_dump()
        config_dict["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        if save_prompts_config(config_dict, type):
            return {
                "success": True,
                "message": f"Configuration des prompts {type} sauvegardée avec succès",
                "last_updated": config_dict["last_updated"],
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la config prompts ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/prompts/{prompt_key}")
async def get_prompt(prompt_key: str, type: str = "Voyageur"):
    """Récupérer un prompt spécifique selon le type de parcours"""
    try:
        config = load_prompts_config(type)

        if prompt_key in config.get("prompts", {}):
            return {
                "success": True,
                "prompt": config["prompts"][prompt_key],
                "parcours_type": type
            }
        elif prompt_key in config.get("user_messages", {}):
            return {
                "success": True,
                "user_message": config["user_messages"][prompt_key],
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=404, detail="Prompt non trouvé")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du prompt {prompt_key} ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/prompts/{prompt_key}")
async def update_prompt(prompt_key: str, prompt_data: dict, type: str = "Voyageur"):
    """Mettre à jour un prompt spécifique selon le type de parcours"""
    try:
        config = load_prompts_config(type)

        if prompt_key in config.get("prompts", {}):
            config["prompts"][prompt_key] = prompt_data
        elif prompt_key in config.get("user_messages", {}):
            config["user_messages"][prompt_key] = prompt_data
        else:
            raise HTTPException(status_code=404, detail="Prompt non trouvé")

        config["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        if save_prompts_config(config, type):
            return {
                "success": True,
                "message": f"Prompt {prompt_key} mis à jour avec succès (parcours {type})",
                "last_updated": config["last_updated"],
                "parcours_type": type
            }
        else:
            raise HTTPException(status_code=500, detail="Erreur lors de la sauvegarde")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du prompt {prompt_key} ({type}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/prompts/preview")
async def preview_prompt(request: PromptPreviewRequest, type: str = "Voyageur"):
    """Prévisualiser un prompt avec des variables d'exemple selon le type de parcours"""
    try:
        config = load_prompts_config(type)

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
            "variables_used": request.variables,
            "parcours_type": type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la prévisualisation du prompt {request.prompt_key} ({type}): {e}")
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

    logger.debug(f"🏗️ Sections disponibles: {list(sections.keys())}")

    for section_key, content in sections.items():
        # 🔥 CORRECTION CRITIQUE: Remplacer les variables dans TOUTES les sections
        # Pas seulement celles qui finissent par '_template'
        section_content = replace_variables_in_template(content, variables)

        # Log pour vérifier si instructions_finales est bien incluse
        if section_key == "instructions_finales" and content:
            logger.debug(f"✅ Section instructions_finales trouvée: {len(content)} caractères")
            logger.info(f"📝 Contenu: {content[:200]}...")

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

    # Vérification finale des variables non remplacées (seulement les vraies variables template)
    import re
    # Pattern pour les vraies variables template: {VARIABLE_NAME} en majuscules avec underscores
    vraies_variables = re.findall(r'\{[A-Z][A-Z0-9_]+\}', final_prompt)
    if vraies_variables:
        logger.warning(f"🏗️ Variables template non remplacées: {vraies_variables}")

    logger.debug(f"🏗️ Prompt construit: {len(final_prompt)} caractères, {len(sections)} sections")
    
    return final_prompt

@app.get("/prompts/export/railway-env")
async def export_prompts_for_railway(type: str = "Voyageur"):
    """🚀 Exporter la configuration actuelle des prompts pour Railway (variable d'environnement)"""
    try:
        config = load_prompts_config(type)
        env_var_value = json.dumps(config, ensure_ascii=False, separators=(',', ':'))

        # Déterminer le nom de la variable selon le type
        var_name = f"PROMPTS_CONFIG_{type.upper()}" if type.lower() == "ménage" else f"PROMPTS_CONFIG_{type.upper()}"

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
    except Exception as e:
        logger.error(f"Erreur lors de l'export Railway des prompts ({type}): {e}")
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
async def serve_scoring_admin(type: str = "Voyageur"):
    """Servir l'interface d'administration pour gérer le système de notation"""
    try:
        # Charger la configuration selon le type de parcours
        config = load_scoring_config(type)

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
async def save_scoring_config_endpoint(request: Request, type: str = "Voyageur"):
    """Sauvegarder la configuration du système de notation"""
    try:
        # Récupérer les données JSON
        new_config = await request.json()

        # Déterminer le suffixe du fichier selon le type
        if type.lower() == "ménage":
            file_suffix = "-menage"
        else:  # Par défaut: Voyageur
            file_suffix = "-voyageur"

        config_path = f"front/scoring-config{file_suffix}.json"

        # Créer un backup avant modification
        import shutil
        from datetime import datetime
        backup_path = f"front/scoring-config{file_suffix}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if os.path.exists(config_path):
            shutil.copy(config_path, backup_path)
            logger.debug(f"✅ Backup créé : {backup_path}")

        # Sauvegarder la nouvelle configuration
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)

        logger.debug(f"✅ Configuration du scoring {type} sauvegardée avec succès dans {config_path}")
        logger.debug(f"📊 Dernière mise à jour : {new_config.get('last_updated', 'N/A')}")

        return {"success": True, "message": "Configuration sauvegardée avec succès"}
    except Exception as e:
        logger.error(f"❌ Erreur lors de la sauvegarde de la configuration scoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scoring-config/reset")
async def reset_scoring_config_endpoint(type: str = "Voyageur"):
    """Réinitialiser la configuration du système de notation aux valeurs par défaut"""
    try:
        # Déterminer le suffixe du fichier selon le type
        if type.lower() == "ménage":
            file_suffix = "-menage"
            description_suffix = "🧹 MÉNAGE - Critères stricts pour agents de ménage"
        else:  # Par défaut: Voyageur
            file_suffix = "-voyageur"
            description_suffix = "🧳 VOYAGEUR - Critères souples pour voyageurs"

        config_path = f"front/scoring-config{file_suffix}.json"

        # Valeurs par défaut V2 - Nouvelle logique: Note = 5 - Σ(pénalités)
        is_menage = type.lower() == "ménage"
        default_config = {
            "version": "2.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "description": f"Configuration du système de notation V2 - Note = 5 - pénalités - {description_suffix}",
            "scoring_system": {
                "severity_penalty": {
                    "description": "Pénalité directe soustraite de la note selon la sévérité",
                    "high": 1.0 if is_menage else 0.8,
                    "medium": 0.4 if is_menage else 0.3,
                    "low": 0.15 if is_menage else 0.1
                },
                "category_multiplier": {
                    "description": "Multiplicateur de la pénalité selon la catégorie d'issue",
                    "cleanliness": 1.5 if is_menage else 1.0,
                    "positioning": 1.2 if is_menage else 0.8,
                    "damage": 1.0 if is_menage else 1.5,
                    "missing_item": 1.0 if is_menage else 1.2,
                    "added_item": 0.5 if is_menage else 0.4,
                    "image_quality": 0.3,
                    "wrong_room": 2.0,
                    "other": 1.0
                },
                "room_importance_weight": {
                    "description": "Poids d'importance par type de pièce (pour la moyenne pondérée des notes)",
                    "cuisine": 2.0,
                    "salle_de_bain": 1.8,
                    "salle_de_bain_et_toilettes": 1.8,
                    "salle_d_eau": 1.7,
                    "salle_d_eau_et_wc": 1.7,
                    "wc": 1.5,
                    "salon": 1.2,
                    "salon_cuisine": 1.8,
                    "chambre": 1.0,
                    "bureau": 1.0,
                    "entree": 0.8,
                    "exterieur": 0.6,
                    "cle": 0.8,
                    "autre": 0.8
                },
                "confidence_threshold": {
                    "description": "Seuil de confiance minimum pour qu'une issue soit prise en compte",
                    "value": 90
                },
                "min_grade": {
                    "description": "Note minimale possible",
                    "value": 1.0
                },
                "max_grade": {
                    "description": "Note maximale possible (note de départ sans pénalité)",
                    "value": 5.0
                }
            },
            "labels": {
                "description": "Labels correspondant aux plages de notes",
                "ranges": [
                    {"min": 4.5, "max": 5.0, "label": "EXCELLENT"},
                    {"min": 4.0, "max": 4.49, "label": "TRÈS BON"},
                    {"min": 3.5, "max": 3.99, "label": "BON"},
                    {"min": 3.0, "max": 3.49, "label": "CORRECT"},
                    {"min": 2.5, "max": 2.99, "label": "MOYEN"},
                    {"min": 2.0, "max": 2.49, "label": "PASSABLE"},
                    {"min": 1.5, "max": 1.99, "label": "INSUFFISANT"},
                    {"min": 1.0, "max": 1.49, "label": "CRITIQUE"}
                ]
            },
            "metadata": {
                "created_by": "CheckEasy Admin",
                "notes": "Configuration V2 - Logique simple: Note = 5 - Σ(pénalités). Chaque issue retire directement des points."
            }
        }

        # Créer un backup avant réinitialisation
        import shutil
        backup_path = f"front/scoring-config{file_suffix}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if os.path.exists(config_path):
            shutil.copy(config_path, backup_path)
            logger.debug(f"✅ Backup créé avant réinitialisation : {backup_path}")

        # Sauvegarder la configuration par défaut
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        logger.debug(f"✅ Configuration du scoring {type} réinitialisée aux valeurs par défaut dans {config_path}")

        return {"success": True, "message": "Configuration réinitialisée", "config": default_config}
    except Exception as e:
        logger.error(f"❌ Erreur lors de la réinitialisation de la configuration scoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def load_scoring_config(parcours_type: str = "Voyageur") -> dict:
    """
    Charger la configuration du système de notation depuis le fichier JSON selon le type de parcours

    Args:
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        dict: Configuration du scoring
    """
    try:
        # Déterminer le suffixe du fichier selon le type
        # Supporter plusieurs variantes: "ménage", "menage", "Ménage", "Menage"
        parcours_lower = parcours_type.lower().replace("é", "e")
        if parcours_lower == "menage":
            file_suffix = "-menage"
        else:  # Par défaut: Voyageur
            file_suffix = "-voyageur"

        config_path = f"front/scoring-config{file_suffix}.json"
        logger.debug(f"📂 Chargement config scoring: parcours_type='{parcours_type}' → fichier={config_path}")

        if not os.path.exists(config_path):
            logger.warning(f"⚠️ Fichier de configuration scoring non trouvé : {config_path}")
            logger.info("📝 Création du fichier avec les valeurs par défaut V2...")

            # Configuration V2 par défaut
            is_menage = parcours_type.lower() == "ménage"
            default_config = {
                "version": "2.0.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "description": f"Configuration V2 - Note = 5 - pénalités - {'Ménage' if is_menage else 'Voyageur'}",
                "scoring_system": {
                    "severity_penalty": {
                        "high": 1.0 if is_menage else 0.8,
                        "medium": 0.4 if is_menage else 0.3,
                        "low": 0.15 if is_menage else 0.1
                    },
                    "category_multiplier": {
                        "cleanliness": 1.5 if is_menage else 1.0,
                        "positioning": 1.2 if is_menage else 0.8,
                        "damage": 1.0 if is_menage else 1.5,
                        "missing_item": 1.0 if is_menage else 1.2,
                        "added_item": 0.5 if is_menage else 0.4,
                        "image_quality": 0.3,
                        "wrong_room": 2.0,
                        "other": 1.0
                    },
                    "room_importance_weight": {
                        "cuisine": 2.0, "salle_de_bain": 1.8, "salle_de_bain_et_toilettes": 1.8,
                        "salle_d_eau": 1.7, "salle_d_eau_et_wc": 1.7, "wc": 1.5,
                        "salon": 1.2, "salon_cuisine": 1.8, "chambre": 1.0, "bureau": 1.0, "entree": 0.8,
                        "exterieur": 0.6, "cle": 0.8, "autre": 0.8
                    },
                    "confidence_threshold": {"value": 90},
                    "min_grade": {"value": 1.0},
                    "max_grade": {"value": 5.0}
                },
                "labels": {
                    "ranges": [
                        {"min": 4.5, "max": 5.0, "label": "EXCELLENT"},
                        {"min": 4.0, "max": 4.49, "label": "TRÈS BON"},
                        {"min": 3.5, "max": 3.99, "label": "BON"},
                        {"min": 3.0, "max": 3.49, "label": "CORRECT"},
                        {"min": 2.5, "max": 2.99, "label": "MOYEN"},
                        {"min": 2.0, "max": 2.49, "label": "PASSABLE"},
                        {"min": 1.5, "max": 1.99, "label": "INSUFFISANT"},
                        {"min": 1.0, "max": 1.49, "label": "CRITIQUE"}
                    ]
                }
            }

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)

            return default_config

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        logger.debug(f"✅ Configuration scoring {parcours_type} chargée depuis {config_path}")
        return config

    except Exception as e:
        logger.error(f"❌ Erreur lors du chargement de la configuration scoring: {e}")
        # Configuration V2 de fallback en cas d'erreur
        return {
            "scoring_system": {
                "severity_penalty": {"high": 0.8, "medium": 0.3, "low": 0.1},
                "category_multiplier": {
                    "damage": 1.5, "cleanliness": 1.0, "missing_item": 1.2,
                    "positioning": 0.8, "added_item": 0.4, "image_quality": 0.3,
                    "wrong_room": 2.0, "other": 1.0
                },
                "room_importance_weight": {
                    "cuisine": 2.0, "salle_de_bain": 1.8, "salle_de_bain_et_toilettes": 1.8,
                    "salle_d_eau": 1.7, "salle_d_eau_et_wc": 1.7, "wc": 1.5,
                    "salon": 1.2, "salon_cuisine": 1.8, "chambre": 1.0, "bureau": 1.0, "entree": 0.8,
                    "exterieur": 0.6, "cle": 0.8, "autre": 0.8
                },
                "confidence_threshold": {"value": 90},
                "min_grade": {"value": 1.0},
                "max_grade": {"value": 5.0}
            },
            "labels": {
                "ranges": [
                    {"min": 4.5, "max": 5.0, "label": "EXCELLENT"},
                    {"min": 4.0, "max": 4.49, "label": "TRÈS BON"},
                    {"min": 3.5, "max": 3.99, "label": "BON"},
                    {"min": 3.0, "max": 3.49, "label": "CORRECT"},
                    {"min": 2.5, "max": 2.99, "label": "MOYEN"},
                    {"min": 2.0, "max": 2.49, "label": "PASSABLE"},
                    {"min": 1.5, "max": 1.99, "label": "INSUFFISANT"},
                    {"min": 1.0, "max": 1.49, "label": "CRITIQUE"}
                ]
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
        "salle_de_bain_et_toilettee": "salle_de_bain_et_toilettes",  # Typo courante de l'IA (double e)
        "salle_d_eau_et_toilettes": "salle_d_eau_et_wc",  # Variation de nommage
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
        logger.debug(f"🗺️ Type mappé: '{detected_type}' → '{mapped_type}'")
        return mapped_type
    
    # Si pas de mapping direct, chercher des mots-clés
    for variant, valid_type in mapping.items():
        if variant in normalized or normalized in variant:
            logger.debug(f"🗺️ Type mappé par mots-clés: '{detected_type}' → '{valid_type}'")
            return valid_type
    
    # Si aucun mapping trouvé, retourner le type original
    logger.debug(f"🗺️ Aucun mapping trouvé pour '{detected_type}', utilisation directe")
    return normalized

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
