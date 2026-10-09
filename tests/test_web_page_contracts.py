"""HTTP contracts for the existing client and proposal web pages."""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models import Client, Proposal, User


def test_client_creation_edit_detail_and_required_name(db):
    with TestClient(app, follow_redirects=False) as browser:
        assert browser.get("/web/clients/new").status_code == 200
        rejected = browser.post("/web/clients/new", data={"razao_social": "  "})
        assert rejected.status_code == 400
        assert rejected.json() == {"detail": "Razao social is required"}
        assert db.query(Client).count() == 0
        created = browser.post("/web/clients/new", data={"razao_social": " Cliente sintético ", "pais": ""})
        assert created.status_code == 303
        assert created.headers["location"].endswith("/web/clients")
        client = db.query(Client).one()
        assert client.razao_social == "Cliente sintético"
        assert client.pais == "Brasil"
        assert "Cliente sintético" in browser.get(f"/web/clients/{client.id}").text
        edited = browser.post(f"/web/clients/{client.id}/edit", data={"razao_social": " Cliente editado ", "telefone": " 123 "})
        assert edited.status_code == 303
        db.refresh(client)
        assert (client.razao_social, client.telefone) == ("Cliente editado", "123")
        assert "Cliente editado" in browser.get("/web/clients").text
        assert browser.post(f"/web/clients/{client.id}/edit", data={"razao_social": ""}).status_code == 400
        assert browser.get("/web/clients/99999").status_code == 404


def test_proposal_pages_import_active_users_and_revision_redirect(db):
    client = Client(razao_social="Cliente contrato")
    active = User(nome="Responsável ativo", email="active@example.test", senha_hash="synthetic", ativo=True)
    inactive = User(nome="Responsável inativo", email="inactive@example.test", senha_hash="synthetic", ativo=False)
    db.add_all([client, active, inactive])
    db.flush()
    proposal = Proposal(numero=42, revisao="00", client_id=client.id, user_id=active.id, data_geracao=date(2026, 10, 1))
    db.add(proposal)
    db.commit()
    with TestClient(app, follow_redirects=False) as browser:
        imported = browser.get("/import-proposals")
        assert imported.status_code == 200
        assert "Responsável ativo" in imported.text
        assert "Responsável inativo" not in imported.text
        listed = browser.get("/web/proposals")
        assert listed.status_code == 200
        assert "Cliente contrato" in listed.text
        form = browser.get(f"/web/proposals/new?client_id={client.id}")
        assert form.status_code == 200
        assert "Responsável ativo" in form.text
        assert "Responsável inativo" not in form.text
        detail = browser.get(f"/web/proposals/{proposal.id}?warning=Aviso")
        assert detail.status_code == 200
        assert "Aviso" in detail.text
        revision = browser.post(f"/web/proposals/{proposal.id}/revision")
        assert revision.status_code == 303
        assert revision.headers["location"].endswith(f"/web/proposals/new?revision_from={proposal.id}")
        assert browser.get(revision.headers["location"]).status_code == 200
        for path in ("/web/proposals/99999", "/web/clients/99999"):
            assert browser.get(path).status_code == 404
        assert browser.post("/web/proposals/99999/revision").status_code == 404
        assert browser.post("/web/proposals/99999/duplicate").status_code == 404
