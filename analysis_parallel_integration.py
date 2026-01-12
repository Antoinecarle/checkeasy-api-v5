"""
🔗 Integration module for parallel analysis processing

This module integrates the ParallelProcessor with the existing analysis workflow,
providing optimized parallel execution for:
- Room/piece analysis with classification
- Etape (step) analysis
- Complete logement (housing) analysis
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from parallel_processor import ParallelProcessor, WorkerConfig, ThreadSafeCache

logger = logging.getLogger(__name__)


class AnalysisParallelExecutor:
    """
    Specialized parallel executor for analysis operations
    Integrates with existing make_request.py functions
    """
    
    def __init__(self, max_workers: int = 15, enable_caching: bool = True):
        """
        Initialize the parallel executor
        
        Args:
            max_workers: Maximum concurrent API calls (default: 15 for high quota)
            enable_caching: Enable result caching
        """
        config = WorkerConfig(
            max_workers=max_workers,
            max_retries=2,
            timeout_seconds=120,
            rate_limit_delay=0.05,  # Small delay to avoid overwhelming API
            enable_caching=enable_caching
        )
        
        self.processor = ParallelProcessor(config=config)
        logger.info(f"🚀 AnalysisParallelExecutor initialisé (max_workers: {max_workers})")
    
    async def analyze_pieces_parallel(
        self,
        pieces: List[Any],
        analyze_func: callable,
        parcours_type: str = "Voyageur",
        request_id: str = None
    ) -> List[Any]:
        """
        Analyze multiple pieces in parallel
        
        Args:
            pieces: List of piece objects to analyze
            analyze_func: Analysis function (should be async)
            parcours_type: Type of parcours
            request_id: Request ID for logging
        
        Returns:
            List of analysis results
        """
        logger.info(f"📊 Analyse parallèle de {len(pieces)} pièces (max_workers: {self.processor.config.max_workers})")
        
        # Prepare tasks
        tasks = []
        for i, piece in enumerate(pieces):
            task = {
                'id': f"piece_{piece.piece_id}",
                'args': [piece],
                'kwargs': {
                    'parcours_type': parcours_type,
                    'request_id': request_id
                }
            }
            tasks.append(task)
        
        # Execute in parallel
        results = await self.processor.process_batch(
            tasks=tasks,
            task_func=analyze_func,
            cache_prefix="piece_analysis",
            return_exceptions=True
        )
        
        # Filter valid results
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Erreur analyse pièce {pieces[i].piece_id}: {result}")
            else:
                valid_results.append(result)
        
        logger.info(f"✅ {len(valid_results)}/{len(pieces)} pièces analysées avec succès")
        return valid_results
    
    async def analyze_etapes_parallel(
        self,
        etapes_data: List[Dict[str, Any]],
        analyze_func: callable,
        parcours_type: str = "Voyageur",
        request_id: str = None
    ) -> List[Any]:
        """
        Analyze multiple etapes in parallel
        
        Args:
            etapes_data: List of (etape, etape_data, piece_id) tuples
            analyze_func: Analysis function (should be async)
            parcours_type: Type of parcours
            request_id: Request ID for logging
        
        Returns:
            List of etape issues (flattened)
        """
        logger.info(f"🎯 Analyse parallèle de {len(etapes_data)} étapes (max_workers: {self.processor.config.max_workers})")
        
        # Prepare tasks
        tasks = []
        for i, data in enumerate(etapes_data):
            etape = data['etape']
            etape_data_dict = data['etape_data']
            piece_id = data['piece_id']
            
            task = {
                'id': f"etape_{etape.etape_id}",
                'args': [etape, etape_data_dict, piece_id],
                'kwargs': {
                    'parcours_type': parcours_type,
                    'request_id': request_id
                }
            }
            tasks.append(task)
        
        # Execute in parallel
        results = await self.processor.process_batch(
            tasks=tasks,
            task_func=analyze_func,
            cache_prefix="etape_analysis",
            return_exceptions=True
        )
        
        # Flatten results (each etape returns a list of issues)
        all_issues = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ Erreur analyse étape {etapes_data[i]['etape'].etape_id}: {result}")
            elif isinstance(result, list):
                all_issues.extend(result)
        
        logger.info(f"✅ {len(all_issues)} issues d'étapes détectées")
        return all_issues

    async def analyze_complete_logement_optimized(
        self,
        input_data: Any,
        analyze_piece_func: callable,
        analyze_etape_func: callable,
        process_etapes_images_func: callable,
        parcours_type: str = "Voyageur",
        request_id: str = None
    ) -> Dict[str, Any]:
        """
        Optimized complete logement analysis with maximum parallelization

        This function:
        1. Analyzes all pieces in parallel (Stage 1)
        2. Processes all etape images in parallel (Stage 2a)
        3. Analyzes all etapes in parallel (Stage 2b)
        4. Compiles results (Stage 3)

        Args:
            input_data: EtapesAnalysisInput object
            analyze_piece_func: Async function to analyze a single piece
            analyze_etape_func: Async function to analyze a single etape
            process_etapes_images_func: Async function to process etape images
            parcours_type: Type of parcours
            request_id: Request ID for logging

        Returns:
            Dictionary with pieces_analysis and etapes_issues
        """
        logger.info(f"🚀 [OPTIMIZED] Analyse complète parallélisée pour logement {input_data.logement_id}")
        logger.info(f"   📊 Configuration: {len(input_data.pieces)} pièces, max_workers={self.processor.config.max_workers}")

        # ═══════════════════════════════════════════════════════════════
        # STAGE 1: Analyze all pieces in parallel
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"📊 [STAGE 1] Analyse parallèle de {len(input_data.pieces)} pièces")

        pieces_analysis = await self.analyze_pieces_parallel(
            pieces=input_data.pieces,
            analyze_func=analyze_piece_func,
            parcours_type=parcours_type,
            request_id=request_id
        )

        logger.info(f"✅ [STAGE 1] {len(pieces_analysis)} pièces analysées")

        # ═══════════════════════════════════════════════════════════════
        # STAGE 2: Process and analyze all etapes in parallel
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"🎯 [STAGE 2] Traitement et analyse des étapes")

        # Prepare all etapes data
        etape_to_piece_mapping = {}
        all_etapes_data = []

        for piece in input_data.pieces:
            # Process images for this piece's etapes
            processed_etapes = await process_etapes_images_func([etape.dict() for etape in piece.etapes])

            for i, etape_data in enumerate(processed_etapes):
                etape = piece.etapes[i]

                # Skip etapes without checkout_picture
                if not etape.checkout_picture or etape.checkout_picture.strip() == "":
                    logger.info(f"⏭️ Étape {etape.etape_id} skippée: pas de checkout_picture")
                    continue

                etape_to_piece_mapping[etape.etape_id] = piece.piece_id

                all_etapes_data.append({
                    'etape': etape,
                    'etape_data': etape_data,
                    'piece_id': piece.piece_id
                })

        # Analyze all etapes in parallel
        if all_etapes_data:
            all_etape_issues = await self.analyze_etapes_parallel(
                etapes_data=all_etapes_data,
                analyze_func=analyze_etape_func,
                parcours_type=parcours_type,
                request_id=request_id
            )
        else:
            all_etape_issues = []

        logger.info(f"✅ [STAGE 2] {len(all_etape_issues)} issues d'étapes détectées")

        # ═══════════════════════════════════════════════════════════════
        # STAGE 3: Compile results
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"🔄 [STAGE 3] Compilation des résultats")

        return {
            'pieces_analysis': pieces_analysis,
            'etapes_issues': all_etape_issues,
            'etape_to_piece_mapping': etape_to_piece_mapping
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        return self.processor.get_cache_stats()

    def clear_cache(self):
        """Clear all cached results"""
        self.processor.clear_cache()


# Global instance for easy access
_global_executor: Optional[AnalysisParallelExecutor] = None


def get_parallel_executor(max_workers: int = 15) -> AnalysisParallelExecutor:
    """
    Get or create global parallel executor instance

    Args:
        max_workers: Maximum concurrent workers

    Returns:
        AnalysisParallelExecutor instance
    """
    global _global_executor

    if _global_executor is None:
        _global_executor = AnalysisParallelExecutor(max_workers=max_workers)
        logger.info("🌍 Global AnalysisParallelExecutor créé")

    return _global_executor

