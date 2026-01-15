#!/bin/bash

# 🚀 Script de démarrage local pour CheckEasy API V5
# ═══════════════════════════════════════════════════

echo "🔧 CheckEasy API V5 - Démarrage en mode LOCAL"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Vérifier que le fichier .env existe
if [ ! -f .env ]; then
    echo "❌ ERREUR: Le fichier .env n'existe pas !"
    echo "📝 Créez-le à partir de .env.example et ajoutez votre clé API OpenAI"
    echo ""
    echo "Commande rapide:"
    echo "  cp .env.example .env"
    echo "  nano .env  # Puis ajoutez votre clé OPENAI_API_KEY"
    echo ""
    exit 1
fi

# Vérifier que la clé API est définie
source .env
if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-proj-VOTRE_CLE_ICI" ]; then
    echo "❌ ERREUR: La clé OPENAI_API_KEY n'est pas définie dans .env !"
    echo "📝 Éditez le fichier .env et ajoutez votre vraie clé API OpenAI"
    echo ""
    echo "Commande:"
    echo "  nano .env"
    echo ""
    exit 1
fi

echo "✅ Fichier .env trouvé"
echo "✅ Clé API OpenAI configurée"
echo ""

# Vérifier que les dépendances sont installées
echo "📦 Vérification des dépendances..."
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "⚠️  Les dépendances ne sont pas installées"
    echo "📦 Installation des dépendances..."
    pip3 install -r requirements.txt
    echo ""
fi

echo "✅ Dépendances installées"
echo ""

# Afficher les informations de configuration
echo "📋 Configuration:"
echo "  • Modèle OpenAI: ${OPENAI_MODEL:-gpt-5.2-2025-12-11 (défaut)}"
echo "  • Version: ${VERSION:-test (défaut)}"
echo "  • Port: 8000"
echo ""

# Démarrer le serveur
echo "🚀 Démarrage du serveur FastAPI..."
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "📍 L'API sera accessible sur:"
echo "   http://localhost:8000"
echo ""
echo "📚 Documentation interactive:"
echo "   http://localhost:8000/docs"
echo ""
echo "🧪 Interface de test:"
echo "   http://localhost:8000/api-tester"
echo ""
echo "📊 Admin des templates:"
echo "   http://localhost:8000/admin"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "💡 Pour arrêter le serveur: Ctrl+C"
echo ""

# Charger les variables d'environnement et démarrer uvicorn
export $(cat .env | grep -v '^#' | xargs)
uvicorn make_request:app --host 0.0.0.0 --port 8000 --reload

