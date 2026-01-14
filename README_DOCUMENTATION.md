# 📚 Documentation CheckEasy API V5

## 📂 Fichiers de documentation disponibles

### 1. 🚀 GUIDE_RESOLUTION_RAPIDE.md
**Pour qui ?** Développeurs qui veulent remettre l'API en marche rapidement

**Contenu :**
- Installation de python-dotenv
- Création du fichier .env
- Configuration de la clé OpenAI
- Vérification et lancement de l'API
- Résolution des problèmes courants

**Temps de lecture :** 5 minutes  
**Temps d'application :** 5 minutes

---

### 2. 📊 RAPPORT_DIAGNOSTIC_2026-01-14.md
**Pour qui ?** Développeurs qui veulent comprendre les problèmes détectés

**Contenu :**
- Diagnostic complet du système
- Problèmes critiques identifiés
- Solutions détaillées
- État de santé de l'API
- Recommandations

**Temps de lecture :** 15 minutes

---

### 3. 📖 DOCUMENTATION_FLUX_IA.md (1842 lignes)
**Pour qui ?** Développeurs qui veulent comprendre TOUT le système en profondeur

**Contenu :**
- Architecture complète du système
- Configuration et initialisation
- Flux principal `/analyze-complete`
- Traitement des images (conversion, normalisation)
- Analyse par pièce (3 étapes détaillées)
- Analyse des étapes de nettoyage
- Synthèse globale du logement
- Construction du payload final
- Envoi du webhook à Bubble
- Gestion des erreurs et fallbacks
- Système de logging
- Points de modification possibles
- Code source complet avec explications

**Temps de lecture :** 1-2 heures  
**Niveau :** Technique avancé

**Sections principales :**
1. Vue d'ensemble du système
2. Architecture et dépendances
3. Configuration et initialisation
4. Flux principal - Endpoint `/analyze-complete`
5. Traitement des images
6. Analyse par pièce (3 étapes)
7. Analyse des étapes de nettoyage
8. Synthèse globale du logement
9. Construction du payload final
10. Envoi du webhook à Bubble
11. Gestion des erreurs et fallbacks
12. Système de logging
13. Système de cache et parallélisation
14. Points de modification possibles
15. Annexes techniques

---

### 4. 🎨 AVIF_SUPPORT_FIX.md
**Pour qui ?** Développeurs qui rencontrent des problèmes avec les images AVIF

**Contenu :**
- Diagnostic du problème AVIF
- Correction des dépendances (pillow-avif + PyAV)
- Flux de conversion AVIF → JPEG
- Tests de validation
- Checklist de déploiement

**Temps de lecture :** 10 minutes

---

### 5. 🔄 EXPLICATION_STAGING_VS_TEST.md
**Pour qui ?** Développeurs qui veulent comprendre la différence entre staging et production

**Contenu :**
- Architecture actuelle (branche unique vs branches séparées)
- Problème du déploiement simultané
- Solution recommandée (branches Git develop/main)
- Configuration Railway pour staging et production
- Workflow de développement
- Détection d'environnement automatique

**Temps de lecture :** 10 minutes

---

### 6. 📝 .env.example
**Pour qui ?** Tous les développeurs

**Contenu :**
- Template de configuration
- Variables d'environnement nécessaires
- Commentaires explicatifs
- Exemples de valeurs

**Usage :**
```bash
cp .env.example .env
# Puis éditer .env avec vos vraies valeurs
```

---

## 🎯 Par où commencer ?

### Scénario 1 : L'API ne fonctionne pas
1. ✅ Lire **GUIDE_RESOLUTION_RAPIDE.md**
2. ✅ Suivre les étapes (5 minutes)
3. ✅ Vérifier que l'API démarre

### Scénario 2 : Je veux comprendre les problèmes
1. ✅ Lire **RAPPORT_DIAGNOSTIC_2026-01-14.md**
2. ✅ Identifier les problèmes critiques
3. ✅ Appliquer les solutions recommandées

### Scénario 3 : Les images AVIF ne sont pas analysées
1. ✅ Lire **AVIF_SUPPORT_FIX.md**
2. ✅ Vérifier que les dépendances sont correctes
3. ✅ Tester avec une image AVIF
4. ✅ Vérifier les logs de conversion

### Scénario 4 : Staging et Production se déploient en même temps
1. ✅ Lire **EXPLICATION_STAGING_VS_TEST.md**
2. ✅ Créer la branche `develop`
3. ✅ Configurer Railway pour utiliser des branches séparées
4. ✅ Tester le nouveau workflow

### Scénario 5 : Je veux modifier le comportement de l'IA
1. ✅ Lire **DOCUMENTATION_FLUX_IA.md** (section "Points de modification possibles")
2. ✅ Identifier ce que vous voulez modifier (prompts, templates, etc.)
3. ✅ Utiliser les interfaces d'administration :
   - `/prompts-admin` pour les prompts
   - `/admin` pour les room templates
   - `/tester` pour tester vos modifications

### Scénario 6 : Je veux comprendre TOUT le système
1. ✅ Lire **DOCUMENTATION_FLUX_IA.md** en entier
2. ✅ Suivre le flux étape par étape
3. ✅ Consulter le code source avec les références de lignes fournies

---

## 🔑 Informations importantes

### Variables d'environnement obligatoires

```bash
# Clé OpenAI (OBLIGATOIRE)
OPENAI_API_KEY=sk-proj-VOTRE_CLE_ICI

# Environnement (OBLIGATOIRE)
VERSION=test  # ou "live" pour production
```

### Variables d'environnement optionnelles

```bash
# Modèle OpenAI (optionnel, défaut: gpt-5.2-2025-12-11)
OPENAI_MODEL=gpt-5.2-2025-12-11

# Prompts personnalisés (optionnel)
PROMPTS_CONFIG_VOYAGEUR={"prompts":{...}}
PROMPTS_CONFIG_MENAGE={"prompts":{...}}

# Templates de pièces personnalisés (optionnel)
ROOM_TEMPLATES_CONFIG_VOYAGEUR={"room_types":{...}}
ROOM_TEMPLATES_CONFIG_MENAGE={"room_types":{...}}
```

---

## 🛠️ Interfaces d'administration

### 1. Gestion des prompts
**URL :** `http://localhost:8080/prompts-admin`

Permet de :
- Visualiser tous les prompts
- Modifier les sections
- Prévisualiser avec variables
- Sauvegarder dans Railway

### 2. Gestion des room templates
**URL :** `http://localhost:8080/admin`

Permet de :
- Gérer les types de pièces
- Modifier les critères de vérification
- Ajouter/supprimer des pièces

### 3. Test de l'API
**URL :** `http://localhost:8080/tester`

Permet de :
- Tester tous les endpoints
- Charger des payloads de test
- Visualiser les réponses JSON

---

## ⚠️ Règles importantes

### ✅ CE QUE VOUS POUVEZ MODIFIER

1. **Prompts système** (fichiers JSON ou variables Railway)
2. **Templates de vérification des pièces**
3. **Modèle OpenAI utilisé** (variable `OPENAI_MODEL`)
4. **Paramètres de l'appel OpenAI** (max_tokens, etc.)
5. **Traitement des images** (qualité, taille, formats)

### ❌ CE QUE VOUS NE DEVEZ JAMAIS MODIFIER

1. **Structure du payload envoyé à Bubble** (cassera l'intégration)
2. **Modèles Pydantic de réponse** (contrat API avec Bubble)
3. **URLs des webhooks Bubble** (sauf si Bubble change)
4. **Logique de détection d'environnement** (risque d'envoyer test en prod)

---

## 🐛 Problèmes connus et solutions

### ❌ Les images AVIF ne sont pas analysées
**Solution :** Lire **AVIF_SUPPORT_FIX.md**
- Problème : Dépendances incorrectes (`pillow-avif-plugin` n'existe pas)
- Fix : Utiliser `pillow-avif>=1.0.0` + `av>=10.0.0` (PyAV)
- Commit : `b17d982`

### ❌ Staging et Production se déploient en même temps
**Solution :** Lire **EXPLICATION_STAGING_VS_TEST.md**
- Problème : Les deux services Railway utilisent la branche `main`
- Fix : Utiliser `develop` pour staging, `main` pour production
- Workflow : develop → test → merge → production

### ❌ Système de malus pour tâches/étapes
**Solution :** Déjà implémenté !
- Localisation : `make_request.py` lignes 5026-5082
- Barème : 1 non-conformité = -0.5, 2 = -1.0, 3-4 = -1.5, 5+ = -2.0
- Comptage : Tâches non approuvées + Étapes NON_VALIDÉ + (Étapes INCERTAIN × 0.5)

---

## 📞 Support

Pour toute question :
1. Consultez d'abord la documentation appropriée
2. Vérifiez les logs dans Railway
3. Utilisez l'interface `/tester` pour débugger

---

## 📋 Historique des modifications

### 2026-01-14
- ✅ Fix support AVIF (correction dépendances)
- ✅ Documentation staging vs production
- ✅ Explication système de malus tâches/étapes

### 2026-01-13
- ✅ Amélioration critères de sévérité
- ✅ Classification basée uniquement sur checkin
- ✅ Support AVIF initial

### 2026-01-12
- ✅ Système de parallélisation avec cache
- ✅ Optimisation des logs Railway
- ✅ Guide de déploiement Railway

---

**Dernière mise à jour :** 2026-01-14
**Version de l'API :** 5.0
**Modèle IA :** OpenAI GPT-5.2 (Responses API)

