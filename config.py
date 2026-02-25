"""
Configuration module for CheckEasy API.

Contains environment detection, webhook URLs, OpenAI client initialization,
room template loading, and multi-model consensus constants.
"""

import os
import json
import logging

# Load environment variables from .env BEFORE anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
except Exception:
    pass

from openai import OpenAI, AsyncOpenAI
from fastapi import HTTPException

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# OpenAI Client Initialization
# ═══════════════════════════════════════════════════════════════

# Configuration de la clé API - priorité aux variables d'environnement Railway
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

try:
    # Approche compatible Railway - pas d'arguments supplémentaires
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
    client = OpenAI()
    logger.info("SUCCESS: Client OpenAI initialisé avec succès")
except Exception as e:
    logger.error(f"Erreur critique lors de l'initialisation du client OpenAI: {e}")
    logger.error(f"Clé API disponible: {'Oui' if OPENAI_API_KEY else 'Non'}")
    try:
        # Fallback - essayer sans aucune configuration spéciale
        import openai
        openai.api_key = OPENAI_API_KEY
        client = openai.OpenAI()
        logger.info("SUCCESS: Client OpenAI initialisé avec fallback")
    except Exception as e2:
        logger.error(f"Erreur aussi avec fallback: {e2}")

# Initialiser le client Async pour la parallélisation
try:
    async_client = AsyncOpenAI()
    logger.info("SUCCESS: Client AsyncOpenAI initialisé avec succès")
except Exception as e:
    logger.warning(f"Impossible d'initialiser AsyncOpenAI: {e}")
    async_client = None
    client = None

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION MODÈLE OPENAI (depuis variable d'environnement Railway)
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


# ═══════════════════════════════════════════════════════════════
# Environment Detection
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


# ═══════════════════════════════════════════════════════════════
# Webhook URLs
# ═══════════════════════════════════════════════════════════════

def get_webhook_url(environment: str) -> str:
    """
    Retourne l'URL du webhook selon l'environnement et la cible (Bubble ou Supabase)

    Variable d'environnement WEBHOOK_TARGET:
    - "bubble" (défaut) : Envoie vers Bubble
    - "supabase" : Envoie vers Supabase

    Args:
        environment: "staging" ou "production"

    Returns:
        str: URL du webhook (Bubble ou Supabase selon WEBHOOK_TARGET)
    """
    target = os.environ.get("WEBHOOK_TARGET", "bubble").lower()

    if target == "supabase":
        # 🆕 Supabase webhooks
        logger.info(f"🔗 WEBHOOK_TARGET=supabase - Envoi vers Supabase ({environment})")
        if environment == "production":
            return os.environ.get("SUPABASE_WEBHOOK_URL_PROD", "https://votre-projet.supabase.co/functions/v1/webhook-analyse")
        else:
            return os.environ.get("SUPABASE_WEBHOOK_URL_STAGING", "https://votre-projet.supabase.co/functions/v1/webhook-analyse-test")
    else:
        # Bubble webhooks (défaut)
        logger.debug(f"🔗 WEBHOOK_TARGET=bubble - Envoi vers Bubble ({environment})")
        if environment == "production":
            return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia"
        else:  # staging par défaut
            return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia"


def get_webhook_url_individual_report(environment: str) -> str:
    """
    Retourne l'URL du webhook individual-report selon l'environnement et la cible

    Variable d'environnement WEBHOOK_TARGET:
    - "bubble" (défaut) : Envoie vers Bubble
    - "supabase" : Envoie vers Supabase

    Ce webhook reçoit le payload au format individual-report-data-model.json
    pour la page de rapport détaillé.

    Args:
        environment: "staging" ou "production"

    Returns:
        str: URL du webhook (Bubble ou Supabase selon WEBHOOK_TARGET)
    """
    target = os.environ.get("WEBHOOK_TARGET", "bubble").lower()

    if target == "supabase":
        # 🆕 Supabase webhooks
        logger.info(f"🔗 WEBHOOK_TARGET=supabase (individual-report) - Envoi vers Supabase ({environment})")
        if environment == "production":
            return os.environ.get("SUPABASE_INDIVIDUAL_WEBHOOK_URL_PROD", "https://votre-projet.supabase.co/functions/v1/individual-report-webhook")
        else:
            return os.environ.get("SUPABASE_INDIVIDUAL_WEBHOOK_URL_STAGING", "https://votre-projet.supabase.co/functions/v1/individual-report-webhook-test")
    else:
        # Bubble webhooks (défaut)
        logger.debug(f"🔗 WEBHOOK_TARGET=bubble (individual-report) - Envoi vers Bubble ({environment})")
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


# ═══════════════════════════════════════════════════════════════
# Room Templates
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTÈME MULTI-MODÈLES OPENROUTER - CONSENSUS VOTING (5 modèles)
# ═══════════════════════════════════════════════════════════════════════════════

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
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
