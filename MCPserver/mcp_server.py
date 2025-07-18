#!/usr/bin/env python3
"""
MCP Server para gestión de documentos con alta concurrencia
Diseñado para manejar 3000-4000 consultas por hora
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import json
import uuid
from pathlib import Path

# Librerías para alta concurrencia y rendimiento
import httpx
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
import uvicorn
from contextlib import asynccontextmanager

# Cache y rate limiting
from cachetools import TTLCache
import redis.asyncio as redis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Logging y monitoreo
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import structlog

# MCP Protocol
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult
from mcp.server.stdio import stdio_server

# Configuración de logging estructurado
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Métricas Prometheus
REQUEST_COUNT = Counter('mcp_requests_total', 'Total requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('mcp_request_duration_seconds', 'Request duration')
ERROR_COUNT = Counter('mcp_errors_total', 'Total errors', ['error_type'])

# Modelos Pydantic
class DocumentBase(BaseModel):
    title: str = Field(..., description="Título del documento")
    subtitle: Optional[str] = Field(None, description="Subtítulo del documento")
    content: str = Field(..., description="Contenido del documento")
    keywords: List[str] = Field(default_factory=list, description="Palabras clave")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadatos adicionales")

class DocumentCreate(DocumentBase):
    pass

class DocumentUpdate(DocumentBase):
    title: Optional[str] = None
    content: Optional[str] = None

class DocumentResponse(DocumentBase):
    id: str
    created_at: datetime
    updated_at: datetime

class SearchResult(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    per_page: int

# Configuración
@dataclass
class Config:
    # API Configuration
    API_BASE_URL: str = "http://localhost:8000"
    MAX_CONCURRENT_REQUESTS: int = 100
    REQUEST_TIMEOUT: int = 30
    
    # Cache Configuration
    CACHE_TTL: int = 300  # 5 minutos
    CACHE_MAXSIZE: int = 1000
    
    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379"
    
    # Rate Limiting
    RATE_LIMIT: str = "100/minute"
    
    # Logging
    LOG_LEVEL: str = "INFO"

config = Config()

# Cache en memoria para respuestas frecuentes
memory_cache = TTLCache(maxsize=config.CACHE_MAXSIZE, ttl=config.CACHE_TTL)

class DocumentsAPIClient:
    """Cliente HTTP optimizado para la API de documentos"""
    
    def __init__(self):
        # Configuración de cliente HTTP con pool de conexiones
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=config.MAX_CONCURRENT_REQUESTS
        )
        
        self.client = httpx.AsyncClient(
            base_url=config.API_BASE_URL,
            timeout=httpx.Timeout(config.REQUEST_TIMEOUT),
            limits=limits,
            headers={
                "User-Agent": "MCP-DocumentsServer/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
        )
        
        # Semáforo para controlar concurrencia
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_REQUESTS)
        
        # Redis para cache distribuido
        self.redis_client = None
    
    async def __aenter__(self):
        try:
            self.redis_client = redis.from_url(config.REDIS_URL)
            await self.redis_client.ping()
            logger.info("Redis conectado exitosamente")
        except Exception as e:
            logger.warning(f"Redis no disponible: {e}")
            self.redis_client = None
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        if self.redis_client:
            await self.redis_client.close()
    
    async def _get_cache_key(self, method: str, url: str, params: Dict = None) -> str:
        """Genera clave de cache única"""
        key_parts = [method.upper(), url]
        if params:
            key_parts.append(json.dumps(params, sort_keys=True))
        return f"mcp_doc:{':'.join(key_parts)}"
    
    async def _get_cached_response(self, cache_key: str) -> Optional[Dict]:
        """Obtiene respuesta del cache"""
        # Primero intenta cache en memoria
        if cache_key in memory_cache:
            return memory_cache[cache_key]
        
        # Luego intenta Redis
        if self.redis_client:
            try:
                cached = await self.redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    memory_cache[cache_key] = data  # Actualiza cache local
                    return data
            except Exception as e:
                logger.warning(f"Error leyendo cache Redis: {e}")
        
        return None
    
    async def _set_cached_response(self, cache_key: str, data: Dict):
        """Guarda respuesta en cache"""
        memory_cache[cache_key] = data
        
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    cache_key, 
                    config.CACHE_TTL, 
                    json.dumps(data, default=str)
                )
            except Exception as e:
                logger.warning(f"Error guardando en cache Redis: {e}")
    
    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Realiza petición HTTP con cache y límites de concurrencia"""
        cache_key = await self._get_cache_key(method, endpoint, kwargs.get('params'))
        
        # Intenta obtener del cache primero
        if method == 'GET':
            cached_response = await self._get_cached_response(cache_key)
            if cached_response:
                return cached_response
        
        async with self.semaphore:
            try:
                with REQUEST_DURATION.time():
                    response = await self.client.request(method, endpoint, **kwargs)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    # Cache respuestas GET exitosas
                    if method == 'GET' and response.status_code == 200:
                        await self._set_cached_response(cache_key, data)
                    
                    REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
                    return data
                    
            except httpx.HTTPStatusError as e:
                ERROR_COUNT.labels(error_type='http_error').inc()
                logger.error(f"HTTP Error {e.response.status_code}: {e.response.text}")
                raise HTTPException(
                    status_code=e.response.status_code,
                    detail=f"API Error: {e.response.text}"
                )
            except httpx.RequestError as e:
                ERROR_COUNT.labels(error_type='request_error').inc()
                logger.error(f"Request Error: {e}")
                raise HTTPException(
                    status_code=503,
                    detail=f"Service unavailable: {str(e)}"
                )
    
    # Métodos CRUD
    async def create_document(self, document: DocumentCreate) -> DocumentResponse:
        """Crear nuevo documento"""
        data = await self._make_request('POST', '/documents', json=document.dict())
        return DocumentResponse(**data)
    
    async def get_documents(self, page: int = 1, per_page: int = 10) -> List[DocumentResponse]:
        """Obtener todos los documentos"""
        params = {'page': page, 'per_page': per_page}
        data = await self._make_request('GET', '/documents', params=params)
        return [DocumentResponse(**doc) for doc in data.get('documents', [])]
    
    async def get_document(self, doc_id: str) -> DocumentResponse:
        """Obtener documento por ID"""
        data = await self._make_request('GET', f'/documents/{doc_id}')
        return DocumentResponse(**data)
    
    async def update_document(self, doc_id: str, document: DocumentUpdate) -> DocumentResponse:
        """Actualizar documento"""
        data = await self._make_request('PUT', f'/documents/{doc_id}', json=document.dict(exclude_unset=True))
        return DocumentResponse(**data)
    
    async def delete_document(self, doc_id: str) -> bool:
        """Eliminar documento"""
        await self._make_request('DELETE', f'/documents/{doc_id}')
        return True
    
    # Métodos de búsqueda
    async def search_by_keyword(self, term: str, page: int = 1, per_page: int = 10) -> SearchResult:
        """Buscar por palabra clave"""
        params = {'term': term, 'page': page, 'per_page': per_page}
        data = await self._make_request('GET', '/search/keywords', params=params)
        return SearchResult(**data)
    
    async def search_by_title(self, term: str, page: int = 1, per_page: int = 10) -> SearchResult:
        """Buscar por título"""
        params = {'term': term, 'page': page, 'per_page': per_page}
        data = await self._make_request('GET', '/search/title', params=params)
        return SearchResult(**data)
    
    async def search_by_subtitle(self, term: str, page: int = 1, per_page: int = 10) -> SearchResult:
        """Buscar por subtítulo"""
        params = {'term': term, 'page': page, 'per_page': per_page}
        data = await self._make_request('GET', '/search/subtitle', params=params)
        return SearchResult(**data)

# Inicializar servidor MCP
server = Server("documents-server")

# Cliente global de la API
api_client = None

@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """Lista todas las herramientas disponibles"""
    return [
        Tool(
            name="create_document",
            description="Crear un nuevo documento",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título del documento"},
                    "subtitle": {"type": "string", "description": "Subtítulo (opcional)"},
                    "content": {"type": "string", "description": "Contenido del documento"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de palabras clave"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Metadatos adicionales"
                    }
                },
                "required": ["title", "content"]
            }
        ),
        Tool(
            name="get_documents",
            description="Obtener lista de documentos",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "minimum": 1, "default": 1},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
                }
            }
        ),
        Tool(
            name="get_document",
            description="Obtener documento por ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "ID del documento"}
                },
                "required": ["doc_id"]
            }
        ),
        Tool(
            name="update_document",
            description="Actualizar documento existente",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "ID del documento"},
                    "title": {"type": "string", "description": "Nuevo título (opcional)"},
                    "subtitle": {"type": "string", "description": "Nuevo subtítulo (opcional)"},
                    "content": {"type": "string", "description": "Nuevo contenido (opcional)"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Nueva lista de palabras clave (opcional)"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Nuevos metadatos (opcional)"
                    }
                },
                "required": ["doc_id"]
            }
        ),
        Tool(
            name="delete_document",
            description="Eliminar documento",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "ID del documento"}
                },
                "required": ["doc_id"]
            }
        ),
        Tool(
            name="search_by_keyword",
            description="Buscar documentos por palabra clave",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "Término de búsqueda"},
                    "page": {"type": "integer", "minimum": 1, "default": 1},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
                },
                "required": ["term"]
            }
        ),
        Tool(
            name="search_by_title",
            description="Buscar documentos por título",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "Término de búsqueda"},
                    "page": {"type": "integer", "minimum": 1, "default": 1},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
                },
                "required": ["term"]
            }
        ),
        Tool(
            name="search_by_subtitle",
            description="Buscar documentos por subtítulo",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "Término de búsqueda"},
                    "page": {"type": "integer", "minimum": 1, "default": 1},
                    "per_page": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
                },
                "required": ["term"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    """Maneja las llamadas a herramientas"""
    try:
        if name == "create_document":
            document = DocumentCreate(**arguments)
            result = await api_client.create_document(document)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Documento creado: {result.json()}")]
            )
        
        elif name == "get_documents":
            page = arguments.get("page", 1)
            per_page = arguments.get("per_page", 10)
            documents = await api_client.get_documents(page, per_page)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Documentos obtenidos: {len(documents)} documentos")]
            )
        
        elif name == "get_document":
            doc_id = arguments["doc_id"]
            document = await api_client.get_document(doc_id)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Documento: {document.json()}")]
            )
        
        elif name == "update_document":
            doc_id = arguments.pop("doc_id")
            document = DocumentUpdate(**arguments)
            result = await api_client.update_document(doc_id, document)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Documento actualizado: {result.json()}")]
            )
        
        elif name == "delete_document":
            doc_id = arguments["doc_id"]
            await api_client.delete_document(doc_id)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Documento {doc_id} eliminado exitosamente")]
            )
        
        elif name == "search_by_keyword":
            term = arguments["term"]
            page = arguments.get("page", 1)
            per_page = arguments.get("per_page", 10)
            result = await api_client.search_by_keyword(term, page, per_page)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Búsqueda por palabra clave '{term}': {result.total} resultados")]
            )
        
        elif name == "search_by_title":
            term = arguments["term"]
            page = arguments.get("page", 1)
            per_page = arguments.get("per_page", 10)
            result = await api_client.search_by_title(term, page, per_page)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Búsqueda por título '{term}': {result.total} resultados")]
            )
        
        elif name == "search_by_subtitle":
            term = arguments["term"]
            page = arguments.get("page", 1)
            per_page = arguments.get("per_page", 10)
            result = await api_client.search_by_subtitle(term, page, per_page)
            return CallToolResult(
                content=[TextContent(type="text", text=f"Búsqueda por subtítulo '{term}': {result.total} resultados")]
            )
        
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Herramienta desconocida: {name}")]
            )
    
    except Exception as e:
        logger.error(f"Error en herramienta {name}: {e}")
        ERROR_COUNT.labels(error_type='tool_error').inc()
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")]
        )

async def main():
    """Función principal"""
    global api_client
    
    # Inicializar cliente API
    api_client = DocumentsAPIClient()
    
    async with api_client:
        # Ejecutar servidor MCP
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    # Configurar logging
    logging.basicConfig(level=getattr(logging, config.LOG_LEVEL.upper()))
    
    # Ejecutar servidor
    asyncio.run(main())
