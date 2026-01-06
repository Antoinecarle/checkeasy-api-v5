# 🧪 Guide d'Utilisation - Test d'Analyse d'Étapes

## 📋 Vue d'ensemble

L'interface de test d'étapes vous permet de tester rapidement l'analyse d'une étape de nettoyage avec des photos réelles, sans avoir à envoyer un payload complet via Postman ou curl.

## 🚀 Comment utiliser

### 1. Accéder à l'interface

1. Démarrez votre serveur API : `uvicorn make_request:app --reload --port 8080`
2. Ouvrez votre navigateur : `http://localhost:8080/tester`
3. Cliquez sur l'onglet **"Test Étapes"** dans la sidebar

### 2. Remplir le formulaire

#### Champs obligatoires :
- **Nom de la tâche** : Le nom de l'étape à vérifier (ex: "Aspirer le sol")
- **Consigne** : Les instructions détaillées (ex: "Sous le lit ; coins de la pièce.")
- **Photo APRÈS (checkout_picture)** : URL de la photo après nettoyage

#### Champs optionnels :
- **Photo AVANT (checking_picture)** : URL de la photo avant nettoyage (si disponible)
- **URL de l'API** : Par défaut `http://localhost:8080/analyze-etapes` (changez pour production si nécessaire)

### 3. Lancer le test

1. Cliquez sur le bouton **"Lancer le Test"**
2. Attendez l'analyse (généralement 3-10 secondes)
3. Les résultats s'affichent automatiquement

## 📊 Comprendre les résultats

### Statistiques
- **Issues détectées** : Nombre de problèmes trouvés
- **Temps de réponse** : Durée de l'analyse en secondes

### Issues détectées

Chaque issue affiche :
- **Catégorie** : Type de problème (cleanliness, positioning, missing_item, etc.)
- **Confiance** : Niveau de certitude de l'IA (70-100%)
- **Description** : Explication détaillée du problème
- **Sévérité** : Gravité (low, medium, high) - indiquée par la couleur

#### Couleurs des issues :
- 🟡 **Jaune** : Sévérité faible (low)
- 🟠 **Orange** : Sévérité moyenne (medium)
- 🔴 **Rouge** : Sévérité élevée (high)

### Aucun problème détecté
Si l'étape est validée, vous verrez :
✅ **"Aucun problème détecté !"**

## 🔍 Exemples d'utilisation

### Exemple 1 : Test avec photo APRÈS uniquement
```
Nom de la tâche : Aspirer le sol
Consigne : Sous le lit ; coins de la pièce.
Photo AVANT : (vide)
Photo APRÈS : https://example.com/photo-apres.jpg
```

L'IA va analyser la photo APRÈS et vérifier si le sol a été aspiré selon la consigne.

### Exemple 2 : Test avec photos AVANT et APRÈS
```
Nom de la tâche : Nettoyer évier
Consigne : Enlever toutes les traces de calcaire
Photo AVANT : https://example.com/evier-avant.jpg
Photo APRÈS : https://example.com/evier-apres.jpg
```

L'IA va comparer les deux photos et vérifier si l'évier a été nettoyé correctement.

## ⚙️ Configuration

### Changer l'URL de l'API

Pour tester en production :
1. Modifiez le champ **"URL de l'API"**
2. Exemple : `https://votre-api.railway.app/analyze-etapes`

### Seuil de confiance

Le seuil de confiance actuel est de **70%**. Les issues avec une confiance inférieure ne sont pas affichées.

Pour modifier ce seuil, éditez `make_request.py` ligne ~5025 :
```python
if issue_data.get("confidence", 0) >= 70:  # Changez 70 par la valeur souhaitée
```

## 🐛 Dépannage

### Erreur : "Veuillez remplir au moins..."
→ Vérifiez que vous avez rempli les champs obligatoires (nom, consigne, photo APRÈS)

### Erreur : "HTTP error! status: 500"
→ Vérifiez les logs du serveur API pour voir l'erreur détaillée

### Erreur : "Failed to fetch"
→ Vérifiez que l'API est bien démarrée et accessible à l'URL configurée

### Aucune issue détectée alors qu'il devrait y en avoir
→ Vérifiez que :
1. La photo est accessible (pas de CORS)
2. La consigne est claire et précise
3. Le seuil de confiance n'est pas trop élevé

## 📝 Format du payload envoyé

```json
{
  "logement_id": "test_logement_1234567890",
  "pieces": [
    {
      "piece_id": "test_piece_1234567890",
      "nom": "Test",
      "commentaire_ia": "",
      "checkin_pictures": [],
      "checkout_pictures": [],
      "etapes": [
        {
          "etape_id": "test_etape_1234567890",
          "task_name": "Aspirer le sol",
          "consigne": "Sous le lit ; coins de la pièce.",
          "checking_picture": "",
          "checkout_picture": "https://example.com/photo.jpg"
        }
      ]
    }
  ]
}
```

## 🎯 Bonnes pratiques

1. **Consignes claires** : Plus la consigne est précise, meilleure sera l'analyse
2. **Photos de qualité** : Utilisez des photos nettes et bien éclairées
3. **Angle pertinent** : La photo doit montrer la zone concernée par la consigne
4. **Test itératif** : Testez plusieurs fois avec différentes photos pour affiner vos prompts

## 📚 Ressources

- Documentation API : `/docs` (Swagger UI)
- Configuration des prompts : `front/prompts-config-voyageur.json`
- Code source : `make_request.py` (ligne 3598 pour l'endpoint)

