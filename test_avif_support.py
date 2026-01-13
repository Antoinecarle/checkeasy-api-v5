#!/usr/bin/env python3
"""
Test du support AVIF dans le système de conversion d'images
"""

import sys
import logging
from image_converter import (
    SUPPORTED_FORMATS, 
    CONVERSION_FORMATS,
    detect_image_format_enhanced,
    ImageConverter
)

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_avif_in_formats():
    """Vérifie que AVIF est dans les formats de conversion"""
    logger.info("🧪 Test 1: Vérification de la présence d'AVIF dans CONVERSION_FORMATS")
    
    if 'avif' in CONVERSION_FORMATS:
        logger.info("✅ AVIF est bien dans CONVERSION_FORMATS")
        logger.info(f"   Formats de conversion: {CONVERSION_FORMATS}")
        return True
    else:
        logger.error("❌ AVIF n'est PAS dans CONVERSION_FORMATS")
        logger.error(f"   Formats de conversion: {CONVERSION_FORMATS}")
        return False

def test_avif_signature_detection():
    """Teste la détection de signature AVIF"""
    logger.info("\n🧪 Test 2: Détection de signature AVIF")
    
    # Signature AVIF typique (simplifié pour le test)
    # Format réel: ftyp + avif dans les premiers 32 bytes
    avif_signature = b'\x00\x00\x00\x20ftypavif\x00\x00\x00\x00'
    
    try:
        import io
        detected_format = detect_image_format_enhanced(io.BytesIO(avif_signature))
        
        if detected_format == 'avif':
            logger.info("✅ Signature AVIF correctement détectée")
            return True
        else:
            logger.warning(f"⚠️ Format détecté: {detected_format} (attendu: 'avif')")
            logger.info("   Note: La signature de test peut être trop simple")
            return False
    except Exception as e:
        logger.error(f"❌ Erreur lors de la détection: {e}")
        return False

def test_avif_url_detection():
    """Teste la détection d'AVIF depuis une URL"""
    logger.info("\n🧪 Test 3: Détection d'AVIF depuis URL")
    
    test_urls = [
        "https://example.com/image.avif",
        "https://example.com/photo.AVIF",
        "https://cdn.example.com/assets/image.avif?v=123",
    ]
    
    all_passed = True
    for url in test_urls:
        detected_format = ImageConverter.get_image_format_from_url(url)
        if detected_format == 'avif':
            logger.info(f"✅ Format AVIF détecté depuis: {url}")
        else:
            logger.warning(f"⚠️ Format détecté: {detected_format} pour {url}")
            all_passed = False
    
    return all_passed

def test_conversion_workflow():
    """Teste le workflow complet de conversion"""
    logger.info("\n🧪 Test 4: Workflow de conversion AVIF")
    
    logger.info("📋 Formats supportés (pas de conversion):")
    logger.info(f"   {SUPPORTED_FORMATS}")
    
    logger.info("📋 Formats nécessitant conversion:")
    logger.info(f"   {CONVERSION_FORMATS}")
    
    # Vérifier que AVIF n'est PAS dans les formats supportés
    if 'avif' not in SUPPORTED_FORMATS:
        logger.info("✅ AVIF n'est pas dans SUPPORTED_FORMATS (correct)")
    else:
        logger.error("❌ AVIF est dans SUPPORTED_FORMATS (devrait être dans CONVERSION_FORMATS)")
        return False
    
    # Vérifier que AVIF EST dans les formats de conversion
    if 'avif' in CONVERSION_FORMATS:
        logger.info("✅ AVIF est dans CONVERSION_FORMATS (correct)")
        return True
    else:
        logger.error("❌ AVIF n'est pas dans CONVERSION_FORMATS")
        return False

def main():
    """Exécute tous les tests"""
    logger.info("=" * 70)
    logger.info("🚀 TESTS DU SUPPORT AVIF")
    logger.info("=" * 70)
    
    results = {
        "Formats de conversion": test_avif_in_formats(),
        "Détection de signature": test_avif_signature_detection(),
        "Détection depuis URL": test_avif_url_detection(),
        "Workflow de conversion": test_conversion_workflow(),
    }
    
    logger.info("\n" + "=" * 70)
    logger.info("📊 RÉSULTATS DES TESTS")
    logger.info("=" * 70)
    
    for test_name, passed in results.items():
        status = "✅ PASSÉ" if passed else "❌ ÉCHOUÉ"
        logger.info(f"{status} - {test_name}")
    
    total_passed = sum(results.values())
    total_tests = len(results)
    
    logger.info("\n" + "=" * 70)
    logger.info(f"🎯 RÉSULTAT GLOBAL: {total_passed}/{total_tests} tests passés")
    logger.info("=" * 70)
    
    if total_passed == total_tests:
        logger.info("🎉 Tous les tests sont passés ! Le support AVIF est opérationnel.")
        return 0
    else:
        logger.warning(f"⚠️ {total_tests - total_passed} test(s) échoué(s)")
        return 1

if __name__ == "__main__":
    sys.exit(main())

