"""
Système de capture et d'analyse des logs du terminal en temps réel
S'intègre avec le système de logging existant pour capturer stdout/stderr
"""

import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


class TerminalLogCapture(logging.Handler):
    """
    Handler personnalisé qui capture tous les logs et les sauvegarde
    dans un fichier structuré pour analyse ultérieure
    """
    
    def __init__(self, log_dir: str = "logs_output"):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Créer un fichier de log avec timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"checkeasy_analysis_{timestamp}.log"
        self.json_file = self.log_dir / f"checkeasy_analysis_{timestamp}.json"
        
        # Ouvrir les fichiers
        self.file_handler = open(self.log_file, 'w', encoding='utf-8')
        self.json_handler = open(self.json_file, 'w', encoding='utf-8')
        
        # Compteurs pour statistiques en temps réel
        self.stats = {
            'total_logs': 0,
            'errors': 0,
            'warnings': 0,
            'info': 0,
            'pieces_analyzed': set(),
            'start_time': datetime.now()
        }
        
        print(f"📝 Capture des logs activée:")
        print(f"   📄 Fichier texte: {self.log_file}")
        print(f"   📊 Fichier JSON: {self.json_file}")
    
    def emit(self, record: logging.LogRecord):
        """Capture chaque log émis"""
        try:
            # Formater le message
            msg = self.format(record)
            
            # Écrire dans le fichier texte
            self.file_handler.write(msg + '\n')
            self.file_handler.flush()
            
            # Créer une entrée JSON structurée
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': record.module,
                'function': record.funcName,
                'line': record.lineno
            }
            
            # Ajouter les données extra si présentes
            if hasattr(record, 'piece_id'):
                log_entry['piece_id'] = record.piece_id
                self.stats['pieces_analyzed'].add(record.piece_id)
            
            if hasattr(record, 'endpoint'):
                log_entry['endpoint'] = record.endpoint
            
            if hasattr(record, 'operation'):
                log_entry['operation'] = record.operation
            
            # Écrire dans le fichier JSON (une ligne par entrée)
            self.json_handler.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            self.json_handler.flush()
            
            # Mettre à jour les statistiques
            self.stats['total_logs'] += 1
            if record.levelname == 'ERROR':
                self.stats['errors'] += 1
            elif record.levelname == 'WARNING':
                self.stats['warnings'] += 1
            elif record.levelname == 'INFO':
                self.stats['info'] += 1
                
        except Exception as e:
            print(f"❌ Erreur dans TerminalLogCapture: {e}")
    
    def close(self):
        """Ferme les fichiers et affiche les statistiques"""
        super().close()
        
        if hasattr(self, 'file_handler'):
            self.file_handler.close()
        
        if hasattr(self, 'json_handler'):
            self.json_handler.close()
        
        # Afficher les statistiques finales
        duration = datetime.now() - self.stats['start_time']
        print("\n" + "="*60)
        print("📊 STATISTIQUES DE CAPTURE DES LOGS")
        print("="*60)
        print(f"📝 Total de logs capturés: {self.stats['total_logs']}")
        print(f"❌ Erreurs: {self.stats['errors']}")
        print(f"⚠️  Warnings: {self.stats['warnings']}")
        print(f"ℹ️  Info: {self.stats['info']}")
        print(f"🏠 Pièces analysées: {len(self.stats['pieces_analyzed'])}")
        print(f"⏱️  Durée: {duration}")
        print(f"\n📄 Logs sauvegardés dans:")
        print(f"   {self.log_file}")
        print(f"   {self.json_file}")
        print("="*60)
    
    def get_stats(self):
        """Retourne les statistiques actuelles"""
        return {
            **self.stats,
            'pieces_analyzed': len(self.stats['pieces_analyzed']),
            'duration': str(datetime.now() - self.stats['start_time'])
        }


class LiveLogMonitor:
    """
    Moniteur de logs en temps réel avec affichage de progression
    Utilise tqdm pour afficher des barres de progression
    """
    
    def __init__(self):
        self.current_piece = None
        self.current_step = None
        self.pieces_progress = {}
        
    def update_piece(self, piece_id: str, piece_name: str):
        """Met à jour la pièce en cours d'analyse"""
        self.current_piece = piece_id
        if piece_id not in self.pieces_progress:
            self.pieces_progress[piece_id] = {
                'name': piece_name,
                'steps': {},
                'start_time': datetime.now()
            }
    
    def update_step(self, step_name: str, progress: int = 0):
        """Met à jour l'étape en cours"""
        self.current_step = step_name
        if self.current_piece:
            self.pieces_progress[self.current_piece]['steps'][step_name] = progress
    
    def get_summary(self):
        """Retourne un résumé de la progression"""
        return {
            'total_pieces': len(self.pieces_progress),
            'current_piece': self.current_piece,
            'current_step': self.current_step,
            'pieces': self.pieces_progress
        }


# Instance globale du moniteur
_live_monitor = LiveLogMonitor()
_log_capture = None


def setup_terminal_log_capture(log_dir: str = "logs_output"):
    """
    Configure la capture des logs du terminal
    À appeler au démarrage de l'application
    
    Args:
        log_dir: Répertoire où sauvegarder les logs
    """
    global _log_capture
    
    # Créer le handler de capture
    _log_capture = TerminalLogCapture(log_dir)
    
    # Définir le format
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)-8s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    _log_capture.setFormatter(formatter)
    
    # Ajouter au logger racine
    root_logger = logging.getLogger()
    root_logger.addHandler(_log_capture)
    
    return _log_capture


def get_log_capture():
    """Retourne l'instance de capture de logs"""
    return _log_capture


def get_live_monitor():
    """Retourne l'instance du moniteur en temps réel"""
    return _live_monitor


def close_log_capture():
    """Ferme la capture de logs et affiche les statistiques"""
    global _log_capture
    if _log_capture:
        _log_capture.close()
        _log_capture = None

