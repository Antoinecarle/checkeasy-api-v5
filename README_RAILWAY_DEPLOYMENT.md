# 🚀 Guide de Déploiement Railway - CheckEasy V5

## 🔥 Problème Initial
Quand vous faites `railway up`, le fichier `room-verification-templates.json` est écrasé par la version locale, perdant toutes les modifications faites via l'interface d'administration.

## ✅ Solution Implémentée

### 1. Configuration Hybrid (Local + Railway)
L'API utilise maintenant un système hybride :
- **Développement local** : Fichier `room-verification-templates.json`
- **Production Railway** : Variable d'environnement `ROOM_TEMPLATES_CONFIG`

### 2. Ordre de Priorité
1. 🥇 **Variable d'environnement Railway** (si présente)
2. 🥈 **Fichier local** (fallback développement)
3. 🥉 **Configuration par défaut** (si rien d'autre)

---

## 📋 Procédure de Déploiement

### Étape 1: Configurer localement
1. Démarrez l'API en local : `python -m uvicorn make_request:app --host 0.0.0.0 --port 8000 --reload`
2. Accédez à l'interface : `http://localhost:8000/admin`
3. Configurez vos types de pièces selon vos besoins

### Étape 2: Exporter vers Railway
1. Dans l'interface d'admin, cliquez sur **🚀 Export Railway**
2. Copiez la valeur de la variable d'environnement
3. Allez sur Railway Dashboard > Votre Projet > Variables
4. Créez la variable : `ROOM_TEMPLATES_CONFIG`
5. Collez la valeur copiée
6. Sauvegardez → Railway redémarre automatiquement

### Étape 3: Déployer en toute sécurité
```bash
railway up
```
✅ **Vos configurations sont maintenant persistantes !**

---

## 🛠️ Endpoints Ajoutés

### CRUD Complet
- `GET /room-templates` - Liste tous les types
- `GET /room-templates/{key}` - Détails d'un type
- `POST /room-templates` - Créer un nouveau type
- `PUT /room-templates/{key}` - Modifier un type
- `DELETE /room-templates/{key}` - Supprimer un type

### Export Railway
- `GET /room-templates/export/railway-env` - Export pour Railway

### Interface d'Admin
- `GET /admin` - Interface web moderne

---

## 🔧 Variables d'Environnement Railway

### Obligatoires
```
OPENAI_API_KEY=sk-proj-...
```

### Optionnelles (mais recommandées)
```
ROOM_TEMPLATES_CONFIG={"room_types":{"cuisine":{"name":"Cuisine",...}}}
```

---

## 📊 Workflow Recommandé

### Pour les Modifications
1. 🏠 **Local** : Testez vos modifications
2. 🚀 **Export** : Utilisez le bouton "Export Railway"
3. ⚙️ **Railway** : Mettez à jour la variable d'environnement
4. 🚀 **Deploy** : `railway up` en toute sécurité

### Pour les Nouveaux Environnements
1. 🚀 **Deploy** : `railway up` avec la config par défaut
2. 🎨 **Configure** : Utilisez l'interface `/admin` sur Railway
3. 🔄 **Export** : Exportez vers les variables Railway
4. ✅ **Persistance** : Vos configs survivront aux redéploiements

---

## 🚨 Points d'Attention

### ⚠️ Sans Variable d'Environnement
- Les modifications via l'interface web seront **perdues** au prochain `railway up`
- L'API utilisera toujours le fichier local par défaut

### ✅ Avec Variable d'Environnement
- Les modifications sont **persistantes**
- L'API charge la config depuis Railway
- Les redéploiements sont sûrs

### 🔄 Synchronisation
- Modifiez **soit** en local **soit** sur Railway, pas les deux
- Utilisez l'export Railway pour synchroniser local → production
- Pas de sync automatique production → local (par design)

---

## 🛡️ Solution Future (Recommandée)

Pour une solution plus robuste, considérez :
1. **Base de données** (PostgreSQL Railway)
2. **API Railway** pour la gestion des variables
3. **Webhooks** pour la synchronisation automatique

Cette solution actuelle est une **solution de transition efficace** qui résout le problème immédiat tout en restant simple à utiliser. 