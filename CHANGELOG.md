# 📋 CHANGELOG - CheckEasy API V5

## 2026-01-15 - Validation en 2 Étapes + Corrections Scoring

### 🔄 Validation en 2 Étapes

**Problème** : L'IA pénalisait les prestataires quand un élément demandé n'était pas présent dès le départ.

**Solution** : Logique en 2 étapes implémentée dans le code (pas seulement les prompts) :

```
ÉTAPE 1 : L'IA vérifie si checkout répond à la consigne
   ├─ ✅ VALIDÉ → Tâche accomplie
   └─ ❌ NON_VALIDÉ → Passer à ÉTAPE 2

ÉTAPE 2 : Comparer checkout avec checking
   ├─ ✅ Images similaires → FORCER VALIDÉ (état maintenu)
   └─ ❌ Images différentes → GARDER NON_VALIDÉ (dégradation)
```

**Fonctions ajoutées** :
- `apply_two_step_validation_logic_sync()` - Version synchrone
- `apply_two_step_validation_logic()` - Version asynchrone

---

### 🐛 Fix : Étapes VALIDÉES n'impactent plus la note

Les étapes avec `validation_status = "VALIDÉ"` étaient comptées comme des pénalités.

**Correction** : Filtre ajouté dans `calculate_weighted_severity_score()` et `calculate_room_algorithmic_score()` pour ignorer les étapes VALIDÉES.

---

### 🔄 Synchronisation `estApprouve` avec `validation_status`

Le champ `estApprouve` dans `tachesValidees[]` est maintenant automatiquement dérivé du `validation_status` IA :

| validation_status | estApprouve |
|-------------------|-------------|
| VALIDÉ            | true        |
| NON_VALIDÉ        | false       |
| INCERTAIN         | false       |

Exception : Si `tache_approuvee` est explicitement défini → surcharge manuelle.

---

## 2026-01-14 - Nettoyage Codebase

- ✅ Documentation consolidée (27 → 2 fichiers .md)
- ✅ Fichiers de test nettoyés (15 supprimés)
- ✅ Clé API en dur supprimée (run_server.py)
- ✅ Cache vidé

---

## 2026-01-16 - Parallélisation + Nettoyage Final

### ⚡ Parallélisation des Analyses

- Traitement parallèle des 15 étapes simultanément
- Gain de performance : ~60s → ~20s
- Fix `LogsManager` thread-safe
- Fallback Data URI pour timeout images

### 🧹 Nettoyage Dépendances

- **Supprimé** : heiya, pyheif, Wand, imageio-ffmpeg (redondants)
- **Gardé** : pillow-heif uniquement (suffisant pour HEIC/AVIF)
- **Simplifié** : `convert_heic_with_modern_libraries()` (215 → 50 lignes)

---

## Notes Techniques

### Dépendances Principales
- `pillow-heif==0.16.0` - Support HEIC + AVIF
- `aiohttp==3.9.1` - Téléchargement async
- `nest-asyncio==1.6.0` - Event loop Jupyter/Railway

### Fichiers Clés
- `make_request.py` - API FastAPI principale
- `image_converter.py` - Conversion et optimisation images
- `parallel_processor.py` - Traitement parallèle étapes

