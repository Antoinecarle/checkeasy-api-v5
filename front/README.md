# 🤖 CheckEasy - Gestionnaire de Prompts IA

Interface web moderne pour gérer tous les prompts utilisés par l'API CheckEasy V5.

## 🚀 Fonctionnalités

### ✨ **Interface Intuitive**
- 📊 **Vue d'ensemble** : Statistiques et aperçu de tous les prompts
- ✏️ **Éditeur avancé** : Modification en temps réel avec syntax highlighting  
- 👀 **Prévisualisation** : Testez vos prompts avec des variables d'exemple
- 💾 **Sauvegarde intelligente** : Suivi des modifications en temps réel
- 📤 **Import/Export** : Sauvegarde et restauration de la configuration

### 🎯 **Prompts Gérés**
1. **Analyse Principale** (`/analyze`) - Prompt principal pour l'analyse des pièces
2. **Classification Pièces** (`/classify-room`) - Identification automatique du type de pièce  
3. **Analyse Étapes** (`/analyze-etapes`) - Vérification des tâches ménagères
4. **Synthèse Globale** (`/analyze-complete`) - Recommandations et score final
5. **Messages Utilisateur** - Templates des messages envoyés aux utilisateurs

## 🛠️ Installation et Démarrage

### Prérequis
- API CheckEasy V5 en cours d'exécution
- Serveur web (optionnel pour développement local)

### Accès à l'Interface
```bash
# Via l'API CheckEasy (recommandé)
http://localhost:8000/prompts-admin

# Ou directement depuis le dossier front/
cd front/
python -m http.server 8080
# Puis ouvrir http://localhost:8080
```

## 📚 Structure des Prompts

### Format JSON
```json
{
  "version": "1.0.0",
  "last_updated": "2025-01-16",
  "description": "Configuration des prompts pour CheckEasy API V5",
  "prompts": {
    "analyze_main": {
      "name": "Analyse Principale des Pièces",
      "description": "Prompt principal pour l'analyse comparative",
      "endpoint": "/analyze, /analyze-with-classification",
      "variables": ["commentaire_ia", "elements_critiques"],
      "sections": {
        "reset_header": "🔄 RESET COMPLET...",
        "role_definition": "Tu es un expert...",
        "instructions_speciales_template": "🤖 INSTRUCTIONS: {commentaire_ia}"
      }
    }
  },
  "user_messages": {
    "analyze_main_user": {
      "name": "Message Utilisateur - Analyse",
      "template": "Analyse les différences de {piece_nom}",
      "variables": ["piece_nom"]
    }
  }
}
```

### Types de Sections

#### **Sections Fixes**
- `reset_header` - En-tête de reset de l'IA
- `role_definition` - Définition du rôle de l'expert
- `focus_principal` - Focus principal de l'analyse
- `instructions_analyse` - Instructions d'analyse
- `format_json` - Format de réponse attendu

#### **Sections Templates** (avec variables)
- `instructions_speciales_template` - Variable: `{commentaire_ia}`
- `elements_critiques_template` - Variable: `{elements_critiques}`
- `points_ignorables_template` - Variable: `{points_ignorables}`
- `defauts_frequents_template` - Variable: `{defauts_frequents}`

## 🎮 Guide d'Utilisation

### 1. **Navigation**
- 🏠 **Vue d'ensemble** : Statistiques et liste des prompts
- 📝 **Sections spécifiques** : Édition par type de prompt
- 👁️ **Prévisualisation** : Test avec variables d'exemple

### 2. **Édition des Prompts**
1. Sélectionner une section dans la navigation
2. Modifier le contenu dans les zones de texte
3. Les modifications sont automatiquement suivies (🟡 indicateur modifié)
4. Utiliser **"Sauvegarder Tout"** pour confirmer les changements

### 3. **Prévisualisation**
1. Aller dans l'onglet **"Prévisualisation"**
2. Sélectionner un prompt dans la liste déroulante
3. Modifier les variables JSON (exemple automatique fourni)
4. Cliquer **"Générer Prévisualisation"** pour voir le résultat

### 4. **Import/Export**
- **Exporter** : Télécharge un fichier JSON avec la configuration actuelle
- **Importer** : Charge une configuration depuis un fichier JSON
- **Railway Export** : Génère la variable d'environnement pour Railway

## 🔧 API Endpoints

### Gestion des Prompts
```http
GET    /prompts                    # Récupérer toute la configuration
PUT    /prompts                    # Sauvegarder la configuration complète
GET    /prompts/{prompt_key}       # Récupérer un prompt spécifique
PUT    /prompts/{prompt_key}       # Mettre à jour un prompt
POST   /prompts/preview            # Prévisualiser avec variables
GET    /prompts/export/railway-env # Export pour Railway
```

### Interface Web
```http
GET    /prompts-admin              # Interface de gestion
GET    /front/*                    # Fichiers statiques (CSS, JS)
```

## 🏗️ Architecture Technique

### Frontend
- **HTML5** + **CSS3** moderne avec variables CSS
- **JavaScript Vanilla** - Classe `PromptManager` 
- **Responsive Design** - Compatible mobile/desktop
- **Prism.js** - Syntax highlighting pour la prévisualisation

### Backend  
- **FastAPI** - Endpoints REST pour CRUD
- **Pydantic** - Validation des données
- **Fallback System** - Prompts hardcodés en backup

### Persistance
1. **Fichier JSON** (`front/prompts-config.json`) - Développement
2. **Variable d'environnement** (`PROMPTS_CONFIG`) - Production Railway
3. **Fallback hardcodé** - Si aucune source disponible

## 🔄 Workflow de Développement

### Modifier un Prompt
1. Ouvrir l'interface : `/prompts-admin`
2. Naviguer vers le prompt à modifier
3. Éditer les sections nécessaires  
4. Prévisualiser le résultat
5. Sauvegarder les changements
6. Tester via l'API (optionnel)

### Déployer en Production
1. Exporter la configuration via **"Export JSON"**
2. Copier le contenu dans Railway Dashboard > Variables
3. Définir `PROMPTS_CONFIG` avec la valeur JSON
4. Redémarrer l'application Railway

## 🚨 Gestion d'Erreurs

### Fallbacks Automatiques
- ✅ **Config JSON invalide** → Prompt hardcodé utilisé
- ✅ **Section manquante** → Template par défaut appliqué  
- ✅ **Variable non définie** → Placeholder conservé
- ✅ **Erreur de formatting** → Logs d'avertissement

### Logs de Debug
```python
logger.warning("⚠️ Erreur lors du chargement, utilisation du fallback")
logger.info("📁 Chargement config depuis fichier: prompts-config.json")
logger.error("❌ Erreur critique lors du parsing JSON")
```

## 🎨 Variables Disponibles

### Prompts Système
- `{commentaire_ia}` - Instructions spéciales utilisateur
- `{elements_critiques}` - Liste des éléments prioritaires  
- `{points_ignorables}` - Éléments d'usure normale à ignorer
- `{defauts_frequents}` - Défauts fréquents à rechercher
- `{piece_nom}` - Nom de la pièce analysée
- `{logement_id}` - Identifiant du logement
- `{total_issues}` - Nombre total de problèmes
- `{room_types_list}` - Liste des types de pièces
- `{etape_task_name}` - Nom de la tâche à vérifier
- `{etape_consigne}` - Consigne spécifique de l'étape

### Messages Utilisateur  
- `{piece_nom}` - Type de pièce à analyser
- `{logement_id}` - Identifiant du logement

## 🔗 Intégration avec l'API

Le système de prompts est automatiquement intégré dans l'API CheckEasy :

```python
# La fonction build_dynamic_prompt() charge automatiquement
# la configuration JSON et construit le prompt final
prompt = build_dynamic_prompt(input_data)

# Fallback automatique vers les prompts hardcodés 
# en cas d'erreur de chargement
```

## 📈 Avantages

### ✅ **Pour les Développeurs**
- 🎯 **Centralisation** : Tous les prompts dans un seul endroit
- 🔄 **Versioning** : Historique et exports faciles  
- 🐛 **Debug** : Prévisualisation avant déploiement
- ⚡ **Rapidité** : Modifications sans redéploiement

### ✅ **Pour les Utilisateurs**
- 🎨 **Interface moderne** : Expérience utilisateur optimale
- 📱 **Responsive** : Utilisable sur mobile/tablette
- 💡 **Intuitive** : Pas besoin de connaissances techniques
- 🔒 **Sécurisée** : Fallbacks automatiques

### ✅ **Pour la Production**
- 🏭 **Railway Ready** : Intégration native avec Railway
- 📊 **Monitoring** : Logs détaillés et gestion d'erreurs
- 🔄 **Hot Reload** : Modifications sans interruption
- 🛡️ **Robuste** : Système de fallback multi-niveaux

## 🚀 Prochaines Améliorations

- [ ] **Éditeur de code** avec autocomplétion
- [ ] **Système de versions** avec rollback
- [ ] **Templates de prompts** prédéfinis  
- [ ] **Tests automatisés** de cohérence
- [ ] **Audit trail** des modifications
- [ ] **Collaboration** multi-utilisateurs

---

## 🆘 Support

Pour toute question ou problème :
1. Vérifier les logs de l'application FastAPI
2. Tester la prévisualisation dans l'interface
3. S'assurer que le fichier JSON est valide
4. Vérifier les variables d'environnement Railway 