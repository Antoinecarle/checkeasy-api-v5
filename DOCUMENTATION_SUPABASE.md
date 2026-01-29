# 📚 CheckEasy API V5 - Intégration Supabase

> **Dernière mise à jour** : 2026-01-29  
> **Version** : 5.0.0

---

## 🎯 Vue d'ensemble

Ce document explique comment intégrer l'API CheckEasy V5 avec Supabase. L'API reste **100% indépendante** - seuls les webhooks changent de destination.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FLUX DE DONNÉES                                 │
└─────────────────────────────────────────────────────────────────────────────┘

  SUPABASE                         API CheckEasy V5                 SUPABASE
  (Edge Function)                     (Railway)                  (Edge Function)
       │                                 │                              │
       │  1. POST /analyze-complete      │                              │
       │ ───────────────────────────────▶│                              │
       │                                 │                              │
       │                                 │  2. Analyse IA (15-90s)      │
       │                                 │                              │
       │◀────────────────────────────────│                              │
       │  3. Réponse JSON immédiate      │                              │
       │                                 │                              │
       │                                 │  4. POST Webhook (async)     │
       │                                 │ ────────────────────────────▶│
       │                                 │                              │
       │                                 │                    5. Sauvegarde DB
```

---

## 🔗 URLs de l'API

| Environnement | URL | Webhook vers |
|---------------|-----|--------------|
| **Production** | `https://checkeasy-api-v5-production.up.railway.app` | Bubble |
| **Staging** | `https://checkeasy-api-v5-staging.up.railway.app` | Supabase ✅ |

### Endpoint principal
```
POST /analyze-complete
Content-Type: application/json
```

---

## 📤 Payload d'entrée (JSON à envoyer)

```json
{
  "logement_id": "uuid-supabase",
  "rapport_id": "uuid-supabase",
  "type": "Voyageur",
  "logementName": "Appartement Paris 11",
  "adresseLogement": "123 rue de la République, 75011 Paris",
  "operatorFirstName": "Jean",
  "operatorLastName": "Dupont",
  "operatorPhone": "+33612345678",
  "date_debut": "25/01/26",
  "date_fin": "28/01/26",
  "voyageur_nom": "Marie Martin",
  "voyageur_email": "marie@email.com",
  "voyageur_telephone": "+33698765432",
  "etat_lieux_moment": "sortie",
  
  "pieces": [
    {
      "piece_id": "uuid-piece",
      "nom": "Cuisine",
      "commentaire_ia": "",
      "checkin_pictures": [
        { "piece_id": "uuid-piece", "url": "https://storage.supabase.co/..." }
      ],
      "checkout_pictures": [
        { "piece_id": "uuid-piece", "url": "https://storage.supabase.co/..." }
      ],
      "etapes": [
        {
          "etape_id": "uuid-etape",
          "task_name": "Vider le lave-vaisselle",
          "consigne": "Vérifier que le lave-vaisselle est vidé et rangé",
          "checking_picture": "https://...",
          "checkout_picture": "https://..."
        }
      ]
    }
  ],
  
  "signalements_utilisateur": [],
  "checklist_finale": []
}
```

### Champs obligatoires

| Champ | Type | Description |
|-------|------|-------------|
| `logement_id` | string | UUID du logement dans Supabase |
| `rapport_id` | string | UUID du rapport/état des lieux |
| `type` | string | `"Voyageur"` ou `"Ménage"` |
| `pieces` | array | Liste des pièces à analyser |
| `pieces[].piece_id` | string | UUID de la pièce |
| `pieces[].checkin_pictures` | array | Photos AVANT (check-in) |
| `pieces[].checkout_pictures` | array | Photos APRÈS (check-out) |

### Champs optionnels

| Champ | Type | Description |
|-------|------|-------------|
| `logementName` | string | Nom du logement |
| `adresseLogement` | string | Adresse complète |
| `operatorFirstName/LastName` | string | Nom de l'opérateur |
| `date_debut/date_fin` | string | Dates du séjour (DD/MM/YY) |
| `voyageur_*` | string | Infos voyageur |
| `etapes` | array | Tâches spécifiques à vérifier |

---

## 📥 Payload de sortie (Webhook reçu)

```json
{
  "reportMetadata": {
    "id": "rapport_id",
    "logement": "Appartement Paris 11",
    "dateDebut": "25/01/26",
    "dateFin": "28/01/26",
    "statut": "Terminé",
    "parcours": "État des lieux voyageur",
    "typeParcours": "voyageur",
    "operateur": "Jean Dupont",
    "etat": 4.2,
    "dateGeneration": "29/01/2026",
    "heureGeneration": "10:30"
  },
  
  "syntheseIA": {
    "globalScore": {
      "score": 4.2,
      "label": "BON",
      "description": "Le logement est globalement en bon état...",
      "scoreExplanation": "Note calculée sur la base de..."
    },
    "summary": {
      "missingItems": ["Télécommande TV"],
      "damages": [],
      "cleanlinessIssues": ["Traces sur le plan de travail"],
      "layoutProblems": []
    },
    "recommendations": [
      "Nettoyer le plan de travail de la cuisine",
      "Vérifier la présence de la télécommande TV"
    ]
  },
  
  "pieces": [
    {
      "pieceId": "uuid-piece",
      "nom": "Cuisine",
      "icon": "🍳",
      "roomType": "cuisine",
      "score": 4.0,
      "scoreLabel": "BON",
      
      "classification": {
        "roomType": "cuisine",
        "roomName": "Cuisine",
        "roomIcon": "🍳",
        "confidence": 95,
        "isValidRoom": true
      },
      
      "issues": [
        {
          "id": "issue-uuid",
          "description": "Traces sur le plan de travail",
          "category": "cleanliness",
          "severity": "low",
          "severityLabel": "faible",
          "confidence": 85,
          "photo": "https://..."
        }
      ]
    }
  ],
  
  "statistics": {
    "totalIssues": 2,
    "issuesByCategory": {
      "cleanliness": 1,
      "missing_item": 1
    },
    "issuesBySeverity": {
      "high": 0,
      "medium": 0,
      "low": 2
    }
  }
}
```

---

## 📊 Catégories de problèmes

| Catégorie | Description | Exemple |
|-----------|-------------|---------|
| `missing_item` | Objet manquant | Télécommande, serviettes |
| `damage` | Dégât/Cassure | Vitre fissurée, trou mur |
| `cleanliness` | Problème de propreté | Traces, poussière |
| `positioning` | Mauvais placement | Meubles déplacés |
| `added_item` | Objet ajouté | Affaires oubliées |
| `wrong_room` | Photos incohérentes | Mauvaise pièce |
| `image_quality` | Photo inutilisable | Floue, mal cadrée |

## 🎯 Niveaux de sévérité

| Sévérité | Label FR | Action |
|----------|----------|--------|
| `high` | `elevee` | Intervention immédiate |
| `medium` | `moyenne` | À corriger rapidement |
| `low` | `faible` | Détail mineur |

---

## ⚙️ Configuration Railway

### Variables d'environnement

#### Service STAGING (Supabase) ✅
```
WEBHOOK_TARGET=supabase
SUPABASE_WEBHOOK_URL_STAGING=https://hjcnfcvecwooxlwficrb.supabase.co/functions/v1/webhook-analyse
SUPABASE_INDIVIDUAL_WEBHOOK_URL_STAGING=https://hjcnfcvecwooxlwficrb.supabase.co/functions/v1/webhook-analyse
```

#### Service PRODUCTION (Bubble) - NE PAS MODIFIER
```
WEBHOOK_TARGET=bubble  (ou non défini = bubble par défaut)
```

### Comment ça marche

```python
def get_webhook_url(environment: str) -> str:
    target = os.environ.get("WEBHOOK_TARGET", "bubble").lower()

    if target == "supabase":
        # Envoie vers Supabase
        return os.environ.get("SUPABASE_WEBHOOK_URL_STAGING", "...")
    else:
        # Envoie vers Bubble (défaut)
        return "https://checkeasy-57905.bubbleapps.io/..."
```

---

## 🚀 Edge Functions Supabase

### 1. trigger-analyse (appeler l'API)

**URL** : `POST https://[PROJET].supabase.co/functions/v1/trigger-analyse`

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "@supabase/supabase-js"

serve(async (req) => {
  const { logement_id, rapport_id } = await req.json()

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  )

  // Récupérer les données depuis Supabase
  const { data: logement } = await supabase
    .from("logements")
    .select("*, pieces(*)")
    .eq("id", logement_id)
    .single()

  // Construire le payload
  const payload = {
    logement_id,
    rapport_id,
    type: "Voyageur",
    logementName: logement.name,
    pieces: logement.pieces.map(p => ({
      piece_id: p.id,
      nom: p.nom,
      checkin_pictures: p.checkin_photos.map(url => ({ piece_id: p.id, url })),
      checkout_pictures: p.checkout_photos.map(url => ({ piece_id: p.id, url }))
    }))
  }

  // Appeler l'API CheckEasy
  const response = await fetch(
    "https://checkeasy-api-v5-staging.up.railway.app/analyze-complete",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }
  )

  return new Response(await response.text(), {
    headers: { "Content-Type": "application/json" }
  })
})
```

### 2. webhook-analyse (recevoir les résultats)

**URL** : `POST https://[PROJET].supabase.co/functions/v1/webhook-analyse`

```typescript
import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "@supabase/supabase-js"

serve(async (req) => {
  const result = await req.json()

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
  )

  // Sauvegarder les résultats
  await supabase
    .from("rapports_analyse")
    .upsert({
      rapport_id: result.reportMetadata.id,
      score_global: result.syntheseIA.globalScore.score,
      score_label: result.syntheseIA.globalScore.label,
      synthese: result.syntheseIA,
      pieces: result.pieces,
      statistics: result.statistics,
      raw_response: result,
      updated_at: new Date().toISOString()
    })

  return new Response(JSON.stringify({ success: true }), {
    headers: { "Content-Type": "application/json" }
  })
})
```

---

## 🗄️ Tables Supabase suggérées

### Table `rapports_analyse`

```sql
CREATE TABLE rapports_analyse (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rapport_id TEXT UNIQUE NOT NULL,
  logement_id TEXT NOT NULL,
  score_global DECIMAL(3,2),
  score_label TEXT,
  synthese JSONB,
  pieces JSONB,
  statistics JSONB,
  raw_response JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index pour recherche rapide
CREATE INDEX idx_rapports_logement ON rapports_analyse(logement_id);
CREATE INDEX idx_rapports_score ON rapports_analyse(score_global);
```

### Table `issues_detectees` (optionnel)

```sql
CREATE TABLE issues_detectees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rapport_id TEXT NOT NULL REFERENCES rapports_analyse(rapport_id),
  piece_id TEXT NOT NULL,
  description TEXT,
  category TEXT CHECK (category IN ('missing_item', 'damage', 'cleanliness', 'positioning', 'added_item', 'wrong_room', 'image_quality')),
  severity TEXT CHECK (severity IN ('low', 'medium', 'high')),
  confidence INTEGER,
  photo_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🧪 Tester l'intégration

### 1. Test manuel avec cURL

```bash
curl -X POST "https://checkeasy-api-v5-staging.up.railway.app/analyze-complete" \
  -H "Content-Type: application/json" \
  -d '{
    "logement_id": "test-123",
    "rapport_id": "rapport-test-123",
    "type": "Voyageur",
    "pieces": [
      {
        "piece_id": "piece-1",
        "nom": "Salon",
        "checkin_pictures": [
          {"piece_id": "piece-1", "url": "https://example.com/before.jpg"}
        ],
        "checkout_pictures": [
          {"piece_id": "piece-1", "url": "https://example.com/after.jpg"}
        ]
      }
    ]
  }'
```

### 2. Vérifier les logs Supabase

```bash
supabase functions logs webhook-analyse
```

### 3. Vérifier la base de données

```sql
SELECT * FROM rapports_analyse WHERE rapport_id = 'rapport-test-123';
```

---

## ⚠️ Points importants

1. **URLs des images** : Doivent être publiquement accessibles (pas d'auth requise)
2. **Temps de traitement** : 15-90 secondes selon le nombre de pièces
3. **Webhook automatique** : Envoyé même si tu reçois déjà la réponse directe
4. **IDs** : Utilise tes UUIDs Supabase pour `logement_id`, `piece_id`, `rapport_id`
5. **Type** : `"Voyageur"` ou `"Ménage"` (critères d'analyse différents)

---

## 🔄 Basculer Production vers Supabase

Quand tu es prêt à migrer la production :

1. **Configurer les variables sur le service production** :
```
WEBHOOK_TARGET=supabase
SUPABASE_WEBHOOK_URL_PROD=https://hjcnfcvecwooxlwficrb.supabase.co/functions/v1/webhook-analyse
SUPABASE_INDIVIDUAL_WEBHOOK_URL_PROD=https://hjcnfcvecwooxlwficrb.supabase.co/functions/v1/webhook-analyse
```

2. **Railway redéploie automatiquement**

3. **Bubble ne recevra plus les webhooks** - Supabase prend le relais !

---

## 📞 Support

- **Documentation API complète** : `DOCUMENTATION.md`
- **Swagger** : `https://checkeasy-api-v5-staging.up.railway.app/docs`
- **Testeur web** : `https://checkeasy-api-v5-staging.up.railway.app/tester`
```

