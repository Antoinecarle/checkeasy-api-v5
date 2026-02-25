"""
services/analysis.py - Core IA analysis functions extracted from make_request.py

Contains:
- analyze_images: Main image analysis function
- verify_checkin_checkout_coherence: Verifies checkin/checkout photo coherence
- classify_room_type: Classifies room type from images
- analyze_with_auto_classification: Combines classification + analysis
- apply_two_step_validation_logic_sync: Sync version of two-step validation
- apply_two_step_validation_logic: Async version of two-step validation
- map_room_type_to_valid: Helper to map room type variations to valid types
"""

from typing import List, Optional
import json
import asyncio
import aiohttp
import logging
import re
import threading
from datetime import datetime

from fastapi import HTTPException

# Models
from models import (
    InputData,
    AnalyseResponse,
    AnalyseGlobale,
    Probleme,
    RoomClassificationInput,
    RoomClassificationResponse,
    RoomVerifications,
    CombinedAnalysisResponse,
    Picture,
)

# Config (client, async_client, OPENAI_MODEL, DOUBLE_PASS_ENABLED, etc.)
from config import (
    client,
    async_client,
    OPENAI_MODEL,
    DOUBLE_PASS_ENABLED,
    detect_environment,
    get_bubble_debug_endpoint,
    load_room_templates,
)

# OpenAI utils
from openai_utils import (
    convert_chat_messages_to_responses_input,
    build_dynamic_prompt,
    extract_usage_tokens,
    convert_message_urls_to_data_uris_sync,
    convert_url_to_data_uri,
    build_full_prompt_from_config,
    _data_uri_cache,
    _data_uri_cache_lock,
)

# Scoring
from scoring import calculate_room_algorithmic_score

# Image converter
from image_converter import (
    process_pictures_list,
    is_valid_image_url,
    normalize_url,
)

logger = logging.getLogger("make_request")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: map_room_type_to_valid
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION: analyze_images
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_images(input_data: InputData, parcours_type: str = "Voyageur", request_id: str = None) -> AnalyseResponse:
    """
    Analyser les images d'entrée et de sortie et retourner une réponse structurée.

    Args:
        input_data: Données d'entrée de la pièce
        parcours_type: Type de parcours ("Voyageur" ou "Ménage")

    Returns:
        AnalyseResponse: Résultat de l'analyse
    """
    # Lazy imports for dependencies that stay in make_request.py
    from logs_viewer.logs_manager import logs_manager

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
# FUNCTION: verify_checkin_checkout_coherence
# ═══════════════════════════════════════════════════════════════════════════════

def verify_checkin_checkout_coherence(
    checkin_pictures: List[Picture],
    checkout_pictures: List[Picture],
    piece_id: str,
    parcours_type: str = "Voyageur"
) -> dict:
    """
    Vérifie la cohérence entre les photos checkin et checkout.
    Détecte si les photos montrent des pièces différentes.

    🆕 AMÉLIORATION V2: Comparaison visuelle DIRECTE au lieu de classifications indépendantes
    pour éviter les faux positifs (ex: même pièce classifiée différemment selon l'angle)

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

        logger.info(f"🔍 [COHERENCE V2] Vérification cohérence checkin/checkout pour pièce {piece_id}")
        logger.info(f"🔍 [COHERENCE V2] Méthode: Comparaison visuelle DIRECTE (évite les faux positifs)")

        # 🆕 ÉTAPE 1: PRÉPARER TOUTES LES IMAGES (checkin ET checkout ensemble)
        checkin_pictures_raw = [pic.model_dump() for pic in checkin_pictures]
        checkout_pictures_raw = [pic.model_dump() for pic in checkout_pictures]

        checkin_processed = process_pictures_list(checkin_pictures_raw)
        checkout_processed = process_pictures_list(checkout_pictures_raw)

        # 🆕 ÉTAPE 2: PROMPT DE COMPARAISON DIRECTE
        # Demander à l'IA de comparer visuellement si c'est la MÊME pièce
        comparison_prompt = """🔍 ANALYSE DE COHÉRENCE VISUELLE - PHOTOS AVANT/APRÈS

Tu es un expert en analyse d'images immobilières. Ta mission est de déterminer si les photos AVANT (checkin) et APRÈS (checkout) montrent LA MÊME PIÈCE physique.

⚠️ RÈGLES IMPORTANTES:
1. Compare les ÉLÉMENTS STRUCTURELS permanents: murs, fenêtres, portes, disposition générale
2. Compare les MEUBLES FIXES: cuisine intégrée, placards, évier, baignoire, etc.
3. IGNORE les différences normales: éclairage, angle de vue, objets déplacés, propreté
4. Une pièce peut être photographiée sous différents angles → c'est NORMAL

🏠 ÉLÉMENTS À COMPARER:
- Structure de la pièce (forme, dimensions apparentes)
- Position des fenêtres et portes
- Revêtements (sol, murs)
- Meubles fixes et intégrés
- Éléments caractéristiques (cheminée, poutres, escalier visible...)

📸 FORMAT DES PHOTOS:
- Les premières photos sont les photos CHECKIN (avant)
- Les dernières photos sont les photos CHECKOUT (après)

🎯 RETOURNE UNIQUEMENT CE JSON:
{
    "is_same_room": true/false,
    "confidence": 0-100,
    "checkin_room_type": "type de pièce détecté sur les photos checkin",
    "checkout_room_type": "type de pièce détecté sur les photos checkout",
    "reasoning": "Explication courte de ta décision",
    "matching_elements": ["liste des éléments identiques trouvés"],
    "different_elements": ["liste des éléments vraiment différents (pas juste angle/éclairage)"]
}

⚠️ SEUIL DE DÉCISION:
- is_same_room = true si tu es à 70%+ sûr que c'est la même pièce
- En cas de doute, privilégie TRUE (même pièce) pour éviter les faux positifs
- Les différences d'angle de vue, d'éclairage, de rangement ne sont PAS des indices de pièces différentes"""

        # 🆕 ÉTAPE 3: CONSTRUIRE LE MESSAGE AVEC TOUTES LES IMAGES
        user_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": comparison_prompt},
                {"type": "text", "text": f"\n📍 Pièce ID: {piece_id}\n\n--- PHOTOS CHECKIN (AVANT) ---"}
            ]
        }

        # Ajouter les photos checkin
        valid_checkin_count = 0
        for photo in checkin_processed:
            normalized_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_url) and not normalized_url.startswith('data:image/gif;base64,R0lGOD'):
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": normalized_url, "detail": "high"}
                })
                valid_checkin_count += 1

        # Séparateur visuel
        user_message["content"].append({"type": "text", "text": "\n--- PHOTOS CHECKOUT (APRÈS) ---"})

        # Ajouter les photos checkout
        valid_checkout_count = 0
        for photo in checkout_processed:
            normalized_url = normalize_url(photo['url'])
            if is_valid_image_url(normalized_url) and not normalized_url.startswith('data:image/gif;base64,R0lGOD'):
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {"url": normalized_url, "detail": "high"}
                })
                valid_checkout_count += 1

        logger.debug(f"🔍 [COHERENCE V2] Photos valides: {valid_checkin_count} checkin, {valid_checkout_count} checkout")

        # 🆕 ÉTAPE 4: APPEL UNIQUE À L'IA POUR COMPARAISON DIRECTE
        logger.debug(f"🔍 [COHERENCE V2] Appel OpenAI pour comparaison visuelle directe...")

        input_content = convert_chat_messages_to_responses_input([user_message])
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=input_content,
            text={"format": {"type": "json_object"}},
            max_output_tokens=800
        )

        result = json.loads(response.output_text)

        is_same_room = result.get("is_same_room", True)  # Par défaut TRUE pour éviter faux positifs
        confidence = result.get("confidence", 80)
        checkin_room_type = result.get("checkin_room_type", "autre")
        checkout_room_type = result.get("checkout_room_type", "autre")
        reasoning = result.get("reasoning", "")
        matching_elements = result.get("matching_elements", [])
        different_elements = result.get("different_elements", [])

        # Appliquer le mapping pour normaliser les types
        checkin_room_type = map_room_type_to_valid(checkin_room_type)
        checkout_room_type = map_room_type_to_valid(checkout_room_type)

        logger.debug(f"✅ [COHERENCE V2] Résultat: is_same_room={is_same_room}, confidence={confidence}%")
        logger.debug(f"✅ [COHERENCE V2] Types détectés: checkin={checkin_room_type}, checkout={checkout_room_type}")
        logger.debug(f"✅ [COHERENCE V2] Reasoning: {reasoning}")

        # 🆕 ÉTAPE 5: DÉCISION FINALE AVEC SEUIL DE TOLÉRANCE
        # Si confiance < 80% ET décision "différent", reconsidérer comme cohérent (doute = pas de blocage)
        if not is_same_room and confidence < 80:
            logger.info(f"🔍 [COHERENCE V2] Confiance faible ({confidence}%) → Reconsidéré comme COHÉRENT (éviter faux positif)")
            is_same_room = True
            reasoning = f"[TOLÉRANCE] Confiance insuffisante ({confidence}%) - Considéré comme même pièce. Original: {reasoning}"

        if is_same_room:
            message = f"Photos cohérentes (confiance: {confidence}%)"
            if matching_elements:
                message += f" - Éléments communs: {', '.join(matching_elements[:3])}"
            logger.info(f"✅ [COHERENCE V2] COHÉRENT: {reasoning}")
        else:
            message = f"Incohérence détectée (confiance: {confidence}%): {reasoning}"
            logger.warning(f"⚠️ [COHERENCE V2] ═══════════════════════════════════════")
            logger.warning(f"⚠️ [COHERENCE V2] INCOHÉRENCE DÉTECTÉE!")
            logger.warning(f"⚠️ [COHERENCE V2] Pièce ID: {piece_id}")
            logger.warning(f"⚠️ [COHERENCE V2] Confiance: {confidence}%")
            logger.warning(f"⚠️ [COHERENCE V2] Checkin → {checkin_room_type}")
            logger.warning(f"⚠️ [COHERENCE V2] Checkout → {checkout_room_type}")
            logger.warning(f"⚠️ [COHERENCE V2] Éléments différents: {different_elements}")
            logger.warning(f"⚠️ [COHERENCE V2] Reasoning: {reasoning}")
            logger.warning(f"⚠️ [COHERENCE V2] ═══════════════════════════════════════")

        return {
            "is_coherent": is_same_room,
            "checkin_room_type": checkin_room_type,
            "checkout_room_type": checkout_room_type,
            "message": message
        }

    except Exception as e:
        logger.error(f"❌ [COHERENCE V2] Erreur lors de la vérification: {e}")
        # En cas d'erreur, considérer comme cohérent pour ne pas bloquer
        return {
            "is_coherent": True,
            "checkin_room_type": "error",
            "checkout_room_type": "error",
            "message": f"Erreur lors de la vérification: {str(e)}"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION: classify_room_type
# ═══════════════════════════════════════════════════════════════════════════════

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
    # Lazy imports for dependencies that stay in make_request.py
    from make_request import load_prompts_config, truncate_url_for_log
    from logs_viewer.logs_manager import logs_manager

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
            logger.error(f"🚫 [COHERENCE V2] INCOHÉRENCE CONFIRMÉE entre checkin et checkout!")
            logger.error(f"   📸 Checkin classifié comme: {coherence_check['checkin_room_type']}")
            logger.error(f"   📸 Checkout classifié comme: {coherence_check['checkout_room_type']}")
            logger.error(f"   📝 Détails: {coherence_check['message']}")

            # Retourner une réponse wrong_room avec le message détaillé de la V2
            return RoomClassificationResponse(
                piece_id=input_data.piece_id,
                room_type="wrong_room",
                room_name="Photos incohérentes",
                room_icon="⚠️",
                confidence=95,
                is_valid_room=False,
                validation_message=coherence_check['message'],  # Utiliser le message détaillé de la V2
                verifications=RoomVerifications(
                    elements_critiques=["Vérifier que les photos correspondent à la même pièce"],
                    points_ignorables=[],
                    defauts_frequents=["Photos de pièces différentes"]
                )
            )
        else:
            logger.debug(f"✅ [COHERENCE V2] Photos checkin/checkout cohérentes: {coherence_check['message']}")

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
            logger.debug(f"🔍 URL avant normalisation: '{truncate_url_for_log(photo['url'])}'")
            logger.debug(f"🔍 URL après normalisation: '{truncate_url_for_log(normalized_photo_url)}'")

            if is_valid_image_url(normalized_photo_url) and not normalized_photo_url.startswith('data:image/gif;base64,R0lGOD'):
                valid_images.append(photo)
                user_message["content"].append({
                    "type": "image_url",
                    "image_url": {
                        "url": normalized_photo_url,  # ✅ Utiliser l'URL normalisée
                        "detail": "high"
                    }
                })
                logger.debug(f"✅ CLASSIFICATION - Image ajoutée au payload OpenAI: {truncate_url_for_log(normalized_photo_url)}")
            else:
                logger.warning(f"⚠️ CLASSIFICATION - Image invalide ignorée: {truncate_url_for_log(normalized_photo_url)}")

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


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION: analyze_with_auto_classification
# ═══════════════════════════════════════════════════════════════════════════════

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
            # Lazy import for functions that stay in make_request.py
            from make_request import extract_inventory_from_images, verify_inventory_on_checkout, convert_inventory_to_issues

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


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION: apply_two_step_validation_logic_sync
# ═══════════════════════════════════════════════════════════════════════════════

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
            comparison_prompt = f"""Tu es un expert en comparaison VISUELLE d'images.

🎯 OBJECTIF : Déterminer si deux photos sont VISUELLEMENT IDENTIQUES ou SIMILAIRES.

📸 CONTEXTE :
- Photo 1 : Image de référence
- Photo 2 : Image à comparer

🔍 QUESTION UNIQUE :
Les deux photos montrent-elles VISUELLEMENT le MÊME CONTENU ?

⚠️ RÈGLES CRITIQUES :
- Compare UNIQUEMENT ce qui est VISIBLE sur les photos
- IGNORE la consigne ou la tâche demandée - tu ne compares QUE les images
- IGNORE les différences d'angle, de luminosité, de cadrage, de qualité
- IGNORE ce qui n'est PAS visible (intérieur des placards, objets hors cadre, etc.)
- Deux photos montrant le même objet dans le même état = MÊME ÉTAT

📸 EXEMPLES DE "MÊME ÉTAT" (same_state = true) :
- Lave-vaisselle vide (photo 1) vs Lave-vaisselle vide (photo 2) → MÊME ÉTAT ✅
- Four propre ouvert (photo 1) vs Four propre ouvert (photo 2) → MÊME ÉTAT ✅
- Lit fait (photo 1) vs Lit fait (photo 2) → MÊME ÉTAT ✅
- Évier vide (photo 1) vs Évier vide (photo 2) → MÊME ÉTAT ✅

📸 EXEMPLES DE "ÉTAT DIFFÉRENT" (same_state = false) :
- Lave-vaisselle plein (photo 1) vs Lave-vaisselle vide (photo 2) → DIFFÉRENT ❌
- Lit défait (photo 1) vs Lit fait (photo 2) → DIFFÉRENT ❌
- Sol sale (photo 1) vs Sol propre (photo 2) → DIFFÉRENT ❌

🚫 NE PAS CONSIDÉRER COMME "DIFFÉRENT" :
- "La vaisselle n'est pas visible dans les placards" → Hors sujet, compare ce qui est VISIBLE
- "On ne peut pas voir les pastilles" → Hors sujet, compare ce qui est VISIBLE
- Éléments non photographiés → Ignore-les

📋 RÉPONDS EN JSON :
{{
    "same_state": true/false,
    "confidence": 0-100,
    "explanation": "Description de ce que tu VOIS sur les deux photos"
}}

- same_state = true → Les deux photos montrent visuellement le même contenu
- same_state = false → Les deux photos montrent visuellement un contenu différent"""

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


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTION: apply_two_step_validation_logic (ASYNC)
# ═══════════════════════════════════════════════════════════════════════════════

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
            comparison_prompt = f"""Tu es un expert en comparaison VISUELLE d'images.

🎯 OBJECTIF : Déterminer si deux photos sont VISUELLEMENT IDENTIQUES ou SIMILAIRES.

📸 CONTEXTE :
- Photo 1 : Image de référence
- Photo 2 : Image à comparer

🔍 QUESTION UNIQUE :
Les deux photos montrent-elles VISUELLEMENT le MÊME CONTENU ?

⚠️ RÈGLES CRITIQUES :
- Compare UNIQUEMENT ce qui est VISIBLE sur les photos
- IGNORE la consigne ou la tâche demandée - tu ne compares QUE les images
- IGNORE les différences d'angle, de luminosité, de cadrage, de qualité
- IGNORE ce qui n'est PAS visible (intérieur des placards, objets hors cadre, etc.)
- Deux photos montrant le même objet dans le même état = MÊME ÉTAT

📸 EXEMPLES DE "MÊME ÉTAT" (same_state = true) :
- Lave-vaisselle vide (photo 1) vs Lave-vaisselle vide (photo 2) → MÊME ÉTAT ✅
- Four propre ouvert (photo 1) vs Four propre ouvert (photo 2) → MÊME ÉTAT ✅
- Lit fait (photo 1) vs Lit fait (photo 2) → MÊME ÉTAT ✅
- Évier vide (photo 1) vs Évier vide (photo 2) → MÊME ÉTAT ✅

📸 EXEMPLES DE "ÉTAT DIFFÉRENT" (same_state = false) :
- Lave-vaisselle plein (photo 1) vs Lave-vaisselle vide (photo 2) → DIFFÉRENT ❌
- Lit défait (photo 1) vs Lit fait (photo 2) → DIFFÉRENT ❌
- Sol sale (photo 1) vs Sol propre (photo 2) → DIFFÉRENT ❌

🚫 NE PAS CONSIDÉRER COMME "DIFFÉRENT" :
- "La vaisselle n'est pas visible dans les placards" → Hors sujet, compare ce qui est VISIBLE
- "On ne peut pas voir les pastilles" → Hors sujet, compare ce qui est VISIBLE
- Éléments non photographiés → Ignore-les

📋 RÉPONDS EN JSON :
{{
    "same_state": true/false,
    "confidence": 0-100,
    "explanation": "Description de ce que tu VOIS sur les deux photos"
}}

- same_state = true → Les deux photos montrent visuellement le même contenu
- same_state = false → Les deux photos montrent visuellement un contenu différent"""

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
