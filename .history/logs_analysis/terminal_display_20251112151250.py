"""
Système d'affichage amélioré des logs dans le terminal
Affiche les logs de manière structurée, colorée et avec des barres de progression
SANS créer de fichiers - juste pour améliorer la lisibilité du terminal
"""

import logging
from typing import Dict, Optional
from datetime import datetime
from tqdm import tqdm
from colorama import Fore, Back, Style, init

# Initialiser colorama pour Windows
init(autoreset=True)


class PrettyTerminalHandler(logging.Handler):
    """
    Handler qui affiche les logs de manière structurée et colorée dans le terminal
    """
    
    def __init__(self):
        super().__init__()
        self.current_piece = None
        self.current_step = None
        self.piece_stats = {}
        self.step_emojis = {
            'classification': '🔍',
            'injection': '💉',
            'image_processing': '🖼️',
            'openai_analysis': '🤖',
            'json_parsing': '📋',
            'final_summary': '✅'
        }
        self.room_emojis = {
            'chambre': '🛏️',
            'cuisine': '🍽️',
            'salle de bain': '🚿',
            'salon': '🛋️',
            'toilettes': '🚽',
            'entrée': '🚪',
            'couloir': '🚶',
            'balcon': '🌿',
            'terrasse': '🌳',
        }
        
    def emit(self, record: logging.LogRecord):
        """Affiche le log de manière formatée"""
        try:
            msg = record.getMessage()
            level = record.levelname

            # Filtrer d'abord le bruit avant tout traitement
            if not self._should_display(msg):
                return

            # Détecter le contexte
            piece_id = getattr(record, 'piece_id', None)

            # Détecter le début d'analyse d'une pièce
            if '🔍 Analyse de la pièce' in msg or 'Analyse de la pièce' in msg:
                self._print_room_header(msg, piece_id)
                return

            # Détecter les étapes
            if 'ÉTAPE' in msg:
                self._print_step(msg, level)
                return

            # Détecter les résultats finaux
            if '✅ Analyse terminée' in msg and 'Score' in msg:
                self._print_result(msg, level)
                return

            # Détecter les erreurs/warnings
            if level == 'ERROR':
                self._print_error(msg)
                return
            elif level == 'WARNING':
                self._print_warning(msg)
                return

            # Détecter les requêtes OpenAI
            if 'OpenAI request' in msg:
                self._print_openai_request(msg)
                return

            # Détecter les injections de critères
            if 'INJECTION DES CRITÈRES' in msg or 'Éléments critiques' in msg:
                self._print_injection(msg)
                return

            # Détecter les messages de succès généraux
            if '🚀 ANALYSE COMPLÈTE démarrée' in msg:
                print(f"\n{Fore.GREEN}{Style.BRIGHT}   {msg}{Style.RESET_ALL}\n")
                return

            if '🎉 ANALYSE COMPLÈTE terminée' in msg:
                print(f"\n{Fore.GREEN}{Style.BRIGHT}   ✅ {msg}{Style.RESET_ALL}")
                return

            # Ignorer les autres messages (trop verbeux)
            # On affiche uniquement ce qui est structuré ci-dessus

        except Exception as e:
            # Fallback sur affichage standard en cas d'erreur
            pass
    
    def _print_room_header(self, msg: str, piece_id: Optional[str]):
        """Affiche l'en-tête d'une pièce"""
        # Extraire le nom de la pièce
        import re
        match = re.search(r'pièce\s+([a-zA-Z0-9_-]+):\s+(.+)', msg, re.IGNORECASE)
        if match:
            piece_id = match.group(1)
            room_name = match.group(2).strip()
            
            # Trouver l'emoji
            emoji = '📦'
            for room_type, room_emoji in self.room_emojis.items():
                if room_type in room_name.lower():
                    emoji = room_emoji
                    break
            
            print("\n" + "="*70)
            print(f"{Fore.CYAN}{Style.BRIGHT}{emoji} {room_name.upper()} {Fore.YELLOW}(ID: {piece_id}){Style.RESET_ALL}")
            print("="*70)
            
            self.current_piece = piece_id
            self.piece_stats[piece_id] = {
                'name': room_name,
                'start_time': datetime.now(),
                'steps': []
            }
    
    def _print_step(self, msg: str, level: str):
        """Affiche une étape"""
        import re
        match = re.search(r'ÉTAPE\s+(\d+)', msg)
        if match:
            step_num = match.group(1)
            
            # Extraire le nom de l'étape
            step_name = msg.split('-', 1)[1].strip() if '-' in msg else msg
            
            # Emoji de l'étape
            emoji = '▶️'
            if 'Classification' in msg:
                emoji = '🔍'
            elif 'Injection' in msg:
                emoji = '💉'
            elif 'Traitement' in msg or 'images' in msg:
                emoji = '🖼️'
            elif 'OpenAI' in msg or 'Analyse' in msg:
                emoji = '🤖'
            elif 'Parsing' in msg or 'validation' in msg:
                emoji = '📋'
            elif 'Résumé' in msg or 'final' in msg:
                emoji = '✅'
            
            print(f"\n{Fore.BLUE}{Style.BRIGHT}├─ {emoji} ÉTAPE {step_num}: {step_name}{Style.RESET_ALL}")
            
            if self.current_piece:
                self.piece_stats[self.current_piece]['steps'].append(step_num)
    
    def _print_result(self, msg: str, level: str):
        """Affiche un résultat"""
        import re
        
        # Extraire le score
        score_match = re.search(r'Score\s+(\d+)/10', msg)
        anomalies_match = re.search(r'(\d+)\s+problèmes?', msg)
        
        if score_match:
            score = int(score_match.group(1))
            anomalies = int(anomalies_match.group(1)) if anomalies_match else 0
            
            # Couleur selon le score
            if score >= 8:
                color = Fore.GREEN
                icon = '🌟'
            elif score >= 5:
                color = Fore.YELLOW
                icon = '⚠️'
            else:
                color = Fore.RED
                icon = '❌'
            
            print(f"\n{color}{Style.BRIGHT}└─ {icon} RÉSULTAT: Score {score}/10 — {anomalies} anomalies détectées{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}└─ ✅ {msg}{Style.RESET_ALL}")
    
    def _print_error(self, msg: str):
        """Affiche une erreur"""
        print(f"{Fore.RED}{Style.BRIGHT}   ❌ ERREUR: {msg}{Style.RESET_ALL}")
    
    def _print_warning(self, msg: str):
        """Affiche un warning"""
        print(f"{Fore.YELLOW}   ⚠️  WARNING: {msg}{Style.RESET_ALL}")
    
    def _print_success(self, msg: str):
        """Affiche un succès"""
        msg_clean = msg.replace('SUCCESS:', '').replace('🎉', '').strip()
        print(f"{Fore.GREEN}{Style.BRIGHT}   ✅ {msg_clean}{Style.RESET_ALL}")
    
    def _print_openai_request(self, msg: str):
        """Affiche une requête OpenAI"""
        import re
        model_match = re.search(r'Model:\s+([^,]+)', msg)
        tokens_match = re.search(r'Tokens:\s+(\d+)', msg)
        
        model = model_match.group(1) if model_match else 'N/A'
        tokens = tokens_match.group(1) if tokens_match else 'N/A'
        
        print(f"{Fore.MAGENTA}   🤖 OpenAI: {model} ({tokens} tokens){Style.RESET_ALL}")
    
    def _print_injection(self, msg: str):
        """Affiche l'injection de critères"""
        if 'INJECTION DES CRITÈRES' in msg:
            print(f"{Fore.CYAN}   💉 Injection des critères:{Style.RESET_ALL}")
        elif 'Éléments critiques' in msg:
            import re
            match = re.search(r'\((\d+)\)', msg)
            count = match.group(1) if match else '?'
            print(f"{Fore.CYAN}      🔍 {count} éléments critiques{Style.RESET_ALL}")
        elif 'Points ignorables' in msg:
            import re
            match = re.search(r'\((\d+)\)', msg)
            count = match.group(1) if match else '?'
            print(f"{Fore.CYAN}      ➖ {count} points ignorables{Style.RESET_ALL}")
        elif 'Défauts fréquents' in msg:
            import re
            match = re.search(r'\((\d+)\)', msg)
            count = match.group(1) if match else '?'
            print(f"{Fore.CYAN}      ⚠️  {count} défauts fréquents{Style.RESET_ALL}")
    
    def _print_normal(self, msg: str, level: str):
        """Affiche un message normal"""
        # Simplifier le message
        msg_short = msg[:100] + '...' if len(msg) > 100 else msg
        print(f"{Fore.WHITE}   {msg_short}{Style.RESET_ALL}")
    
    def _should_display(self, msg: str) -> bool:
        """Détermine si un message doit être affiché (filtrer le bruit)"""
        # Filtrer les messages trop verbeux ou redondants
        noise_keywords = [
            'DEBUG',
            'Logging configuré',
            'Environment detected',
            'Templates loaded',
            'Configuration',
            'Initialisation',
            'Starting',
            'Startup',
            'Application startup',
            'Uvicorn running',
            'Started server',
        ]

        # Filtrer aussi les messages qui sont déjà affichés autrement
        already_handled = [
            'Classification terminée',
            'Traitement terminé',
            'Analyse combinée terminée',
            'ANALYSE COMPLÈTE',
        ]

        for keyword in noise_keywords + already_handled:
            if keyword in msg:
                return False

        return True


def setup_pretty_terminal_logging():
    """
    Configure l'affichage amélioré des logs dans le terminal
    À appeler au début de make_request.py

    REMPLACE tous les handlers existants pour éviter les doublons
    """
    # Créer le handler
    handler = PrettyTerminalHandler()
    handler.setLevel(logging.INFO)

    # SUPPRIMER tous les handlers existants du logger racine
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Ajouter uniquement notre handler
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Supprimer aussi les handlers des loggers spécifiques
    for logger_name in ['uvicorn', 'fastapi', 'uvicorn.access', 'uvicorn.error']:
        specific_logger = logging.getLogger(logger_name)
        specific_logger.handlers.clear()
        specific_logger.setLevel(logging.WARNING)  # Réduire le bruit

    print(f"{Fore.GREEN}{Style.BRIGHT}")
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     CheckEasy - Affichage Amélioré des Logs Activé          ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print(f"{Style.RESET_ALL}\n")

    return handler


# Fonctions helper pour afficher des barres de progression
def create_progress_bar(total: int, desc: str = "Progression", unit: str = "item"):
    """Crée une barre de progression tqdm"""
    return tqdm(
        total=total,
        desc=f"{Fore.CYAN}{desc}{Style.RESET_ALL}",
        unit=unit,
        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]',
        colour='cyan'
    )


def print_summary_box(title: str, data: Dict[str, any]):
    """Affiche un résumé dans une boîte"""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}╔{'═'*68}╗{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}║ {title:^66} ║{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}╠{'═'*68}╣{Style.RESET_ALL}")
    
    for key, value in data.items():
        print(f"{Fore.CYAN}║{Style.RESET_ALL} {key:30} {Fore.WHITE}{Style.BRIGHT}{value:>35}{Style.RESET_ALL} {Fore.CYAN}║{Style.RESET_ALL}")
    
    print(f"{Fore.CYAN}{Style.BRIGHT}╚{'═'*68}╝{Style.RESET_ALL}\n")

