from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.services.document_index_service import reindex_registered_documents


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia o índice de documentos registrados na aplicação.")
    parser.add_argument("--force", action="store_true", help="Reextrai todos os documentos registrados.")
    args = parser.parse_args()
    settings = get_settings()
    db = SessionLocal()
    try:
        result = reindex_registered_documents(db, output_dir=Path(settings.output_dir), force=args.force)
        db.commit()
        # Only counts are printed. Filenames, extracted text and configuration secrets are never emitted.
        print(
            "Indexação concluída: "
            f"registrados={result.discovered} novos={result.indexed} atualizados={result.updated} "
            f"inalterados={result.unchanged} OCR_páginas={result.ocr_pages} "
            f"ausentes={result.missing} bloqueados={result.blocked} "
            f"sem_texto={result.unsearchable} removidos={result.removed}"
        )
        return 0
    except Exception:  # noqa: BLE001 - keep database/path/parser details out of the command output.
        db.rollback()
        print("A indexação falhou; nenhum conteúdo de arquivo foi registrado no log.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
