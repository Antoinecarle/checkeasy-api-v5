"""
🚀 Parallel Processing System with Caching for Analysis Operations

This module provides a high-performance parallel processing system that:
1. Executes multiple analyses concurrently using asyncio
2. Implements thread-safe caching for intermediate results
3. Handles rate limiting gracefully
4. Compiles final results from cached data
5. Provides error handling without blocking other workers
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import hashlib
from concurrent.futures import ThreadPoolExecutor
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Represents a cached analysis result"""
    key: str
    data: Any
    timestamp: datetime
    worker_id: str
    status: str  # 'pending', 'completed', 'failed'
    error: Optional[str] = None


class ThreadSafeCache:
    """Thread-safe cache for storing analysis results"""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._cache_dir = cache_dir or Path("./cache/analysis_results")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📦 Cache initialisé: {self._cache_dir}")
    
    def _generate_key(self, prefix: str, identifier: str) -> str:
        """Generate a unique cache key"""
        return f"{prefix}_{hashlib.md5(identifier.encode()).hexdigest()}"
    
    def set(self, key: str, data: Any, worker_id: str, status: str = 'completed', error: Optional[str] = None):
        """Store a result in cache (thread-safe)"""
        with self._lock:
            entry = CacheEntry(
                key=key,
                data=data,
                timestamp=datetime.now(),
                worker_id=worker_id,
                status=status,
                error=error
            )
            self._cache[key] = entry
            
            # Persist to disk for recovery
            if status == 'completed' and data is not None:
                self._persist_to_disk(key, entry)
            
            logger.debug(f"✅ Cache SET: {key} (worker: {worker_id}, status: {status})")
    
    def get(self, key: str) -> Optional[CacheEntry]:
        """Retrieve a result from cache (thread-safe)"""
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                logger.debug(f"📥 Cache HIT: {key}")
            return entry
    
    def _persist_to_disk(self, key: str, entry: CacheEntry):
        """Persist cache entry to disk"""
        try:
            cache_file = self._cache_dir / f"{key}.json"
            # Convert data to JSON-serializable format
            data_dict = {
                'key': entry.key,
                'timestamp': entry.timestamp.isoformat(),
                'worker_id': entry.worker_id,
                'status': entry.status,
                'data': self._serialize_data(entry.data)
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors de la persistance du cache {key}: {e}")
    
    def _serialize_data(self, data: Any) -> Any:
        """Convert Pydantic models to dict for JSON serialization"""
        if hasattr(data, 'model_dump'):
            return data.model_dump()
        elif hasattr(data, 'dict'):
            return data.dict()
        elif isinstance(data, list):
            return [self._serialize_data(item) for item in data]
        return data
    
    def get_all_completed(self) -> Dict[str, Any]:
        """Get all completed cache entries"""
        with self._lock:
            return {
                key: entry.data 
                for key, entry in self._cache.items() 
                if entry.status == 'completed'
            }
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        with self._lock:
            stats = defaultdict(int)
            for entry in self._cache.values():
                stats[entry.status] += 1
            stats['total'] = len(self._cache)
            return dict(stats)
    
    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self._cache.clear()
            logger.info("🗑️ Cache vidé")


@dataclass
class WorkerConfig:
    """Configuration for parallel workers"""
    max_workers: int = 10  # Maximum concurrent workers
    max_retries: int = 2  # Retry failed tasks
    timeout_seconds: int = 120  # Timeout per task
    rate_limit_delay: float = 0.1  # Delay between tasks (seconds)
    enable_caching: bool = True


class ParallelProcessor:
    """
    High-performance parallel processor for analysis operations
    """

    def __init__(self, config: WorkerConfig = None, cache: ThreadSafeCache = None):
        self.config = config or WorkerConfig()
        self.cache = cache or ThreadSafeCache()
        self._semaphore = None  # Will be created in async context
        logger.info(f"🚀 ParallelProcessor initialisé (max_workers: {self.config.max_workers})")

    async def _get_semaphore(self) -> asyncio.Semaphore:
        """Get or create semaphore for rate limiting"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_workers)
        return self._semaphore

    async def process_single_task(
        self,
        task_id: str,
        task_func: Callable,
        *args,
        worker_id: str = None,
        cache_prefix: str = "task",
        **kwargs
    ) -> Any:
        """
        Process a single task with caching and error handling

        Args:
            task_id: Unique identifier for the task
            task_func: Async or sync function to execute
            *args: Positional arguments for task_func
            worker_id: Optional worker identifier
            cache_prefix: Prefix for cache key
            **kwargs: Keyword arguments for task_func

        Returns:
            Result from task_func or cached result
        """
        worker_id = worker_id or f"worker_{id(asyncio.current_task())}"
        cache_key = self.cache._generate_key(cache_prefix, task_id)

        # Check cache first
        if self.config.enable_caching:
            cached = self.cache.get(cache_key)
            if cached and cached.status == 'completed':
                logger.info(f"📦 [CACHE HIT] {task_id} - Utilisation du résultat en cache")
                return cached.data

        # Mark as pending
        self.cache.set(cache_key, None, worker_id, status='pending')

        # Acquire semaphore for rate limiting
        semaphore = await self._get_semaphore()

        async with semaphore:
            # Rate limiting delay
            if self.config.rate_limit_delay > 0:
                await asyncio.sleep(self.config.rate_limit_delay)

            # Execute task with retry logic
            for attempt in range(self.config.max_retries + 1):
                try:
                    logger.info(f"🔄 [{worker_id}] Traitement: {task_id} (tentative {attempt + 1}/{self.config.max_retries + 1})")

                    # Execute with timeout
                    if asyncio.iscoroutinefunction(task_func):
                        result = await asyncio.wait_for(
                            task_func(*args, **kwargs),
                            timeout=self.config.timeout_seconds
                        )
                    else:
                        # Run sync function in thread pool
                        loop = asyncio.get_event_loop()
                        result = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: task_func(*args, **kwargs)),
                            timeout=self.config.timeout_seconds
                        )

                    # Cache successful result
                    self.cache.set(cache_key, result, worker_id, status='completed')
                    logger.info(f"✅ [{worker_id}] Terminé: {task_id}")
                    return result

                except asyncio.TimeoutError:
                    error_msg = f"Timeout après {self.config.timeout_seconds}s"
                    logger.warning(f"⏱️ [{worker_id}] {task_id}: {error_msg}")
                    if attempt == self.config.max_retries:
                        self.cache.set(cache_key, None, worker_id, status='failed', error=error_msg)
                        raise

                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ [{worker_id}] {task_id}: {error_msg}")
                    if attempt == self.config.max_retries:
                        self.cache.set(cache_key, None, worker_id, status='failed', error=error_msg)
                        raise

                    # Wait before retry
                    await asyncio.sleep(1 * (attempt + 1))

    async def process_batch(
        self,
        tasks: List[Dict[str, Any]],
        task_func: Callable,
        cache_prefix: str = "batch",
        return_exceptions: bool = True
    ) -> List[Any]:
        """
        Process multiple tasks in parallel with caching

        Args:
            tasks: List of task configurations, each with 'id' and 'args'/'kwargs'
            task_func: Function to execute for each task
            cache_prefix: Prefix for cache keys
            return_exceptions: If True, return exceptions instead of raising

        Returns:
            List of results (or exceptions if return_exceptions=True)
        """
        logger.info(f"📊 Démarrage du traitement parallèle de {len(tasks)} tâches")
        start_time = datetime.now()

        # Create coroutines for all tasks
        coroutines = []
        for i, task in enumerate(tasks):
            task_id = task.get('id', f"task_{i}")
            args = task.get('args', [])
            kwargs = task.get('kwargs', {})

            # Call process_single_task with proper argument unpacking
            # Signature: process_single_task(task_id, task_func, *args, worker_id=None, cache_prefix="task", **kwargs)
            coro = self.process_single_task(
                task_id,
                task_func,
                *args,
                worker_id=f"worker_{i % self.config.max_workers}",
                cache_prefix=cache_prefix,
                **kwargs
            )
            coroutines.append(coro)

        # Execute all tasks in parallel
        results = await asyncio.gather(*coroutines, return_exceptions=return_exceptions)

        # Calculate statistics
        duration = (datetime.now() - start_time).total_seconds()
        successful = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - successful

        logger.info(f"✅ Traitement parallèle terminé en {duration:.2f}s")
        logger.info(f"📊 Résultats: {successful} succès, {failed} échecs sur {len(tasks)} tâches")

        # Log cache statistics
        cache_stats = self.cache.get_stats()
        logger.info(f"📦 Cache: {cache_stats}")

        return results

    def compile_results(
        self,
        results: List[Any],
        compilation_func: Optional[Callable] = None
    ) -> Any:
        """
        Compile all cached results into final output

        Args:
            results: List of individual results from parallel processing
            compilation_func: Optional function to aggregate results

        Returns:
            Compiled final result
        """
        logger.info(f"🔄 Compilation de {len(results)} résultats")

        # Filter out exceptions
        valid_results = [r for r in results if not isinstance(r, Exception)]
        failed_results = [r for r in results if isinstance(r, Exception)]

        if failed_results:
            logger.warning(f"⚠️ {len(failed_results)} tâches ont échoué lors de la compilation")
            for i, error in enumerate(failed_results):
                logger.error(f"   Erreur {i+1}: {error}")

        # Apply custom compilation function if provided
        if compilation_func:
            try:
                compiled = compilation_func(valid_results)
                logger.info(f"✅ Compilation personnalisée terminée")
                return compiled
            except Exception as e:
                logger.error(f"❌ Erreur lors de la compilation personnalisée: {e}")
                raise

        # Default: return all valid results
        logger.info(f"✅ Compilation terminée: {len(valid_results)} résultats valides")
        return valid_results

    async def process_and_compile(
        self,
        tasks: List[Dict[str, Any]],
        task_func: Callable,
        compilation_func: Optional[Callable] = None,
        cache_prefix: str = "batch"
    ) -> Any:
        """
        Complete workflow: process tasks in parallel and compile results

        Args:
            tasks: List of task configurations
            task_func: Function to execute for each task
            compilation_func: Optional function to aggregate results
            cache_prefix: Prefix for cache keys

        Returns:
            Compiled final result
        """
        # Process all tasks in parallel
        results = await self.process_batch(
            tasks=tasks,
            task_func=task_func,
            cache_prefix=cache_prefix,
            return_exceptions=True
        )

        # Compile results
        final_result = self.compile_results(results, compilation_func)

        return final_result

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get detailed cache statistics"""
        stats = self.cache.get_stats()
        return {
            'cache_stats': stats,
            'config': {
                'max_workers': self.config.max_workers,
                'max_retries': self.config.max_retries,
                'timeout_seconds': self.config.timeout_seconds,
                'rate_limit_delay': self.config.rate_limit_delay,
                'caching_enabled': self.config.enable_caching
            }
        }

    def clear_cache(self):
        """Clear all cached results"""
        self.cache.clear()


# Convenience function for quick parallel processing
async def run_parallel(
    tasks: List[Dict[str, Any]],
    task_func: Callable,
    max_workers: int = 10,
    enable_caching: bool = True,
    compilation_func: Optional[Callable] = None
) -> Any:
    """
    Quick helper to run tasks in parallel with default configuration

    Args:
        tasks: List of task configurations
        task_func: Function to execute for each task
        max_workers: Maximum concurrent workers
        enable_caching: Enable result caching
        compilation_func: Optional function to aggregate results

    Returns:
        Compiled results
    """
    config = WorkerConfig(
        max_workers=max_workers,
        enable_caching=enable_caching
    )
    processor = ParallelProcessor(config=config)

    return await processor.process_and_compile(
        tasks=tasks,
        task_func=task_func,
        compilation_func=compilation_func
    )

