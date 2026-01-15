# 🔄 Changement : Synchronisation automatique `estApprouve` avec `validation_status` IA

## 📅 Date : 2026-01-15

---

## 🎯 Objectif

Synchroniser automatiquement le champ `estApprouve` (dans `tachesValidees[]`) avec le statut de validation IA (`validation_status`) pour éviter les incohérences.

---

## ⚙️ Ancien Comportement

### Avant :
- `estApprouve` était défini **manuellement** via `tache_approuvee` dans l'input
- `validation_status` était calculé **automatiquement** par l'IA
- **Problème** : Les deux pouvaient être en désaccord

**Exemple d'incohérence :**
```json
{
  "tachesValidees": [
    {
      "etapeId": "etape_001",
      "estApprouve": true  // ← Validation manuelle
    }
  ],
  "problemes": [
    {
      "etapeId": "etape_001",
      "validationStatus": "NON_VALIDÉ"  // ← IA dit KO
    }
  ]
}
```

---

## ✅ Nouveau Comportement

### Maintenant :
- `estApprouve` est **automatiquement dérivé** du `validation_status` IA **UNIQUEMENT si l'IA a analysé l'étape**
- Logique de mapping :

#### 🤖 Si analyse IA disponible (`validation_status` présent) :
  - `validation_status = "VALIDÉ"` → `estApprouve = true`
  - `validation_status = "NON_VALIDÉ"` → `estApprouve = false`
  - `validation_status = "INCERTAIN"` → `estApprouve = false`
  - **Exception** : Si `tache_approuvee` est explicitement défini → utiliser cette valeur (surcharge manuelle)

#### 👤 Si PAS d'analyse IA (`validation_status` absent) :
  - Respecter `tache_approuvee` tel quel (ne pas toucher à la validation manuelle)
  - Si `tache_approuvee` est `null` → `estApprouve = true` (par défaut)

---

## 📊 Exemples

### Exemple 1 : IA valide la tâche ✅

**Input :**
```json
{
  "etape_id": "etape_001",
  "task_name": "Laver le four",
  "consigne": "Nettoyer l'intérieur du four",
  "tache_approuvee": null  // ← Pas de surcharge manuelle
}
```

**Analyse IA :**
```json
{
  "validation_status": "VALIDÉ",
  "issues": []
}
```

**Output :**
```json
{
  "tachesValidees": [
    {
      "etapeId": "etape_001",
      "estApprouve": true,  // ← Automatiquement true car VALIDÉ
      "validationStatusIA": "VALIDÉ"
    }
  ],
  "problemes": []
}
```

---

### Exemple 2 : IA rejette la tâche ❌

**Input :**
```json
{
  "etape_id": "etape_002",
  "task_name": "Laver le four",
  "consigne": "Nettoyer l'intérieur du four",
  "tache_approuvee": null
}
```

**Analyse IA :**
```json
{
  "validation_status": "NON_VALIDÉ",
  "commentaire": "Résidus de graisse visibles",
  "issues": [...]
}
```

**Output :**
```json
{
  "tachesValidees": [
    {
      "etapeId": "etape_002",
      "estApprouve": false,  // ← Automatiquement false car NON_VALIDÉ
      "validationStatusIA": "NON_VALIDÉ"
    }
  ],
  "problemes": [
    {
      "etapeId": "etape_002",
      "validationStatus": "NON_VALIDÉ",
      "description": "Résidus de graisse visibles"
    }
  ]
}
```

---

### Exemple 3 : Photo floue (INCERTAIN) ⚠️

**Input :**
```json
{
  "etape_id": "etape_003",
  "task_name": "Laver le four",
  "tache_approuvee": null
}
```

**Analyse IA :**
```json
{
  "validation_status": "INCERTAIN",
  "commentaire": "Photo floue, impossible de vérifier",
  "issues": [...]
}
```

**Output :**
```json
{
  "tachesValidees": [
    {
      "etapeId": "etape_003",
      "estApprouve": false,  // ← false car INCERTAIN
      "validationStatusIA": "INCERTAIN"
    }
  ],
  "problemes": [
    {
      "etapeId": "etape_003",
      "validationStatus": "INCERTAIN",
      "category": "image_quality"
    }
  ]
}
```

---

## 🔧 Modifications Techniques

### Fichier : `make_request.py`

**Ligne 4784-4815 :** Nouvelle logique de construction de `tachesValidees`

1. **Créer un mapping** `etape_id` → `validation_status` depuis les issues IA
2. **Déterminer `estApprouve`** selon la priorité :
   - **Si PAS d'analyse IA** → respecter `tache_approuvee` tel quel (ou `true` par défaut)
   - **Si analyse IA disponible** :
     - Si `tache_approuvee` explicite → utiliser cette valeur (surcharge manuelle)
     - Sinon → utiliser le mapping IA (`VALIDÉ` = true, autres = false)
3. **Ajouter `validationStatusIA`** dans chaque tâche pour traçabilité

**Ligne 4864-4880 :** Calcul du malus simplifié
- Utilise directement le mapping IA
- Plus besoin de compter `taches_non_approuvees` séparément

---

## 📈 Impact

### Avantages :
✅ Cohérence automatique entre `estApprouve` et `validation_status`  
✅ Moins de confusion pour l'utilisateur  
✅ Calcul de note plus fiable  
✅ Traçabilité avec `validationStatusIA`  

### Compatibilité :
✅ Rétrocompatible : surcharge manuelle toujours possible  
✅ Pas de changement dans le format de l'API  

---

## 🧪 Tests Recommandés

1. **Avec analyse IA** : `validation_status = "VALIDÉ"` + `tache_approuvee = null` → vérifier `estApprouve = true`
2. **Avec analyse IA** : `validation_status = "NON_VALIDÉ"` + `tache_approuvee = null` → vérifier `estApprouve = false`
3. **Avec analyse IA** : `validation_status = "INCERTAIN"` + `tache_approuvee = null` → vérifier `estApprouve = false`
4. **Surcharge manuelle** : `validation_status = "NON_VALIDÉ"` + `tache_approuvee = true` → vérifier `estApprouve = true`
5. **Sans analyse IA** : `validation_status = null` + `tache_approuvee = null` → vérifier `estApprouve = true`
6. **Sans analyse IA + validation manuelle** : `validation_status = null` + `tache_approuvee = false` → vérifier `estApprouve = false`

