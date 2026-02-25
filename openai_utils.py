"""
OpenAI utility functions extracted from make_request.py

Contains:
- Message format conversion (Chat Completions <-> Responses API)
- Token usage extraction
- URL to Data URI conversion (sync, async, parallel)
- Dynamic prompt building from config
- Template variable replacement
"""

import logging
import json
import os
import re
import asyncio
import threading
from typing import Optional

from models import InputData
from image_converter import (
    ImageConverter,
    create_placeholder_image_url,
)

logger = logging.getLogger("make_request")


# ═══════════════════════════════════════════════════════════════
# Message Format Conversion
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# Token Usage Extraction
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# URL to Data URI Conversion
# ═══════════════════════════════════════════════════════════════

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
        placeholder_count = 0
        for url, content_item, data_uri in zip(urls_to_convert, content_items, data_uris):
            if isinstance(data_uri, Exception):
                # 🆕 Utiliser un placeholder au lieu de garder l'URL originale
                placeholder_uri = create_placeholder_image_url()
                content_item["image_url"]["url"] = placeholder_uri
                placeholder_count += 1
                logger.warning(f"⚠️ Conversion échouée (exception), placeholder utilisé pour: {url[:60]}...")
            elif data_uri:
                content_item["image_url"]["url"] = data_uri
                with _data_uri_cache_lock:
                    _data_uri_cache[url] = data_uri
                converted_count += 1
            else:
                # 🆕 Utiliser un placeholder au lieu de garder l'URL originale
                placeholder_uri = create_placeholder_image_url()
                content_item["image_url"]["url"] = placeholder_uri
                placeholder_count += 1
                logger.warning(f"⚠️ Conversion retournée None, placeholder utilisé pour: {url[:60]}...")

        logger.debug(f"🔄 Conversion parallèle: {converted_count} converties, {cached_count} cached, {placeholder_count} placeholders")
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
                        # 🆕 Utiliser un placeholder au lieu de garder l'URL originale
                        placeholder_uri = create_placeholder_image_url()
                        content_item["image_url"]["url"] = placeholder_uri
                        failed_count += 1
                        logger.warning(f"⚠️ Conversion sync échouée, placeholder utilisé pour: {original_url[:60]}...")

        logger.debug(f"🔄 Conversion sync: {converted_count} converties, {cached_count} cached, {failed_count} placeholders")
        return user_message

    except Exception as e:
        logger.error(f"❌ Erreur conversion sync: {e}")
        return user_message


# ═══════════════════════════════════════════════════════════════
# Dynamic Prompt Building
# ═══════════════════════════════════════════════════════════════

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

def build_dynamic_prompt(input_data: InputData, parcours_type: str = "Voyageur") -> str:
    """
    Construire un prompt dynamique basé sur les critères spécifiques de la pièce

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        str: Prompt dynamique construit
    """
    # Lazy import to avoid circular dependency with make_request.py
    from make_request import load_prompts_config

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
