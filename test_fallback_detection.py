#!/usr/bin/env python3
"""Test de détection des erreurs de téléchargement pour le fallback"""

# Simuler les erreurs OpenAI
test_errors = [
    "Error code: 400 - {'error': {'message': 'Timeout while downloading https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1760356972296x100076229364439940/File.jpg.', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_image_url'}}",
    "Error code: 400 - {'error': {'message': 'Error while downloading https://example.com/image.jpg', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_image_url'}}",
    "Error code: 400 - {'error': {'message': 'Failed to download https://example.com/image.jpg', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_image_url'}}",
    "Error code: 400 - {'error': {'message': 'Invalid image format', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_image_format'}}",
]

keywords = [
    "error while downloading",
    "timeout while downloading",
    "invalid_image_url",
    "failed to download"
]

print("=" * 80)
print("TEST DE DÉTECTION DES ERREURS DE TÉLÉCHARGEMENT")
print("=" * 80)

for i, error_str in enumerate(test_errors, 1):
    print(f"\nTest {i}:")
    print(f"Erreur: {error_str[:100]}...")
    
    error_str_lower = error_str.lower()
    
    # Tester chaque keyword
    matches = []
    for keyword in keywords:
        if keyword in error_str_lower:
            matches.append(keyword)
    
    # Tester avec any()
    should_fallback = any(keyword in error_str_lower for keyword in keywords)
    
    print(f"Keywords trouvés: {matches}")
    print(f"Fallback activé: {should_fallback}")
    
    if should_fallback:
        print("✅ FALLBACK DATA URI ACTIVÉ")
    else:
        print("❌ FALLBACK NON ACTIVÉ")

print("\n" + "=" * 80)
print("RÉSUMÉ")
print("=" * 80)
print(f"Total tests: {len(test_errors)}")
print(f"Fallbacks activés: {sum(1 for e in test_errors if any(k in e.lower() for k in keywords))}")

