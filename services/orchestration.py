"""
services/orchestration.py - Orchestration functions extracted from make_request.py

Contains:
- transform_to_individual_report: Transforms analysis results to individual report format
- generate_logement_enrichment: Generates enrichment data (summary, score, etc.)
- analyze_single_piece_async: Analyzes a single piece asynchronously
- analyze_complete_logement_parallel: Parallel analysis of a complete logement
- analyze_complete_logement: Main orchestration function for complete logement analysis
"""

from typing import List, Optional
import json
import asyncio
import logging
from datetime import datetime

from fastapi import HTTPException

# Models
from models import (
    InputData,
    Picture,
    AnalyseGlobale,
    Probleme,
    CombinedAnalysisResponse,
    PieceWithEtapes,
    EtapesAnalysisInput,
    EtapeIssue,
    EtapesAnalysisResponse,
    LogementSummary,
    GlobalScore,
    LogementAnalysisEnrichment,
    CompleteAnalysisResponse,
)

# Config (client, OPENAI_MODEL, DOUBLE_PASS_ENABLED)
from config import (
    client,
    OPENAI_MODEL,
    DOUBLE_PASS_ENABLED,
)

# OpenAI utils
from openai_utils import (
    convert_chat_messages_to_responses_input,
    extract_usage_tokens,
    build_full_prompt_from_config,
)

# Scoring
from scoring import (
    calculate_category_scores,
    calculate_weighted_severity_score,
    calculate_room_algorithmic_score,
)

# Image converter
from image_converter import (
    normalize_url,
    is_valid_image_url,
)

# Services
from services.analysis import (
    analyze_with_auto_classification,
)
from services.etapes import (
    analyze_etapes,
    analyze_single_etape_async,
    process_etapes_images_parallel,
)

from tqdm import tqdm

logger = logging.getLogger("make_request")


# ═══════════════════════════════════════════════════════════════
# transform_to_individual_report
# ═══════════════════════════════════════════════════════════════

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
        # ÉTAPE 1: Créer un mapping etape_id -> validation_status depuis les issues IA
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
        # ÉTAPE 2: Construire tachesValidees avec estApprouve basé sur validation_status IA
        # ═══════════════════════════════════════════════════════════════
        taches_validees = []
        for etape in piece_input.etapes:
            # Récupérer le validation_status de l'IA pour cette étape
            ia_validation_status = etape_validation_status_map.get(etape.etape_id)

            # Déterminer estApprouve selon la logique suivante :
            # 1. Si PAS d'analyse IA (ia_validation_status absent) -> utiliser tache_approuvee tel quel (ou True par défaut)
            # 2. Si analyse IA disponible -> utiliser le statut IA (sauf si surcharge manuelle explicite)

            if ia_validation_status is None:
                # Pas d'analyse IA -> respecter la valeur manuelle ou True par défaut
                est_approuve = etape.tache_approuvee if etape.tache_approuvee is not None else True
            else:
                # Analyse IA disponible
                if etape.tache_approuvee is not None:
                    # Surcharge manuelle explicite -> prioritaire
                    est_approuve = etape.tache_approuvee
                else:
                    # Utiliser le statut IA
                    est_approuve = (ia_validation_status == "VALIDÉ")

            taches_validees.append({
                "etapeId": etape.etape_id,
                "nom": etape.task_name,
                "consigne": etape.consigne,
                "checkingPicture": etape.checking_picture,
                "checkoutPicture": etape.checkout_picture,
                "estApprouve": est_approuve,
                "dateHeureValidation": etape.tache_date_validation or "",
                "commentaire": etape.tache_commentaire,
                "validationStatusIA": ia_validation_status
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

            # Ajouter etapeId si l'issue provient d'une étape
            if hasattr(issue, 'etape_id') and issue.etape_id:
                probleme_dict["etapeId"] = issue.etape_id

            # Ajouter validation_status si disponible
            if hasattr(issue, 'validation_status') and issue.validation_status:
                probleme_dict["validationStatus"] = issue.validation_status

            # Ajouter commentaireIA si disponible
            if hasattr(issue, 'commentaire') and issue.commentaire:
                probleme_dict["commentaireIA"] = issue.commentaire

            # Ajouter photoUrl pour chaque problème
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
        # CALCUL DU MALUS BASÉ SUR LES ISSUES D'ÉTAPES
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
# generate_logement_enrichment
# ═══════════════════════════════════════════════════════════════

def generate_logement_enrichment(logement_id: str, pieces_analysis: List[CombinedAnalysisResponse], total_issues: int, general_issues: int, etapes_issues: int, parcours_type: str = "Voyageur", request_id: str = None) -> LogementAnalysisEnrichment:
    """
    Générer une synthèse globale et des recommandations pour le logement

    VERSION AVEC SYSTÈME DE NOTATION ALGORITHMIQUE (APPROCHE 2)
    - Le score est calculé de manière déterministe via calculate_weighted_severity_score()
    - L'IA génère uniquement le summary et les recommendations
    - Plus de variabilité, plus de traçabilité, plus d'équité
    """
    try:
        # Lazy imports to avoid circular dependencies
        from logs_viewer.logs_manager import logs_manager

        # LOGS D'ENTRÉE DÉTAILLÉS
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
        weighted_average = score_result["weighted_average_grade"]

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

        # ÉTAPE 1: Créer un résumé structuré des problèmes détectés
        logger.debug(f"🔍 ÉTAPE 1 - Création du résumé structuré des problèmes")
        issues_summary = []
        pieces_avec_problemes = 0

        for i, piece in enumerate(pieces_analysis):
            piece_issues = []

            # Vérification de la structure de la pièce
            if not hasattr(piece, 'issues'):
                logger.warning(f"⚠️ Pièce {piece.piece_id} sans attribut 'issues'")
                continue

            if piece.issues is None:
                logger.warning(f"⚠️ piece.issues est None pour {piece.piece_id}")
                piece.issues = []

            # Filtrer les issues avec confiance >= 75%
            issues_filtrees = 0
            for issue in piece.issues:
                if hasattr(issue, 'confidence') and issue.confidence >= 75:
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

        # ÉTAPE 2: Construire le prompt pour la synthèse globale
        logger.debug(f"🔍 ÉTAPE 2 - Construction du prompt de synthèse")

        try:
            # Lazy import for load_prompts_config (defined in make_request.py)
            from make_request import load_prompts_config

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

            # LOG DÉTAILLÉ DU PROMPT POUR DEBUG
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

        # ÉTAPE 3: Faire l'appel API pour la synthèse
        logger.debug(f"🔍 ÉTAPE 3 - Appel à l'IA de synthèse (OpenAI)")

        try:
            logger.debug(f"   🤖 Modèle: {OPENAI_MODEL}")
            logger.debug(f"   🌡️ Température: 0.1")
            logger.debug(f"   📏 Max tokens: 16000")

            # LOG DU PROMPT DE SYNTHÈSE
            if request_id:
                logs_manager.add_prompt_log(
                    request_id=request_id,
                    prompt_type="Synthesis",
                    prompt_content=synthesis_prompt,
                    model=OPENAI_MODEL
                )

            # MIGRATION vers Responses API
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

        # ÉTAPE 4: Parser et valider la réponse
        logger.debug(f"🔍 ÉTAPE 4 - Parsing et validation de la réponse IA")

        # MIGRATION: Extraction depuis Responses API
        response_content = (response.output_text if hasattr(response, 'output_text') else str(response.output[0].content[0].text)).strip()
        logger.debug(f"   📄 Longueur réponse: {len(response_content)} caractères")

        # LOG DE LA RÉPONSE DE SYNTHÈSE
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
        # GÉNÉRATION DE L'EXPLICATION COMPRÉHENSIBLE
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
# analyze_single_piece_async
# ═══════════════════════════════════════════════════════════════

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
        # Lazy import for truncate_url_for_log (defined in make_request.py)
        from make_request import truncate_url_for_log

        logger.debug(f"🔍 [ASYNC] Analyse de la pièce {piece.piece_id}: {piece.nom} (parcours: {parcours_type})")

        # Filtrer les images invalides avant l'analyse
        valid_checkin_pictures = []
        for pic in piece.checkin_pictures:
            logger.debug(f"🔍 Traitement image checkin - URL originale: '{truncate_url_for_log(pic.url)}'")
            normalized_url = normalize_url(pic.url)
            logger.debug(f"🔍 Traitement image checkin - URL normalisée: '{truncate_url_for_log(normalized_url)}'")

            if is_valid_image_url(normalized_url):
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkin_pictures.append(normalized_pic)
                logger.debug(f"✅ Image checkin valide ajoutée: {truncate_url_for_log(normalized_url)}")
            else:
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {truncate_url_for_log(pic.url)}")
                logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {truncate_url_for_log(normalized_url)}")

        valid_checkout_pictures = []
        for pic in piece.checkout_pictures:
            logger.debug(f"🔍 Traitement image checkout - URL originale: '{truncate_url_for_log(pic.url)}'")
            normalized_url = normalize_url(pic.url)
            logger.debug(f"🔍 Traitement image checkout - URL normalisée: '{truncate_url_for_log(normalized_url)}'")

            if is_valid_image_url(normalized_url):
                normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                valid_checkout_pictures.append(normalized_pic)
                logger.debug(f"✅ Image checkout valide ajoutée: {truncate_url_for_log(normalized_url)}")
            else:
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {truncate_url_for_log(pic.url)}")
                logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {truncate_url_for_log(normalized_url)}")

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
        # Utiliser run_in_executor pour exécuter dans un thread pool
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
        # DÉSACTIVÉ TEMPORAIREMENT (DOUBLE_PASS_ENABLED = False)
        # ═══════════════════════════════════════════════════════════════
        if DOUBLE_PASS_ENABLED and len(valid_checkin_pictures) > 0 and len(valid_checkout_pictures) > 0:
            logger.debug(f"📦 [ASYNC] DOUBLE-PASS: Vérification renforcée des objets manquants pour {piece.nom}")

            try:
                # Lazy import for inventory functions (still in make_request.py)
                from make_request import extract_inventory_from_images, verify_inventory_on_checkout, convert_inventory_to_issues

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


# ═══════════════════════════════════════════════════════════════
# analyze_complete_logement_parallel
# ═══════════════════════════════════════════════════════════════

async def analyze_complete_logement_parallel(input_data: EtapesAnalysisInput, request_id: str = None) -> CompleteAnalysisResponse:
    """
    Version PARALLÉLISÉE de analyze_complete_logement
    Utilise asyncio.gather() pour analyser toutes les pièces et étapes en parallèle

    Gain attendu: 70-80% de réduction du temps (80s -> 14s pour 5 pièces)
    """
    try:
        # Lazy imports to avoid circular dependencies
        from logs_viewer.logs_manager import logs_manager

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

        # DEBUG: Logger les issues de chaque pièce
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

                # RÈGLE: Exclure les tâches sans checkout_picture de l'analyse AI
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
                    etape_id=etape_issue.etape_id
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

            # RECALCULER LE SCORE DE LA PIÈCE avec TOUTES les issues (générales + étapes)
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

        # DEBUG: Logger les issues après reconstruction
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


# ═══════════════════════════════════════════════════════════════
# analyze_complete_logement (VERSION SÉQUENTIELLE)
# ═══════════════════════════════════════════════════════════════

def analyze_complete_logement(input_data: EtapesAnalysisInput, request_id: str = None) -> CompleteAnalysisResponse:
    """
    Analyse complète d'un logement : classification + analyse générale + analyse des étapes
    VERSION SÉQUENTIELLE (originale)
    """
    try:
        # Lazy import for truncate_url_for_log (defined in make_request.py)
        from make_request import truncate_url_for_log

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
                # DEBUG: Logger l'URL originale
                logger.debug(f"🔍 Traitement image checkin - URL originale: '{truncate_url_for_log(pic.url)}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.debug(f"🔍 Traitement image checkin - URL normalisée: '{truncate_url_for_log(normalized_url)}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkin_pictures.append(normalized_pic)
                    logger.debug(f"✅ Image checkin valide ajoutée: {truncate_url_for_log(normalized_url)}")
                else:
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL originale: {truncate_url_for_log(pic.url)}")
                    logger.warning(f"⚠️ Image checkin invalide ignorée - URL normalisée: {truncate_url_for_log(normalized_url)}")

            valid_checkout_pictures = []
            for pic in piece.checkout_pictures:
                # DEBUG: Logger l'URL originale
                logger.debug(f"🔍 Traitement image checkout - URL originale: '{truncate_url_for_log(pic.url)}'")

                # Normaliser l'URL avant validation
                normalized_url = normalize_url(pic.url)
                logger.debug(f"🔍 Traitement image checkout - URL normalisée: '{truncate_url_for_log(normalized_url)}'")

                if is_valid_image_url(normalized_url):
                    # Créer un nouveau Picture avec l'URL normalisée
                    normalized_pic = Picture(piece_id=pic.piece_id, url=normalized_url)
                    valid_checkout_pictures.append(normalized_pic)
                    logger.debug(f"✅ Image checkout valide ajoutée: {truncate_url_for_log(normalized_url)}")
                else:
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL originale: {truncate_url_for_log(pic.url)}")
                    logger.warning(f"⚠️ Image checkout invalide ignorée - URL normalisée: {truncate_url_for_log(normalized_url)}")

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
                    etape_id=etape_issue.etape_id
                )
                etapes_issues_by_piece[piece_id].append(probleme)

        logger.debug(f"✅ Analyse des étapes terminée: {len(etapes_analysis.preliminary_issues)} issues d'étapes détectées")

        # ÉTAPE 3: Ajouter les issues d'étapes aux pièces correspondantes
        logger.debug(f"🔄 ÉTAPE 3 - Ajout des issues d'étapes aux pièces correspondantes")

        # VÉRIFICATIONS SCRUPULEUSES AVANT CALCUL
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

        # LOGS DÉTAILLÉS POUR CHAQUE PIÈCE
        for i, piece_analysis in enumerate(pieces_analysis_results):
            piece_id = piece_analysis.piece_id

            # Vérifier que piece_analysis.issues existe et est une liste
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

        # VÉRIFICATIONS FINALES AVANT TRANSMISSION
        logger.debug(f"📊 ÉTAPE 4 - Compilation et vérifications des résultats finaux")

        # Calculs de vérification
        verification_total = general_issues_count + etapes_issues_count

        logger.debug(f"🔍 VÉRIFICATIONS COMPTEURS:")
        logger.debug(f"   📋 Issues générales: {general_issues_count}")
        logger.debug(f"   🎯 Issues d'étapes: {etapes_issues_count}")
        logger.debug(f"   📊 Total calculé: {total_issues_count}")
        logger.debug(f"   🧮 Vérification: {general_issues_count} + {etapes_issues_count} = {verification_total}")

        # ALERTE si les compteurs ne correspondent pas
        if total_issues_count != verification_total:
            logger.warning(f"⚠️ ATTENTION: Différence de comptage détectée!")
            logger.warning(f"   Total calculé: {total_issues_count}")
            logger.warning(f"   Somme attendue: {verification_total}")
            # On continue mais on log l'anomalie

        # VÉRIFICATION CRITIQUE: Si des issues sont visibles mais total_issues_count = 0
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

        # VALIDATION DES DONNÉES AVANT TRANSMISSION À L'IA
        logger.debug(f"🧠 ÉTAPE 5 - Génération de la synthèse globale via IA")

        # Vérifier que nous avons des données valides
        if not pieces_analysis_results:
            logger.error("❌ ERREUR: Aucune analyse de pièce pour la synthèse!")
            raise ValueError("Impossible de générer la synthèse sans données d'analyse")

        # Vérifier que logement_id est valide
        if not input_data.logement_id or input_data.logement_id.strip() == "":
            logger.error("❌ ERREUR: logement_id vide!")
            raise ValueError("logement_id manquant pour la synthèse")

        # LOG FINAL AVANT TRANSMISSION
        logger.debug(f"🚀 TRANSMISSION À L'IA DE SYNTHÈSE:")
        logger.debug(f"   🏠 Logement ID: {input_data.logement_id}")
        logger.debug(f"   🏘️ Nombre de pièces: {len(pieces_analysis_results)}")
        logger.debug(f"   📊 Total issues: {total_issues_count}")
        logger.debug(f"   📋 Issues générales: {general_issues_count}")
        logger.debug(f"   🎯 Issues étapes: {etapes_issues_count}")

        # APPEL SÉCURISÉ À L'IA DE SYNTHÈSE
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

            # VÉRIFICATION DE LA RÉPONSE
            if not analysis_enrichment:
                logger.error("❌ ERREUR: generate_logement_enrichment a retourné None!")
                raise ValueError("Échec de génération de l'enrichissement")

            if not hasattr(analysis_enrichment, 'global_score'):
                logger.error("❌ ERREUR: Pas de global_score dans l'enrichissement!")
                raise ValueError("global_score manquant dans la réponse d'enrichissement")

            # ACCEPTATION DU SCORE DE L'IA BASÉ SUR SON RESSENTI GÉNÉRAL
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
