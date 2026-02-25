"""
Scoring functions extracted from make_request.py

Contains:
- calculate_category_scores()
- get_label_for_grade()
- calculate_weighted_severity_score()
- calculate_room_algorithmic_score()
"""

import logging
from typing import List

from models import CombinedAnalysisResponse, Probleme

logger = logging.getLogger("make_request")


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

    # Late import to avoid circular dependency
    from make_request import load_scoring_config

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
    # Late import to avoid circular dependency
    from make_request import load_scoring_config

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
