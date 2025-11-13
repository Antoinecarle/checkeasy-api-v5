# 🚀 Guide de Déploiement Railway - Système Dual Voyageur/Ménage

## ✅ ÉTAPE 1 : Code Déployé sur GitHub

**Status : ✅ TERMINÉ**

- ✅ Commit créé avec toutes les modifications
- ✅ Push vers GitHub réussi (commit `ecf1a4a`)
- ✅ 9 fichiers modifiés, 4947 insertions

**Fichiers déployés :**
- `make_request.py` (avec logs améliorés)
- `room_classfication/room-verification-templates-voyageur.json`
- `room_classfication/room-verification-templates-menage.json`
- `front/prompts-config-voyageur.json`
- `front/prompts-config-menage.json`
- `front/scoring-config-voyageur.json`
- `front/scoring-config-menage.json`
- `templates/scoring-admin.html`

---

## 📋 ÉTAPE 2 : Configuration des Variables d'Environnement Railway

### 2.1 Accéder à Railway

1. Allez sur : https://railway.app/
2. Connectez-vous avec votre compte
3. Sélectionnez le projet **CheckEasy API V5**
4. Cliquez sur le service (normalement nommé `web` ou `api`)
5. Allez dans l'onglet **"Variables"**

### 2.2 Ajouter les Variables d'Environnement

**⚠️ IMPORTANT :** Ouvrez le fichier `railway_env_vars.txt` qui a été généré.

Pour chaque variable ci-dessous, cliquez sur **"+ New Variable"** dans Railway :

#### Variable 1 : PROMPTS_CONFIG_VOYAGEUR
```
Nom : PROMPTS_CONFIG_VOYAGEUR
Valeur : [Copier depuis railway_env_vars.txt]
```

#### Variable 2 : PROMPTS_CONFIG_MENAGE
```
Nom : PROMPTS_CONFIG_MENAGE
Valeur : [Copier depuis railway_env_vars.txt]
```

#### Variable 3 : ROOM_TEMPLATES_CONFIG_VOYAGEUR
```
Nom : ROOM_TEMPLATES_CONFIG_VOYAGEUR
Valeur : [Copier depuis railway_env_vars.txt]
```

#### Variable 4 : ROOM_TEMPLATES_CONFIG_MENAGE
```
Nom : ROOM_TEMPLATES_CONFIG_MENAGE
Valeur : [Copier depuis railway_env_vars.txt]
```

#### Variable 5 : SCORING_CONFIG_VOYAGEUR
```
Nom : SCORING_CONFIG_VOYAGEUR
Valeur : [Copier depuis railway_env_vars.txt]
```

#### Variable 6 : SCORING_CONFIG_MENAGE
```
Nom : SCORING_CONFIG_MENAGE
Valeur : [Copier depuis railway_env_vars.txt]
```

### 2.3 Vérifier les Variables

Après avoir ajouté toutes les variables, vous devriez voir **6 nouvelles variables** dans la liste.

**Tailles attendues :**
- PROMPTS_CONFIG_VOYAGEUR: ~22.74 KB
- PROMPTS_CONFIG_MENAGE: ~21.61 KB
- ROOM_TEMPLATES_CONFIG_VOYAGEUR: ~7.57 KB
- ROOM_TEMPLATES_CONFIG_MENAGE: ~6.40 KB
- SCORING_CONFIG_VOYAGEUR: ~2.30 KB
- SCORING_CONFIG_MENAGE: ~2.27 KB

---

## 🔄 ÉTAPE 3 : Redéploiement Automatique

Railway va **automatiquement redéployer** le service après l'ajout des variables d'environnement.

### 3.1 Surveiller le Déploiement

1. Allez dans l'onglet **"Deployments"**
2. Vous devriez voir un nouveau déploiement en cours
3. Attendez que le status passe à **"Success"** (généralement 2-5 minutes)

### 3.2 Vérifier les Logs de Déploiement

Cliquez sur le déploiement en cours et vérifiez les logs :

**Logs attendus au démarrage :**
```
🔧 Chargement des templates de vérification pour le parcours: Voyageur (suffixe: -voyageur)
📡 Chargement des templates depuis la variable d'environnement ROOM_TEMPLATES_CONFIG_VOYAGEUR
✅ Templates Voyageur chargés depuis variable d'environnement (11 types de pièces)
```

**Si vous voyez ces logs, c'est bon ! ✅**

---

## 🧪 ÉTAPE 4 : Test du Déploiement

### 4.1 Lancer le Script de Test

Une fois le déploiement terminé, lancez le script de test :

```bash
python test_deployment_voyageur.py
```

### 4.2 Résultats Attendus

**Test 1 - Voyageur :**
```
✅ 'lit fait ou pas fait' est bien dans les points ignorables (CONFIG VOYAGEUR)
✅ Nombre de points ignorables correct : 6 (attendu: 6)
✅ Aucun défaut lié au lit pas fait (comportement attendu en Voyageur)
```

**Test 2 - Ménage :**
```
✅ 'lit fait ou pas fait' ABSENT des points ignorables (CONFIG MÉNAGE)
```

**Résumé :**
```
🎉 TOUS LES TESTS SONT RÉUSSIS !
Le système dual Voyageur/Ménage fonctionne correctement.
```

---

## 🔍 ÉTAPE 5 : Vérification des Logs Railway

### 5.1 Accéder aux Logs

1. Dans Railway, allez dans l'onglet **"Logs"**
2. Lancez une analyse via votre application
3. Recherchez les logs suivants :

### 5.2 Logs à Vérifier

**Chargement des Templates :**
```
🔧 Chargement des templates de vérification pour le parcours: Voyageur (suffixe: -voyageur)
✅ Templates Voyageur chargés depuis variable d'environnement (11 types de pièces)
🛏️ Chambre - Points ignorables (6): ['COULEUR DES DRAPS ET DE LA COUETTE', "état d'éclairage (lumière allumée ou éteinte)", 'lit fait ou pas fait', 'position des oreillers', 'organisation des tiroirs', 'position exacte des meubles']
```

**Chargement des Prompts :**
```
🔧 Chargement de la config prompts pour le parcours: Voyageur (suffixe: -voyageur)
📡 Chargement de la config prompts depuis la variable d'environnement PROMPTS_CONFIG_VOYAGEUR
✅ Config prompts Voyageur chargée depuis variable d'environnement
```

**Classification :**
```
🔍 ÉTAPE 1 - Classification automatique pour la pièce XXX (parcours: Voyageur)
➖ Points ignorables injectés (6): ['COULEUR DES DRAPS ET DE LA COUETTE', "état d'éclairage (lumière allumée ou éteinte)", 'lit fait ou pas fait', 'position des oreillers', 'organisation des tiroirs', 'position exacte des meubles']
```

---

## ❌ Dépannage

### Problème 1 : Les logs ne montrent pas le parcours_type

**Symptôme :**
```
📡 Chargement de la config prompts depuis les variables d'environnement Railway
```
(sans mention de "Voyageur" ou "Ménage")

**Solution :**
- Le code n'a pas été redéployé correctement
- Vérifiez que le commit `ecf1a4a` est bien déployé
- Forcez un redéploiement manuel dans Railway

### Problème 2 : Seulement 2 points_ignorables au lieu de 6

**Symptôme :**
```
➖ Points ignorables injectés (2): ['COULEUR DES DRAPS ET DE LA COUETTE', "état d'éclairage (lumière allumée ou éteinte)"]
```

**Solution :**
- Les variables d'environnement ne sont pas configurées
- Vérifiez que `ROOM_TEMPLATES_CONFIG_VOYAGEUR` existe dans Railway
- Vérifiez que la valeur est correcte (doit contenir 6 points_ignorables pour chambre)

### Problème 3 : Variables d'environnement trop grandes

**Symptôme :**
Railway refuse d'accepter la variable (limite de taille)

**Solution :**
- Railway accepte normalement jusqu'à 64KB par variable
- Nos variables sont bien en dessous (max 22.74 KB)
- Si problème persiste, contactez le support Railway

---

## 📊 Checklist Finale

Avant de considérer le déploiement comme réussi, vérifiez :

- [ ] Code poussé sur GitHub (commit `ecf1a4a`)
- [ ] 6 variables d'environnement ajoutées sur Railway
- [ ] Déploiement Railway terminé avec succès
- [ ] Logs Railway montrent le chargement des configs Voyageur/Ménage
- [ ] Script de test `test_deployment_voyageur.py` réussi
- [ ] Points ignorables = 6 pour Voyageur (dont "lit fait ou pas fait")
- [ ] Points ignorables ≠ 6 pour Ménage (sans "lit fait ou pas fait")

---

## 🎯 Prochaines Étapes

Une fois le déploiement validé :

1. ✅ Testez avec de vraies données depuis votre application
2. ✅ Vérifiez que le dropdown Voyageur/Ménage fonctionne
3. ✅ Comparez les scores entre Voyageur et Ménage pour la même pièce
4. ✅ Ajustez les configurations si nécessaire via les interfaces admin

---

## 📞 Support

En cas de problème :
1. Consultez les logs Railway
2. Lancez le script de test
3. Vérifiez le fichier `rapportlog.json` après une analyse
4. Contactez l'équipe de développement avec les logs

---

**Date de création :** 2025-11-12
**Version :** 1.0
**Auteur :** CheckEasy API V5 Team

