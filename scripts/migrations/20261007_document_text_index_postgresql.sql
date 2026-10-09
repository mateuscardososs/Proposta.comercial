BEGIN;

CREATE TABLE IF NOT EXISTS document_text_indexes (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(30) NOT NULL,
    source_id INTEGER NOT NULL,
    source_slot VARCHAR(10) NOT NULL,
    relative_path VARCHAR(1000) NOT NULL,
    document_name VARCHAR(255) NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    mtime_ns BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    extraction_method VARCHAR(30) NOT NULL DEFAULT '',
    language VARCHAR(20) NOT NULL DEFAULT '',
    indexed_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_document_text_source UNIQUE (source_type, source_id, source_slot),
    CONSTRAINT ck_document_text_source_type CHECK (source_type IN ('proposal', 'service_report')),
    CONSTRAINT ck_document_text_source_slot CHECK (source_slot IN ('pdf', 'docx')),
    CONSTRAINT ck_document_text_status CHECK (status IN ('searchable', 'partial', 'unsearchable', 'missing', 'blocked'))
);

CREATE INDEX IF NOT EXISTS ix_document_text_indexes_source_type ON document_text_indexes (source_type);
CREATE INDEX IF NOT EXISTS ix_document_text_indexes_source_id ON document_text_indexes (source_id);

CREATE TABLE IF NOT EXISTS document_text_index_entries (
    id SERIAL PRIMARY KEY,
    document_index_id INTEGER NOT NULL REFERENCES document_text_indexes(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    page INTEGER NULL,
    section VARCHAR(500) NULL,
    text TEXT NOT NULL,
    CONSTRAINT uq_document_text_entry_ordinal UNIQUE (document_index_id, ordinal),
    CONSTRAINT ck_document_text_entry_page CHECK (page IS NULL OR page > 0)
);

CREATE INDEX IF NOT EXISTS ix_document_text_index_entries_document_index_id
    ON document_text_index_entries (document_index_id);

COMMIT;
