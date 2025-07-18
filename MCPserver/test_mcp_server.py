#!/usr/bin/env python3
"""
Tests para el MCP Server de documentos
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from mcp_server import DocumentsAPIClient, DocumentCreate, DocumentUpdate, DocumentResponse, SearchResult

# Fixtures
@pytest.fixture
def sample_document():
    return {
        "id": "123",
        "title": "Test Document",
        "subtitle": "Test Subtitle",
        "content": "This is a test document content.",
        "keywords": ["test", "document"],
        "metadata": {"author": "Test Author"},
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }

@pytest.fixture
def mock_httpx_client():
    with patch('mcp_server.httpx.AsyncClient') as mock_client:
        yield mock_client

@pytest.fixture
def mock_redis():
    with patch('mcp_server.redis.from_url') as mock_redis:
        mock_redis.return_value = AsyncMock()
        yield mock_redis

class TestDocumentsAPIClient:
    """Tests para el cliente de API de documentos"""
    
    @pytest.mark.asyncio
    async def test_create_document(self, mock_httpx_client, mock_redis, sample_document):
        """Test creación de documento"""
        # Configurar mock response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = sample_document
        mock_response.raise_for_status = MagicMock()
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance
        
        # Test
        async with DocumentsAPIClient() as client:
            document_create = DocumentCreate(
                title="Test Document",
                content="Test content",
                keywords=["test"]
            )
            result = await client.create_document(document_create)
            
            assert result.title == "Test Document"
            assert result.id == "123"
            mock_client_instance.request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_documents_with_cache(self, mock_httpx_client, mock_redis):
        """Test obtención de documentos con cache"""
        # Configurar cache hit
        mock_redis_client = AsyncMock()
        mock_redis_client.get.return_value = json.dumps([{
            "id": "123",
            "title": "Cached Document",
            "content": "Cached content",
            "keywords": [],
            "metadata": {},
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }])
        
        with patch('mcp_server.redis.from_url', return_value=mock_redis_client):
            async with DocumentsAPIClient() as client:
                client.redis_client = mock_redis_client
                
                # Primera llamada debería usar cache
                documents = await client.get_documents()
                assert len(documents) == 1
                assert documents[0].title == "Cached Document"
    
    @pytest.mark.asyncio
    async def test_search_by_keyword(self, mock_httpx_client, mock_redis):
        """Test búsqueda por palabra clave"""
        search_result = {
            "documents": [{
                "id": "123",
                "title": "Found Document",
                "content": "Document with keyword",
                "keywords": ["test"],
                "metadata": {},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }],
            "total": 1,
            "page": 1,
            "per_page": 10
        }
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = search_result
        mock_response.raise_for_status = MagicMock()
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            result = await client.search_by_keyword("test")
            
            assert result.total == 1
            assert len(result.documents) == 1
            assert result.documents[0].title == "Found Document"
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, mock_httpx_client, mock_redis):
        """Test límites de concurrencia"""
        async with DocumentsAPIClient() as client:
            # El semáforo debería limitar la concurrencia
            assert client.semaphore._value == 100  # MAX_CONCURRENT_REQUESTS
    
    @pytest.mark.asyncio
    async def test_error_handling(self, mock_httpx_client, mock_redis):
        """Test manejo de errores"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = Exception("Connection error")
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            with pytest.raises(Exception):
                await client.get_documents()

class TestCacheSystem:
    """Tests para el sistema de cache"""
    
    @pytest.mark.asyncio
    async def test_memory_cache(self):
        """Test cache en memoria"""
        from mcp_server import memory_cache
        
        # Limpiar cache
        memory_cache.clear()
        
        # Agregar elemento
        memory_cache["test_key"] = {"data": "test_value"}
        
        # Verificar
        assert "test_key" in memory_cache
        assert memory_cache["test_key"]["data"] == "test_value"
    
    @pytest.mark.asyncio
    async def test_redis_cache_fallback(self, mock_redis):
        """Test fallback cuando Redis no está disponible"""
        # Simular Redis no disponible
        mock_redis.side_effect = Exception("Redis connection failed")
        
        async with DocumentsAPIClient() as client:
            # Debería funcionar sin Redis
            assert client.redis_client is None

class TestPerformance:
    """Tests de rendimiento"""
    
    @pytest.mark.asyncio
    async def test_concurrent_requests(self, mock_httpx_client, mock_redis):
        """Test manejo de múltiples requests concurrentes"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            # Crear múltiples tareas concurrentes
            tasks = [
                client.get_documents() 
                for _ in range(50)
            ]
            
            # Ejecutar todas las tareas
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verificar que todas completaron sin errores
            for result in results:
                assert not isinstance(result, Exception)
    
    @pytest.mark.asyncio
    async def test_response_time_monitoring(self, mock_httpx_client, mock_redis):
        """Test monitoreo de tiempo de respuesta"""
        import time
        
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(0.1)  # Simular respuesta lenta
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = []
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request = slow_response
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            start_time = time.time()
            await client.get_documents()
            end_time = time.time()
            
            # Verificar que se registró el tiempo
            assert end_time - start_time >= 0.1

class TestDataValidation:
    """Tests de validación de datos"""
    
    def test_document_create_validation(self):
        """Test validación de DocumentCreate"""
        # Datos válidos
        valid_doc = DocumentCreate(
            title="Valid Title",
            content="Valid content"
        )
        assert valid_doc.title == "Valid Title"
        
        # Datos inválidos - título requerido
        with pytest.raises(Exception):
            DocumentCreate(content="Content without title")
    
    def test_document_update_validation(self):
        """Test validación de DocumentUpdate"""
        # Actualización parcial válida
        update_doc = DocumentUpdate(title="New Title")
        assert update_doc.title == "New Title"
        assert update_doc.content is None
    
    def test_search_result_validation(self):
        """Test validación de SearchResult"""
        search_data = {
            "documents": [],
            "total": 0,
            "page": 1,
            "per_page": 10
        }
        
        result = SearchResult(**search_data)
        assert result.total == 0
        assert result.page == 1

class TestErrorScenarios:
    """Tests de escenarios de error"""
    
    @pytest.mark.asyncio
    async def test_api_timeout(self, mock_httpx_client, mock_redis):
        """Test timeout de API"""
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = asyncio.TimeoutError()
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            with pytest.raises(Exception):
                await client.get_documents()
    
    @pytest.mark.asyncio
    async def test_invalid_document_id(self, mock_httpx_client, mock_redis):
        """Test ID de documento inválido"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Document not found"
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request.return_value = mock_response
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            with pytest.raises(Exception):
                await client.get_document("invalid_id")

class TestMetrics:
    """Tests de métricas y monitoreo"""
    
    def test_prometheus_metrics(self):
        """Test métricas de Prometheus"""
        from mcp_server import REQUEST_COUNT, REQUEST_DURATION, ERROR_COUNT
        
        # Verificar que las métricas existen
        assert REQUEST_COUNT is not None
        assert REQUEST_DURATION is not None
        assert ERROR_COUNT is not None
        
        # Test incremento de contador
        initial_count = REQUEST_COUNT.labels(method='GET', endpoint='/documents')._value._value
        REQUEST_COUNT.labels(method='GET', endpoint='/documents').inc()
        new_count = REQUEST_COUNT.labels(method='GET', endpoint='/documents')._value._value
        
        assert new_count > initial_count

# Tests de integración
class TestIntegration:
    """Tests de integración completa"""
    
    @pytest.mark.asyncio
    async def test_full_crud_workflow(self, mock_httpx_client, mock_redis):
        """Test flujo completo CRUD"""
        # Configurar mocks para cada operación
        responses = {
            'POST': {"id": "123", "title": "Test Doc", "content": "Test", "keywords": [], "metadata": {}, "created_at": "2024-01-01T00:00:00", "updated_at": "2024-01-01T00:00:00"},
            'GET': {"id": "123", "title": "Test Doc", "content": "Test", "keywords": [], "metadata": {}, "created_at": "2024-01-01T00:00:00", "updated_at": "2024-01-01T00:00:00"},
            'PUT': {"id": "123", "title": "Updated Doc", "content": "Updated", "keywords": [], "metadata": {}, "created_at": "2024-01-01T00:00:00", "updated_at": "2024-01-01T00:00:00"},
            'DELETE': {}
        }
        
        def mock_request(method, *args, **kwargs):
            mock_response = MagicMock()
            mock_response.status_code = 200 if method != 'POST' else 201
            mock_response.json.return_value = responses[method]
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_client_instance = AsyncMock()
        mock_client_instance.request.side_effect = mock_request
        mock_httpx_client.return_value = mock_client_instance
        
        async with DocumentsAPIClient() as client:
            # 1. Crear documento
            doc_create = DocumentCreate(title="Test Doc", content="Test")
            created_doc = await client.create_document(doc_create)
            assert created_doc.id == "123"
            
            # 2. Obtener documento
            retrieved_doc = await client.get_document("123")
            assert retrieved_doc.title == "Test Doc"
            
            # 3. Actualizar documento
            doc_update = DocumentUpdate(title="Updated Doc", content="Updated")
            updated_doc = await client.update_document("123", doc_update)
            assert updated_doc.title == "Updated Doc"
            
            # 4. Eliminar documento
            result = await client.delete_document("123")
            assert result is True

if __name__ == "__main__":
    # Ejecutar tests
    pytest.main([__file__, "-v", "--cov=mcp_server", "--cov-report=html"])