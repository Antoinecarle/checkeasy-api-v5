from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from models import *
from config import *
from scoring import *
from webhook import *
from openai_utils import *
from services.analysis import *
from services.etapes import *
from services.orchestration import *
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
import traceback

# Import du gestionnaire de logs
from logs_viewer.logs_manager import logs_manager

# 🚀 CONFIGURATION LOGGING OPTIMISÉE RAILWAY
import re

def truncate_base64_in_text(text: str, max_base64_length: int = 50) -> str:
    """Tronque les chaînes base64 dans un texte pour éviter de polluer les logs"""
    if not text or len(text) < 100:
        return text

    # Pattern pour détecter les data URIs base64
    data_uri_pattern = r'data:image/[^;]+;base64,[A-Za-z0-9+/=]{50,}'
    text = re.sub(data_uri_pattern, lambda m: m.group(0)[:40] + '...[base64 truncated]', text)

    # Pattern pour détecter les longues chaînes base64 brutes (>100 chars de A-Za-z0-9+/=)
    base64_pattern = r'[A-Za-z0-9+/=]{100,}'
    text = re.sub(base64_pattern, lambda m: m.group(0)[:50] + '...[truncated ' + str(len(m.group(0))) + ' chars]', text)

    return text

class RailwayJSONFormatter(logging.Formatter):
    """
    Formatter JSON optimisé pour Railway qui produit des logs structurés
    sans caractères spéciaux qui causent des problèmes d'interprétation
    """

    def format(self, record):
        # Créer un objet de log structuré
        from datetime import datetime
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

        # Récupérer et tronquer le message si nécessaire
        message = record.getMessage()
        message = truncate_base64_in_text(message)

        log_obj = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Ajouter le traceback si présent (aussi tronqué)
        if record.exc_info:
            exception_text = self.formatException(record.exc_info)
            log_obj["exception"] = truncate_base64_in_text(exception_text)

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

def truncate_url_for_log(url: str, max_length: int = 100) -> str:
    """Tronque une URL pour les logs (évite les base64 énormes)"""
    if not url:
        return url
    if url.startswith('data:'):
        # Pour les data URIs, afficher seulement le type MIME
        mime_end = url.find(';')
        if mime_end > 0:
            return f"{url[:mime_end]}...[base64 truncated]"
        return "data:...[base64 truncated]"
    if len(url) > max_length:
        return url[:max_length] + "..."
    return url

# ========== LOGGING DÉTAILLÉ DES REQUÊTES/RÉPONSES ==========

def log_request_received(endpoint: str, data: dict, request_id: str = None):
    """Log détaillé des données reçues par un endpoint"""
    logger.info(f"{'='*60}")
    logger.info(f"📥 REQUÊTE REÇUE - {endpoint}")
    logger.info(f"{'='*60}")

    if request_id:
        logger.info(f"   🆔 Request ID: {request_id}")

    # Log des champs principaux
    if 'logement_id' in data:
        logger.info(f"   🏠 Logement ID: {data['logement_id']}")
    if 'piece_id' in data:
        logger.info(f"   🚪 Pièce ID: {data['piece_id']}")
    if 'nom' in data:
        logger.info(f"   📛 Nom: {data['nom']}")
    if 'type' in data:
        logger.info(f"   📋 Type parcours: {data['type']}")

    # Log des images
    if 'checkin_pictures' in data:
        pics = data['checkin_pictures']
        logger.info(f"   📸 Checkin pictures: {len(pics)} images")
        for i, pic in enumerate(pics[:3]):  # Max 3 pour éviter spam
            url = pic.get('url', pic) if isinstance(pic, dict) else str(pic)
            logger.info(f"      [{i+1}] {truncate_url_for_log(url, 80)}")
        if len(pics) > 3:
            logger.info(f"      ... et {len(pics) - 3} autres images")

    if 'checkout_pictures' in data:
        pics = data['checkout_pictures']
        logger.info(f"   📸 Checkout pictures: {len(pics)} images")
        for i, pic in enumerate(pics[:3]):
            url = pic.get('url', pic) if isinstance(pic, dict) else str(pic)
            logger.info(f"      [{i+1}] {truncate_url_for_log(url, 80)}")
        if len(pics) > 3:
            logger.info(f"      ... et {len(pics) - 3} autres images")

    # Log des pièces (pour analyze-complete)
    if 'pieces' in data:
        pieces = data['pieces']
        logger.info(f"   🏠 Pièces: {len(pieces)} pièces")
        for p in pieces[:5]:
            piece_id = p.get('piece_id', 'N/A')
            nom = p.get('nom', 'N/A')
            checkin = len(p.get('checkin_pictures', []))
            checkout = len(p.get('checkout_pictures', []))
            etapes = len(p.get('etapes', []))
            logger.info(f"      • {nom} ({piece_id}): {checkin} checkin, {checkout} checkout, {etapes} étapes")
        if len(pieces) > 5:
            logger.info(f"      ... et {len(pieces) - 5} autres pièces")

    # Log des étapes
    if 'etapes' in data and isinstance(data['etapes'], list):
        etapes = data['etapes']
        if etapes and isinstance(etapes[0], dict):
            logger.info(f"   📝 Étapes: {len(etapes)} étapes")
            for e in etapes[:3]:
                etape_id = e.get('etape_id', 'N/A')
                consigne = e.get('consigne', 'N/A')[:50]
                logger.info(f"      • {etape_id}: {consigne}...")
            if len(etapes) > 3:
                logger.info(f"      ... et {len(etapes) - 3} autres étapes")

    logger.info(f"{'='*60}")

def log_openai_request_details(model: str, messages: list, endpoint: str = "OpenAI"):
    """Log détaillé de ce qui est envoyé à OpenAI"""
    logger.info(f"📤 ENVOI À {endpoint}")
    logger.info(f"   🤖 Modèle: {model}")
    logger.info(f"   📨 Messages: {len(messages)}")

    for i, msg in enumerate(messages):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        if isinstance(content, str):
            logger.info(f"   [{i+1}] {role}: {len(content)} caractères")
        elif isinstance(content, list):
            text_count = sum(1 for c in content if c.get('type') == 'text')
            image_count = sum(1 for c in content if c.get('type') == 'image_url')
            logger.info(f"   [{i+1}] {role}: {text_count} textes, {image_count} images")

def log_openai_response_details(response_content: str, tokens_used: int = None):
    """Log détaillé de la réponse OpenAI"""
    logger.info(f"📥 RÉPONSE OPENAI REÇUE")
    logger.info(f"   📄 Taille: {len(response_content)} caractères")
    if tokens_used:
        logger.info(f"   🎫 Tokens utilisés: {tokens_used}")

    # Aperçu du contenu (premiers 200 chars)
    preview = response_content[:200].replace('\n', ' ')
    logger.info(f"   👀 Aperçu: {preview}...")

def log_response_sent(endpoint: str, response_data: dict, success: bool = True):
    """Log détaillé de la réponse envoyée au client"""
    status = "✅ SUCCÈS" if success else "❌ ERREUR"
    logger.info(f"{'='*60}")
    logger.info(f"📤 RÉPONSE ENVOYÉE - {endpoint} - {status}")
    logger.info(f"{'='*60}")

    if 'piece_id' in response_data:
        logger.info(f"   🚪 Pièce: {response_data.get('piece_id')}")
    if 'nom_piece' in response_data:
        logger.info(f"   📛 Nom: {response_data.get('nom_piece')}")
    if 'room_type' in response_data:
        logger.info(f"   🏷️ Type détecté: {response_data.get('room_type')}")
    if 'confidence' in response_data:
        logger.info(f"   📊 Confiance: {response_data.get('confidence')}%")

    # Analyse globale
    if 'analyse_globale' in response_data:
        ag = response_data['analyse_globale']
        logger.info(f"   📊 Analyse globale:")
        logger.info(f"      • Status: {ag.get('status')}")
        logger.info(f"      • Score: {ag.get('score')}")
        logger.info(f"      • Temps nettoyage: {ag.get('temps_nettoyage_estime')}")

    # Issues
    if 'preliminary_issues' in response_data:
        issues = response_data['preliminary_issues']
        logger.info(f"   ⚠️ Issues détectées: {len(issues)}")
        for issue in issues[:3]:
            desc = issue.get('description', 'N/A')[:60]
            severity = issue.get('severity', 'N/A')
            logger.info(f"      • [{severity}] {desc}...")
        if len(issues) > 3:
            logger.info(f"      ... et {len(issues) - 3} autres issues")

    # Résumé pièces (pour analyze-complete)
    if 'pieces_results' in response_data:
        pieces = response_data['pieces_results']
        logger.info(f"   🏠 Résultats pièces: {len(pieces)}")

    logger.info(f"{'='*60}")

# Créer l'application FastAPI
app = FastAPI(
    title="API d'Analyse d'Images",
    description="API pour analyser les différences entre les photos d'entrée et de sortie d'une pièce",
    version="1.0.0"
)

# Configurer CORS - origines restreintes
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8080",
        "http://72.61.194.129:5173",
        "http://72.61.194.129:8000",
        "https://checkeasy.co",
        "https://app.checkeasy.co",
        "https://check.checkeasy.co",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Key Authentication middleware (only enforced if API_SECRET_KEY is set in .env)
from auth import APIKeyAuthMiddleware
app.add_middleware(APIKeyAuthMiddleware)

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Monter les fichiers statiques
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates-static", StaticFiles(directory="templates"), name="templates-static")

# ═══════════════════════════════════════════════════════════════
# SUPABASE CLIENT (READ-ONLY) - Pour le Rapport Tester
# ═══════════════════════════════════════════════════════════════
_supabase_client = None

def get_supabase():
    """Read-only Supabase client. NEVER use for insert/update/delete."""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
        except ImportError:
            raise HTTPException(500, "supabase package not installed")
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise HTTPException(500, "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client

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

# ═══════════════════════════════════════════════════════════════
# 🔗 CONFIGURATION WEBHOOK (extracted to webhook.py)
# ═══════════════════════════════════════════════════════════════

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

🆕 RÈGLE CRITIQUE - COUVERTURE PHOTO :
7. AVANT de déclarer un objet "missing", vérifie si la ZONE où il se trouvait est visible sur les photos de sortie
8. Si la zone de l'objet (ex: "à gauche du lit", "coin droit de la pièce") N'EST PAS VISIBLE sur les photos de sortie → status = "not_verifiable"
9. Un objet est "not_verifiable" quand le CADRAGE ou l'ANGLE des photos de sortie ne couvre pas la zone où il était visible à l'entrée

📸 EXEMPLES DE "not_verifiable" :
- Armoire visible à gauche sur photo entrée, mais photo sortie cadrée sur la droite
- Objet dans un coin non photographié en sortie
- Photo de sortie prise d'un angle différent qui masque certaines zones

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
            "details": "Non visible sur aucune des X photos de sortie alors que la zone est bien visible"
        }
    ],
    "not_verifiable_objects": [
        {
            "object_id": "obj_YYY",
            "name": "Nom",
            "location": "Localisation sur photo entrée",
            "status": "not_verifiable",
            "confidence": 90,
            "details": "Zone non couverte par les photos de sortie - cadrage différent empêchant la vérification"
        }
    ],
    "moved_objects": [...],
    "present_objects": [...]
}

🚨 IMPORTANT :
- Un objet est "missing" UNIQUEMENT si la zone où il se trouvait EST VISIBLE sur les photos de sortie ET que l'objet n'y apparaît pas
- Si la zone n'est pas visible → "not_verifiable" (PAS "missing")
- Ne pas confondre "objet volé" et "photo mal cadrée"
"""


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
            present_objects=[],
            not_verifiable_objects=[]
        )

    logger.debug(f"🔀 [AGGREGATE] Agrégation de {len(responses)} réponses de vérification...")

    # Collecter les votes pour chaque objet de l'inventaire
    object_status_votes = {}  # object_id -> {missing: count, moved: count, present: count, not_verifiable: count, details: []}

    for resp in responses:
        model_weight = resp.get("weight", 1.0)

        # Traiter les objets manquants
        for obj in resp.get("response", {}).get("missing_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "not_verifiable": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["missing"] += model_weight
            object_status_votes[obj_id]["details"].append(obj.get("details", ""))

        # Traiter les objets déplacés
        for obj in resp.get("response", {}).get("moved_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "not_verifiable": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["moved"] += model_weight
            object_status_votes[obj_id]["details"].append(obj.get("details", ""))

        # 🆕 Traiter les objets non vérifiables (zone non visible sur photos de sortie)
        for obj in resp.get("response", {}).get("not_verifiable_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "not_verifiable": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["not_verifiable"] += model_weight
            object_status_votes[obj_id]["details"].append(obj.get("details", ""))

        # Traiter les objets présents
        for obj in resp.get("response", {}).get("present_objects", []):
            obj_id = obj.get("object_id", "")
            if not obj_id:
                continue
            if obj_id not in object_status_votes:
                object_status_votes[obj_id] = {"missing": 0, "moved": 0, "present": 0, "not_verifiable": 0, "details": [], "name": obj.get("name", ""), "location": obj.get("location", "")}
            object_status_votes[obj_id]["present"] += model_weight

    # Déterminer le statut final par consensus
    missing_objects = []
    moved_objects = []
    present_objects = []
    not_verifiable_objects = []

    for obj_id, votes in object_status_votes.items():
        # Trouver le statut majoritaire (incluant not_verifiable)
        max_votes = max(votes["missing"], votes["moved"], votes["present"], votes["not_verifiable"])

        # Confidence basée sur le consensus
        total_votes = votes["missing"] + votes["moved"] + votes["present"] + votes["not_verifiable"]
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

        # Seuil de consensus: au moins 2 votes pondérés (CONSENSUS_THRESHOLD)
        # 🆕 Priorité: not_verifiable > missing > moved > present
        # Si la zone n'est pas vérifiable, c'est prioritaire sur "missing"
        if votes["not_verifiable"] >= CONSENSUS_THRESHOLD and votes["not_verifiable"] == max_votes:
            result.status = "not_verifiable"
            if confidence >= 70:
                not_verifiable_objects.append(result)
                logger.debug(f"   📸 NON VÉRIFIABLE: {votes['name']} (votes: {votes['not_verifiable']:.1f}, conf: {confidence}%) - zone non couverte")
        elif votes["missing"] >= CONSENSUS_THRESHOLD and votes["missing"] == max_votes:
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

    logger.debug(f"✅ [AGGREGATE] Résultat: {len(missing_objects)} manquants, {len(moved_objects)} déplacés, {len(not_verifiable_objects)} non vérifiables, {len(present_objects)} présents")

    return InventoryVerificationResponse(
        piece_id=piece_id,
        total_checked=len(object_status_votes),
        missing_objects=missing_objects,
        moved_objects=moved_objects,
        present_objects=present_objects,
        not_verifiable_objects=not_verifiable_objects
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
            present_objects=[],
            not_verifiable_objects=[]
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
            present_objects=[],
            not_verifiable_objects=[]
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
            present_objects=[],
            not_verifiable_objects=[]
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
        not_verifiable = []

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

        # 🆕 Parser les objets non vérifiables (zone non visible sur photos de sortie)
        for obj in response_json.get("not_verifiable_objects", []):
            if obj.get("confidence", 0) >= 85:
                not_verifiable.append(ObjectVerificationResult(
                    object_id=obj.get("object_id", ""),
                    name=obj.get("name", ""),
                    location=obj.get("location", ""),
                    status="not_verifiable",
                    confidence=obj.get("confidence", 90),
                    details=obj.get("details", "Zone non couverte par les photos de sortie")
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

        logger.debug(f"✅ PHASE 2 terminée (FALLBACK OpenAI): {len(missing)} manquants, {len(moved)} déplacés, {len(not_verifiable)} non vérifiables")

        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=inventory.total_objects,
            missing_objects=missing,
            moved_objects=moved,
            present_objects=present,
            not_verifiable_objects=not_verifiable
        )

    except Exception as e:
        logger.error(f"❌ Erreur fallback OpenAI: {e}")
        return InventoryVerificationResponse(
            piece_id=piece_id,
            total_checked=0,
            missing_objects=[],
            moved_objects=[],
            present_objects=[],
            not_verifiable_objects=[]
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

    # 🆕 Objets non vérifiables → image_quality (problème de cadrage photo)
    for obj in verification.not_verifiable_objects:
        issues.append(Probleme(
            description=f"Zone non contrôlable: {obj.name} ({obj.location}) visible sur photo d'entrée mais zone non couverte par les photos de sortie. {obj.details}",
            category="image_quality",
            severity="medium",
            confidence=obj.confidence
        ))

    logger.debug(f"🔄 Conversion: {len(issues)} issues générées depuis l'inventaire (dont {len(verification.not_verifiable_objects)} zones non contrôlables)")
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
@limiter.limit("20/minute")
async def analyze_room(request: Request, input_data: InputData):
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

    # 📥 LOG DÉTAILLÉ DE LA REQUÊTE REÇUE
    log_request_received("/analyze", {
        "piece_id": input_data.piece_id,
        "nom": input_data.nom,
        "type": input_data.type,
        "checkin_pictures": [{"url": p.url} for p in input_data.checkin_pictures],
        "checkout_pictures": [{"url": p.url} for p in input_data.checkout_pictures],
        "elements_critiques": input_data.elements_critiques,
        "points_ignorables": input_data.points_ignorables,
        "defauts_frequents": input_data.defauts_frequents,
        "commentaire_ia": input_data.commentaire_ia
    }, request_id)

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

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: analyze_images(input_data, parcours_type, request_id=request_id)
        )

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

@app.post("/classify-room", response_model=RoomClassificationResponse)
@limiter.limit("20/minute")
async def classify_room(request: Request, input_data: RoomClassificationInput):
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

    # 📥 LOG DÉTAILLÉ DE LA REQUÊTE REÇUE
    log_request_received("/classify-room", {
        "piece_id": input_data.piece_id,
        "nom": input_data.nom,
        "type": input_data.type,
        "checkin_pictures": [{"url": p.url} for p in input_data.checkin_pictures]
    }, request_id)

    logs_manager.start_request(
        request_id=request_id,
        endpoint="/classify-room",
        data={"piece_id": input_data.piece_id}
    )

    logger.info(f"Classification démarrée pour la pièce {input_data.piece_id}")

    try:
        # Récupérer le type de parcours depuis input_data
        parcours_type = input_data.type if hasattr(input_data, 'type') else "Voyageur"
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: classify_room_type(input_data, parcours_type, request_id=request_id)
        )
        logger.info(f"Classification terminée pour la pièce {input_data.piece_id}: {result.room_type} (confiance: {result.confidence}%)")

        # 📤 LOG DÉTAILLÉ DE LA RÉPONSE
        log_response_sent("/classify-room", {
            "piece_id": result.piece_id,
            "room_type": result.room_type,
            "confidence": result.confidence,
            "is_valid_room": result.is_valid_room
        }, success=True)

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

@app.post("/analyze-with-classification", response_model=CombinedAnalysisResponse)
@limiter.limit("20/minute")
async def analyze_with_classification(request: Request, input_data: InputData):
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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: analyze_with_auto_classification(input_data, parcours_type)
        )
        logger.debug(f"🎯 Analyse combinée terminée pour la pièce {input_data.piece_id}")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-with-classification: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# analyze_etapes has been moved to services/etapes.py


@app.post("/analyze-etapes", response_model=EtapesAnalysisResponse)
@limiter.limit("15/minute")
async def analyze_etapes_endpoint(request: Request, input_data: EtapesAnalysisInput):
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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: analyze_etapes(input_data))
        total_issues = len(result.preliminary_issues)
        logger.debug(f"🎯 Analyse des étapes terminée pour le logement {input_data.logement_id}: {total_issues} problèmes détectés")
        return result
    except Exception as e:
        logger.error(f"❌ Erreur dans l'endpoint analyze-etapes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze-complete")
@limiter.limit("10/minute")
async def analyze_complete_endpoint(request: Request, input_data: EtapesAnalysisInput):
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

    # 📥 LOG DÉTAILLÉ DE LA REQUÊTE REÇUE
    log_request_received("/analyze-complete", {
        "logement_id": input_data.logement_id,
        "logement_name": input_data.logement_name,
        "logement_adresse": input_data.logement_adresse,
        "rapport_id": input_data.rapport_id,
        "type": input_data.type,
        "pieces": [
            {
                "piece_id": p.piece_id,
                "nom": p.nom,
                "checkin_pictures": [{"url": pic.url} for pic in p.checkin_pictures],
                "checkout_pictures": [{"url": pic.url} for pic in p.checkout_pictures],
                "etapes": [{"etape_id": e.etape_id, "consigne": e.consigne} for e in p.etapes] if p.etapes else []
            }
            for p in input_data.pieces
        ]
    }, request_id)

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

        # Utilisation de la version PARALLÉLISÉE standard
        logs_manager.add_log(
            request_id=request_id,
            level="INFO",
            message=f"⚡ Utilisation de la version PARALLÉLISÉE"
        )
        logger.debug(f"⚡ Utilisation de la version PARALLÉLISÉE")
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

            # 🔍 LOG DÉTAILLÉ: Configuration webhook
            webhook_target = os.environ.get("WEBHOOK_TARGET", "bubble").lower()
            logger.warning(f"{'='*60}")
            logger.warning(f"🔗 CONFIGURATION WEBHOOKS")
            logger.warning(f"{'='*60}")
            logger.warning(f"   📌 WEBHOOK_TARGET = '{webhook_target}'")
            logger.warning(f"   📌 Environment = '{environment}'")

            webhook_url_current = get_webhook_url(environment)
            webhook_url_individual = get_webhook_url_individual_report(environment)

            logger.warning(f"   📤 URL Webhook 1 (actuel): {webhook_url_current}")
            logger.warning(f"   📤 URL Webhook 2 (individual): {webhook_url_individual}")
            logger.warning(f"{'='*60}")

            # Préparer le payload pour le webhook actuel (format CompleteAnalysisResponse)
            webhook_payload_current = result.model_dump()

            # Log des payloads (résumé)
            logger.info(f"📦 Payload webhook actuel: logement_id={result.logement_id}, pieces={len(result.pieces_analysis)}, issues={result.total_issues_count}")
            logger.info(f"📦 Payload individual-report: rapport_id={webhook_payload_individual.get('rapport_id', 'N/A')}")

            # Envoyer les deux webhooks EN PARALLÈLE pour optimiser les performances
            logger.warning(f"🚀 ENVOI DES WEBHOOKS pour logement {input_data.logement_id}...")

            # Utiliser asyncio.gather pour envoyer les deux webhooks simultanément
            webhook_results = await asyncio.gather(
                send_webhook(webhook_payload_current, webhook_url_current),
                send_webhook(webhook_payload_individual, webhook_url_individual),
                return_exceptions=True  # Ne pas faire échouer si un webhook échoue
            )

            # Analyser les résultats
            webhook_current_success = webhook_results[0] if not isinstance(webhook_results[0], Exception) else False
            webhook_individual_success = webhook_results[1] if not isinstance(webhook_results[1], Exception) else False

            # 📊 RÉSULTATS DES WEBHOOKS (niveau WARNING pour visibilité)
            logger.warning(f"{'='*60}")
            logger.warning(f"📊 RÉSULTATS WEBHOOKS")
            logger.warning(f"{'='*60}")

            if webhook_current_success:
                logger.warning(f"   ✅ Webhook 1 (actuel): SUCCÈS → {webhook_url_current}")
            else:
                logger.error(f"   ❌ Webhook 1 (actuel): ÉCHEC → {webhook_url_current}")
                if isinstance(webhook_results[0], Exception):
                    logger.error(f"      Erreur: {webhook_results[0]}")

            if webhook_individual_success:
                logger.warning(f"   ✅ Webhook 2 (individual): SUCCÈS → {webhook_url_individual}")
            else:
                logger.error(f"   ❌ Webhook 2 (individual): ÉCHEC → {webhook_url_individual}")
                if isinstance(webhook_results[1], Exception):
                    logger.error(f"      Erreur: {webhook_results[1]}")

            # Résumé
            success_count = sum([webhook_current_success, webhook_individual_success])
            logger.warning(f"{'='*60}")
            logger.warning(f"📊 BILAN: {success_count}/2 webhooks envoyés avec succès")
            logger.warning(f"{'='*60}")

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

        # 📤 LOG DÉTAILLÉ DE LA RÉPONSE ENVOYÉE
        log_response_sent("/analyze-complete", {
            "logement_id": result.logement_id,
            "pieces_results": [
                {
                    "piece_id": p.piece_id,
                    "nom_piece": p.nom_piece,
                    "room_type": p.room_classification.room_type if p.room_classification else "N/A",
                    "issues_count": len(p.issues)
                }
                for p in result.pieces_analysis
            ],
            "total_issues_count": result.total_issues_count,
            "general_issues_count": result.general_issues_count,
            "etapes_issues_count": result.etapes_issues_count,
            "analyse_globale": {
                "score": result.analysis_enrichment.global_score.score if result.analysis_enrichment else None,
                "label": result.analysis_enrichment.global_score.label if result.analysis_enrichment else None
            }
        }, success=True)

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

# Dashboard - Page d'accueil visuelle
@app.get("/")
async def serve_dashboard():
    """Servir le dashboard visuel avec liens vers tous les outils"""
    return FileResponse("templates/dashboard.html")

@app.get("/health")
async def health():
    """Endpoint de santé pour Railway healthcheck et monitoring"""
    return {"status": "ok", "message": "CheckEasy API V5 is running", "version": "5.0"}

# ═══════════════════════════════════════════════════════════════
# RAPPORT TESTER - Browse & re-analyze real rapports
# ═══════════════════════════════════════════════════════════════

@app.get("/rapport-tester")
async def serve_rapport_tester():
    """Servir l'interface Rapport Tester"""
    return FileResponse("templates/rapport_tester.html")

@app.get("/api/rapports")
async def api_list_rapports():
    """List last 50 rapports with basic info (READ-ONLY)."""
    try:
        sb = get_supabase()
        # Fetch rapports
        res = sb.table("rapports").select(
            "id, check_id, status, logement_id, created_at, completed_at, flow_type, user_info"
        ).order("created_at", desc=True).limit(50).execute()

        rapports = res.data or []

        # Fetch analyse score for each rapport
        check_ids = [r.get("check_id") for r in rapports if r.get("check_id")]
        analyses_map = {}
        if check_ids:
            ana_res = sb.table("rapports_analyse").select(
                "rapport_id, score_global, score_label"
            ).in_("rapport_id", check_ids).execute()
            for a in (ana_res.data or []):
                a["status"] = "completed" if a.get("score_global") is not None else "pending"
                analyses_map[a["rapport_id"]] = a

        # Fetch logement names
        logement_ids = list(set(r.get("logement_id") for r in rapports if r.get("logement_id")))
        logements_map = {}
        if logement_ids:
            log_res = sb.table("logements").select("id, name").in_("id", logement_ids).execute()
            for l in (log_res.data or []):
                logements_map[l["id"]] = l.get("name", "")

        result = []
        for r in rapports:
            check_id = r.get("check_id") or str(r.get("id", ""))
            ana = analyses_map.get(check_id, {})
            user_info = r.get("user_info") or {}
            result.append({
                "id": r.get("id"),
                "check_id": check_id,
                "status": r.get("status"),
                "analyse_status": ana.get("status"),
                "score_global": ana.get("score_global"),
                "logement_name": logements_map.get(r.get("logement_id"), ""),
                "created_at": r.get("created_at"),
                "flow_type": r.get("flow_type"),
                "operator_name": f"{user_info.get('firstName', '')} {user_info.get('lastName', '')}".strip() or None
            })
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching rapports: {e}")
        raise HTTPException(500, f"Error fetching rapports: {str(e)}")

@app.get("/api/rapports/{check_id}")
async def api_get_rapport(check_id: str):
    """Get full rapport detail with pieces, photos, and analysis (READ-ONLY)."""
    try:
        sb = get_supabase()

        # Fetch rapport by check_id
        res = sb.table("rapports").select("*").eq("check_id", check_id).execute()
        if not res.data:
            # Fallback: try by id
            res = sb.table("rapports").select("*").eq("id", check_id).execute()
        if not res.data:
            raise HTTPException(404, f"Rapport {check_id} not found")
        rapport = res.data[0]

        # Fetch analysis
        ana_res = sb.table("rapports_analyse").select("*").eq("rapport_id", check_id).execute()
        analyse = ana_res.data[0] if ana_res.data else None

        # Fetch logement
        logement_name = ""
        if rapport.get("logement_id"):
            log_res = sb.table("logements").select("id, name, address").eq("id", rapport["logement_id"]).execute()
            if log_res.data:
                logement_name = log_res.data[0].get("name", "")

        # Extract pieces and photos
        checkin_data = rapport.get("checkin_data") or {}
        checkout_data = rapport.get("checkout_data") or {}
        user_info = rapport.get("user_info") or {}

        # Detect unified format
        checkout_has_content = any(
            p.get("etapes") and len(p["etapes"]) > 0
            for p in (checkout_data.get("pieces") or [])
        )
        is_unified = not checkout_has_content and bool(checkin_data.get("pieces"))

        checkin_pieces = checkin_data.get("pieces") or []
        checkout_pieces = checkout_data.get("pieces") or []

        # Merge piece IDs
        all_piece_ids = {}
        for p in checkin_pieces:
            pid = p.get("piece_id") or p.get("id")
            if pid:
                all_piece_ids[pid] = p.get("nom") or all_piece_ids.get(pid, f"Piece {str(pid)[:8]}")
        for p in checkout_pieces:
            pid = p.get("piece_id") or p.get("id")
            if pid:
                all_piece_ids[pid] = p.get("nom") or all_piece_ids.get(pid, f"Piece {str(pid)[:8]}")

        # Parse analysis results per piece
        analysis_by_piece = {}
        if analyse and analyse.get("raw_response"):
            raw = analyse["raw_response"]
            # Handle both direct format and nested
            pieces_analysis = None
            if isinstance(raw, dict):
                pieces_analysis = raw.get("pieces_analysis") or raw.get("detailParPieceSection")
            if pieces_analysis and isinstance(pieces_analysis, list):
                for pa in pieces_analysis:
                    pid = pa.get("piece_id") or pa.get("pieceId")
                    if pid:
                        ag = pa.get("analyse_globale") or {}
                        analysis_by_piece[pid] = {
                            "score": ag.get("score"),
                            "label": ag.get("label") or _score_to_label(ag.get("score")),
                            "status": ag.get("status"),
                            "commentaire_global": ag.get("commentaire_global") or ag.get("comment"),
                            "problemes": pa.get("preliminary_issues") or pa.get("issues") or pa.get("problemes") or []
                        }

        # Fetch parcours etapes for reference photos
        parcours_etapes_map = {}
        if rapport.get("logement_id"):
            parcours_etapes_map = _fetch_parcours_etapes_map(
                sb, rapport["logement_id"], rapport.get("parcours_index") or 0
            )

        # Build pieces with photos
        progress = rapport.get("progress") or {}
        pieces_result = []
        for pid, nom in all_piece_ids.items():
            checkin_photos = _extract_photos_for_piece(checkin_data, pid, "checkin", progress)
            if is_unified:
                checkout_photos = _extract_photos_for_piece(checkin_data, pid, "checkout", progress)
            else:
                checkout_photos = _extract_photos_for_piece(checkout_data, pid, "checkout", progress)

            # Reference photos from DB (non-todo etapes with reference_image_url)
            ref_photos_from_db = []
            if parcours_etapes_map.get(pid):
                for e in parcours_etapes_map[pid]:
                    if not e.get("is_todo") and e.get("reference_image_url"):
                        ref_url = e["reference_image_url"]
                        if ref_url.startswith("//"):
                            ref_url = "https:" + ref_url
                        if ref_url.startswith("http"):
                            ref_photos_from_db.append(ref_url)

            # Use DB reference photos as fallback
            final_checkin_photos = checkin_photos if checkin_photos else ref_photos_from_db

            # Extract task etapes
            etapes = _extract_etapes_for_piece(checkin_data, checkout_data, pid, is_unified)

            pieces_result.append({
                "piece_id": pid,
                "nom": nom,
                "checkin_pictures": final_checkin_photos,
                "checkout_pictures": checkout_photos,
                "etapes": etapes,
                "analysis": analysis_by_piece.get(pid)
            })

        return {
            "check_id": check_id,
            "id": rapport.get("id"),
            "logement_name": logement_name,
            "type": (rapport.get("parcours_info") or {}).get("type") or "Voyageur",
            "status": rapport.get("status"),
            "analyse_status": ("completed" if analyse and analyse.get("score_global") is not None else "pending") if analyse else None,
            "score_global": analyse.get("score_global") if analyse else None,
            "created_at": rapport.get("created_at"),
            "operator_name": f"{user_info.get('firstName', '')} {user_info.get('lastName', '')}".strip() or None,
            "pieces": pieces_result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching rapport detail: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Error fetching rapport detail: {str(e)}")

@app.post("/api/rapports/reanalyze-piece")
async def api_reanalyze_piece(request: Request):
    """Re-analyze a single piece using current prompts. IN-MEMORY ONLY, no DB writes."""
    try:
        body = await request.json()
        check_id = body.get("check_id")
        piece_id = body.get("piece_id")
        if not check_id or not piece_id:
            raise HTTPException(400, "check_id and piece_id are required")

        sb = get_supabase()

        # 1. Fetch rapport (READ-ONLY)
        res = sb.table("rapports").select("*").eq("check_id", check_id).execute()
        if not res.data:
            raise HTTPException(404, f"Rapport {check_id} not found")
        rapport = res.data[0]

        # 2. Fetch logement (READ-ONLY)
        logement = {"id": rapport.get("logement_id"), "name": "", "address": "", "fields": {}}
        if rapport.get("logement_id"):
            log_res = sb.table("logements").select("*").eq("id", rapport["logement_id"]).execute()
            if log_res.data:
                logement = log_res.data[0]

        # 3. Fetch parcours etapes map (reference photos from DB)
        parcours_etapes_map = _fetch_parcours_etapes_map(
            sb, rapport.get("logement_id"), rapport.get("parcours_index") or 0
        )

        # 4. Build the payload (Python port of buildAnalysePayload)
        payload = _build_analyse_payload(rapport, logement, parcours_etapes_map)

        # 5. Filter to keep ONLY the requested piece
        target_pieces = [p for p in payload.get("pieces", []) if p.get("piece_id") == piece_id]
        if not target_pieces:
            raise HTTPException(404, f"Piece {piece_id} not found in payload (may have no photos)")

        payload["pieces"] = target_pieces
        tp = target_pieces[0]
        logger.info(f"Re-analyze piece '{tp.get('nom')}': {len(tp.get('checkin_pictures', []))} checkin, {len(tp.get('checkout_pictures', []))} checkout, {len(tp.get('etapes', []))} etapes")

        # 6. Call the internal analyze-complete logic
        input_data = EtapesAnalysisInput(**payload)
        new_result = await analyze_complete_logement_parallel(input_data)

        # 7. Extract old result from rapports_analyse
        old_result = None
        ana_res = sb.table("rapports_analyse").select("raw_response").eq("rapport_id", check_id).execute()
        if ana_res.data and ana_res.data[0].get("raw_response"):
            raw = ana_res.data[0]["raw_response"]
            pieces_analysis = None
            if isinstance(raw, dict):
                pieces_analysis = raw.get("pieces_analysis") or raw.get("detailParPieceSection")
            if pieces_analysis:
                for pa in pieces_analysis:
                    if (pa.get("piece_id") or pa.get("pieceId")) == piece_id:
                        ag = pa.get("analyse_globale") or {}
                        old_result = {
                            "score": ag.get("score"),
                            "label": ag.get("label") or _score_to_label(ag.get("score")),
                            "status": ag.get("status"),
                            "commentaire_global": ag.get("commentaire_global"),
                            "problemes": pa.get("preliminary_issues") or pa.get("issues") or []
                        }
                        break

        # 8. Extract new result for the piece
        new_piece_result = None
        if new_result and hasattr(new_result, "pieces_analysis") and new_result.pieces_analysis:
            for pa in new_result.pieces_analysis:
                pa_dict = pa.model_dump() if hasattr(pa, "model_dump") else (pa.dict() if hasattr(pa, "dict") else pa)
                if pa_dict.get("piece_id") == piece_id:
                    ag = pa_dict.get("analyse_globale") or {}
                    if hasattr(ag, "model_dump"):
                        ag = ag.model_dump()
                    elif hasattr(ag, "dict"):
                        ag = ag.dict()
                    issues_raw = pa_dict.get("issues") or []
                    new_piece_result = {
                        "score": ag.get("score"),
                        "label": ag.get("label") or _score_to_label(ag.get("score")),
                        "status": ag.get("status"),
                        "commentaire_global": ag.get("commentaire_global"),
                        "problemes": [
                            i.model_dump() if hasattr(i, "model_dump") else (i.dict() if hasattr(i, "dict") else i)
                            for i in issues_raw
                        ]
                    }
                    break

        return {
            "check_id": check_id,
            "piece_id": piece_id,
            "old_result": old_result,
            "new_result": new_piece_result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error re-analyzing piece: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Error re-analyzing piece: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# RAPPORT TESTER - Helper functions (Python port of trigger-analyse logic)
# ═══════════════════════════════════════════════════════════════

def _score_to_label(score):
    """Convert score to label (same as rapport.types.ts scoreToLabel)"""
    if score is None:
        return "N/A"
    if score >= 4.5:
        return "EXCELLENT"
    if score >= 3.5:
        return "BON"
    if score >= 2.5:
        return "MOYEN"
    if score >= 1.5:
        return "MAUVAIS"
    return "INSUFFISANT"

def _extract_photos_for_piece(flow_data, piece_id, flow_type, progress=None):
    """Python port of extractPhotosForPiece from trigger-analyse/index.ts.
    Extracts photo URLs for a piece, handling all 5 formats."""
    photos = []
    if not flow_data:
        return photos

    # Helper to match piece id
    def matches_piece(p):
        pid = p.get("id") or p.get("piece_id") or p.get("pieceId")
        return pid == piece_id

    # Format 1: flow_data.photos[pieceId]
    if isinstance(flow_data.get("photos"), dict):
        piece_photos = flow_data["photos"].get(piece_id)
        if piece_photos:
            if isinstance(piece_photos, list):
                photos.extend(piece_photos)
            elif isinstance(piece_photos, str):
                photos.append(piece_photos)

    # Format 2: flow_data.pieces[].photos or .images
    pieces = flow_data.get("pieces")
    if isinstance(pieces, list):
        piece = next((p for p in pieces if matches_piece(p)), None)
        if piece:
            for key in ("photos", "images"):
                val = piece.get(key)
                if val:
                    if isinstance(val, list):
                        photos.extend(val)
                    elif isinstance(val, str):
                        photos.append(val)

    # Format 3: progress.interactions.photosTaken
    if progress and isinstance(progress.get("interactions", {}).get("photosTaken"), dict):
        photos_taken = progress["interactions"]["photosTaken"]
        for key, value in photos_taken.items():
            if key.startswith(piece_id) or piece_id in key:
                if isinstance(value, str):
                    photos.append(value)
                elif isinstance(value, dict) and value.get("url"):
                    photos.append(value["url"])

    # Format 4: Array format with piece_id
    if isinstance(flow_data.get("photos"), list):
        for p in flow_data["photos"]:
            if isinstance(p, dict) and (p.get("piece_id") == piece_id or p.get("pieceId") == piece_id):
                if p.get("url"):
                    photos.append(p["url"])
                if p.get("photo_url"):
                    photos.append(p["photo_url"])

    # Format 5: Webhook checkapp-supabase unified format (etapes array)
    if isinstance(pieces, list):
        piece = next((p for p in pieces if matches_piece(p)), None)
        if piece and isinstance(piece.get("etapes"), list):
            # Build todo etape_ids set to exclude from general photos
            todo_ids = set()
            for etape in piece["etapes"]:
                if etape.get("is_todo") is True and etape.get("etape_id"):
                    todo_ids.add(etape["etape_id"])

            for etape in piece["etapes"]:
                etape_type = etape.get("etape_type") or etape.get("flowType") or "unified"
                should_include = (
                    etape_type == "unified" or
                    etape_type == flow_type or
                    (flow_type == "checkout" and etape_type != "checkin")
                )
                if not should_include:
                    continue

                # Exclude todo task photos
                if etape.get("etape_id") and etape["etape_id"] in todo_ids:
                    continue

                # photo_taken events
                if etape.get("type") == "photo_taken" and etape.get("photo_url"):
                    photos.append(etape["photo_url"])

                # photos_attached
                if isinstance(etape.get("photos_attached"), list):
                    for photo in etape["photos_attached"]:
                        if isinstance(photo, str):
                            photos.append(photo)
                        elif isinstance(photo, dict):
                            photos.append(photo.get("url") or photo.get("photo_url") or "")

    # Deduplicate and filter: only valid HTTP URLs
    seen = set()
    result = []
    for url in photos:
        if not url or not isinstance(url, str):
            continue
        if url.startswith("data:"):
            continue
        if not url.startswith("http") and len(url) > 100:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)

    return result

def _extract_etapes_for_piece(checkin_data, checkout_data, piece_id, is_unified):
    """Extract task etapes (photo-required) for a piece from raw rapport data."""
    etapes = []
    seen_ids = set()

    # Combine etapes from both checkin and checkout pieces
    all_pieces_data = []
    for p in (checkin_data.get("pieces") or []):
        pid = p.get("piece_id") or p.get("id")
        if pid == piece_id and isinstance(p.get("etapes"), list):
            all_pieces_data.extend(p["etapes"])
    if not is_unified:
        for p in (checkout_data.get("pieces") or []):
            pid = p.get("piece_id") or p.get("id")
            if pid == piece_id and isinstance(p.get("etapes"), list):
                all_pieces_data.extend(p["etapes"])

    # Find button_click events that represent tasks
    for etape in all_pieces_data:
        etype = etape.get("type", "")
        is_todo = etape.get("is_todo")
        eid = etape.get("etape_id")

        if etype == "button_click" and is_todo is True and eid and eid not in seen_ids:
            etape_data = etape.get("etapeData") or {}
            # Only include photoRequired tasks (simple checkbox tasks don't need AI analysis)
            todo_param = etape_data.get("todo_param") or etape.get("todo_param")
            if todo_param and todo_param != "photoRequired":
                continue

            seen_ids.add(eid)
            # Find photo for this task
            task_photo = ""
            for e2 in all_pieces_data:
                if e2.get("type") == "photo_taken" and e2.get("etape_id") == eid and e2.get("photo_url"):
                    task_photo = e2["photo_url"]
                    break

            ref_photo = etape_data.get("reference_image_url") or etape_data.get("todoImage") or ""
            if ref_photo.startswith("//"):
                ref_photo = "https:" + ref_photo

            etapes.append({
                "etape_id": eid,
                "task_name": etape_data.get("todo_title") or etape_data.get("name") or "Tache",
                "consigne": etape_data.get("todo_order") or "",
                "checking_picture": ref_photo,
                "checkout_picture": task_photo
            })

    return etapes

def _find_task_photo(flow_data, piece_id, task_id):
    """Find a photo for a specific task (Python port of findTaskPhoto)."""
    if not flow_data:
        return ""
    # Check flowData.pieces[].etapes[]
    for p in (flow_data.get("pieces") or []):
        pid = p.get("piece_id") or p.get("id")
        if pid != piece_id:
            continue
        for etape in (p.get("etapes") or []):
            if etape.get("type") == "photo_taken" and etape.get("photo_url") and etape.get("etape_id") == task_id:
                return etape["photo_url"]
    return ""

def _map_severity(severity):
    """Map severity string to expected format."""
    s = (severity or "").lower()
    if s in ("high", "haute", "critical"):
        return "haute"
    if s in ("low", "basse", "minor"):
        return "basse"
    return "moyenne"

def _format_date(iso_date):
    """Format ISO date to DD/MM/YY."""
    if not iso_date:
        return ""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%y")
    except Exception:
        return ""

def _fetch_parcours_etapes_map(sb, logement_id, parcours_index=0):
    """Fetch etapes from DB grouped by piece_id. Same as trigger-analyse step 2b."""
    parcours_etapes_map = {}
    try:
        # Find parcours via logement_parcours
        lp_res = sb.table("logement_parcours").select("parcours_id").eq("logement_id", logement_id).order("created_at").execute()
        lp_data = lp_res.data or []

        if lp_data and len(lp_data) > parcours_index:
            parcours_id = lp_data[parcours_index]["parcours_id"]
            # Get pieces for this parcours
            pieces_res = sb.table("pieces").select("id, nom").eq("parcours_id", parcours_id).execute()
            pieces_data = pieces_res.data or []

            if pieces_data:
                piece_ids = [p["id"] for p in pieces_data]
                # Get etapes for all pieces
                etapes_res = sb.table("etapes").select(
                    "id, piece_id, is_todo, todo_title, reference_image_url, todo_order, todo_param"
                ).in_("piece_id", piece_ids).execute()

                for etape in (etapes_res.data or []):
                    pid = etape["piece_id"]
                    if pid not in parcours_etapes_map:
                        parcours_etapes_map[pid] = []
                    parcours_etapes_map[pid].append(etape)

            logger.info(f"Parcours etapes loaded: {len(parcours_etapes_map)} pieces")
    except Exception as e:
        logger.warning(f"Could not load parcours etapes: {e}")

    return parcours_etapes_map

def _build_analyse_payload(rapport, logement, parcours_etapes_map=None):
    """Python port of buildAnalysePayload from trigger-analyse/index.ts.
    Reconstructs the exact same payload format sent to /analyze-complete."""
    if parcours_etapes_map is None:
        parcours_etapes_map = {}

    checkin_data = rapport.get("checkin_data") or {}
    checkout_data = rapport.get("checkout_data") or {}
    user_info = rapport.get("user_info") or {}
    parcours_info = rapport.get("parcours_info") or {}
    progress = rapport.get("progress") or {}

    # Get parcours from logement
    fields = logement.get("fields") or {}
    parcours_list = fields.get("parcours") or []
    parcours_index = rapport.get("parcours_index") or 0
    current_parcours = {}
    if parcours_list and len(parcours_list) > parcours_index:
        current_parcours = parcours_list[parcours_index]
    elif parcours_list:
        current_parcours = parcours_list[0]

    # Merge pieces from checkin and checkout
    checkin_pieces = checkin_data.get("pieces") or []
    checkout_pieces = checkout_data.get("pieces") or []

    all_piece_ids = {}  # {id: nom}
    for p in checkin_pieces:
        pid = p.get("piece_id") or p.get("id")
        if pid:
            all_piece_ids[pid] = p.get("nom") or f"Piece {str(pid)[:8]}"
    for p in checkout_pieces:
        pid = p.get("piece_id") or p.get("id")
        if pid:
            if pid not in all_piece_ids:
                all_piece_ids[pid] = p.get("nom") or f"Piece {str(pid)[:8]}"

    # Detect unified format
    checkout_has_content = any(
        p.get("etapes") and len(p["etapes"]) > 0
        for p in (checkout_data.get("pieces") or [])
    )
    is_unified = not checkout_has_content and bool(checkin_data.get("pieces"))

    # Build pieces
    pieces = []
    for pid, nom in all_piece_ids.items():
        checkin_photos = _extract_photos_for_piece(checkin_data, pid, "checkin", progress)
        if is_unified:
            checkout_photos = _extract_photos_for_piece(checkin_data, pid, "checkout", progress)
        else:
            checkout_photos = _extract_photos_for_piece(checkout_data, pid, "checkout", progress)

        # Reference photos from DB (non-todo etapes with reference_image_url)
        ref_photos_from_db = []
        if parcours_etapes_map.get(pid):
            for e in parcours_etapes_map[pid]:
                if not e.get("is_todo") and e.get("reference_image_url"):
                    ref_url = e["reference_image_url"]
                    if ref_url.startswith("//"):
                        ref_url = "https:" + ref_url
                    if ref_url.startswith("http"):
                        ref_photos_from_db.append(ref_url)

        # Use DB reference photos as fallback if no checkin photos from rapport
        final_checkin_photos = checkin_photos if checkin_photos else ref_photos_from_db

        # Extract task etapes (with DB fallback for photoRequired filtering)
        etapes = _extract_etapes_for_piece(checkin_data, checkout_data, pid, is_unified)

        # If no etapes from rapport data, try from DB (same as TS lines 637-670)
        if not etapes and parcours_etapes_map.get(pid):
            db_etapes = parcours_etapes_map[pid]
            # Build photo map from raw rapport etapes
            raw_etapes = []
            for p in checkin_pieces:
                if (p.get("piece_id") or p.get("id")) == pid and isinstance(p.get("etapes"), list):
                    raw_etapes.extend(p["etapes"])
            if not is_unified:
                for p in checkout_pieces:
                    if (p.get("piece_id") or p.get("id")) == pid and isinstance(p.get("etapes"), list):
                        raw_etapes.extend(p["etapes"])

            photo_by_etape_id = {}
            for re in raw_etapes:
                if re.get("photo_url") and re.get("etape_id"):
                    photo_by_etape_id[re["etape_id"]] = re["photo_url"]

            for e in db_etapes:
                if e.get("is_todo") and e.get("todo_param") == "photoRequired":
                    ref_url = e.get("reference_image_url") or ""
                    if ref_url.startswith("//"):
                        ref_url = "https:" + ref_url
                    etapes.append({
                        "etape_id": e["id"],
                        "task_name": e.get("todo_title") or "Tache",
                        "consigne": e.get("todo_order") or "",
                        "checking_picture": ref_url,
                        "checkout_picture": photo_by_etape_id.get(e["id"], ""),
                    })

        # Check if piece has any content
        has_checkout = len(checkout_photos) > 0
        has_checkin = len(final_checkin_photos) > 0
        has_task_photos = any(e.get("checkout_picture") for e in etapes)

        if not has_checkout and not has_checkin and not has_task_photos:
            continue  # Skip pieces with no photos

        pieces.append({
            "piece_id": pid,
            "nom": nom,
            "commentaire_ia": "",
            "checkin_pictures": [{"piece_id": pid, "url": url} for url in final_checkin_photos],
            "checkout_pictures": [{"piece_id": pid, "url": url} for url in checkout_photos],
            "etapes": etapes
        })

    # Signalements
    signalements = []
    for s in (rapport.get("signalements") or []):
        s_piece_id = s.get("piece_id") or s.get("pieceId") or s.get("roomId") or s.get("room_id")
        if not s_piece_id and s.get("roomName"):
            for pid, nom in all_piece_ids.items():
                if nom.lower().strip() == s["roomName"].lower().strip():
                    s_piece_id = pid
                    break
        signalements.append({
            "id": s.get("id", str(uuid.uuid4())),
            "piece_id": s_piece_id or "unknown",
            "titre": s.get("title") or s.get("titre") or s.get("description") or "Signalement",
            "description": s.get("description") or s.get("comment") or s.get("title") or s.get("titre") or "",
            "severite": _map_severity(s.get("severity") or s.get("severite") or s.get("status")),
            "photo": s.get("photo") or s.get("photo_url") or s.get("photoUrl") or "",
            "date_signalement": s.get("createdAt") or s.get("timestamp") or s.get("date_signalement") or datetime.utcnow().isoformat()
        })

    # Checklist finale
    checklist = []
    for q in (rapport.get("exit_questions") or []):
        checklist.append({
            "id": q.get("id") or q.get("question_id") or str(uuid.uuid4()),
            "text": q.get("text") or q.get("question") or q.get("question_text") or q.get("question_content") or q.get("intitule") or "Question",
            "completed": q.get("completed") or q.get("answer") is True or q.get("checked") or False,
            "icon": q.get("icon") or "V",
            "photo": q.get("photo") or q.get("image_url") or q.get("image_base64") or ""
        })

    # Detect type
    detected_type = (
        current_parcours.get("parcoursType") or
        parcours_info.get("type") or
        parcours_info.get("parcoursType") or
        ("menage" if user_info.get("type") == "AGENT" else None) or
        "voyageur"
    )
    is_menage = "menage" in detected_type.lower() or "ménage" in detected_type.lower()
    parcours_type = "Ménage" if is_menage else "Voyageur"

    return {
        "logement_id": logement.get("id") or "",
        "rapport_id": rapport.get("check_id") or str(rapport.get("id", "")),
        "type": parcours_type,
        "logementName": logement.get("name") or "",
        "adresseLogement": logement.get("address") or "",
        "operatorFirstName": user_info.get("firstName"),
        "operatorLastName": user_info.get("lastName"),
        "operatorPhone": user_info.get("phone"),
        "date_debut": _format_date(rapport.get("checkin_date") or rapport.get("created_at")),
        "date_fin": _format_date(rapport.get("checkout_date") or rapport.get("completed_at") or datetime.utcnow().isoformat()),
        "voyageur_nom": f"{user_info.get('firstName', '')} {user_info.get('lastName', '')}".strip() if user_info.get("type") == "CLIENT" else None,
        "voyageur_email": user_info.get("email"),
        "voyageur_telephone": user_info.get("phone"),
        "etat_lieux_moment": "arrivee-sortie" if rapport.get("flow_type") == "checkin" else "sortie",
        "pieces": pieces,
        "signalements_utilisateur": signalements if signalements else None,
        "checklist_finale": checklist if checklist else None
    }

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
                    "value": 75
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
                    "confidence_threshold": {"value": 75},
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
                "confidence_threshold": {"value": 75},
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

# map_room_type_to_valid -> moved to services/analysis.py

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
