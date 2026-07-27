import os
import json
import hashlib
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from app.config.settings import settings

# Configurar logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL, "INFO"))
logger = logging.getLogger("simple_cache")

def get_cache_path(key: str) -> Path:
    """
    Obtener ruta de archivo de caché para una clave
    
    Args:
        key: Clave única para identificar el contenido cacheado
        
    Returns:
        Ruta del archivo de caché
    """
    hash_key = hashlib.md5(key.encode()).hexdigest()
    return settings.CACHE_DIR / f"{hash_key}.json"

def get_from_cache(key: str) -> Optional[Dict[str, Any]]:
    """
    Obtener resultado de caché si existe y no ha expirado
    
    Args:
        key: Clave única para buscar en caché
        
    Returns:
        El resultado cacheado o None si no existe o expiró
    """
    if not settings.ENABLE_CACHE:
        return None
        
    cache_path = get_cache_path(key)
    
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Verificar expiración
            if time.time() - data.get('timestamp', 0) < settings.CACHE_EXPIRY:
                logger.info(f"Cache hit para: {key[:50]}...")
                return data.get('result')
            else:
                logger.info(f"Cache expirado para: {key[:50]}...")
                try:
                    os.remove(cache_path)
                except Exception as e:
                    logger.warning(f"Error al eliminar caché expirada: {e}")
        except Exception as e:
            logger.warning(f"Error al leer caché: {e}")
    
    logger.debug(f"Cache miss para: {key[:50]}...")
    return None

def save_to_cache(key: str, result: Dict[str, Any], query: str = "") -> bool:
    """
    Guardar resultado en caché
    
    Args:
        key: Clave única para identificar el contenido
        result: Resultado a guardar en caché
        query: Consulta o prompt original (opcional)
        
    Returns:
        True si se guardó correctamente, False en caso contrario
    """
    if not settings.ENABLE_CACHE:
        return False
        
    cache_path = get_cache_path(key)
    
    try:
        os.makedirs(settings.CACHE_DIR, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': time.time(),
                'query': query,  # Guardamos la consulta original
                'result': result
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"Guardado en caché: {key[:50]}...")
        return True
    except Exception as e:
        logger.warning(f"Error al guardar en caché: {e}")
        return False
    
    try:
        os.makedirs(settings.CACHE_DIR, exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': time.time(),
                'query': query,  # Guardamos la consulta original
                'result': result
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"Guardado en caché: {key[:50]}...")
        return True
    except Exception as e:
        logger.warning(f"Error al guardar en caché: {e}")
        return False
def delete_from_cache(key: str) -> bool:
    """
    Eliminar una entrada específica de la caché
    
    Args:
        key: Clave única de la entrada a eliminar
        
    Returns:
        True si se eliminó correctamente, False en caso contrario
    """
    if not settings.ENABLE_CACHE:
        return False
        
    cache_path = get_cache_path(key)
    
    if cache_path.exists():
        try:
            os.remove(cache_path)
            logger.info(f"Eliminado de caché: {key[:50]}...")
            return True
        except Exception as e:
            logger.warning(f"Error al eliminar caché: {e}")
    
    return False

def clear_cache(days: Optional[int] = None) -> int:
    """
    Limpiar toda la caché o solo entradas más antiguas que cierto número de días
    
    Args:
        days: Si se especifica, solo elimina entradas más antiguas que este número de días
        
    Returns:
        Número de archivos eliminados
    """
    if not os.path.exists(settings.CACHE_DIR):
        return 0
        
    deleted = 0
    current_time = time.time()
    
    for cache_file in Path(settings.CACHE_DIR).glob('*.json'):
        try:
            # Si se especificó un límite de días
            if days is not None:
                file_time = cache_file.stat().st_mtime
                age_days = (current_time - file_time) / (24 * 60 * 60)
                
                # Omitir archivos más recientes que el límite
                if age_days < days:
                    continue
            
            os.remove(cache_file)
            deleted += 1
        except Exception as e:
            logger.warning(f"Error al eliminar caché {cache_file}: {e}")
    
    logger.info(f"Limpieza de caché completada: {deleted} archivos eliminados")
    return deleted

def get_cache_stats() -> Dict[str, Any]:
    """
    Obtener estadísticas básicas del sistema de caché
    
    Returns:
        Diccionario con estadísticas de la caché
    """
    if not settings.ENABLE_CACHE or not os.path.exists(settings.CACHE_DIR):
        return {"enabled": False, "file_count": 0, "size_mb": 0}
    
    try:
        # Listar archivos de caché
        cache_files = list(Path(settings.CACHE_DIR).glob('*.json'))
        
        # Calcular estadísticas
        file_count = len(cache_files)
        total_size = sum(f.stat().st_size for f in cache_files)
        size_mb = total_size / (1024 * 1024)
        
        # Fechas del archivo más antiguo y más reciente
        if file_count > 0:
            oldest_file = min(cache_files, key=lambda f: f.stat().st_mtime)
            newest_file = max(cache_files, key=lambda f: f.stat().st_mtime)
            
            oldest_time = oldest_file.stat().st_mtime
            newest_time = newest_file.stat().st_mtime
            
            oldest_days = (time.time() - oldest_time) / (24 * 60 * 60)
            newest_days = (time.time() - newest_time) / (24 * 60 * 60)
            
            oldest_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(oldest_time))
            newest_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest_time))
        else:
            oldest_days = newest_days = 0
            oldest_date = newest_date = "N/A"
        
        return {
            "enabled": True,
            "file_count": file_count,
            "size_mb": round(size_mb, 2),
            "oldest_days": round(oldest_days, 1),
            "newest_days": round(newest_days, 1),
            "oldest_date": oldest_date,
            "newest_date": newest_date,
            "cache_dir": str(settings.CACHE_DIR)
        }
    except Exception as e:
        logger.error(f"Error al obtener estadísticas de caché: {e}")
        return {"enabled": True, "error": str(e)}