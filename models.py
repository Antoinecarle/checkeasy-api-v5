from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════
# MODÈLES DE BASE
# ═══════════════════════════════════════════════════════════════

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
    status: Literal["ok", "attention", "probleme", "non_evaluable"]
    score: float = Field(ge=0, le=5, description="Note algorithmique de 0 à 5 (0 = non évaluable, 1-5 = note normale)")
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


# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR LA CLASSIFICATION DE PIÈCES
# ═══════════════════════════════════════════════════════════════

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
    status: str = Field(description="present, missing, moved, damaged, not_verifiable")
    confidence: int = Field(ge=0, le=100)
    details: str = Field(description="Détails de la vérification")

class InventoryVerificationResponse(BaseModel):
    """Réponse de la vérification d'inventaire"""
    piece_id: str
    total_checked: int
    missing_objects: List[ObjectVerificationResult]
    moved_objects: List[ObjectVerificationResult]
    present_objects: List[ObjectVerificationResult]
    not_verifiable_objects: List[ObjectVerificationResult] = Field(default_factory=list, description="Objets non vérifiables car zone non visible sur photos de sortie")

class VerifyInventoryInput(BaseModel):
    piece_id: str
    inventory: InventoryExtractionResponse
    checkout_pictures: List[Picture]


# ═══════════════════════════════════════════════════════════════
# MODÈLE POUR LA RÉPONSE COMBINÉE
# ═══════════════════════════════════════════════════════════════

class CombinedAnalysisResponse(BaseModel):
    piece_id: str
    nom_piece: str
    # Informations de classification
    room_classification: RoomClassificationResponse
    # Résultats de l'analyse
    analyse_globale: AnalyseGlobale
    issues: List[Probleme]  # Issues générales + issues d'étapes (fusionnées)


# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR LE RAPPORT INDIVIDUAL-REPORT
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


# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR LA SYNTHÈSE GLOBALE DU LOGEMENT
# ═══════════════════════════════════════════════════════════════

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
# MODÈLES POUR LA GESTION DES ROOM TEMPLATES
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


# ═══════════════════════════════════════════════════════════════
# MODÈLES POUR LA GESTION DES PROMPTS
# ═══════════════════════════════════════════════════════════════

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
