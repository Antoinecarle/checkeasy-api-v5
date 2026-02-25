"""
services/etapes.py - Etapes (steps) analysis functions extracted from make_request.py

Contains:
- analyze_etapes: Main synchronous etapes analysis function
- analyze_single_etape_async: Analyzes a single etape asynchronously
- process_single_etape_image_task: Processes a single etape image task (async)
- process_etapes_images_parallel: Processes etapes images in parallel (async)
"""

from typing import List
import json
import asyncio
import logging
from datetime import datetime

from fastapi import HTTPException

# Models
from models import (
    Etape,
    EtapesAnalysisInput,
    EtapesAnalysisResponse,
    EtapeIssue,
)

# Config (client, async_client, OPENAI_MODEL)
from config import (
    client,
    async_client,
    OPENAI_MODEL,
)

# OpenAI utils
from openai_utils import (
    convert_chat_messages_to_responses_input,
    extract_usage_tokens,
    convert_message_urls_to_data_uris_sync,
    convert_message_urls_to_data_uris_parallel,
    build_full_prompt_from_config,
)

# Image converter
from image_converter import (
    process_etapes_images,
    is_valid_image_url,
    normalize_url,
    create_placeholder_image_url,
    ImageConverter,
)

# Logs manager
from logs_viewer.logs_manager import logs_manager

# Analysis services (apply_two_step_validation_logic)
from services.analysis import (
    apply_two_step_validation_logic_sync,
    apply_two_step_validation_logic,
)

logger = logging.getLogger("make_request")


# ═══════════════════════════════════════════════════════════════════════════════
# analyze_etapes - Main synchronous etapes analysis
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_etapes(input_data: EtapesAnalysisInput, request_id: str = None) -> EtapesAnalysisResponse:
    """
    Analyser toutes les étapes du logement en comparant les images selon leurs consignes
    """
    try:
        # Lazy import for functions that remain in make_request.py
        from make_request import load_prompts_config, truncate_url_for_log

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
                    logger.debug(f"🔍 URL avant normalisation: '{truncate_url_for_log(checking_url)}'")
                    logger.debug(f"🔍 URL après normalisation: '{truncate_url_for_log(checking_url_normalized)}'")
                    checking_url = checking_url_normalized

                if checkout_url is not None and isinstance(checkout_url, str):
                    checkout_url_normalized = normalize_url(checkout_url)
                    logger.debug(f"🔍 URL avant normalisation: '{truncate_url_for_log(checkout_url)}'")
                    logger.debug(f"🔍 URL après normalisation: '{truncate_url_for_log(checkout_url_normalized)}'")
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
                    logger.debug(f"✅ ÉTAPE CHECKING - Image ajoutée au payload OpenAI: {truncate_url_for_log(checking_url)}")
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
                    logger.debug(f"✅ ÉTAPE CHECKOUT - Image ajoutée au payload OpenAI: {truncate_url_for_log(checkout_url)}")
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


# ═══════════════════════════════════════════════════════════════════════════════
# analyze_single_etape_async - Async single etape analysis
# ═══════════════════════════════════════════════════════════════════════════════

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
        # Lazy import for functions that remain in make_request.py
        from make_request import load_prompts_config

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

                    # 🆕 FALLBACK DERNIER RECOURS: Analyse sans images
                    logger.warning(f"⚠️ [ASYNC] Fallback dernier recours: analyse sans images pour l'étape {etape.etape_id}")
                    try:
                        # Créer un message texte uniquement
                        fallback_message = {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Analyse de l'étape '{etape.task_name}' (ID: {etape.etape_id}). "
                                            f"Consigne: {etape.consigne}. "
                                            f"Les images sont indisponibles (timeout CDN). "
                                            f"Retourner validation_status='non_verifiable' avec un commentaire explicatif et issues=[]."
                                }
                            ]
                        }

                        messages_fallback = [
                            {"role": "system", "content": system_prompt},
                            fallback_message
                        ]
                        input_content_fallback = convert_chat_messages_to_responses_input(messages_fallback)

                        if 'async_client' in globals() and async_client:
                            response = await async_client.responses.create(
                                model=OPENAI_MODEL,
                                input=input_content_fallback,
                                text={"format": {"type": "json_object"}},
                                max_output_tokens=500,
                                temperature=0.2
                            )
                        else:
                            response = client.responses.create(
                                model=OPENAI_MODEL,
                                input=input_content_fallback,
                                text={"format": {"type": "json_object"}},
                                max_output_tokens=500,
                                temperature=0.2
                            )

                        response_text = response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)
                        logger.info(f"✅ [ASYNC] Fallback sans images réussi pour l'étape {etape.etape_id}")

                    except Exception as fallback_error:
                        logger.error(f"❌ [ASYNC] Échec total pour l'étape {etape.etape_id}: {str(fallback_error)}")
                        # Retourner une réponse par défaut en dernier recours absolu
                        response_text = json.dumps({
                            "validation_status": "non_verifiable",
                            "commentaire": f"Analyse impossible : images indisponibles (timeout CDN) pour l'étape {etape.task_name}",
                            "issues": []
                        })
                        logger.warning(f"⚠️ [ASYNC] Réponse par défaut générée pour l'étape {etape.etape_id}")
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


# ═══════════════════════════════════════════════════════════════════════════════
# process_single_etape_image_task - Async single etape image processing
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# process_etapes_images_parallel - Parallel image processing for all etapes
# ═══════════════════════════════════════════════════════════════════════════════

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
