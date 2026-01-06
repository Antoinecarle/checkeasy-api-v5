# 🔍 Guide d'utilisation - Logs Viewer

## 📋 Vue d'ensemble

Le **Logs Viewer** est un système de visualisation en temps réel des logs de l'API CheckEasy. Il permet de suivre visuellement le workflow de chaque requête avec un canvas interactif.

## 🚀 Démarrage rapide

### 1. Lancer l'API
```bash
python make_request.py
```

### 2. Ouvrir l'interface de logs
Ouvrez votre navigateur à l'adresse :
```
http://localhost:8000/logs-viewer
```

### 3. Faire une requête
Utilisez n'importe quel endpoint de l'API :
- `/analyze` - Analyse simple d'une pièce
- `/analyze-complete` - Analyse complète d'un logement

## 🎯 Fonctionnalités

### Interface principale

L'interface est divisée en 2 parties :

#### 📋 Sidebar (gauche)
- Liste de toutes les requêtes actives et récentes
- Affiche l'endpoint, l'ID et l'heure de chaque requête
- Cliquez sur une requête pour voir son workflow détaillé

#### 🎨 Canvas (droite)
- Affiche le workflow visuel de la requête sélectionnée
- Chaque étape est représentée par une card colorée :
  - 🟡 **Jaune** : Étape en cours (animation pulsante)
  - 🟢 **Vert** : Étape terminée avec succès
  - 🔴 **Rouge** : Étape échouée

### Cards de workflow

Chaque card affiche :
- **Icône** : Type d'étape (🏷️ classification, 🔍 analyse, ✅ étapes, 📊 synthèse)
- **Nom** : Description de l'étape
- **Statut** : État actuel (en cours, terminé, erreur)
- **Durée** : Temps d'exécution
- **Logs** : Aperçu des 3 derniers logs

### 🔍 Logs détaillés

Cliquez sur n'importe quelle card pour ouvrir une modal avec :
- Tous les logs de l'étape
- Horodatage précis
- Niveau de log (INFO, WARNING, ERROR)
- Messages détaillés

## 📊 Types d'étapes

| Icône | Type | Description |
|-------|------|-------------|
| 🏷️ | classification | Classification automatique du type de pièce |
| 🔍 | analyze | Analyse des images avec l'IA |
| ✅ | etapes | Analyse des étapes de nettoyage |
| 📊 | synthesis | Synthèse et envoi des webhooks |

## 🔄 Connexion WebSocket

Le badge en haut à droite indique l'état de la connexion :
- 🟢 **Connecté** : Vous recevez les mises à jour en temps réel
- 🔴 **Déconnecté** : Reconnexion automatique dans 3 secondes

## 🧪 Test du système

Un script de test est fourni :
```bash
python test_logs_viewer.py
```

Ce script :
1. Attend 3 secondes
2. Envoie une requête `/analyze` de test
3. Affiche le résultat dans le terminal

Pendant ce temps, vous pouvez observer le workflow en temps réel dans l'interface !

## 🎨 Codes couleur

- **Requêtes** :
  - Bordure bleue : Requête en cours
  - Fond vert : Requête terminée avec succès
  - Fond rouge : Requête échouée

- **Étapes** :
  - Fond jaune + animation : En cours
  - Fond vert : Succès
  - Fond rouge : Erreur

## 💡 Astuces

1. **Rafraîchissement** : L'interface se met à jour automatiquement via WebSocket
2. **Historique** : Les requêtes restent visibles même après leur complétion
3. **Multi-requêtes** : Vous pouvez suivre plusieurs requêtes simultanément
4. **Logs détaillés** : Cliquez sur une card pour voir tous les logs de l'étape

## 🔧 Intégration dans le code

Pour ajouter le tracking à un nouvel endpoint :

```python
# 1. Créer un ID de requête
request_id = str(uuid.uuid4())

# 2. Démarrer le tracking
logs_manager.start_request(
    request_id=request_id,
    endpoint="/mon-endpoint",
    data={"info": "metadata"}
)

# 3. Ajouter une étape
step_id = logs_manager.add_step(
    request_id=request_id,
    step_name="Mon étape",
    step_type="analyze",  # ou "classification", "etapes", "synthesis"
    metadata={}
)

# 4. Ajouter des logs
logs_manager.add_log(
    request_id=request_id,
    level="INFO",  # ou "WARNING", "ERROR"
    message="Mon message"
)

# 5. Terminer l'étape
logs_manager.complete_step(
    request_id=request_id,
    step_id=step_id,
    status="success",  # ou "error"
    result={}
)

# 6. Terminer la requête
logs_manager.complete_request(
    request_id=request_id,
    status="success"  # ou "error"
)
```

## 📁 Fichiers du système

- `logs_viewer/logs_manager.py` : Gestionnaire de logs avec WebSocket
- `templates/logs_viewer.html` : Interface web
- `test_logs_viewer.py` : Script de test

