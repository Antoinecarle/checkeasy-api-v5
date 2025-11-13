#!/usr/bin/env python3
"""Test de la fonction normalize_url avec les URLs problématiques"""

import re

def normalize_url(url: str) -> str:
    """
    Normalise une URL en corrigeant les problèmes courants
    """
    if not url or not isinstance(url, str):
        return url

    # Nettoyer les espaces
    url = url.strip()
    
    print(f"🔍 URL après strip: '{url}'")
    print(f"🔍 Premiers 20 chars: {repr(url[:20])}")

    # Cas 1: URL commence par "//" (protocole manquant)
    if url.startswith('//'):
        print(f"✅ Cas 1 détecté: URL commence par //")
        url = 'https:' + url
        print(f"✅ Après Cas 1: {url}")

    # Cas 2: Double protocole "https:https://"
    if url.startswith('https:https://'):
        print(f"✅ Cas 2 détecté: Double protocole https:https://")
        url = url.replace('https:https://', 'https://', 1)
        print(f"✅ Après Cas 2: {url}")
    elif url.startswith('http:http://'):
        print(f"✅ Cas 2 détecté: Double protocole http:http://")
        url = url.replace('http:http://', 'http://', 1)
        print(f"✅ Après Cas 2: {url}")

    # Cas 3: Protocole sans slashes "https:cdn.bubble.io"
    if re.match(r'^https?:[^/]', url):
        print(f"✅ Cas 3 détecté: Protocole sans slashes")
        url = url.replace('https:', 'https://', 1).replace('http:', 'http://', 1)
        print(f"✅ Après Cas 3: {url}")

    # Cas 4: Caractères problématiques en fin d'URL
    original_url = url
    while url and len(url) > 0:
        last_char = url[-1]
        if last_char == '.':
            filename = url.split('/')[-1]
            if '.' in filename[:-1]:
                url = url[:-1]
                continue
            else:
                break
        elif last_char in [',', ';', ':', '!', '?', ' ']:
            url = url[:-1]
            continue
        break

    if url != original_url:
        print(f"✅ Cas 4 détecté: Caractères en fin d'URL")
        print(f"✅ Après Cas 4: {original_url} -> {url}")

    return url

# Test avec les URLs problématiques
print("=" * 80)
print("TEST 1: URL avec double protocole https:https://")
print("=" * 80)
url1 = "https:https://a0.muscache.com/im/pictures/miso/Hosting-1437486592415063469/original/10665544-6263-4eb6-9d1d-37474a403b25.jpeg"
print(f"URL originale: {url1}")
result1 = normalize_url(url1)
print(f"URL normalisée: {result1}")
print()

print("=" * 80)
print("TEST 2: URL avec point en fin")
print("=" * 80)
url2 = "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1760354846752x710226594438164100/File.jpeg."
print(f"URL originale: {url2}")
result2 = normalize_url(url2)
print(f"URL normalisée: {result2}")
print()

print("=" * 80)
print("TEST 3: URL normale (contrôle)")
print("=" * 80)
url3 = "https://eb0bcaf95c312d7fe9372017cb5f1835.cdn.bubble.io/f1756976227449x921014691220175500/IMG_0754.jpg"
print(f"URL originale: {url3}")
result3 = normalize_url(url3)
print(f"URL normalisée: {result3}")

