import os
import re
import io
import hashlib
from pathlib import Path
import tempfile
from typing import List, Dict, Any, Tuple, Optional
from pdfminer.high_level import extract_text
import nltk
from bs4 import BeautifulSoup
import markdown
from app.config.settings import settings
from app.utils import simple_cache

# Agregar soporte para documentos Word
import docx2txt
import docx

# Para manejar documentos grandes
import concurrent.futures
from tqdm import tqdm

# Descargar recursos de NLTK necesarios si no existen
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

class DocumentProcessor:
    """Clase para procesar documentos de términos y condiciones en diferentes formatos"""
    
    def __init__(self):
        self.upload_dir = settings.UPLOAD_DIR
        # Tamaño máximo de documento en bytes (100MB por defecto)
        self.max_file_size = settings.MAX_FILE_SIZE
        # Tamaño máximo de contexto para el modelo
        self.max_context_size = settings.MODEL_MAX_CONTEXT_SIZE
        
    async def save_uploaded_file(self, file) -> Path:
        """Guarda un archivo cargado y devuelve la ruta"""
        # Crear un nombre de archivo único
        filename = Path(file.filename)
        file_path = self.upload_dir / f"{filename.stem}_{os.urandom(8).hex()}{filename.suffix}"
        
        # Guardar el archivo en partes para manejar archivos grandes
        with open(file_path, "wb") as f:
            # Leer en partes de 1MB
            chunk_size = 1024 * 1024
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
            
        return file_path
    
    def extract_text_from_file(self, file_path: Path) -> str:
        """Extrae texto del archivo según su formato"""
        suffix = file_path.suffix.lower()
        
        # Verificar tamaño del archivo
        file_size = os.path.getsize(file_path)
        if file_size > self.max_file_size:
            raise ValueError(f"El archivo es demasiado grande ({file_size/1024/1024:.2f}MB). Tamaño máximo: {self.max_file_size/1024/1024:.2f}MB")
        
        if suffix == '.pdf':
            return self._extract_from_pdf(file_path)
        elif suffix == '.txt':
            return self._extract_from_txt(file_path)
        elif suffix in ['.html', '.htm']:
            return self._extract_from_html(file_path)
        elif suffix == '.md':
            return self._extract_from_markdown(file_path)
        elif suffix in ['.docx', '.doc']:
            return self._extract_from_word(file_path)
        else:
            raise ValueError(f"Formato de archivo no soportado: {suffix}")
    
    def _extract_from_pdf(self, file_path: Path) -> str:
        """Extrae texto de un archivo PDF con manejo de documentos grandes"""
        try:
            # Extraer texto por páginas para manejar PDFs grandes
            from pdfminer.pdfpage import PDFPage
            from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
            from pdfminer.converter import TextConverter
            from pdfminer.layout import LAParams
            
            text_parts = []
            
            with open(file_path, 'rb') as file:
                # Contar páginas primero
                page_count = sum(1 for _ in PDFPage.get_pages(file))
                file.seek(0)  # Volver al inicio del archivo
                
                # Configurar el extractor
                resource_manager = PDFResourceManager()
                
                # Procesar páginas en bloques
                for i in range(0, page_count, 10):  # 10 páginas a la vez
                    file.seek(0)  # Volver al inicio para cada bloque
                    
                    pages = []
                    for j, page in enumerate(PDFPage.get_pages(file)):
                        if i <= j < i + 10:
                            pages.append(page)
                    
                    output_string = io.StringIO()
                    with TextConverter(resource_manager, output_string, laparams=LAParams()) as converter:
                        interpreter = PDFPageInterpreter(resource_manager, converter)
                        for page in pages:
                            interpreter.process_page(page)
                    
                    text_parts.append(output_string.getvalue())
            
            # Unir todas las partes
            full_text = '\n'.join(text_parts)
            
            # Limitar la longitud del texto si es demasiado grande
            if len(full_text) > self.max_context_size:
                print(f"El texto extraído es demasiado largo ({len(full_text)} caracteres). Se truncará.")
                return full_text[:self.max_context_size]
            
            return full_text
        except Exception as e:
            print(f"Error procesando PDF, intentando método alternativo: {str(e)}")
            # Método alternativo si el anterior falla
            return extract_text(file_path)
    
    def _extract_from_txt(self, file_path: Path) -> str:
        """Extrae texto de un archivo TXT con manejo de archivos grandes"""
        chunks = []
        size = 0
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                chunks.append(line)
                size += len(line)
                if size > self.max_context_size:
                    break
        return ''.join(chunks)[:self.max_context_size]
    
    def _extract_from_html(self, file_path: Path) -> str:
        """Extrae texto de un archivo HTML con manejo de archivos grandes"""
        text = ""
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()
        
        # Procesar HTML por partes si es muy grande
        if len(html_content) > 10 * 1024 * 1024:  # Más de 10MB
            # Crear chunks del HTML
            chunk_size = 5 * 1024 * 1024  # 5MB chunks
            chunks = [html_content[i:i + chunk_size] for i in range(0, len(html_content), chunk_size)]
            
            for chunk in chunks:
                soup = BeautifulSoup(chunk, 'html.parser')
                text += soup.get_text(separator=' ', strip=True) + " "
                
                # Si el texto es demasiado grande, cortar
                if len(text) > self.max_context_size:
                    return text[:self.max_context_size]
        else:
            soup = BeautifulSoup(html_content, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            
            # Si el texto es demasiado grande, cortar
            if len(text) > self.max_context_size:
                return text[:self.max_context_size]
            
        return text
    
    def _extract_from_markdown(self, file_path: Path) -> str:
        """Extrae texto de un archivo Markdown"""
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            md_content = f.read()
        html_content = markdown.markdown(md_content)
        soup = BeautifulSoup(html_content, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        if len(text) > self.max_context_size:
            return text[:self.max_context_size]
        return text
    
    def _extract_from_word(self, file_path: Path) -> str:
        """Extrae texto de un documento Word (.docx, .doc)"""
        try:
            # Intentar usar docx2txt primero (más rápido)
            text = docx2txt.process(file_path)
            
            # Si el texto es demasiado grande, cortar
            if len(text) > self.max_context_size:
                return text[:self.max_context_size]
                
            return text
        except Exception as e:
            print(f"Error con docx2txt: {str(e)}. Intentando con python-docx")
            # Método alternativo con python-docx
            try:
                doc = docx.Document(file_path)
                text = "\n".join([para.text for para in doc.paragraphs])
                
                # Si el texto es demasiado grande, cortar
                if len(text) > self.max_context_size:
                    return text[:self.max_context_size]
                    
                return text
            except Exception as e2:
                raise ValueError(f"No se pudo extraer texto del documento Word: {str(e2)}")
    
    def chunk_document(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Divide el documento en chunks más pequeños para procesamiento con paralelismo"""
        # Tokenizar por oraciones
        sentences = nltk.sent_tokenize(text)
        chunks = []
        current_chunk = []
        current_size = 0
        
        for sentence in sentences:
            sentence_size = len(sentence)
            
            if current_size + sentence_size <= chunk_size:
                current_chunk.append(sentence)
                current_size += sentence_size
            else:
                # Guardar el chunk actual
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                
                # Comenzar un nuevo chunk, posiblemente con solapamiento
                if overlap > 0 and current_chunk:
                    # Tomar las últimas oraciones que entren en el solapamiento
                    overlap_text = ''
                    for i in range(len(current_chunk) - 1, -1, -1):
                        if len(overlap_text) + len(current_chunk[i]) <= overlap:
                            overlap_text = current_chunk[i] + ' ' + overlap_text
                        else:
                            break
                    
                    current_chunk = overlap_text.strip().split()
                    current_size = len(overlap_text)
                else:
                    current_chunk = []
                    current_size = 0
                
                # Agregar la oración actual
                current_chunk.append(sentence)
                current_size += sentence_size
        
        # Agregar el último chunk si existe
        if current_chunk:
            chunks.append(' '.join(current_chunk))
            
        return chunks
    
    def process_chunks_parallel(self, chunks: List[str], process_func) -> List[Any]:
        """Procesa chunks en paralelo usando múltiples hilos"""
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as executor:
            # Enviar trabajos
            future_to_chunk = {executor.submit(process_func, chunk): i for i, chunk in enumerate(chunks)}
            
            # Recolectar resultados en orden
            for future in concurrent.futures.as_completed(future_to_chunk):
                chunk_index = future_to_chunk[future]
                try:
                    result = future.result()
                    results.append((chunk_index, result))
                except Exception as e:
                    print(f"Error procesando chunk {chunk_index}: {str(e)}")
                    results.append((chunk_index, None))
        
        # Ordenar resultados por índice original
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results if r[1] is not None]
    
    def preprocess_text(self, text: str) -> str:
        """Preprocesa el texto para mejorar el análisis"""
        # Eliminar caracteres especiales y espacios múltiples
        text = re.sub(r'\s+', ' ', text)
        
        # Eliminar encabezados y pies de página comunes en documentos de T&C
        text = re.sub(r'Page \d+ of \d+', '', text)
        
        # Eliminar marcas de agua y texto repetitivo
        text = re.sub(r'(?i)(confidential|draft|internal use only|do not distribute)', '', text)
        
        # Eliminar URLs y correos electrónicos que no sean relevantes
        text = re.sub(r'https?://\S+|www\.\S+', '[URL]', text)
        text = re.sub(r'\S+@\S+\.\S+', '[EMAIL]', text)
        
        return text.strip()
    
    def get_document_hash(self, file_path: Path) -> str:
        """
        Calcula un hash único para un archivo basado en su contenido
        
        Args:
            file_path: Ruta al archivo
            
        Returns:
            Hash SHA-256 del contenido del archivo
        """
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            # Leer en bloques para no cargar todo el archivo en memoria
            for chunk in iter(lambda: f.read(4096), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def extract_text_with_cache(self, file_path: Path) -> str:
        """
        Extrae texto de un archivo usando caché si está disponible
        
        Args:
            file_path: Ruta al archivo
            
        Returns:
            Texto extraído del archivo
        """
        # Calcular hash del archivo
        file_hash = self.get_document_hash(file_path)
        cache_key = f"extract_text_{file_hash}"
        
        # Intentar obtener de la caché
        cached_result = simple_cache.get_from_cache(cache_key)
        
        if cached_result and "text" in cached_result:
            print(f"Texto recuperado de caché: {len(cached_result['text'])} caracteres")
            return cached_result["text"]
        
        # Si no está en caché, extraer el texto
        extracted_text = self.extract_text_from_file(file_path)
        extracted_text = self.preprocess_text(extracted_text)
        
        # Guardar en caché
        simple_cache.save_to_cache(cache_key, {"text": extracted_text})
        
        return extracted_text

# Instancia del procesador de documentos
document_processor = DocumentProcessor()    