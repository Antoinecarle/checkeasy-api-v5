"""
Générateur de rapports HTML interactifs à partir des logs analysés
"""

from typing import Dict, List
from pathlib import Path
from datetime import timedelta
from .log_analyzer import LogAnalyzer, RoomAnalysis, GlobalSummary
from .log_parser import LogEntry
import html


class ReportGenerator:
    """Génère des rapports HTML interactifs"""
    
    def __init__(self, analyzer: LogAnalyzer):
        self.analyzer = analyzer
        
    def generate_html_report(self, output_path: str, log_file_path: str = None):
        """
        Génère un rapport HTML complet
        
        Args:
            output_path: Chemin du fichier HTML de sortie
            log_file_path: Chemin du fichier de logs brut (pour les liens)
        """
        html_content = self._build_html(log_file_path)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"✅ Rapport HTML généré: {output_path}")
    
    def _build_html(self, log_file_path: str = None) -> str:
        """Construit le contenu HTML complet"""
        summary = self.analyzer.global_summary
        rooms = self.analyzer.rooms
        
        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CheckEasy - Rapport d'Analyse des Logs</title>
    <style>
        {self._get_css()}
    </style>
</head>
<body>
    <div class="container">
        {self._build_header(summary)}
        {self._build_global_summary(summary)}
        {self._build_rooms_section(rooms, log_file_path)}
        {self._build_errors_section(summary)}
    </div>
    <script>
        {self._get_javascript()}
    </script>
</body>
</html>"""
        return html
    
    def _build_header(self, summary: GlobalSummary) -> str:
        """Construit l'en-tête du rapport"""
        return f"""
        <header>
            <h1>📦 CheckEasy - Rapport d'Analyse des Logs</h1>
            <p class="subtitle">Type de parcours : <strong>{summary.parcours_type}</strong></p>
            <p class="timestamp">Généré le {summary.end_time.strftime('%d/%m/%Y à %H:%M:%S') if summary.end_time else 'N/A'}</p>
        </header>
        """
    
    def _build_global_summary(self, summary: GlobalSummary) -> str:
        """Construit le résumé global"""
        duration_str = self._format_duration(summary.total_duration) if summary.total_duration else "N/A"
        
        # Calculer le statut global
        status_class = "success" if summary.total_errors == 0 else "error" if summary.total_errors > 5 else "warning"
        status_icon = "✅" if summary.total_errors == 0 else "❌" if summary.total_errors > 5 else "⚠️"
        
        return f"""
        <section class="summary-section">
            <h2>📊 Résumé Global</h2>
            <div class="summary-grid">
                <div class="summary-card {status_class}">
                    <div class="card-icon">{status_icon}</div>
                    <div class="card-content">
                        <div class="card-label">Statut</div>
                        <div class="card-value">{status_class.upper()}</div>
                    </div>
                </div>
                
                <div class="summary-card">
                    <div class="card-icon">🏠</div>
                    <div class="card-content">
                        <div class="card-label">Pièces analysées</div>
                        <div class="card-value">{summary.total_rooms}</div>
                    </div>
                </div>
                
                <div class="summary-card">
                    <div class="card-icon">⚠️</div>
                    <div class="card-content">
                        <div class="card-label">Anomalies détectées</div>
                        <div class="card-value">{summary.total_anomalies}</div>
                    </div>
                </div>
                
                <div class="summary-card">
                    <div class="card-icon">❌</div>
                    <div class="card-content">
                        <div class="card-label">Erreurs</div>
                        <div class="card-value">{summary.total_errors}</div>
                    </div>
                </div>
                
                <div class="summary-card">
                    <div class="card-icon">📊</div>
                    <div class="card-content">
                        <div class="card-label">Score moyen</div>
                        <div class="card-value">{summary.average_score:.1f}/10</div>
                    </div>
                </div>
                
                <div class="summary-card">
                    <div class="card-icon">⏱️</div>
                    <div class="card-content">
                        <div class="card-label">Durée totale</div>
                        <div class="card-value">{duration_str}</div>
                    </div>
                </div>
            </div>
            
            <div class="steps-overview">
                <h3>Étapes principales</h3>
                <div class="steps-list">
                    {self._build_steps_overview()}
                </div>
            </div>
        </section>
        """
    
    def _build_steps_overview(self) -> str:
        """Construit l'aperçu des étapes"""
        steps_html = ""
        for i, (step_key, step_name) in enumerate(self.analyzer.STEP_NAMES.items(), 1):
            # Vérifier si au moins une pièce a complété cette étape
            completed = any(
                room.steps_completed.get(step_key, False) 
                for room in self.analyzer.rooms.values()
            )
            icon = "✅" if completed else "❌"
            steps_html += f'<div class="step-item"><span class="step-number">{i}️⃣</span> {step_name} {icon}</div>'
        
        return steps_html
    
    def _build_rooms_section(self, rooms: Dict[str, RoomAnalysis], log_file_path: str = None) -> str:
        """Construit la section des pièces"""
        rooms_html = '<section class="rooms-section"><h2>🏠 Analyse par Pièce</h2>'
        
        for piece_id, room in sorted(rooms.items(), key=lambda x: x[1].start_time or x[0]):
            rooms_html += self._build_room_card(room, log_file_path)
        
        rooms_html += '</section>'
        return rooms_html
    
    def _build_room_card(self, room: RoomAnalysis, log_file_path: str = None) -> str:
        """Construit la carte d'une pièce"""
        progress = self.analyzer.get_step_progress(room)
        score_class = "high" if (room.score or 0) >= 8 else "medium" if (room.score or 0) >= 5 else "low"
        
        # Construire la liste des étapes
        steps_html = ""
        for step_key in self.analyzer.STEP_ORDER:
            step_name = self.analyzer.STEP_NAMES[step_key]
            completed = room.steps_completed.get(step_key, False)
            icon = self.analyzer.get_step_status_emoji(completed)
            steps_html += f'<li class="step-item {"completed" if completed else ""}"><span class="step-icon">{icon}</span> {step_name}</li>'
        
        # Construire la liste des erreurs
        errors_html = ""
        if room.errors:
            errors_html = '<div class="errors-list"><h4>⚠️ Erreurs détectées:</h4><ul>'
            for error in room.errors[:5]:  # Limiter à 5 erreurs
                error_msg = html.escape(error.message[:200])
                link = f'<a href="file:///{log_file_path}#L{error.line_number}" class="log-link" target="_blank">Ligne {error.line_number}</a>' if log_file_path and error.line_number else ''
                errors_html += f'<li class="error-item"><span class="error-msg">{error_msg}</span> {link}</li>'
            errors_html += '</ul></div>'
        
        return f"""
        <div class="room-card">
            <div class="room-header">
                <h3>{room.room_emoji} {room.room_name} <span class="room-id">(ID: {room.piece_id})</span></h3>
                <div class="room-score score-{score_class}">{room.score or 'N/A'}/10</div>
            </div>
            
            <div class="room-progress">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {progress}%"></div>
                </div>
                <span class="progress-text">{progress:.0f}% complété</span>
            </div>
            
            <div class="room-stats">
                <span class="stat">⚠️ {room.anomalies_count} anomalies</span>
                <span class="stat">❌ {len(room.errors)} erreurs</span>
                <span class="stat">⚡ {len(room.warnings)} warnings</span>
                {f'<span class="stat">🎯 {room.confidence}% confiance</span>' if room.confidence else ''}
            </div>
            
            <details class="room-details">
                <summary>📋 Détails des étapes</summary>
                <ul class="steps-list">
                    {steps_html}
                </ul>
            </details>
            
            {errors_html}
        </div>
        """
    
    def _build_errors_section(self, summary: GlobalSummary) -> str:
        """Construit la section des erreurs critiques"""
        if not summary.critical_errors:
            return ""
        
        errors_html = '<section class="critical-errors"><h2>🚨 Erreurs Critiques</h2><ul>'
        
        for error in summary.critical_errors[:10]:  # Limiter à 10
            error_msg = html.escape(error.message[:300])
            errors_html += f'<li class="critical-error-item"><strong>{error.timestamp.strftime("%H:%M:%S")}</strong> - {error_msg}</li>'
        
        errors_html += '</ul></section>'
        return errors_html
    
    def _format_duration(self, duration: timedelta) -> str:
        """Formate une durée en format lisible"""
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def _get_css(self) -> str:
        """Retourne le CSS du rapport"""
        return """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        
        header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .subtitle { font-size: 1.2em; opacity: 0.9; }
        .timestamp { font-size: 0.9em; opacity: 0.7; margin-top: 10px; }
        
        section { padding: 30px 40px; }
        
        h2 { color: #667eea; margin-bottom: 20px; font-size: 1.8em; }
        h3 { color: #333; font-size: 1.3em; }
        
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .summary-card {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            transition: transform 0.2s;
        }
        
        .summary-card:hover { transform: translateY(-5px); box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        .summary-card.success { background: #d4edda; border-left: 4px solid #28a745; }
        .summary-card.warning { background: #fff3cd; border-left: 4px solid #ffc107; }
        .summary-card.error { background: #f8d7da; border-left: 4px solid #dc3545; }
        
        .card-icon { font-size: 2.5em; }
        .card-label { font-size: 0.85em; color: #666; text-transform: uppercase; }
        .card-value { font-size: 1.8em; font-weight: bold; color: #333; }
        
        .steps-overview { margin-top: 30px; }
        .steps-list { display: flex; flex-direction: column; gap: 10px; }
        .step-item { padding: 12px; background: #f8f9fa; border-radius: 8px; display: flex; align-items: center; gap: 10px; }
        .step-number { font-size: 1.2em; }
        
        .room-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            transition: all 0.3s;
        }
        
        .room-card:hover { border-color: #667eea; box-shadow: 0 5px 20px rgba(102, 126, 234, 0.2); }
        
        .room-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        
        .room-id { font-size: 0.8em; color: #999; font-weight: normal; }
        
        .room-score {
            font-size: 2em;
            font-weight: bold;
            padding: 10px 20px;
            border-radius: 8px;
        }
        
        .score-high { background: #d4edda; color: #28a745; }
        .score-medium { background: #fff3cd; color: #ffc107; }
        .score-low { background: #f8d7da; color: #dc3545; }
        
        .room-progress {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 15px;
        }
        
        .progress-bar {
            flex: 1;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s;
        }
        
        .progress-text { font-weight: bold; color: #667eea; }
        
        .room-stats {
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }
        
        .stat {
            padding: 8px 15px;
            background: #f8f9fa;
            border-radius: 6px;
            font-size: 0.9em;
        }
        
        details { margin-top: 15px; }
        summary {
            cursor: pointer;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 6px;
            font-weight: bold;
            user-select: none;
        }
        
        summary:hover { background: #e9ecef; }
        
        .steps-list { list-style: none; padding: 15px 0; }
        .steps-list .step-item { padding: 8px 15px; margin: 5px 0; background: #f8f9fa; border-radius: 6px; }
        .steps-list .step-item.completed { background: #d4edda; }
        .step-icon { margin-right: 10px; }
        
        .errors-list { margin-top: 15px; padding: 15px; background: #fff3cd; border-radius: 8px; border-left: 4px solid #ffc107; }
        .errors-list h4 { margin-bottom: 10px; color: #856404; }
        .errors-list ul { list-style: none; }
        .error-item { padding: 8px 0; border-bottom: 1px solid #ffeaa7; }
        .error-item:last-child { border-bottom: none; }
        .error-msg { color: #856404; }
        .log-link { color: #667eea; text-decoration: none; margin-left: 10px; font-size: 0.85em; }
        .log-link:hover { text-decoration: underline; }
        
        .critical-errors { background: #f8d7da; }
        .critical-errors h2 { color: #dc3545; }
        .critical-error-item { padding: 15px; margin: 10px 0; background: white; border-radius: 8px; border-left: 4px solid #dc3545; }
        """
    
    def _get_javascript(self) -> str:
        """Retourne le JavaScript du rapport"""
        return """
        // Animation au chargement
        document.addEventListener('DOMContentLoaded', function() {
            const cards = document.querySelectorAll('.room-card, .summary-card');
            cards.forEach((card, index) => {
                setTimeout(() => {
                    card.style.opacity = '0';
                    card.style.transform = 'translateY(20px)';
                    card.style.transition = 'all 0.5s ease';
                    setTimeout(() => {
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    }, 50);
                }, index * 50);
            });
        });
        """

