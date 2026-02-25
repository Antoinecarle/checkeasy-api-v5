import logging
import asyncio
import aiohttp

logger = logging.getLogger("make_request")


async def send_webhook(payload: dict, webhook_url: str) -> bool:
    """
    Envoie le webhook de manière asynchrone

    Args:
        payload: Données à envoyer
        webhook_url: URL du webhook Bubble

    Returns:
        bool: True si succès, False sinon
    """
    try:
        logger.info(f"📤 WEBHOOK: Envoi vers {webhook_url}")
        logger.info(f"   📦 Payload size: {len(str(payload))} caractères")

        # Configuration du timeout et des headers
        timeout = aiohttp.ClientTimeout(total=30)  # 30 secondes max
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'CheckEasy-API-V5'
        }

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers=headers
            ) as response:
                response_text = await response.text()

                if response.status == 200:
                    logger.info(f"   ✅ SUCCÈS (HTTP 200)")
                    logger.info(f"   📥 Réponse: {response_text[:300]}...")
                    return True
                else:
                    logger.error(f"   ❌ ÉCHEC (HTTP {response.status})")
                    logger.error(f"   📥 Réponse: {response_text[:500]}")
                    return False

    except asyncio.TimeoutError:
        logger.error(f"   ❌ TIMEOUT après 30s vers {webhook_url}")
        return False
    except aiohttp.ClientError as e:
        logger.error(f"   ❌ ERREUR CLIENT: {e}")
        return False
    except Exception as e:
        logger.error(f"   ❌ ERREUR INATTENDUE: {e}")
        return False
