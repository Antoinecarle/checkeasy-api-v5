"""
Module d'analyse des logs parsés
Extrait les métriques, regroupe par pièce, identifie les erreurs
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta
from tqdm import tqdm
from .log_parser import LogEntry


@dataclass
class RoomAnalysis:
    """Analyse d'une pièce"""
    piece_id: str
    room_name: str
    room_emoji: str
    steps_completed: Dict[str, bool] = field(default_factory=dict)
    errors: List[LogEntry] = field(default_factory=list)
    warnings: List[LogEntry] = field(default_factory=list)
    score: Optional[int] = None
    anomalies_count: int = 0
    confidence: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_logs: List[LogEntry] = field(default_factory=list)


@dataclass
class GlobalSummary:
    """Résumé global de l'analyse"""
    parcours_type: str = "Inconnu"
    total_rooms: int = 0
    total_anomalies: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    average_score: float = 0.0
    total_duration: Optional[timedelta] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    critical_errors: List[LogEntry] = field(default_factory=list)


class LogAnalyzer:
    """Analyseur de logs CheckEasy"""
    
    STEP_ORDER = [
        'classification',
        'injection',
        'image_processing',
        'openai_analysis',
        'json_parsing',
        'final_summary'
    ]
    
    STEP_NAMES = {
        'classification': 'Classification automatique',
        'injection': 'Injection des critères',
        'image_processing': 'Traitement des images',
        'openai_analysis': 'Analyse OpenAI',
        'json_parsing': 'Parsing & validation JSON',
        'final_summary': 'Résumé final'
    }
    
    def __init__(self, log_entries: List[LogEntry]):
        self.log_entries = log_entries
        self.rooms: Dict[str, RoomAnalysis] = {}
        self.global_summary = GlobalSummary()
        
    def analyze(self, show_progress: bool = True) -> Dict[str, RoomAnalysis]:
        """
        Analyse les logs et regroupe par pièce
        
        Args:
            show_progress: Afficher une barre de progression
            
        Returns:
            Dictionnaire {piece_id: RoomAnalysis}
        """
        print("🔍 Analyse des logs en cours...")
        
        # Étape 1: Regrouper par pièce
        self._group_by_room(show_progress)
        
        # Étape 2: Analyser chaque pièce
        self._analyze_rooms(show_progress)
        
        # Étape 3: Calculer le résumé global
        self._compute_global_summary()
        
        return self.rooms
    
    def _group_by_room(self, show_progress: bool):
        """Regroupe les logs par pièce"""
        iterator = tqdm(self.log_entries, desc="📦 Regroupement par pièce", disable=not show_progress)
        
        for entry in iterator:
            if not entry.piece_id:
                continue
            
            if entry.piece_id not in self.rooms:
                from .log_parser import LogParser
                parser = LogParser()
                
                self.rooms[entry.piece_id] = RoomAnalysis(
                    piece_id=entry.piece_id,
                    room_name=entry.room_name or "Pièce inconnue",
                    room_emoji=parser.get_room_emoji(entry.room_name),
                    steps_completed={step: False for step in self.STEP_ORDER}
                )
            
            self.rooms[entry.piece_id].all_logs.append(entry)
    
    def _analyze_rooms(self, show_progress: bool):
        """Analyse chaque pièce individuellement"""
        iterator = tqdm(self.rooms.items(), desc="🔬 Analyse des pièces", disable=not show_progress)
        
        for piece_id, room in iterator:
            # Trier les logs par timestamp
            room.all_logs.sort(key=lambda x: x.timestamp)
            
            # Définir les timestamps de début et fin
            if room.all_logs:
                room.start_time = room.all_logs[0].timestamp
                room.end_time = room.all_logs[-1].timestamp
            
            # Analyser les étapes
            for entry in room.all_logs:
                if entry.step:
                    room.steps_completed[entry.step] = True
                
                # Collecter les erreurs et warnings
                if entry.level == 'ERROR':
                    room.errors.append(entry)
                elif entry.level == 'WARNING':
                    room.warnings.append(entry)
                
                # Extraire le score
                score_match = self._extract_score(entry.message)
                if score_match:
                    room.score = score_match
                
                # Extraire le nombre d'anomalies
                anomalies_match = self._extract_anomalies_count(entry.message)
                if anomalies_match:
                    room.anomalies_count = anomalies_match
                
                # Extraire la confiance
                confidence_match = self._extract_confidence(entry.message)
                if confidence_match:
                    room.confidence = confidence_match
    
    def _compute_global_summary(self):
        """Calcule le résumé global"""
        self.global_summary.total_rooms = len(self.rooms)
        
        scores = []
        all_errors = []
        all_warnings = []
        
        for room in self.rooms.values():
            if room.score is not None:
                scores.append(room.score)
            
            self.global_summary.total_anomalies += room.anomalies_count
            all_errors.extend(room.errors)
            all_warnings.extend(room.warnings)
        
        self.global_summary.total_errors = len(all_errors)
        self.global_summary.total_warnings = len(all_warnings)
        
        if scores:
            self.global_summary.average_score = sum(scores) / len(scores)
        
        # Identifier les erreurs critiques
        self.global_summary.critical_errors = [
            err for err in all_errors 
            if any(keyword in err.message.lower() for keyword in ['crash', 'fatal', 'exception', 'failed'])
        ]
        
        # Détecter le type de parcours
        self.global_summary.parcours_type = self._detect_parcours_type()
        
        # Calculer la durée totale
        if self.log_entries:
            sorted_entries = sorted(self.log_entries, key=lambda x: x.timestamp)
            self.global_summary.start_time = sorted_entries[0].timestamp
            self.global_summary.end_time = sorted_entries[-1].timestamp
            self.global_summary.total_duration = self.global_summary.end_time - self.global_summary.start_time
    
    def _detect_parcours_type(self) -> str:
        """Détecte le type de parcours depuis les logs"""
        for entry in self.log_entries:
            if 'parcours' in entry.message.lower():
                if 'voyageur' in entry.message.lower():
                    return 'Voyageur'
                elif 'ménage' in entry.message.lower() or 'menage' in entry.message.lower():
                    return 'Ménage'
        return 'Inconnu'
    
    def _extract_score(self, message: str) -> Optional[int]:
        """Extrait le score depuis un message"""
        import re
        patterns = [
            r'[Ss]core[:\s]+(\d+)',
            r'Score\s+(\d+)/10',
            r'score:\s*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                return int(match.group(1))
        return None
    
    def _extract_anomalies_count(self, message: str) -> Optional[int]:
        """Extrait le nombre d'anomalies depuis un message"""
        import re
        patterns = [
            r'(\d+)\s+anomalies?',
            r'(\d+)\s+problèmes?',
            r'(\d+)\s+issues?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None
    
    def _extract_confidence(self, message: str) -> Optional[int]:
        """Extrait le niveau de confiance depuis un message"""
        import re
        patterns = [
            r'confiance[:\s]+(\d+)',
            r'confidence[:\s]+(\d+)',
            r'\((\d+)%\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None
    
    def get_step_progress(self, room: RoomAnalysis) -> float:
        """Calcule le pourcentage de progression des étapes pour une pièce"""
        completed = sum(1 for completed in room.steps_completed.values() if completed)
        total = len(room.steps_completed)
        return (completed / total * 100) if total > 0 else 0
    
    def get_step_status_emoji(self, completed: bool) -> str:
        """Retourne l'emoji de statut pour une étape"""
        return '✅' if completed else '❌'

