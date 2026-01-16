import requests
import io
import base64
import tempfile
import os
from PIL import Image
import logging
from typing import Optional, Tuple, List
from urllib.parse import urlparse, parse_qs
import pillow_heif
import re

# Configuration du logging
logger = logging.getLogger(__name__)

# Enregistrer le support HEIF/HEIC avec Pillow
try:
    pillow_heif.register_heif_opener()
    logger.info("✅ Support HEIF/HEIC activé au démarrage du module")
except Exception as e:
    logger.error(f"❌ Erreur lors de l'activation du support HEIF/HEIC: {e}")

def ensure_heif_support():
    """
    S'assure que le support HEIF est activé
    À appeler avant chaque opération critique sur des images HEIC
    """
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return True
    except ImportError:
        logger.warning("⚠️ pillow_heif non disponible")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'activation HEIF: {e}")
        return False

# Formats supportés par OpenAI Vision API
SUPPORTED_FORMATS = {'png', 'jpeg', 'jpg', 'gif', 'webp'}

# Formats qui nécessitent une conversion
CONVERSION_FORMATS = {'heic', 'heif', 'bmp', 'tiff', 'tif', 'avif'}

def normalize_url(url: str) -> str:
    """
    Normalise une URL en corrigeant les problèmes courants

    Args:
        url: L'URL à normaliser

    Returns:
        str: URL normalisée
    """
    if not url or not isinstance(url, str):
        return url

    # Nettoyer les espaces
    url = url.strip()

    # Cas 1: URL commence par "//" (protocole manquant)
    # Exemple: "//cdn.bubble.io/image.jpg" -> "https://cdn.bubble.io/image.jpg"
    if url.startswith('//'):
        logger.info(f"🔧 Correction URL Bubble: {url[:60]}... → https:{url[:60]}...")
        url = 'https:' + url
    elif url.startswith('/'):
        # Cas où l'URL commence par un seul slash (chemin relatif invalide)
        logger.warning(f"⚠️ URL invalide (commence par /): {url[:80]}")

    # Cas 2: Double protocole "https:https://"
    # Exemple: "https:https://cdn.bubble.io/image.jpg" -> "https://cdn.bubble.io/image.jpg"
    if url.startswith('https:https://'):
        logger.info(f"🔧 Correction du double protocole: {url}")
        url = url.replace('https:https://', 'https://', 1)
    elif url.startswith('http:http://'):
        logger.info(f"🔧 Correction du double protocole: {url}")
        url = url.replace('http:http://', 'http://', 1)

    # Cas 3: Protocole sans slashes "https:cdn.bubble.io"
    # Exemple: "https:cdn.bubble.io/image.jpg" -> "https://cdn.bubble.io/image.jpg"
    if re.match(r'^https?:[^/]', url):
        logger.info(f"🔧 Ajout des slashes manquants: {url}")
        url = url.replace('https:', 'https://', 1).replace('http:', 'http://', 1)

    # Cas 4: Caractères problématiques en fin d'URL
    # Exemple: "image.jpg." -> "image.jpg" ou "image.jpg," -> "image.jpg"
    original_url = url

    # Supprimer les points, virgules, etc. en fin d'URL
    # Mais garder le point de l'extension (ex: .jpg, .png)
    while url and len(url) > 0:
        last_char = url[-1]

        # Si c'est un point
        if last_char == '.':
            # Vérifier si c'est un double point (ex: .jpg.)
            # En regardant s'il y a déjà un point dans le nom de fichier
            filename = url.split('/')[-1]  # Dernière partie après /
            # Si le nom de fichier a déjà un point avant le dernier caractère
            if '.' in filename[:-1]:
                # C'est un point en trop, on le supprime
                url = url[:-1]
                continue
            else:
                # C'est le point de l'extension, on le garde
                break

        # Pour les autres caractères problématiques, toujours supprimer
        elif last_char in [',', ';', ':', '!', '?', ' ']:
            url = url[:-1]
            continue

        # Caractère normal, on arrête
        break

    if url != original_url:
        logger.info(f"🔧 Nettoyage des caractères en fin d'URL: {original_url} -> {url}")

    return url

def is_valid_image_url(url: str) -> bool:
    """
    Valide si une URL d'image est correctement formée et potentiellement accessible

    Args:
        url: L'URL à valider

    Returns:
        bool: True si l'URL semble valide, False sinon
    """
    try:
        # Vérifications de base
        if not url or not isinstance(url, str):
            logger.warning(f"⚠️ URL invalide: vide ou non-string: {url}")
            return False

        # Normaliser l'URL (corriger les problèmes courants)
        url = normalize_url(url)
        
        # Vérifier les cas problématiques courants
        invalid_patterns = [
            r'^https?:$',  # Juste "http:" ou "https:"
            r'^https?://$',  # "http://" ou "https://" sans rien après
            r'^https?://\s*$',  # Avec espaces
        ]
        
        for pattern in invalid_patterns:
            if re.match(pattern, url, re.IGNORECASE):
                logger.warning(f"⚠️ URL invalide détectée (pattern): {url}")
                return False
        
        # Vérification avec urlparse
        parsed = urlparse(url)
        
        # Vérifier le schéma
        if parsed.scheme not in ['http', 'https', 'data']:
            logger.warning(f"⚠️ Schéma URL non supporté: {parsed.scheme} dans {url}")
            return False
        
        # Pour les data URIs, vérification spéciale
        if parsed.scheme == 'data':
            if 'image/' not in url[:50]:  # Vérifier au début de l'URL
                logger.warning(f"⚠️ Data URI non-image: {url[:100]}...")
                return False
            return True
        
        # Vérifier le hostname pour http/https
        if not parsed.netloc:
            logger.warning(f"⚠️ Pas de hostname dans l'URL: {url}")
            return False
        
        # Vérifier la longueur minimale
        if len(url) < 10:
            logger.warning(f"⚠️ URL trop courte: {url}")
            return False
        
        # Vérifier les caractères suspects
        if any(char in url for char in [' ', '\n', '\r', '\t']):
            logger.warning(f"⚠️ Caractères suspects dans l'URL: {repr(url)}")
            return False
        
        logger.debug(f"✅ URL validée: {url}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la validation de l'URL {url}: {e}")
        return False

def create_placeholder_image_url() -> str:
    """
    Crée une image placeholder en data URI pour remplacer les images invalides
    
    Returns:
        str: Data URI d'une image placeholder
    """
    try:
        # Créer une image simple 100x100 avec texte "Image indisponible"
        img = Image.new('RGB', (100, 100), color='lightgray')
        
        # Convertir en base64
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=80)
        img_data = buffer.getvalue()
        
        base64_data = base64.b64encode(img_data).decode('utf-8')
        data_uri = f'data:image/jpeg;base64,{base64_data}'
        
        return data_uri
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création du placeholder: {e}")
        # Fallback : data URI très simple
        return "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"

class ImageConverter:
    """
    Convertisseur d'images pour assurer la compatibilité avec OpenAI Vision API
    """
    
    @staticmethod
    def get_image_format_from_url(url: str) -> Optional[str]:
        """
        Détermine le format d'image depuis l'URL avec détection optimisée HEIC/HEIF
        """
        try:
            # Extraire l'extension du nom de fichier
            parsed_url = urlparse(url)
            path = parsed_url.path.lower()
            
            # Extraire l'extension
            if '.' in path:
                extension = path.split('.')[-1]
                # Nettoyer l'extension des paramètres
                if '?' in extension:
                    extension = extension.split('?')[0]
                if '#' in extension:
                    extension = extension.split('#')[0]
                
                # Normaliser les formats HEIC/HEIF
                if extension in ['heic', 'heif', 'heix', 'heics']:
                    logger.info(f"🎯 Format HEIC/HEIF détecté depuis l'URL: {extension}")
                    # Activer immédiatement le support HEIF
                    ensure_heif_support()
                    return 'heic'  # Normaliser vers 'heic'
                
                logger.info(f"🔍 Format détecté depuis URL: {extension}")
                return extension
            
            return None
        except Exception as e:
            logger.warning(f"⚠️ Impossible de déterminer le format depuis l'URL: {e}")
            return None
    
    @staticmethod
    def detect_image_format_from_content(image_data: bytes) -> Optional[str]:
        """
        Détecte le format d'image depuis le contenu binaire
        """
        try:
            # S'assurer que le support HEIF est activé avant chaque détection
            ensure_heif_support()
            
            with Image.open(io.BytesIO(image_data)) as img:
                detected_format = img.format.lower() if img.format else None
                logger.info(f"🔍 Format détecté depuis le contenu: {detected_format}")
                return detected_format
        except Exception as e:
            logger.warning(f"⚠️ Impossible de détecter le format d'image: {e}")
            
            # Tentative de détection alternative par les premiers bytes
            try:
                # Vérification des signatures de fichier (magic bytes)
                # ⚠️ IMPORTANT: Vérifier AVIF AVANT HEIC car les deux utilisent 'ftyp'
                if len(image_data) >= 12:
                    # AVIF signature (PRIORITÉ 1)
                    if b'ftyp' in image_data[:20] and b'avif' in image_data[:32]:
                        logger.info("🔍 Format AVIF détecté par signature")
                        return 'avif'
                    # HEIC/HEIF signature - vérification plus robuste (PRIORITÉ 2)
                    elif (b'ftyp' in image_data[:20] and
                        (b'heic' in image_data[:32] or b'mif1' in image_data[:32] or
                         b'heif' in image_data[:32] or b'heix' in image_data[:32])):
                        logger.info("🔍 Format HEIC/HEIF détecté par signature")
                        return 'heic'
                    # JPEG signature
                    elif image_data[:2] == b'\xff\xd8':
                        logger.info("🔍 Format JPEG détecté par signature")
                        return 'jpeg'
                    # PNG signature
                    elif image_data[:8] == b'\x89PNG\r\n\x1a\n':
                        logger.info("🔍 Format PNG détecté par signature")
                        return 'png'
                    # GIF signature
                    elif image_data[:6] in [b'GIF87a', b'GIF89a']:
                        logger.info("🔍 Format GIF détecté par signature")
                        return 'gif'
                    # WebP signature
                    elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
                        logger.info("🔍 Format WebP détecté par signature")
                        return 'webp'
                
                logger.warning("⚠️ Format d'image non identifiable")
                return None
                
            except Exception as signature_error:
                logger.error(f"❌ Erreur lors de la détection par signature: {signature_error}")
                return None
    
    @staticmethod
    def download_image(url: str) -> Tuple[bytes, Optional[str]]:
        """
        Télécharge une image et détecte son format
        """
        try:
            logger.info(f"⬇️ Téléchargement de l'image: {url}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            image_data = response.content
            logger.info(f"📥 Image téléchargée: {len(image_data)} bytes")
            
            # Vérifier que nous avons bien des données
            if not image_data:
                raise ValueError("Image téléchargée vide")
            
            # Détecter le format depuis le contenu (plus fiable)
            detected_format = ImageConverter.detect_image_format_from_content(image_data)
            
            # Si pas détecté depuis le contenu, essayer depuis l'URL
            if not detected_format:
                logger.warning("⚠️ Format non détecté depuis le contenu, tentative depuis l'URL")
                detected_format = ImageConverter.get_image_format_from_url(url)
                if detected_format:
                    logger.info(f"🎯 Format détecté depuis l'URL: {detected_format}")
            
            if detected_format:
                logger.info(f"✅ Format final détecté: {detected_format}")
            else:
                logger.warning("⚠️ Aucun format détecté, traitement en mode unknown")
            
            return image_data, detected_format
            
        except requests.exceptions.RequestException as req_error:
            logger.error(f"❌ Erreur de requête lors du téléchargement de {url}: {req_error}")
            raise
        except Exception as e:
            logger.error(f"❌ Erreur lors du téléchargement de l'image {url}: {e}")
            raise
    
    @staticmethod
    def convert_image_to_jpeg_for_ai(image_data: bytes, max_quality: bool = True) -> bytes:
        """
        🎯 CONVERSION IA-OPTIMISÉE v2025 - Utilise les librairies modernes pour HEIC
        
        Args:
            image_data: Données binaires de l'image source
            max_quality: Si True, utilise la qualité maximale pour l'IA (défaut)
            
        Returns:
            bytes: Image JPEG optimisée pour l'analyse IA
        """
        try:
            import io
            from PIL import Image
            
            # DÉTECTION DU FORMAT AVANT TRAITEMENT
            image_format = detect_image_format_enhanced(io.BytesIO(image_data))
            logger.info(f"🔍 Format détecté: {image_format}")

            # === TRAITEMENT SPÉCIAL HEIC AVEC LIBRAIRIES MODERNES ===
            if image_format and image_format.lower() in ['heic', 'heif']:
                logger.info("🚀 Utilisation des librairies modernes 2025 pour HEIC")

                success, converted_result = convert_heic_with_modern_libraries(
                    image_data,
                    max_size=(4096, 4096),
                    quality=98 if max_quality else 90
                )

                if success:
                    logger.info("✅ Conversion HEIC moderne réussie")
                    return converted_result.getvalue()
                else:
                    logger.error(f"❌ Échec conversion HEIC moderne: {converted_result}")
                    # Fallback vers le traitement normal
                    logger.info("🔄 Tentative de fallback avec PIL classique")

            # === TRAITEMENT SPÉCIAL AVIF ===
            if image_format and image_format.lower() == 'avif':
                logger.info("🎨 Conversion AVIF → JPEG pour compatibilité OpenAI")

                try:
                    # Méthode 1: Essayer avec pillow-avif-plugin si disponible
                    try:
                        import pillow_avif
                        # Le plugin s'enregistre automatiquement à l'import
                        logger.info("✅ Plugin AVIF (pillow-avif) activé")
                    except ImportError:
                        logger.warning("⚠️ pillow-avif non installé, tentative avec imageio")
                    except Exception as plugin_error:
                        logger.warning(f"⚠️ Erreur plugin AVIF: {plugin_error}, tentative avec imageio")

                    # Méthode 2: Utiliser imageio comme fallback
                    try:
                        import imageio.v3 as iio
                        logger.info("🔄 Conversion AVIF avec imageio...")

                        # Lire l'image AVIF avec imageio
                        img_array = iio.imread(io.BytesIO(image_data))

                        # Convertir en PIL Image
                        img = Image.fromarray(img_array)

                        # Convertir en RGB si nécessaire
                        if img.mode in ('RGBA', 'LA'):
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'RGBA':
                                background.paste(img, mask=img.split()[-1])
                            else:
                                background.paste(img, mask=img.split()[1])
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')

                        # Sauvegarder en JPEG haute qualité
                        output = io.BytesIO()
                        img.save(output, format='JPEG', quality=98, optimize=True)
                        output.seek(0)

                        logger.info("✅ Conversion AVIF réussie avec imageio")
                        return output.getvalue()

                    except Exception as imageio_error:
                        logger.error(f"❌ Échec conversion AVIF avec imageio: {imageio_error}")
                        # Continuer avec le traitement normal (peut échouer)
                        logger.info("🔄 Tentative de fallback avec PIL standard")

                except Exception as avif_error:
                    logger.error(f"❌ Erreur lors du traitement AVIF: {avif_error}")
                    # Continuer avec le traitement normal

            # === TRAITEMENT NORMAL POUR AUTRES FORMATS ===
            # S'assurer que le support HEIF est activé avant la conversion
            if ensure_heif_support():
                logger.info("✅ Support HEIF confirmé pour la conversion")
            else:
                logger.warning("⚠️ Support HEIF non disponible, formats HEIC non supportés")
            
            with Image.open(io.BytesIO(image_data)) as img:
                logger.info(f"🔄 Conversion IA-optimisée: {img.format} {img.size} {img.mode}")
                
                # ÉTAPE 1: Préservation des informations colorimétriques
                # Convertir en RGB en préservant au maximum la qualité
                if img.mode in ('RGBA', 'LA'):
                    # Pour les images avec transparence, créer un fond blanc de haute qualité
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    # Utiliser un alpha blending de qualité
                    background.paste(img, mask=img.split()[-1])
                    img = background
                    logger.info("✅ Conversion RGBA→RGB avec alpha blending de qualité")
                elif img.mode == 'P':
                    # Pour les images palette, convertir avec préservation des couleurs
                    img = img.convert('RGB')
                    logger.info("✅ Conversion palette→RGB")
                elif img.mode in ('L', 'LA'):
                    # Pour les images en niveaux de gris, convertir en RGB
                    img = img.convert('RGB')
                    logger.info("✅ Conversion niveaux de gris→RGB")
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                    logger.info(f"✅ Conversion {img.mode}→RGB")
                
                # ÉTAPE 2: Correction d'orientation EXIF
                # Tag EXIF 274 = Orientation (standard EXIF)
                EXIF_ORIENTATION_TAG = 274
                try:
                    exif = img.getexif()
                    if exif:
                        orientation = exif.get(EXIF_ORIENTATION_TAG)
                        if orientation and orientation != 1:
                            # Appliquer les rotations selon les standards EXIF
                            if orientation == 2:
                                img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            elif orientation == 3:
                                img = img.rotate(180, expand=True)
                            elif orientation == 4:
                                img = img.rotate(180, expand=True).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            elif orientation == 5:
                                img = img.rotate(-90, expand=True).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            elif orientation == 6:
                                img = img.rotate(-90, expand=True)
                            elif orientation == 7:
                                img = img.rotate(90, expand=True).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                            elif orientation == 8:
                                img = img.rotate(90, expand=True)
                            logger.debug(f"✅ Orientation EXIF corrigée: {orientation}")

                except (AttributeError, KeyError, TypeError) as exif_error:
                    logger.debug(f"ℹ️ Pas de métadonnées EXIF: {exif_error}")
                
                # ÉTAPE 3: Redimensionnement intelligent pour l'IA
                # OpenAI Vision peut traiter des images jusqu'à 20MB, donc on peut être plus généreux
                original_size = img.size
                max_dimension = 4096  # Plus généreux pour l'IA (était 2048)
                min_dimension = 512   # Assurer une résolution minimale décente

                # Calculer les nouvelles dimensions en préservant le ratio
                width, height = img.size

                # UPSCALING pour images trop petites (utilise OR au lieu de AND)
                if width < min_dimension or height < min_dimension:
                    # Utiliser la fonction d'upscaling dédiée avec amélioration de la netteté
                    img = upscale_image_for_ai(img, min_size=(min_dimension, min_dimension), logger=logger)
                    logger.info(f"� Image agrandie pour l'IA: {original_size} → {img.size}")

                # DOWNSCALING pour images trop grandes
                elif width > max_dimension or height > max_dimension:
                    # Redimensionner en gardant le ratio
                    ratio = min(max_dimension / width, max_dimension / height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)

                    # Utiliser un algorithme de redimensionnement de haute qualité
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    logger.info(f"� Image redimensionnée: {original_size} → {img.size} (ratio: {ratio:.2f})")
                
                # ÉTAPE 4: Optimisation de la compression JPEG pour l'IA
                if max_quality:
                    # Qualité maximale pour l'analyse IA
                    quality = 98  # Très haute qualité
                    optimize = True
                    progressive = True  # JPEG progressif pour meilleure qualité
                else:
                    # Qualité équilibrée
                    quality = 90
                    optimize = True
                    progressive = False
                
                # ÉTAPE 5: Sauvegarde optimisée
                output = io.BytesIO()
                img.save(
                    output, 
                    format='JPEG', 
                    quality=quality,
                    optimize=optimize,
                    progressive=progressive,
                    # Préserver les métadonnées utiles
                    exif=img.getexif() if hasattr(img, 'getexif') else None
                )
                output.seek(0)
                
                # Statistiques de conversion
                original_size_mb = len(image_data) / 1024 / 1024
                converted_size_mb = len(output.getvalue()) / 1024 / 1024
                logger.info(f"📊 Conversion terminée: {original_size_mb:.1f}MB → {converted_size_mb:.1f}MB (qualité: {quality})")
                
                return output.getvalue()
                
        except Exception as e:
            logger.error(f"❌ Erreur lors de la conversion IA-optimisée: {e}")
            raise

    @staticmethod
    def convert_image_to_jpeg(image_data: bytes, quality: int = 100) -> bytes:
        """
        Convertit une image vers le format JPEG (version standard)
        Pour l'IA, utilisez convert_image_to_jpeg_for_ai() à la place
        """
        # Appeler la version optimisée IA par défaut pour tous les cas
        return ImageConverter.convert_image_to_jpeg_for_ai(image_data, max_quality=False)
    
    @staticmethod
    def upload_to_temp_service(image_data: bytes, format: str = 'jpeg') -> str:
        """
        Upload l'image convertie vers un service temporaire et retourne l'URL
        Pour l'instant, on utilise une approche data URI comme fallback
        """
        try:
            # Convertir en data URI comme solution temporaire
            # En production, vous voudrez uploader vers un service cloud (S3, etc.)
            
            mime_type = f'image/{format}'
            base64_data = base64.b64encode(image_data).decode('utf-8')
            data_uri = f'data:{mime_type};base64,{base64_data}'
            
            # Vérifier la taille de la data URI (limite pratique pour IA ~15MB plus généreux)
            if len(data_uri) > 15 * 1024 * 1024:  # 15MB au lieu de 10MB
                logger.warning("Image convertie trop grande, compression intelligente nécessaire")
                # Reconvertir avec compression intelligente pour préserver la qualité IA
                if format == 'jpeg':
                    # Réduire la qualité de façon progressive pour trouver le bon équilibre
                    with Image.open(io.BytesIO(image_data)) as img:
                        # Essayer quality=85 d'abord (meilleur que 60)
                        output = io.BytesIO()
                        img.save(output, format='JPEG', quality=85, optimize=True)
                        compressed_data = output.getvalue()
                        
                        # Si encore trop gros, essayer 75
                        if len(compressed_data) * 1.33 > 15 * 1024 * 1024:  # *1.33 pour base64
                            output = io.BytesIO()
                            img.save(output, format='JPEG', quality=75, optimize=True)
                            compressed_data = output.getvalue()
                            logger.info("🔄 Compression à quality=75 pour optimiser la taille")
                        else:
                            logger.info("🔄 Compression à quality=85 (préservation qualité IA)")
                        
                        base64_data = base64.b64encode(compressed_data).decode('utf-8')
                        data_uri = f'data:{mime_type};base64,{base64_data}'
            
            return data_uri
            
        except Exception as e:
            logger.error(f"Erreur lors de l'upload temporaire: {e}")
            raise
    
    @staticmethod
    def process_image_url(url: str, use_placeholder_for_invalid: bool = True) -> Optional[str]:
        """
        Fonction principale : traite une URL d'image et retourne une URL compatible OpenAI

        Args:
            url: URL à traiter
            use_placeholder_for_invalid: Si False, retourne None pour les URLs invalides au lieu d'un placeholder

        Returns:
            URL traitée ou None si invalide et use_placeholder_for_invalid=False
        """
        try:
            # Normaliser l'URL avant traitement
            url = normalize_url(url)
            logger.info(f"🔍 Traitement de l'image: {url}")

            # ÉTAPE 1: Validation préliminaire de l'URL
            if not is_valid_image_url(url):
                if use_placeholder_for_invalid:
                    logger.warning(f"⚠️ URL invalide, utilisation d'un placeholder: {url}")
                    return create_placeholder_image_url()
                else:
                    logger.warning(f"⚠️ URL invalide, ignorée: {url}")
                    return None
            
            # ÉTAPE 2: Détecter le format depuis l'URL
            url_format = ImageConverter.get_image_format_from_url(url)

            # Si format HEIC ou AVIF détecté depuis l'URL, procéder directement à la conversion
            if url_format in ['heic', 'avif']:
                logger.info(f"🎯 Format {url_format.upper()} détecté depuis l'URL, conversion nécessaire")
                # Pas besoin de test HEAD, on sait qu'il faut convertir
                # Passer directement au téléchargement et conversion
            elif url_format and url_format in SUPPORTED_FORMATS:
                logger.info(f"✅ Format {url_format} supporté, vérification de la validité...")
                # Tester rapidement l'accessibilité
                try:
                    response = requests.head(url, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"✅ Image accessible, pas de conversion nécessaire")
                        return url
                    else:
                        logger.warning(f"⚠️ Image non accessible (status {response.status_code}), fallback")
                        return create_placeholder_image_url()
                except Exception as head_error:
                    logger.warning(f"⚠️ Erreur lors de la vérification HEAD: {head_error}")
                    # Continuer avec le téléchargement complet
            
            # ÉTAPE 3: Télécharger et détecter le format réel
            try:
                image_data, detected_format = ImageConverter.download_image(url)
            except Exception as download_error:
                logger.error(f"❌ Échec du téléchargement: {download_error}")
                logger.info("⚠️ Utilisation d'un placeholder pour remplacer l'image défaillante")
                return create_placeholder_image_url()
            
            if not detected_format:
                logger.warning("⚠️ Format non détectable, tentative de conversion en JPEG")
                detected_format = 'unknown'
            
            # ÉTAPE 4: Vérifier si conversion nécessaire
            if detected_format in SUPPORTED_FORMATS:
                logger.info(f"✅ Format {detected_format} supporté après vérification")
                return url
            
            # ÉTAPE 5: Conversion nécessaire
            if url_format == 'heic' and detected_format == 'heic':
                logger.info(f"🎯 Conversion HEIC confirmée (URL + contenu) → JPEG (IA-optimisée)")
            elif detected_format == 'heic':
                logger.info(f"🔄 Conversion HEIC détectée → JPEG (IA-optimisée)")
            elif detected_format == 'avif':
                logger.info(f"🎨 Conversion AVIF détectée → JPEG (IA-optimisée)")
            else:
                logger.info(f"🔄 Conversion nécessaire: {detected_format} → JPEG (IA-optimisée)")
            
            try:
                # Convertir en JPEG avec optimisation IA
                jpeg_data = ImageConverter.convert_image_to_jpeg_for_ai(image_data, max_quality=True)
                
                # Valider la qualité de la conversion
                validation_report = validate_converted_image(jpeg_data, detected_format)
                
                # Log de la validation
                if validation_report["status"] in ["EXCELLENT", "BON"]:
                    logger.info(f"✅ Conversion validée: {validation_report['status']} ({validation_report['quality_score']}/100)")
                else:
                    logger.warning(f"⚠️ Qualité de conversion: {validation_report['status']} ({validation_report['quality_score']}/100)")
                    if validation_report.get("issues"):
                        logger.warning(f"🔍 Problèmes détectés: {', '.join(validation_report['issues'])}")
                
                # Upload vers service temporaire
                converted_url = ImageConverter.upload_to_temp_service(jpeg_data, 'jpeg')
                
                logger.info(f"✅ Image convertie avec succès (IA-optimisée, qualité validée)")
                return converted_url
                
            except Exception as conversion_error:
                logger.error(f"❌ Échec de la conversion: {conversion_error}")
                logger.info("⚠️ Utilisation d'un placeholder pour remplacer l'image non convertible")
                return create_placeholder_image_url()
            
        except Exception as e:
            logger.error(f"❌ Erreur générale lors du traitement de l'image {url}: {e}")
            # En cas d'erreur générale, utiliser un placeholder
            logger.info("⚠️ Utilisation d'un placeholder en dernier recours")
            return create_placeholder_image_url()

def validate_converted_image(image_data: bytes, original_format: str = None) -> dict:
    """
    Valide la qualité d'une image convertie pour s'assurer qu'elle est optimale pour l'IA
    
    Args:
        image_data: Données de l'image convertie
        original_format: Format original (pour logs)
        
    Returns:
        dict: Rapport de validation avec métriques de qualité
    """
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            # Métriques de base
            width, height = img.size
            file_size_mb = len(image_data) / 1024 / 1024
            
            # Calculs de qualité
            total_pixels = width * height
            megapixels = total_pixels / 1000000
            
            # Analyse de la qualité
            quality_score = 0
            issues = []
            recommendations = []
            
            # Vérification de la résolution
            if total_pixels >= 512 * 512:  # Minimum pour une bonne analyse IA
                quality_score += 25
            else:
                issues.append(f"Résolution trop faible: {width}x{height}")
                recommendations.append("Augmenter la résolution minimale")
            
            if total_pixels <= 4096 * 4096:  # Pas trop gros non plus
                quality_score += 25
            else:
                issues.append(f"Image très volumineuse: {width}x{height}")
                recommendations.append("Considérer un redimensionnement")
            
            # Vérification du format
            if img.format == 'JPEG':
                quality_score += 25
            else:
                issues.append(f"Format inattendu: {img.format}")
            
            # Vérification du mode colorimétrique
            if img.mode == 'RGB':
                quality_score += 25
            else:
                issues.append(f"Mode colorimétrique: {img.mode} (attendu: RGB)")
                recommendations.append("Convertir en RGB")
            
            # Vérification de la taille de fichier
            if 0.1 <= file_size_mb <= 15:  # Entre 100KB et 15MB
                quality_score += 0  # Neutre, on a déjà vérifié la résolution
            elif file_size_mb > 15:
                issues.append(f"Fichier volumineux: {file_size_mb:.1f}MB")
                recommendations.append("Optimiser la compression")
            else:
                issues.append(f"Fichier petit: {file_size_mb:.1f}MB")
                recommendations.append("Vérifier la qualité de compression")
            
            # Évaluation globale
            if quality_score >= 90:
                status = "EXCELLENT"
            elif quality_score >= 75:
                status = "BON"
            elif quality_score >= 50:
                status = "MOYEN"
            else:
                status = "PROBLÉMATIQUE"
            
            validation_report = {
                "status": status,
                "quality_score": quality_score,
                "metrics": {
                    "dimensions": f"{width}x{height}",
                    "megapixels": round(megapixels, 1),
                    "file_size_mb": round(file_size_mb, 2),
                    "format": img.format,
                    "mode": img.mode
                },
                "issues": issues,
                "recommendations": recommendations,
                "original_format": original_format
            }
            
            # Log du rapport
            if original_format:
                logger.info(f"🔍 Validation conversion {original_format}→JPEG: {status} ({quality_score}/100)")
            else:
                logger.info(f"🔍 Validation image: {status} ({quality_score}/100)")
            
            if issues:
                logger.warning(f"⚠️ Problèmes détectés: {', '.join(issues)}")
            
            return validation_report
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la validation: {e}")
        return {
            "status": "ERREUR",
            "quality_score": 0,
            "error": str(e)
        }

def test_heic_conversion(test_url: str = None) -> bool:
    """
    Teste la conversion HEIC pour s'assurer qu'elle fonctionne correctement
    
    Args:
        test_url: URL d'une image HEIC à tester (optionnel)
        
    Returns:
        bool: True si le test passe, False sinon
    """
    try:
        logger.info("🧪 Test de conversion HEIC démarré")
        
        if test_url:
            # Tester avec une vraie URL HEIC
            try:
                processed_url = ImageConverter.process_image_url(test_url)
                if processed_url and processed_url != test_url:
                    logger.info("✅ Test HEIC réussi avec URL réelle")
                    return True
                else:
                    logger.warning("⚠️ Aucune conversion détectée")
                    return False
            except Exception as e:
                logger.error(f"❌ Échec test URL HEIC: {e}")
                return False
        else:
            # Test basique - vérifier que les dépendances sont disponibles
            try:
                import pillow_heif
                logger.info("✅ Dépendance pillow-heif disponible")
                
                # Vérifier que l'ouverture HEIF est enregistrée
                if hasattr(pillow_heif, 'register_heif_opener'):
                    logger.info("✅ Support HEIF/HEIC configuré")
                    return True
                else:
                    logger.error("❌ Support HEIF/HEIC non configuré")
                    return False
                    
            except ImportError as e:
                logger.error(f"❌ Dépendance pillow-heif manquante: {e}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Erreur lors du test HEIC: {e}")
        return False

def diagnose_heic_image(url: str) -> dict:
    """
    Diagnostique complet d'une image HEIC pour identifier les problèmes
    
    Args:
        url: URL de l'image HEIC à diagnostiquer
        
    Returns:
        dict: Rapport de diagnostic détaillé
    """
    try:
        logger.info(f"🔬 Diagnostic HEIC démarré pour: {url}")
        
        diagnostic = {
            "url": url,
            "status": "unknown",
            "steps": [],
            "errors": [],
            "recommendations": []
        }
        
        # ÉTAPE 1: Validation URL
        if not is_valid_image_url(url):
            diagnostic["status"] = "invalid_url"
            diagnostic["errors"].append("URL invalide ou malformée")
            diagnostic["recommendations"].append("Vérifier que l'URL est complète et accessible")
            return diagnostic
        
        diagnostic["steps"].append("✅ URL valide")
        
        # ÉTAPE 2: Test accessibilité
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.head(url, headers=headers, timeout=10)
            if response.status_code == 200:
                diagnostic["steps"].append(f"✅ Image accessible (status: {response.status_code})")
                content_type = response.headers.get('content-type', 'unknown')
                diagnostic["steps"].append(f"📋 Content-Type: {content_type}")
            else:
                diagnostic["errors"].append(f"Image non accessible (status: {response.status_code})")
        except Exception as access_error:
            diagnostic["errors"].append(f"Erreur d'accès: {access_error}")
        
        # ÉTAPE 3: Téléchargement et analyse
        try:
            image_data, detected_format = ImageConverter.download_image(url)
            diagnostic["steps"].append(f"✅ Image téléchargée: {len(image_data)} bytes")
            
            if detected_format:
                diagnostic["steps"].append(f"✅ Format détecté: {detected_format}")
            else:
                diagnostic["errors"].append("Format non détecté")
                diagnostic["recommendations"].append("Le fichier pourrait être corrompu ou dans un format non supporté")
            
        except Exception as download_error:
            diagnostic["errors"].append(f"Erreur téléchargement: {download_error}")
            return diagnostic
        
        # ÉTAPE 4: Test support HEIF
        heif_support = ensure_heif_support()
        if heif_support:
            diagnostic["steps"].append("✅ Support HEIF/HEIC disponible")
        else:
            diagnostic["errors"].append("Support HEIF/HEIC non disponible")
            diagnostic["recommendations"].append("Installer pillow-heif: pip install pillow-heif")
        
        # ÉTAPE 5: Test ouverture avec PIL
        try:
            ensure_heif_support()  # S'assurer du support avant test
            with Image.open(io.BytesIO(image_data)) as img:
                diagnostic["steps"].append(f"✅ Ouverture PIL réussie: {img.format} {img.size} {img.mode}")
                
                # Test conversion
                try:
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Test sauvegarde JPEG
                    output = io.BytesIO()
                    img.save(output, format='JPEG', quality=95)
                    jpeg_size = len(output.getvalue())
                    diagnostic["steps"].append(f"✅ Conversion JPEG réussie: {jpeg_size} bytes")
                    
                    diagnostic["status"] = "success"
                    
                except Exception as convert_error:
                    diagnostic["errors"].append(f"Erreur conversion: {convert_error}")
                    diagnostic["status"] = "conversion_failed"
                    
        except Exception as pil_error:
            diagnostic["errors"].append(f"Erreur ouverture PIL: {pil_error}")
            diagnostic["status"] = "pil_failed"
            diagnostic["recommendations"].append("Vérifier que pillow-heif est correctement installé et configuré")
        
        # ÉTAPE 6: Test conversion complète avec notre pipeline
        if diagnostic["status"] in ["success", "unknown"]:
            try:
                processed_url = ImageConverter.process_image_url(url)
                if processed_url and processed_url != url:
                    diagnostic["steps"].append("✅ Pipeline de conversion complet réussi")
                    if processed_url.startswith('data:image/'):
                        diagnostic["steps"].append(f"✅ Data URI générée: {len(processed_url)} chars")
                    diagnostic["status"] = "pipeline_success"
                else:
                    diagnostic["errors"].append("Pipeline de conversion n'a pas transformé l'image")
                    
            except Exception as pipeline_error:
                diagnostic["errors"].append(f"Erreur pipeline: {pipeline_error}")
                diagnostic["status"] = "pipeline_failed"
        
        # Recommandations finales
        if diagnostic["status"] == "pipeline_success":
            diagnostic["recommendations"].append("🎉 Image HEIC traitée avec succès")
            diagnostic["recommendations"].append("L'image sera correctement analysée par l'IA")
        elif len(diagnostic["errors"]) > 0:
            diagnostic["recommendations"].append("❌ Problèmes détectés avec cette image HEIC")
            diagnostic["recommendations"].append("Considérer la conversion manuelle en JPEG")
        
        logger.info(f"🔬 Diagnostic terminé: {diagnostic['status']}")
        return diagnostic
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du diagnostic HEIC: {e}")
        return {
            "url": url,
            "status": "diagnostic_error",
            "errors": [f"Erreur diagnostic: {e}"],
            "steps": [],
            "recommendations": ["Réessayer le diagnostic"]
        }

def process_pictures_list(pictures_list: list) -> list:
    """
    Traite une liste de photos et convertit automatiquement les formats incompatibles
    Filtre automatiquement les images invalides
    
    Args:
        pictures_list: Liste de dictionnaires avec url et piece_id
        
    Returns:
        Liste des photos avec URLs converties si nécessaire (sans les images invalides)
    """
    try:
        processed_pictures = []
        invalid_count = 0
        
        for i, picture in enumerate(pictures_list):
            try:
                # Traiter l'URL de l'image - picture est maintenant un dictionnaire
                picture_url = picture['url'] if isinstance(picture, dict) else picture.url
                piece_id = picture['piece_id'] if isinstance(picture, dict) else picture.piece_id

                logger.info(f"📸 Traitement image {i+1}/{len(pictures_list)} pour piece {piece_id}")

                # Vérification préliminaire : ignorer les URLs complètement invalides
                if not picture_url or picture_url.strip() == "":
                    logger.warning(f"⚠️ URL vide pour piece {piece_id}, ignorée")
                    invalid_count += 1
                    continue

                # NORMALISER L'URL AVANT TRAITEMENT
                picture_url = normalize_url(picture_url)

                # Traiter l'image (ceci retournera un placeholder si nécessaire)
                converted_url = ImageConverter.process_image_url(picture_url)
                
                # Créer un nouvel objet picture avec l'URL convertie
                processed_picture = {
                    'piece_id': piece_id,
                    'url': converted_url
                }
                processed_pictures.append(processed_picture)
                
            except Exception as e:
                picture_url = picture.get('url', 'URL_UNKNOWN') if isinstance(picture, dict) else getattr(picture, 'url', 'URL_UNKNOWN')
                piece_id = picture.get('piece_id', 'UNKNOWN') if isinstance(picture, dict) else getattr(picture, 'piece_id', 'UNKNOWN')
                logger.error(f"❌ Erreur lors du traitement de l'image {picture_url} (piece {piece_id}): {e}")
                
                # En cas d'erreur, utiliser un placeholder
                try:
                    processed_pictures.append({
                        'piece_id': piece_id,
                        'url': create_placeholder_image_url()
                    })
                except Exception as placeholder_error:
                    logger.error(f"❌ Erreur lors de la création du placeholder: {placeholder_error}")
                    invalid_count += 1
                    continue
        
        if invalid_count > 0:
            logger.warning(f"⚠️ {invalid_count} images invalides ignorées ou remplacées")
        
        logger.info(f"✅ Traitement terminé: {len(processed_pictures)} images traitées avec succès")
        return processed_pictures
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de la liste d'images: {e}")
        # En cas d'erreur globale, essayer de récupérer ce qui est possible
        try:
            recovery_list = []
            for p in pictures_list:
                try:
                    piece_id = p['piece_id'] if isinstance(p, dict) else p.piece_id
                    picture_url = p['url'] if isinstance(p, dict) else p.url
                    
                    # Utiliser un placeholder pour chaque image en cas d'erreur globale
                    recovery_list.append({
                        'piece_id': piece_id,
                        'url': create_placeholder_image_url()
                    })
                except Exception:
                    continue  # Ignorer les éléments corrompus
            
            logger.info(f"🔧 Récupération: {len(recovery_list)} placeholders créés")
            return recovery_list
            
        except Exception as e2:
            logger.error(f"❌ Erreur lors de la récupération d'urgence: {e2}")
            return []

def process_etapes_images(etapes_list: list) -> list:
    """
    Traite les images des étapes et convertit automatiquement les formats incompatibles
    Gère gracieusement les URLs d'images invalides
    
    Args:
        etapes_list: Liste de dictionnaires Etape avec checking_picture et checkout_picture
        
    Returns:
        Liste des étapes avec URLs converties si nécessaire (avec placeholders pour images invalides)
    """
    try:
        processed_etapes = []
        issues_count = 0
        
        for i, etape in enumerate(etapes_list):
            try:
                # Traiter l'image de vérification - etape est maintenant un dictionnaire
                checking_picture = etape['checking_picture'] if isinstance(etape, dict) else etape.checking_picture
                checkout_picture = etape['checkout_picture'] if isinstance(etape, dict) else etape.checkout_picture
                etape_id = etape['etape_id'] if isinstance(etape, dict) else etape.etape_id
                task_name = etape['task_name'] if isinstance(etape, dict) else etape.task_name
                consigne = etape['consigne'] if isinstance(etape, dict) else etape.consigne
                
                logger.info(f"🔄 Traitement étape {i+1}/{len(etapes_list)} - ID: {etape_id}")

                # Traiter l'image de checking - ne pas créer de placeholder pour les URLs invalides
                if not checking_picture or checking_picture.strip() == "":
                    logger.warning(f"⚠️ checking_picture vide pour étape {etape_id}")
                    converted_checking = None
                    issues_count += 1
                else:
                    # NORMALISER L'URL AVANT VALIDATION
                    checking_picture = normalize_url(checking_picture)

                    # Vérifier si l'URL est valide avant traitement
                    if is_valid_image_url(checking_picture):
                        converted_checking = ImageConverter.process_image_url(checking_picture, use_placeholder_for_invalid=False)
                    else:
                        logger.warning(f"⚠️ checking_picture invalide pour étape {etape_id}: {checking_picture}")
                        converted_checking = None
                        issues_count += 1

                # Traiter l'image de checkout - ne pas créer de placeholder pour les URLs invalides
                if not checkout_picture or checkout_picture.strip() == "":
                    logger.warning(f"⚠️ checkout_picture vide pour étape {etape_id}")
                    converted_checkout = None
                    issues_count += 1
                else:
                    # NORMALISER L'URL AVANT VALIDATION
                    checkout_picture = normalize_url(checkout_picture)

                    # Vérifier si l'URL est valide avant traitement
                    if is_valid_image_url(checkout_picture):
                        converted_checkout = ImageConverter.process_image_url(checkout_picture, use_placeholder_for_invalid=False)
                    else:
                        logger.warning(f"⚠️ checkout_picture invalide pour étape {etape_id}: {checkout_picture}")
                        converted_checkout = None
                        issues_count += 1
                
                # Créer un nouvel objet étape avec les URLs converties (ou None pour invalides)
                # ✅ CORRECTION: Utiliser les clés *_processed pour correspondre à analyze_single_etape_async()
                processed_etape = {
                    'etape_id': etape_id,
                    'task_name': task_name,
                    'consigne': consigne,
                    'checking_picture_processed': converted_checking,  # Peut être None
                    'checkout_picture_processed': converted_checkout   # Peut être None
                }
                processed_etapes.append(processed_etape)
                
            except Exception as e:
                etape_id = etape.get('etape_id', 'UNKNOWN') if isinstance(etape, dict) else getattr(etape, 'etape_id', 'UNKNOWN')
                logger.error(f"❌ Erreur lors du traitement de l'étape {etape_id}: {e}")
                
                # En cas d'erreur, utiliser des placeholders pour toutes les images
                try:
                    task_name = etape.get('task_name', 'Tâche inconnue') if isinstance(etape, dict) else getattr(etape, 'task_name', 'Tâche inconnue')
                    consigne = etape.get('consigne', 'Consigne indisponible') if isinstance(etape, dict) else getattr(etape, 'consigne', 'Consigne indisponible')

                    # ✅ CORRECTION: Utiliser les clés *_processed
                    processed_etapes.append({
                        'etape_id': etape_id,
                        'task_name': task_name,
                        'consigne': consigne,
                        'checking_picture_processed': create_placeholder_image_url(),
                        'checkout_picture_processed': create_placeholder_image_url()
                    })
                    issues_count += 2  # 2 placeholders créés
                    
                except Exception as fallback_error:
                    logger.error(f"❌ Erreur lors de la création des placeholders pour étape {etape_id}: {fallback_error}")
                    continue  # Ignorer cette étape complètement
        
        if issues_count > 0:
            logger.warning(f"⚠️ {issues_count} images d'étapes remplacées par des placeholders")
        
        logger.info(f"✅ Traitement des étapes terminé: {len(processed_etapes)} étapes traitées avec succès")
        return processed_etapes
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de la liste d'étapes: {e}")
        # En cas d'erreur globale, essayer de créer des placeholders pour toutes les étapes
        try:
            recovery_list = []
            for etape in etapes_list:
                try:
                    etape_id = etape.get('etape_id', 'UNKNOWN') if isinstance(etape, dict) else getattr(etape, 'etape_id', 'UNKNOWN')
                    task_name = etape.get('task_name', 'Tâche inconnue') if isinstance(etape, dict) else getattr(etape, 'task_name', 'Tâche inconnue')
                    consigne = etape.get('consigne', 'Consigne indisponible') if isinstance(etape, dict) else getattr(etape, 'consigne', 'Consigne indisponible')

                    # ✅ CORRECTION: Utiliser les clés *_processed
                    recovery_list.append({
                        'etape_id': etape_id,
                        'task_name': task_name,
                        'consigne': consigne,
                        'checking_picture_processed': create_placeholder_image_url(),
                        'checkout_picture_processed': create_placeholder_image_url()
                    })
                except Exception:
                    continue  # Ignorer les étapes corrompues
            
            logger.info(f"🔧 Récupération: {len(recovery_list)} étapes avec placeholders créées")
            return recovery_list
            
        except Exception as e2:
            logger.error(f"❌ Erreur lors de la récupération d'urgence des étapes: {e2}")
            return [] 

def detect_image_format_enhanced(image_data) -> Optional[str]:
    """
    Détection améliorée du format d'image avec support étendu
    
    Args:
        image_data: BytesIO ou bytes de l'image
    
    Returns:
        str: Format détecté ('heic', 'jpeg', 'png', etc.) ou None
    """
    try:
        import io
        import logging
        from PIL import Image
        
        # Utiliser le logger existant
        logger = logging.getLogger(__name__)
        
        # Convertir en BytesIO si nécessaire
        if isinstance(image_data, bytes):
            image_data = io.BytesIO(image_data)
        
        # Réinitialiser la position
        image_data.seek(0)
        
        # Lire les premiers bytes pour l'analyse
        header_bytes = image_data.read(32)
        image_data.seek(0)
        
        # === DÉTECTION PAR SIGNATURES ÉTENDUES ===

        # ⚠️ IMPORTANT: Vérifier AVIF AVANT HEIC car les deux utilisent 'ftyp'

        # AVIF - Signature (PRIORITÉ 1)
        if len(header_bytes) >= 12:
            if b'ftyp' in header_bytes[:20] and b'avif' in header_bytes[:32]:
                logger.info("🎯 Format AVIF détecté par signature")
                return 'avif'

        # HEIC/HEIF - Signatures multiples (PRIORITÉ 2)
        if len(header_bytes) >= 12:
            if (b'ftyp' in header_bytes[:20] and
                (b'heic' in header_bytes[:32] or b'mif1' in header_bytes[:32] or
                 b'heif' in header_bytes[:32] or b'heix' in header_bytes[:32] or
                 b'msf1' in header_bytes[:32] or b'hevc' in header_bytes[:32])):
                logger.info("🎯 Format HEIC/HEIF détecté par signature étendue")
                return 'heic'

        # JPEG - Standard
        if header_bytes[:2] == b'\xff\xd8':
            return 'jpeg'

        # PNG - Standard
        if header_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            return 'png'

        # GIF - Standard
        if header_bytes[:6] in [b'GIF87a', b'GIF89a']:
            return 'gif'

        # WebP - Standard
        if header_bytes[:4] == b'RIFF' and len(header_bytes) >= 12 and header_bytes[8:12] == b'WEBP':
            return 'webp'
        
        # === DÉTECTION PAR PIL EN FALLBACK ===
        try:
            image_data.seek(0)
            with Image.open(image_data) as img:
                detected_format = img.format.lower() if img.format else None
                logger.info(f"🔍 Format détecté par PIL: {detected_format}")
                return detected_format
        except Exception as pil_error:
            logger.warning(f"⚠️ PIL n'a pas pu détecter le format: {pil_error}")
        
        logger.warning("⚠️ Format d'image non identifiable")
        return None
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la détection format améliorée: {e}")
        return None

def upscale_image_for_ai(img, min_size=(512, 512), logger=None):
    """
    📈 UPSCALING INTELLIGENT POUR L'IA

    Agrandit les images trop petites pour améliorer l'analyse IA.
    Utilise LANCZOS pour un redimensionnement de haute qualité.

    Args:
        img: Image PIL
        min_size: Taille minimum requise (largeur, hauteur)
        logger: Logger optionnel

    Returns:
        Image PIL (agrandie si nécessaire)
    """
    from PIL import ImageEnhance

    if logger is None:
        logger = logging.getLogger(__name__)

    width, height = img.size
    min_width, min_height = min_size

    # Vérifier si l'image est trop petite (au moins une dimension < minimum)
    if width < min_width or height < min_height:
        # Calculer le facteur d'agrandissement pour atteindre la taille minimale
        scale_factor = max(min_width / width, min_height / height)

        # Limiter l'agrandissement à x3 pour éviter trop de flou
        scale_factor = min(scale_factor, 3.0)

        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)

        logger.info(f"📈 UPSCALING IA: {width}x{height} → {new_width}x{new_height} (facteur: {scale_factor:.2f})")

        # Redimensionnement avec LANCZOS (haute qualité)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # Amélioration de la netteté après upscaling pour compenser le flou
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(1.3)  # +30% netteté

        # Légère amélioration du contraste pour mieux distinguer les détails
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.05)  # +5% contraste

        logger.info(f"✅ Image agrandie avec amélioration netteté/contraste pour l'IA")

    return img


def convert_heic_with_modern_libraries(image_bytes, max_size=(4096, 4096), quality=98, min_size=(512, 512)):
    """
    Conversion HEIC/HEIF vers JPEG avec pillow-heif

    Args:
        image_bytes: Données binaires de l'image HEIC
        max_size: Taille maximum (largeur, hauteur)
        quality: Qualité JPEG (90-100 recommandé pour IA)
        min_size: Taille minimum (images plus petites seront agrandies)

    Returns:
        tuple: (success: bool, result: BytesIO ou str d'erreur)
    """
    import io
    import logging
    from PIL import Image

    logger = logging.getLogger(__name__)

    try:
        import pillow_heif
        pillow_heif.register_heif_opener()

        # Ouvrir directement avec PIL (pillow-heif enregistre le handler)
        img = Image.open(io.BytesIO(image_bytes))

        # Upscaling si image trop petite
        img = upscale_image_for_ai(img, min_size=min_size, logger=logger)

        # Downscaling si image trop grande
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Conversion en JPEG
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)

        logger.debug("✅ Conversion HEIC → JPEG réussie (pillow-heif)")
        return True, output

    except ImportError:
        error_msg = "❌ pillow-heif non installé. Installer avec: pip install pillow-heif"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"❌ Échec conversion HEIC: {e}"
        logger.error(error_msg)
        return False, error_msg


def convert_image_to_jpeg_for_ai(image_url, max_size=(4096, 4096), quality=98, min_size=(512, 512)):
    """
    🎯 CONVERSION OPTIMISÉE IA (v2025) - Multi-fallback robuste
    
    Conversion d'images pour analyse IA avec qualité maximale.
    Supporte tous formats via des librairies modernes.
    
    Args:
        image_url: URL de l'image
        max_size: Taille maximum (largeur, hauteur)
        quality: Qualité JPEG (95-100 pour IA)
        min_size: Taille minimum avec upscaling
    
    Returns:
        tuple: (success: bool, result: BytesIO ou str d'erreur, metadata: dict)
    """
    import requests
    import io
    import logging
    from PIL import Image, ImageEnhance
    from PIL.ExifTags import TAGS
    
    # Utiliser le logger existant
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"⬇️ Téléchargement de l'image: {image_url}")
        
        # Téléchargement avec headers appropriés
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; ImageProcessor/2025)',
            'Accept': 'image/*,*/*;q=0.9'
        }
        
        response = requests.get(image_url, headers=headers, timeout=30, stream=True)
        response.raise_for_status()
        
        image_bytes = response.content
        logger.info(f"📥 Image téléchargée: {len(image_bytes)} bytes")
        
        # Détection automatique du format
        image_format = detect_image_format_enhanced(io.BytesIO(image_bytes))
        logger.info(f"🔍 Format détecté: {image_format}")
        
        metadata = {
            'original_url': image_url,
            'original_size_bytes': len(image_bytes),
            'original_format': image_format,
            'processing_version': '2025_AI_OPTIMIZED'
        }
        
        # === TRAITEMENT SPÉCIAL HEIC ===
        if image_format.lower() in ['heic', 'heif']:
            logger.info("🔄 Conversion HEIC avec librairies modernes 2025")
            success, result = convert_heic_with_modern_libraries(
                image_bytes, max_size=max_size, quality=quality
            )
            
            if not success:
                return False, result, metadata
            
            image_bytes = result.getvalue()
            result.seek(0)
            image_format = 'jpeg'
        
        # === TRAITEMENT POUR TOUS LES AUTRES FORMATS ===
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                
                # Extraction des métadonnées EXIF complètes
                exif_dict = {}
                if hasattr(img, '_getexif') and img._getexif():
                    for tag_id, value in img._getexif().items():
                        tag = TAGS.get(tag_id, tag_id)
                        exif_dict[tag] = value
                
                metadata['exif'] = exif_dict
                metadata['original_size'] = img.size
                metadata['original_mode'] = img.mode
                
                # Correction d'orientation EXIF
                if 'Orientation' in exif_dict:
                    orientation = exif_dict['Orientation']
                    if orientation == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation == 8:
                        img = img.rotate(90, expand=True)
                    logger.info(f"🔄 Correction orientation EXIF: {orientation}")
                
                # Conversion en RGB si nécessaire
                if img.mode in ('RGBA', 'LA', 'P'):
                    logger.info(f"🎨 Conversion {img.mode} → RGB")
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGB')
                    else:
                        background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                        img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                original_size = img.size
                
                # Upscaling si l'image est trop petite
                if img.size[0] < min_size[0] or img.size[1] < min_size[1]:
                    # Calcul du facteur d'agrandissement
                    scale_factor = max(
                        min_size[0] / img.size[0],
                        min_size[1] / img.size[1]
                    )
                    new_size = (
                        int(img.size[0] * scale_factor),
                        int(img.size[1] * scale_factor)
                    )
                    
                    logger.info(f"📈 Upscaling: {img.size} → {new_size} (facteur: {scale_factor:.2f})")
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    
                    # Amélioration de la netteté après upscaling
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.2)
                    
                    metadata['upscaled'] = True
                    metadata['scale_factor'] = scale_factor
                
                # Redimensionnement si trop grande
                elif img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                    logger.info(f"📉 Redimensionnement: {img.size} → {max_size}")
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    metadata['downscaled'] = True
                
                metadata['final_size'] = img.size
                
                # Optimisations pour l'analyse IA
                if quality >= 95:
                    # Amélioration subtile de la netteté pour l'IA
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.1)
                    
                    # Amélioration subtile du contraste
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.05)
                    
                    logger.info("✨ Optimisations IA appliquées")
                
                # Sauvegarde optimale
                output = io.BytesIO()
                save_kwargs = {
                    'format': 'JPEG',
                    'quality': quality,
                    'optimize': True,
                    'progressive': True,
                    'subsampling': 0,  # Pas de sous-échantillonnage chromatique
                }
                
                # Préservation des métadonnées importantes
                if exif_dict:
                    try:
                        exif_bytes = img.getexif().tobytes()
                        save_kwargs['exif'] = exif_bytes
                    except:
                        pass  # Ignore les erreurs EXIF
                
                img.save(output, **save_kwargs)
                output.seek(0)
                
                metadata['final_size_bytes'] = len(output.getvalue())
                metadata['compression_ratio'] = metadata['original_size_bytes'] / metadata['final_size_bytes']
                
                logger.info(f"✅ Conversion réussie: {original_size} → {img.size}")
                logger.info(f"📊 Compression: {metadata['original_size_bytes']} → {metadata['final_size_bytes']} bytes (ratio: {metadata['compression_ratio']:.2f})")
                
                return True, output, metadata
                
        except Exception as e:
            logger.error(f"❌ Erreur traitement image: {e}")
            return False, f"Erreur de traitement: {str(e)}", metadata
    
    except requests.RequestException as e:
        logger.error(f"❌ Erreur téléchargement: {e}")
        return False, f"Erreur de téléchargement: {str(e)}", {}
    except Exception as e:
        logger.error(f"❌ Erreur générale: {e}")
        return False, f"Erreur: {str(e)}", {} 