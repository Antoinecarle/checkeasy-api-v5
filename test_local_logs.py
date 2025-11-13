#!/usr/bin/env python3
"""
Script de test pour vérifier l'affichage amélioré des logs EN LOCAL
Lance ce script pour voir si l'affichage fonctionne correctement
"""

import logging
import os
import sys

# Simuler un environnement LOCAL (pas Railway)
if 'RAILWAY_ENVIRONMENT' in os.environ:
    del os.environ['RAILWAY_ENVIRONMENT']
if 'RAILWAY_PUBLIC_DOMAIN' in os.environ:
    del os.environ['RAILWAY_PUBLIC_DOMAIN']
if 'RAILWAY_SERVICE_NAME' in os.environ:
    del os.environ['RAILWAY_SERVICE_NAME']

print("🧪 Test de l'affichage amélioré des logs EN LOCAL\n")
print("=" * 70)
print("Environnement détecté :")
print(f"  - RAILWAY_ENVIRONMENT: {os.environ.get('RAILWAY_ENVIRONMENT', 'Non défini')}")
print(f"  - RAILWAY_PUBLIC_DOMAIN: {os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'Non défini')}")
print(f"  - RAILWAY_SERVICE_NAME: {os.environ.get('RAILWAY_SERVICE_NAME', 'Non défini')}")
print(f"  - Terminal interactif: {sys.stderr.isatty()}")
print("=" * 70)
print()

# Configurer le logging de base
logging.basicConfig(level=logging.INFO)

# Activer l'affichage amélioré
try:
    from enable_pretty_logs import enable_pretty_logs
    enable_pretty_logs()
    print("✅ Module enable_pretty_logs importé avec succès\n")
except ImportError as e:
    print(f"❌ Erreur d'import: {e}\n")
    sys.exit(1)

# Créer un logger
logger = logging.getLogger(__name__)

# Simuler des logs d'analyse
print("\n🎬 Simulation de logs d'analyse...\n")

logger.info("🚀 ANALYSE COMPLÈTE démarrée pour le logement TEST_001 (parcours: Voyageur)")

# Pièce 1
logger.info("🔍 Analyse de la pièce room_001: Chambre principale", extra={'piece_id': 'room_001'})
logger.info("📊 ÉTAPE 1 - Classification automatique pour room_001")
logger.info("Classification terminée pour la pièce room_001: chambre (confiance: 95%)", extra={'piece_id': 'room_001'})

logger.info("🔧 ÉTAPE 2 - Injection des critères automatiques dans le payload d'analyse", extra={'piece_id': 'room_001'})
logger.info("📌 INJECTION DES CRITÈRES:", extra={'piece_id': 'room_001'})
logger.info("   🔍 Éléments critiques injectés (3): ['propreté', 'ordre', 'état']", extra={'piece_id': 'room_001'})
logger.info("   ➖ Points ignorables injectés (2): ['usure normale', 'décoration']", extra={'piece_id': 'room_001'})
logger.info("   ⚠️ Défauts fréquents injectés (4): ['taches', 'poussière', 'désordre', 'odeur']", extra={'piece_id': 'room_001'})

logger.info("🖼️ ÉTAPE 3 - Traitement des images pour la pièce room_001", extra={'piece_id': 'room_001'})
logger.info("OpenAI request - Model: gpt-4.1-2025-04-14, Tokens: 1500", extra={'piece_id': 'room_001'})

logger.info("📋 ÉTAPE 5 - Parsing & validation JSON pour room_001", extra={'piece_id': 'room_001'})
logger.info("✅ Analyse terminée: Score 8/10, 2 problèmes détectés", extra={'piece_id': 'room_001'})

# Pièce 2
logger.info("🔍 Analyse de la pièce room_002: Cuisine", extra={'piece_id': 'room_002'})
logger.info("📊 ÉTAPE 1 - Classification automatique pour room_002")
logger.info("Classification terminée pour la pièce room_002: cuisine (confiance: 92%)", extra={'piece_id': 'room_002'})

logger.info("🔧 ÉTAPE 2 - Injection des critères automatiques dans le payload d'analyse", extra={'piece_id': 'room_002'})
logger.info("📌 INJECTION DES CRITÈRES:", extra={'piece_id': 'room_002'})
logger.info("   🔍 Éléments critiques injectés (3): ['propreté', 'ordre', 'état']", extra={'piece_id': 'room_002'})

logger.info("🖼️ ÉTAPE 3 - Traitement des images pour la pièce room_002", extra={'piece_id': 'room_002'})
logger.info("OpenAI request - Model: gpt-4.1-2025-04-14, Tokens: 1800", extra={'piece_id': 'room_002'})

# Simuler un warning
logger.warning("⚠️ Qualité d'image moyenne détectée pour room_002", extra={'piece_id': 'room_002'})

logger.info("📋 ÉTAPE 5 - Parsing & validation JSON pour room_002", extra={'piece_id': 'room_002'})
logger.info("✅ Analyse terminée: Score 6/10, 5 problèmes détectés", extra={'piece_id': 'room_002'})

# Pièce 3 avec erreur
logger.info("🔍 Analyse de la pièce room_003: Salle de bain", extra={'piece_id': 'room_003'})
logger.info("📊 ÉTAPE 1 - Classification automatique pour room_003")
logger.info("Classification terminée pour la pièce room_003: salle de bain (confiance: 98%)", extra={'piece_id': 'room_003'})

logger.info("🖼️ ÉTAPE 3 - Traitement des images pour la pièce room_003", extra={'piece_id': 'room_003'})
logger.error("❌ Erreur lors du traitement de l'image 2 pour room_003", extra={'piece_id': 'room_003'})

logger.info("✅ Analyse terminée: Score 4/10, 8 problèmes détectés", extra={'piece_id': 'room_003'})

logger.info("🎉 ANALYSE COMPLÈTE terminée pour le logement TEST_001")

print("\n" + "=" * 70)
print("✅ Test terminé !")
print("=" * 70)
print()
print("💡 Si tu vois un affichage structuré avec des couleurs et des emojis,")
print("   c'est que l'affichage amélioré fonctionne correctement !")
print()
print("📝 Note : Sur Railway, les logs seront en format JSON (c'est normal).")
print()

