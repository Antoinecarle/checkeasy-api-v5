# 🧪 Comment Tester l'Affichage Amélioré en Local

## ⚠️ IMPORTANT

L'affichage amélioré des logs fonctionne **UNIQUEMENT EN LOCAL** sur ton ordinateur.

Sur **Railway**, les logs restent en format JSON (c'est normal et optimal pour la production).

---

## 🚀 Étapes pour Tester en Local

### 1. Ouvrir un terminal sur ton ordinateur

Ouvre PowerShell ou CMD sur Windows.

### 2. Aller dans le dossier du projet

```bash
cd "C:\Users\admin\Dropbox\CHECKEASY\API V5 FINETUNED"
```

### 3. Installer les dépendances (si pas déjà fait)

```bash
pip install tqdm colorama
```

### 4. Lancer l'application EN LOCAL

**Option A : Avec uvicorn (recommandé)**
```bash
uvicorn make_request:app --reload --host 0.0.0.0 --port 8000
```

**Option B : Directement avec Python**
```bash
python make_request.py
```

### 5. Faire une requête de test

Ouvre un autre terminal et fais une requête vers `http://localhost:8000/analyze-complete`

Ou utilise Postman/Insomnia pour envoyer une requête POST.

---

## ✅ Ce que tu verras

Dans le terminal où tu as lancé l'application, tu verras :

```
╔══════════════════════════════════════════════════════════════╗
║     CheckEasy - Affichage Amélioré des Logs Activé          ║
╚══════════════════════════════════════════════════════════════╝

🏠 Analyse des pièces:   0%|                    | 0/5 [00:00<?, ?pièce/s]

======================================================================
🛏️ CHAMBRE PRINCIPALE (ID: room_001)
======================================================================

├─ 🔍 ÉTAPE 1: Classification automatique
   ✅ Classification terminée: chambre (confiance: 95%)

├─ 💉 ÉTAPE 2: Injection des critères
   💉 Injection des critères:
      🔍 3 éléments critiques
      ➖ 2 points ignorables

├─ 🖼️ ÉTAPE 3: Traitement des images
   🤖 OpenAI: gpt-4.1-2025-04-14 (1500 tokens)

└─ 🌟 RÉSULTAT: Score 8/10 — 2 anomalies détectées

🏠 Analyse des pièces:  20%|████| 1/5 [00:03<00:12, 3.5s/pièce]
```

---

## 🌐 Sur Railway

Sur Railway, les logs resteront comme avant :

```json
{"timestamp":"2025-11-12T14:30:22.123Z","level":"INFO","message":"Analyse de la pièce room_001"}
```

**C'est normal !** Le format JSON est optimal pour :
- Les systèmes de monitoring
- L'analyse automatique des logs
- La recherche et le filtrage
- Les environnements de production

---

## 🎯 Résumé

| Environnement | Format des Logs | Affichage Amélioré |
|---------------|-----------------|-------------------|
| **Local** (ton PC) | Structuré, coloré, avec emojis | ✅ OUI |
| **Railway** (production) | JSON structuré | ❌ NON (normal) |

---

## 💡 Astuce

Pour tester rapidement sans lancer toute l'application, utilise la démo :

```bash
python demo_pretty_logs.py
```

Cela te montrera exactement ce que tu verras en local quand tu lanceras l'application !

