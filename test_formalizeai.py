import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# Adiciona o diretório atual ao path para importar os módulos
sys.path.append(os.path.dirname(__file__))

# Importa os módulos do projeto
from config import REQUIRED_SECTIONS, QUALITY_THRESHOLD
from validator import Validator
from scorer import Scorer
from orchestrator import Orchestrator, _extract_sdd

# ----------------------------------------------------------------------
# 1. Testes do Validador (validator.py)
# ----------------------------------------------------------------------
def test_validator_completo():
    """Testa um SDD que contém todas as seções obrigatórias."""
    sdd_completo = "\n".join(REQUIRED_SECTIONS)
    result = Validator.validate(sdd_completo)
    assert result["valid"] is True
    assert len(result["missing"]) == 0

def test_validator_incompleto():
    """Testa um SDD faltando a seção de Segurança."""
    sdd_incompleto = "## 1. Visão Geral\nConteúdo..."
    result = Validator.validate(sdd_incompleto)
    assert result["valid"] is False
    assert "## 9. Segurança" in result["missing"]

def test_validator_case_insensitive():
    """Garante que a validação não quebre por diferenças de capitalização."""
    sdd_lower = "## 9. segurança\n## 10. observabilidade"
    result = Validator.validate(sdd_lower)
    # Não deve listar "Segurança" como missing se encontrou "segurança"
    assert "## 9. Segurança" not in result["missing"]

# ----------------------------------------------------------------------
# 2. Testes do Scorer (scorer.py)
# ----------------------------------------------------------------------
def test_scorer_max_score():
    """Testa um SDD perfeito com bônus."""
    base = "\n".join(REQUIRED_SECTIONS)
    bonus = "```mermaid\ngraph TD;\n```\n" \
            '{"exemplo": "json"}\n' \
            "| Tabela | Teste |\n|--------|-------|\n" \
            "POST /api/v1/test"
    
    sdd = base + bonus
    score = Scorer.score(sdd)
    breakdown = Scorer.breakdown(sdd)
    
    # Deve atingir o score máximo (18) por causa dos bônus
    assert score == Scorer.MAX_SCORE
    assert breakdown["total"] == Scorer.MAX_SCORE
    assert breakdown["bonus"] == 4 # 2 (mermaid) + 1 (json) + 1 (tabela)

def test_scorer_empty():
    """Testa SDD vazio."""
    assert Scorer.score("") == 0
    assert Scorer.breakdown("")["total"] == 0

# ----------------------------------------------------------------------
# 3. Testes do Orquestrador (orchestrator.py)
# ----------------------------------------------------------------------
def test_extract_sdd_tag():
    """Testa a remoção da tag [FINALIZANDO SDD]."""
    response = "[FINALIZANDO SDD]\n\n# Título do Projeto\nConteúdo..."
    clean = _extract_sdd(response)
    assert clean.startswith("# Título do Projeto")
    assert "[FINALIZANDO SDD]" not in clean

@patch('orchestrator.generate_with_fallback')
def test_orchestrator_run_success(mock_generate):
    """
    Simula o ciclo completo do orquestrador:
    Primeira tentativa falha (score baixo), segunda tentativa passa.
    """
    # Mock das respostas da Groq
    mock_generate.side_effect = [
        "Resposta ruim sem seções completas",  # Ciclo 1 (score 0)
        "[FINALIZANDO SDD]\n" + "\n".join(REQUIRED_SECTIONS) + "\n```mermaid\ngraph TD;\n```"  # Ciclo 2 (score alto)
    ]

    orch = Orchestrator(model="test-model")
    messages = [{"role": "user", "content": "Crie um SDD"}]
    
    result = orch.run(messages)
    
    # Verificações
    assert result["status"] == "approved"
    assert result["cycles"] == 2
    assert result["score"] >= QUALITY_THRESHOLD
    assert mock_generate.call_count == 2

@patch('orchestrator.generate_with_fallback')
def test_orchestrator_max_cycles_reached(mock_generate):
    """
    Simula o orquestrador falhando em todos os ciclos.
    """
    # Sempre retorna uma resposta vazia (score 0)
    mock_generate.return_value = "Resposta muito curta"
    
    orch = Orchestrator(model="test-model")
    messages = [{"role": "user", "content": "Crie um SDD"}]
    
    result = orch.run(messages)
    
    assert result["status"] == "needs_review"
    assert result["cycles"] == orch.MAX_CYCLES
    assert result["validation"]["valid"] is False

# ----------------------------------------------------------------------
# 4. Testes de Integração (API Flask)
# ----------------------------------------------------------------------
@pytest.fixture
def client():
    """Cria um cliente de teste Flask."""
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_health_endpoint(client):
    """Testa a rota /api/health."""
    response = client.get('/api/health')
    assert response.status_code == 200
    json_data = response.get_json()
    assert "version" in json_data
    assert json_data["version"] == "4.1"

def test_models_endpoint(client):
    """Testa a rota /api/models."""
    response = client.get('/api/models')
    assert response.status_code == 200
    json_data = response.get_json()
    assert "models" in json_data
    assert "llama-3.3-70b-versatile" in json_data["models"]