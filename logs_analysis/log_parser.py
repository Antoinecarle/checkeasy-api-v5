"""
Module de parsing des fichiers de logs CheckEasy
Supporte les formats JSON (Railway) et texte coloré (local)
"""

import json
import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
from tqdm import tqdm


@dataclass
class LogEntry:
    """Représente une entrée de log parsée"""
    timestamp: datetime
    level: str  # INFO, WARNING, ERROR, SUCCESS
    message: str
    piece_id: Optional[str] = None
    room_name: Optional[str] = None
    step: Optional[str] = None
    line_number: Optional[int] = None
    raw_line: Optional[str] = None
    extra_data: Optional[Dict] = None


class LogParser:
    """Parser pour les fichiers de logs CheckEasy"""
    
    # Patterns de détection
    STEP_PATTERNS = {
        'classification': r'(?:Classification|ÉTAPE 1|classify_room_type)',
        'injection': r'(?:Injection des critères|ÉTAPE 2|INJECTION DES CRITÈRES)',
        'image_processing': r'(?:Traitement des images|ÉTAPE 3|🖼️)',
        'openai_analysis': r'(?:Analyse OpenAI|ÉTAPE 4|OpenAI request)',
        'json_parsing': r'(?:Parsing|validation|ÉTAPE 5|json\.loads)',
        'final_summary': r'(?:Résumé final|ÉTAPE 6|Analyse combinée terminée)',
    }
    
    ROOM_EMOJI_MAP = {
        'chambre': '🛏️',
        'cuisine': '🍽️',
        'salle de bain': '🚿',
        'salon': '🛋️',
        'toilettes': '🚽',
        'entrée': '🚪',
        'couloir': '🚶',
        'balcon': '🌿',
        'terrasse': '🌳',
        'autre': '📦',
    }
    
    def __init__(self):
        self.entries: List[LogEntry] = []
        
    def parse_file(self, filepath: str, show_progress: bool = True) -> List[LogEntry]:
        """
        Parse un fichier de logs et retourne une liste d'entrées structurées
        
        Args:
            filepath: Chemin vers le fichier de logs
            show_progress: Afficher une barre de progression avec tqdm
            
        Returns:
            Liste d'objets LogEntry
        """
        self.entries = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Détecter le format (JSON ou texte)
        is_json_format = self._detect_json_format(lines)
        
        # Parser avec barre de progression
        iterator = tqdm(enumerate(lines, 1), total=len(lines), desc="📖 Parsing logs", disable=not show_progress)
        
        for line_num, line in iterator:
            line = line.strip()
            if not line:
                continue
                
            if is_json_format:
                entry = self._parse_json_line(line, line_num)
            else:
                entry = self._parse_text_line(line, line_num)
                
            if entry:
                self.entries.append(entry)
        
        return self.entries
    
    def _detect_json_format(self, lines: List[str]) -> bool:
        """Détecte si le fichier est au format JSON"""
        for line in lines[:10]:  # Vérifier les 10 premières lignes
            line = line.strip()
            if line and line.startswith('{'):
                try:
                    json.loads(line)
                    return True
                except:
                    pass
        return False
    
    def _parse_json_line(self, line: str, line_num: int) -> Optional[LogEntry]:
        """Parse une ligne au format JSON (Railway)"""
        try:
            data = json.loads(line)
            
            # Extraire les informations
            timestamp_str = data.get('timestamp', data.get('time', ''))
            timestamp = self._parse_timestamp(timestamp_str)
            
            level = data.get('level', 'INFO').upper()
            message = data.get('message', data.get('msg', ''))
            
            # Extraire piece_id et autres métadonnées
            piece_id = data.get('piece_id')
            
            # Détecter l'étape
            step = self._detect_step(message)
            
            # Extraire le nom de la pièce depuis le message
            room_name = self._extract_room_name(message)
            
            return LogEntry(
                timestamp=timestamp,
                level=level,
                message=message,
                piece_id=piece_id,
                room_name=room_name,
                step=step,
                line_number=line_num,
                raw_line=line,
                extra_data=data
            )
        except Exception as e:
            return None
    
    def _parse_text_line(self, line: str, line_num: int) -> Optional[LogEntry]:
        """Parse une ligne au format texte coloré (local)"""
        # Pattern pour le format: 2024-01-01 12:00:00 - INFO - module - message
        pattern = r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-\s*(\w+)\s*-\s*[\w\.]+\s*-\s*(.+)'
        
        # Nettoyer les codes ANSI
        clean_line = re.sub(r'\033\[[0-9;]+m', '', line)
        
        match = re.match(pattern, clean_line)
        if not match:
            return None
        
        timestamp_str, level, message = match.groups()
        timestamp = self._parse_timestamp(timestamp_str)
        
        # Détecter SUCCESS dans le message
        if message.startswith('SUCCESS:'):
            level = 'SUCCESS'
            message = message.replace('SUCCESS:', '').strip()
        
        # Extraire piece_id depuis le message
        piece_id = self._extract_piece_id(message)
        room_name = self._extract_room_name(message)
        step = self._detect_step(message)
        
        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=message,
            piece_id=piece_id,
            room_name=room_name,
            step=step,
            line_number=line_num,
            raw_line=line
        )
    
    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse un timestamp depuis différents formats"""
        if not timestamp_str:
            return datetime.now()
        
        # Essayer différents formats
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S.%fZ',
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str.split('.')[0], fmt.split('.')[0])
            except:
                continue
        
        return datetime.now()
    
    def _extract_piece_id(self, message: str) -> Optional[str]:
        """Extrait le piece_id depuis le message"""
        # Pattern: piece_id ou pièce {piece_id}
        patterns = [
            r'piece_id[:\s]+([a-zA-Z0-9_-]+)',
            r'pièce\s+([a-zA-Z0-9_-]+)',
            r'Analyse de la pièce\s+([a-zA-Z0-9_-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_room_name(self, message: str) -> Optional[str]:
        """Extrait le nom de la pièce depuis le message"""
        # Pattern: pièce {id}: {nom}
        pattern = r'pièce\s+[a-zA-Z0-9_-]+:\s+([^(]+)'
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Chercher les types de pièces connus
        for room_type in self.ROOM_EMOJI_MAP.keys():
            if room_type in message.lower():
                return room_type.capitalize()
        
        return None
    
    def _detect_step(self, message: str) -> Optional[str]:
        """Détecte l'étape du processus depuis le message"""
        for step_name, pattern in self.STEP_PATTERNS.items():
            if re.search(pattern, message, re.IGNORECASE):
                return step_name
        return None
    
    def get_room_emoji(self, room_name: Optional[str]) -> str:
        """Retourne l'emoji correspondant au type de pièce"""
        if not room_name:
            return '📦'
        
        room_lower = room_name.lower()
        for room_type, emoji in self.ROOM_EMOJI_MAP.items():
            if room_type in room_lower:
                return emoji
        
        return '📦'

