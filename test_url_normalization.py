#!/usr/bin/env python3
"""
Test de normalisation des URLs pour les images AVIF de Bubble
"""

from image_converter import normalize_url, is_valid_image_url

def test_url_normalization():
    """Teste la normalisation des URLs problématiques de Bubble"""
    
    print("🧪 Test de normalisation des URLs\n")
    print("=" * 70)
    
    # Cas de test : URLs qui commencent par //
    test_cases = [
        {
            "name": "URL AVIF Bubble avec //",
            "input": "//eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1763417923718x601587939146102800/e43314a0-b225-4fdf-9cb1-b49b1aa17d1b.avif",
            "expected": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1763417923718x601587939146102800/e43314a0-b225-4fdf-9cb1-b49b1aa17d1b.avif"
        },
        {
            "name": "URL JPG Bubble avec //",
            "input": "//eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1763993470109x581599532674915500/image.jpg",
            "expected": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1763993470109x581599532674915500/image.jpg"
        },
        {
            "name": "URL normale avec https://",
            "input": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1767448559358x500723038352564100/File.jpg",
            "expected": "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1767448559358x500723038352564100/File.jpg"
        },
        {
            "name": "URL avec un seul /",
            "input": "/image.jpg",
            "expected": "/image.jpg"  # Reste invalide
        },
        {
            "name": "URL vide",
            "input": "",
            "expected": ""
        }
    ]
    
    passed = 0
    failed = 0
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n📝 Test {i}: {test['name']}")
        print(f"   Input:    {test['input'][:80]}...")
        
        result = normalize_url(test['input'])
        
        print(f"   Expected: {test['expected'][:80]}...")
        print(f"   Result:   {result[:80] if result else 'None'}...")
        
        if result == test['expected']:
            print(f"   ✅ PASS")
            passed += 1
        else:
            print(f"   ❌ FAIL")
            failed += 1
        
        # Test de validation
        if test['input']:
            is_valid = is_valid_image_url(result)
            print(f"   Validation: {'✅ Valide' if is_valid else '❌ Invalide'}")
    
    print("\n" + "=" * 70)
    print(f"\n📊 Résultats: {passed} réussis, {failed} échoués sur {len(test_cases)} tests")
    
    if failed == 0:
        print("✅ Tous les tests sont passés !")
    else:
        print(f"❌ {failed} test(s) ont échoué")
    
    return failed == 0


if __name__ == "__main__":
    success = test_url_normalization()
    exit(0 if success else 1)

