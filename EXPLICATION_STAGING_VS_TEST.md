# 🔍 EXPLICATION : Pourquoi Staging ≠ Test ?

## 📅 Date : 2026-01-14

---

## ❓ **QUESTION INITIALE**

> "Pourquoi la version staging n'est pas la même que la version test ?"

---

## 🎯 **RÉPONSE COURTE**

**Staging et Test sont en fait LA MÊME VERSION de code**, mais ils pointent vers **des endpoints Bubble différents** :

- **Staging** → `https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia`
- **Production** → `https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia`

La différence est contrôlée par la **variable d'environnement `VERSION`** sur Railway.

---

## 🏗️ **ARCHITECTURE ACTUELLE**

### **Repository GitHub**
```
checkeasy-api-v5 (branche main)
    ↓
    └── Déploiement automatique vers Railway
```

### **Services Railway**

Vous avez probablement **2 services Railway** :

| **Service** | **Branche Git** | **Variable `VERSION`** | **Webhook Bubble** |
|-------------|-----------------|------------------------|-------------------|
| **checkeasy-api-staging** | `main` | `VERSION=test` | `version-test` |
| **checkeasy-api-production** | `main` | `VERSION=live` | `version-live` |

---

## 🔄 **FLUX DE DÉPLOIEMENT ACTUEL**

```
Commit sur main
    ↓
    ├─→ Railway Staging (VERSION=test)
    │   └─→ Webhook: version-test
    │
    └─→ Railway Production (VERSION=live)
        └─→ Webhook: version-live
```

**Problème** : Les deux se déploient **en même temps** !

---

## ⚠️ **POURQUOI C'EST PROBLÉMATIQUE ?**

### **Scénario typique**

1. **Vous développez une nouvelle fonctionnalité** (ex: fix AVIF)
2. **Vous committez sur `main`**
3. **Railway redéploie AUTOMATIQUEMENT** :
   - ✅ Staging reçoit le nouveau code
   - ❌ Production reçoit AUSSI le nouveau code **en même temps**

**Conséquence** : Vous ne pouvez **PAS tester en staging avant de déployer en production** !

---

## ✅ **SOLUTION RECOMMANDÉE : Branches Git séparées**

### **Configuration idéale**

| **Service Railway** | **Branche Git** | **Variable `VERSION`** | **Déploiement** |
|---------------------|-----------------|------------------------|-----------------|
| **checkeasy-api-staging** | `develop` | `VERSION=test` | Automatique |
| **checkeasy-api-production** | `main` | `VERSION=live` | Automatique |

### **Nouveau flux de déploiement**

```
Développement
    ↓
Commit sur develop
    ↓
Railway Staging (VERSION=test)
    ↓
Tests validés ?
    ↓ OUI
Merge develop → main
    ↓
Railway Production (VERSION=live)
```

---

## 🛠️ **MISE EN PLACE (5 MINUTES)**

### **Étape 1 : Créer la branche `develop`**

```bash
cd /Users/adriengabillet/DEV/API\ 5\ /checkeasy-api-v5
git checkout -b develop
git push -u origin develop
```

### **Étape 2 : Configurer Railway Staging**

1. Allez sur **Railway Dashboard**
2. Sélectionnez le service **Staging**
3. Allez dans **Settings** → **Deployments**
4. Changez **Branch** de `main` → `develop`
5. Cliquez sur **Save**

### **Étape 3 : Configurer Railway Production**

1. Sélectionnez le service **Production**
2. Allez dans **Settings** → **Deployments**
3. Vérifiez que **Branch** = `main`
4. Vérifiez que `VERSION=live` dans **Variables**

---

## 🔄 **WORKFLOW DE DÉVELOPPEMENT**

### **Pour développer une nouvelle fonctionnalité**

```bash
# 1. Travailler sur develop
git checkout develop

# 2. Faire vos modifications
# ... éditer les fichiers ...

# 3. Commiter et pusher
git add .
git commit -m "feat: nouvelle fonctionnalité"
git push origin develop

# → Railway Staging se déploie automatiquement
```

### **Pour déployer en production**

```bash
# 1. Tester sur staging
# ... vérifier que tout fonctionne ...

# 2. Merger vers main
git checkout main
git merge develop
git push origin main

# → Railway Production se déploie automatiquement
```

---

## 📊 **DÉTECTION D'ENVIRONNEMENT**

Le code détecte automatiquement l'environnement via `detect_environment()` :

```python
def detect_environment() -> str:
    # 🔥 PRIORITÉ 1: Variable VERSION (Railway custom)
    version = os.environ.get('VERSION', '').lower()
    if version == 'live':
        return "production"
    elif version == 'test':
        return "staging"
    
    # Fallback: staging par défaut
    return "staging"
```

### **Webhooks selon l'environnement**

```python
def get_webhook_url(environment: str) -> str:
    if environment == "production":
        return "https://checkeasy-57905.bubbleapps.io/version-live/api/1.1/wf/webhookia"
    else:  # staging
        return "https://checkeasy-57905.bubbleapps.io/version-test/api/1.1/wf/webhookia"
```

---

## 🧪 **VÉRIFIER VOTRE CONFIGURATION ACTUELLE**

### **Méthode 1 : Via Railway Dashboard**

1. Allez sur **Railway**
2. Comptez le nombre de services
3. Pour chaque service, vérifiez :
   - **Branch** (Settings → Deployments)
   - **VERSION** (Variables)

### **Méthode 2 : Via l'API**

```bash
# Tester staging
curl https://votre-staging.railway.app/check-environment

# Tester production
curl https://votre-production.railway.app/check-environment
```

**Résultat attendu** :
```json
{
  "detected_environment": "staging",  // ou "production"
  "webhook_url": "https://checkeasy-57905.bubbleapps.io/version-test/...",
  "env_variables": {
    "VERSION": "test"  // ou "live"
  }
}
```

---

## ✅ **CHECKLIST DE VALIDATION**

Après avoir mis en place la solution :

- [ ] Branche `develop` créée et pushée
- [ ] Railway Staging configuré sur branche `develop`
- [ ] Railway Production configuré sur branche `main`
- [ ] Variable `VERSION=test` sur Staging
- [ ] Variable `VERSION=live` sur Production
- [ ] Test : commit sur `develop` → seul Staging se déploie
- [ ] Test : merge `develop` → `main` → seul Production se déploie

---

## 🎯 **AVANTAGES DE CETTE APPROCHE**

✅ **Séparation claire** entre staging et production  
✅ **Tests avant déploiement** en production  
✅ **Rollback facile** (revert sur la branche)  
✅ **Workflow Git standard** (develop → main)  
✅ **Déploiements automatiques** pour les deux environnements  
✅ **Pas de risque** de casser la production par accident  

---

## 📝 **NOTES IMPORTANTES**

### **Alternative : Déploiement manuel en production**

Si vous ne voulez pas utiliser de branches :

1. **Staging** : Déploiement automatique depuis `main`
2. **Production** : Déploiement **manuel** uniquement

Configuration Railway Production :
- Désactiver **Auto Deploy**
- Déclencher manuellement après validation staging

---

**Auteur** : Augment Agent  
**Date** : 2026-01-14  
**Recommandation** : ⭐ Utiliser des branches Git séparées (develop/main)

