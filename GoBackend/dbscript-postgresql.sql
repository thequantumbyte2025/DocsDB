-- Script PostgreSQL  

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    subtitle TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content TEXT NOT NULL,
    keywords TEXT[]
);

-- Índices útiles
CREATE INDEX idx_documents_created_at ON documents(created_at);
CREATE INDEX idx_documents_keywords ON documents USING GIN (keywords);
