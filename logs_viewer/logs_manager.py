"""
Gestionnaire de logs en temps réel pour CheckEasy API V5
Collecte et diffuse les logs via WebSocket
"""

import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import uuid

class LogsManager:
    """Gestionnaire centralisé des logs pour visualisation en temps réel"""

    def __init__(self):
        self.active_requests: Dict[str, Dict] = {}  # request_id -> request_data
        self.completed_requests: Dict[str, Dict] = {}  # Requêtes complétées (conservées 1 heure)
        self.websocket_clients: List = []  # Liste des clients WebSocket connectés
        self.logger = logging.getLogger(__name__)

    def start_request(self, request_id: str, endpoint: str, data: dict):
        """Démarre le tracking d'une nouvelle requête"""
        self.active_requests[request_id] = {
            "request_id": request_id,
            "endpoint": endpoint,
            "start_time": datetime.now().isoformat(),
            "status": "in_progress",
            "steps": [],
            "current_step": None,
            "logs": [],
            "metadata": data
        }

        self.logger.info(f"✅ Requête démarrée: {request_id} ({endpoint})")

        # Notifier les clients WebSocket
        asyncio.create_task(self._broadcast({
            "type": "request_started",
            "data": self.active_requests[request_id]
        }))

    def add_step(self, request_id: str, step_name: str, step_type: str, metadata: dict = None):
        """Ajoute une étape au workflow de la requête"""
        if request_id not in self.active_requests:
            return

        step = {
            "step_id": str(uuid.uuid4()),
            "name": step_name,
            "type": step_type,  # classification, analyze, etapes, synthesis
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "logs": [],
            "metadata": metadata or {}
        }

        self.active_requests[request_id]["steps"].append(step)
        self.active_requests[request_id]["current_step"] = step["step_id"]

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "step_started",
            "request_id": request_id,
            "data": step
        }))

        return step["step_id"]

    def add_log(self, request_id: str, level: str, message: str, metadata: dict = None):
        """Ajoute un log à la requête en cours"""
        if request_id not in self.active_requests:
            return

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "metadata": metadata or {}
        }

        # Ajouter au log global de la requête
        self.active_requests[request_id]["logs"].append(log_entry)

        # Ajouter au log de l'étape en cours si elle existe
        current_step_id = self.active_requests[request_id].get("current_step")
        if current_step_id:
            for step in self.active_requests[request_id]["steps"]:
                if step["step_id"] == current_step_id:
                    step["logs"].append(log_entry)
                    break

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "log_added",
            "request_id": request_id,
            "data": log_entry
        }))

    def add_prompt_log(self, request_id: str, prompt_type: str, prompt_content: str, model: str = None, metadata: dict = None):
        """Ajoute un log de prompt (système ou utilisateur)"""
        if request_id not in self.active_requests:
            return

        # Limiter la taille du prompt pour l'affichage (premiers 500 caractères)
        prompt_preview = prompt_content[:500] + "..." if len(prompt_content) > 500 else prompt_content

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": "PROMPT",
            "message": f"📝 {prompt_type} Prompt ({model or 'N/A'}): {len(prompt_content)} caractères",
            "metadata": {
                "prompt_type": prompt_type,
                "prompt_preview": prompt_preview,
                "prompt_length": len(prompt_content),
                "model": model,
                **(metadata or {})
            }
        }

        # Ajouter au log global de la requête
        self.active_requests[request_id]["logs"].append(log_entry)

        # Ajouter au log de l'étape en cours si elle existe
        current_step_id = self.active_requests[request_id].get("current_step")
        if current_step_id:
            for step in self.active_requests[request_id]["steps"]:
                if step["step_id"] == current_step_id:
                    step["logs"].append(log_entry)
                    break

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "log_added",
            "request_id": request_id,
            "data": log_entry
        }))

    def add_response_log(self, request_id: str, response_type: str, response_content: str, model: str = None, tokens_used: dict = None, metadata: dict = None):
        """Ajoute un log de réponse de l'IA"""
        if request_id not in self.active_requests:
            return

        # Limiter la taille de la réponse pour l'affichage (premiers 500 caractères)
        response_preview = response_content[:500] + "..." if len(response_content) > 500 else response_content

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": "RESPONSE",
            "message": f"🤖 {response_type} Response ({model or 'N/A'}): {len(response_content)} caractères",
            "metadata": {
                "response_type": response_type,
                "response_preview": response_preview,
                "response_length": len(response_content),
                "model": model,
                "tokens_used": tokens_used or {},
                **(metadata or {})
            }
        }

        # Ajouter au log global de la requête
        self.active_requests[request_id]["logs"].append(log_entry)

        # Ajouter au log de l'étape en cours si elle existe
        current_step_id = self.active_requests[request_id].get("current_step")
        if current_step_id:
            for step in self.active_requests[request_id]["steps"]:
                if step["step_id"] == current_step_id:
                    step["logs"].append(log_entry)
                    break

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "log_added",
            "request_id": request_id,
            "data": log_entry
        }))

    def complete_step(self, request_id: str, step_id: str, status: str = "success", result: dict = None):
        """Marque une étape comme terminée"""
        if request_id not in self.active_requests:
            return

        for step in self.active_requests[request_id]["steps"]:
            if step["step_id"] == step_id:
                step["status"] = status
                step["end_time"] = datetime.now().isoformat()
                if result:
                    step["result"] = result
                break

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "step_completed",
            "request_id": request_id,
            "step_id": step_id,
            "status": status
        }))

    def complete_request(self, request_id: str, status: str = "success", result: dict = None):
        """Marque une requête comme terminée"""
        if request_id not in self.active_requests:
            self.logger.warning(f"⚠️ Tentative de compléter une requête inexistante: {request_id}")
            return

        self.active_requests[request_id]["status"] = status
        self.active_requests[request_id]["end_time"] = datetime.now().isoformat()
        if result:
            self.active_requests[request_id]["result"] = result

        # Conserver la requête complétée dans completed_requests
        self.completed_requests[request_id] = self.active_requests[request_id].copy()

        self.logger.info(f"✅ Requête complétée: {request_id} ({status}) - {len(self.active_requests[request_id]['logs'])} logs")

        # Garder aussi dans active_requests pour le polling (ne pas supprimer)
        # Les requêtes seront conservées en mémoire

        # Notifier les clients
        asyncio.create_task(self._broadcast({
            "type": "request_completed",
            "request_id": request_id,
            "status": status,
            "data": self.active_requests[request_id]
        }))

    async def register_client(self, websocket):
        """Enregistre un nouveau client WebSocket"""
        self.websocket_clients.append(websocket)
        self.logger.info(f"✅ Client WebSocket connecté. Total: {len(self.websocket_clients)}")

        # Envoyer l'état actuel des requêtes au nouveau client
        await websocket.send_json({
            "type": "initial_state",
            "data": list(self.active_requests.values())
        })

    async def unregister_client(self, websocket):
        """Désenregistre un client WebSocket"""
        if websocket in self.websocket_clients:
            self.websocket_clients.remove(websocket)
            self.logger.info(f"❌ Client WebSocket déconnecté. Total: {len(self.websocket_clients)}")

    def get_all_requests(self):
        """Retourne toutes les requêtes (actives + complétées)"""
        # Nettoyer les requêtes complétées trop anciennes (> 1 heure)
        self._cleanup_old_requests()

        all_requests = {}
        all_requests.update(self.active_requests)
        all_requests.update(self.completed_requests)
        return all_requests

    def _cleanup_old_requests(self):
        """Supprime les requêtes complétées de plus d'1 heure"""
        now = datetime.now()
        to_delete = []

        for request_id, request_data in self.completed_requests.items():
            if 'end_time' in request_data:
                end_time = datetime.fromisoformat(request_data['end_time'])
                if now - end_time > timedelta(hours=1):
                    to_delete.append(request_id)

        for request_id in to_delete:
            del self.completed_requests[request_id]
            self.logger.info(f"🗑️ Requête complétée supprimée: {request_id}")

    async def _broadcast(self, message: dict):
        """Diffuse un message à tous les clients WebSocket connectés"""
        if not self.websocket_clients:
            return

        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(message)
            except Exception as e:
                self.logger.error(f"Erreur envoi WebSocket: {e}")
                disconnected.append(client)

        # Nettoyer les clients déconnectés
        for client in disconnected:
            await self.unregister_client(client)

# Instance globale
logs_manager = LogsManager()
