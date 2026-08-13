# test_formalizeai.py — FormalizeAI v4.1
# Suite completa de testes — todos os testes originais preservados + novos para v4.1

import pytest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(__file__))

from config import REQUIRED_SECTIONS, QUALITY_THRESHOLD
from validator import Validator
from scorer import Scorer
from orchestrator import Orchestrator, _extract_sdd

# Fixture: SDD completo reutilizável nos testes
SDD_BASE = "\n".join(REQUIRED_SECTIONS)
SDD_COM_BONUS = (
    SDD_BASE
    + "\n```mermaid\ngraph TD;\n```\n"
    + '{"exemplo": "json"}\n'
    + "| Tabela | Teste |\n|--------|-------|\n"
    + "POST /api/v1/test GET VARCHAR INTEGER JWT bcrypt ADR-001 v1.0"
)

# -----------------------------------------------------------------------
# 1. Testes do Validador (validator.py) — originais preservados
# -----------------------------------------------------------------------

def test_validator_completo():
    """SDD com todas as seções obrigatórias deve ser válido."""
    result = Validator.validate(SDD_BASE)
    assert result["valid"] is True
    assert len(result["missing"]) == 0


def test_validator_incompleto():
    """SDD sem seção de Segurança deve reportar a seção como missing."""
    sdd = "## 1. Visão Geral\nConteúdo..."
    result = Validator.validate(sdd)
    assert result["valid"] is False
    assert "## 9. Segurança" in result["missing"]


def test_validator_case_insensitive():
    """Validação deve tolerar variações de capitalização."""
    sdd = "## 9. segurança\n## 10. observabilidade"
    result = Validator.validate(sdd)
    assert "## 9. Segurança" not in result["missing"]


def test_validator_sdd_vazio():
    """SDD vazio deve ser inválido com todas as seções faltando."""
    result = Validator.validate("")
    assert result["valid"] is False
    assert len(result["missing"]) == len(REQUIRED_SECTIONS)


# -----------------------------------------------------------------------
# 2. Testes do Scorer heurístico — originais preservados
# -----------------------------------------------------------------------

def test_scorer_max_score():
    """SDD completo com bônus deve atingir MAX_SCORE (18)."""
    score = Scorer.score(SDD_COM_BONUS)
    breakdown = Scorer.breakdown(SDD_COM_BONUS)

    assert score == Scorer.MAX_SCORE
    assert breakdown["total"] == Scorer.MAX_SCORE
    assert breakdown["bonus"] == 4  # mermaid(2) + json(1) + tabela(1)


def test_scorer_empty():
    """SDD vazio deve retornar score 0."""
    assert Scorer.score("") == 0
    assert Scorer.breakdown("")["total"] == 0


def test_scorer_sem_bonus():
    """SDD com seções mas sem elementos de bônus deve ter bonus=0."""
    score = Scorer.score(SDD_BASE)
    breakdown = Scorer.breakdown(SDD_BASE)
    assert breakdown["bonus"] == 0
    assert score < Scorer.MAX_SCORE


def test_scorer_use_llm_false_retrocompat():
    """score(use_llm=False) deve se comportar identicamente ao score() original."""
    assert Scorer.score(SDD_COM_BONUS) == Scorer.score(SDD_COM_BONUS, use_llm=False)
    assert Scorer.score("") == Scorer.score("", use_llm=False)


# -----------------------------------------------------------------------
# 3. Testes do Scorer com LLM (v4.1) — novos
# -----------------------------------------------------------------------

@patch("scorer.Scorer._llm_score_section", return_value=2)
def test_scorer_llm_max_score(mock_llm):
    """
    Com LLM retornando 2 para todas as 5 seções, o score combinado deve ser
    MAX_SCORE_WITH_LLM (28 = 18 heurístico + 10 LLM).
    """
    score = Scorer.score(SDD_COM_BONUS, use_llm=True)
    assert score == Scorer.MAX_SCORE_WITH_LLM
    assert mock_llm.call_count == 5  # uma chamada por seção crítica


@patch("scorer.Scorer._llm_score_section", return_value=0)
def test_scorer_llm_fallback_zero(mock_llm):
    """
    Se LLM retorna 0 para todas as seções, o score total
    deve ser idêntico ao heurístico puro.
    """
    score_heuristic = Scorer.score(SDD_COM_BONUS, use_llm=False)
    score_with_llm = Scorer.score(SDD_COM_BONUS, use_llm=True)
    assert score_with_llm == score_heuristic


@patch("scorer.Scorer._llm_score_section", return_value=1)
def test_scorer_llm_parcial(mock_llm):
    """Score parcial: 5 seções × 1pt = +5 pts sobre o heurístico."""
    score_heuristic = Scorer.score(SDD_COM_BONUS, use_llm=False)
    score_with_llm = Scorer.score(SDD_COM_BONUS, use_llm=True)
    assert score_with_llm == min(score_heuristic + 5, Scorer.MAX_SCORE_WITH_LLM)


@patch("scorer.Scorer._llm_score_section", side_effect=Exception("Groq timeout"))
def test_scorer_llm_exception_retorna_zero(mock_llm):
    """
    Se o LLM lançar exceção, _llm_score_section deve retornar 0
    e o sistema não deve crashar (degradação graciosa).
    """
    # _llm_score_section já captura a exceção internamente e retorna 0
    # Testamos via score_sections_with_llm que agrega os resultados
    result = Scorer.score_sections_with_llm(SDD_COM_BONUS)
    assert result["llm_total"] == 0


def test_scorer_breakdown_llm_campos():
    """breakdown(use_llm=False) deve retornar campo llm_score=0."""
    bd = Scorer.breakdown(SDD_BASE, use_llm=False)
    assert "llm_score" in bd
    assert bd["llm_score"] == 0
    assert bd["max"] == Scorer.MAX_SCORE


@patch("scorer.Scorer._llm_score_section", return_value=2)
def test_scorer_breakdown_llm_detalhado(mock_llm):
    """breakdown(use_llm=True) deve ter entradas de tipo 'llm' nos detalhes."""
    bd = Scorer.breakdown(SDD_COM_BONUS, use_llm=True)
    llm_details = [d for d in bd["details"] if d["type"] == "llm"]
    assert len(llm_details) == 5
    assert bd["max"] == Scorer.MAX_SCORE_WITH_LLM


def test_extract_section_presente():
    """_extract_section deve retornar o conteúdo da seção corretamente."""
    sdd = "## 6. Arquitetura\nUsamos microsserviços.\n\n## 7. Modelo de Dados\nTabelaX."
    content = Scorer._extract_section(sdd, "## 6. Arquitetura")
    assert "microsserviços" in content
    assert "TabelaX" not in content  # não vaza para a seção seguinte


def test_extract_section_ausente():
    """_extract_section deve retornar string vazia para seção inexistente."""
    content = Scorer._extract_section("## 1. Visão Geral\nTexto.", "## 9. Segurança")
    assert content == ""


# -----------------------------------------------------------------------
# 4. Testes do evaluate_with_llm — API retrocompatível
# -----------------------------------------------------------------------

@patch("scorer.generate_response", return_value="4")
def test_evaluate_with_llm_valido(mock_gen):
    """evaluate_with_llm deve retornar inteiro 1–5."""
    score = Scorer.evaluate_with_llm("Seção com conteúdo técnico detalhado " * 5)
    assert 1 <= score <= 5


def test_evaluate_with_llm_conteudo_vazio():
    """evaluate_with_llm com conteúdo vazio deve retornar 1 (mínimo) sem chamar LLM."""
    score = Scorer.evaluate_with_llm("")
    assert score == 1


# -----------------------------------------------------------------------
# 5. Testes do Orquestrador (orchestrator.py) — originais preservados
# -----------------------------------------------------------------------

def test_extract_sdd_tag():
    """_extract_sdd deve remover a tag [FINALIZANDO SDD]."""
    response = "[FINALIZANDO SDD]\n\n# Título do Projeto\nConteúdo..."
    clean = _extract_sdd(response)
    assert clean.startswith("# Título do Projeto")
    assert "[FINALIZANDO SDD]" not in clean


@patch("orchestrator.Scorer.score_sections_with_llm")
@patch("orchestrator.generate_with_fallback")
def test_orchestrator_run_success(mock_generate, mock_llm_scoring):
    """
    Ciclo 1 falha (score baixo), ciclo 2 aprova e dispara LLM scoring final.
    """
    sdd_aprovado = "[FINALIZANDO SDD]\n" + SDD_COM_BONUS
    mock_generate.side_effect = [
        "Resposta ruim sem seções",   # Ciclo 1
        sdd_aprovado,                 # Ciclo 2
    ]
    mock_llm_scoring.return_value = {
        "by_section": {s: {"score": 2} for s in Scorer._LLM_SECTIONS},
        "llm_total": 10,
        "llm_max": 10,
    }

    orch = Orchestrator(model="test-model")
    result = orch.run([{"role": "user", "content": "Crie um SDD"}])

    assert result["status"] == "approved"
    assert result["cycles"] == 2
    assert result["heuristic_score"] >= QUALITY_THRESHOLD
    assert result["llm_score"] == 10
    assert mock_generate.call_count == 2
    mock_llm_scoring.assert_called_once()  # LLM scoring só roda ao final


@patch("orchestrator.generate_with_fallback")
def test_orchestrator_max_cycles_reached(mock_generate):
    """Orquestrador deve retornar needs_review após esgotar todos os ciclos."""
    mock_generate.return_value = "Resposta muito curta"

    orch = Orchestrator(model="test-model")
    result = orch.run([{"role": "user", "content": "Crie um SDD"}])

    assert result["status"] == "needs_review"
    assert result["cycles"] == orch.MAX_CYCLES
    assert result["validation"]["valid"] is False
    assert result["llm_score"] == 0  # LLM não roda em needs_review


@patch("orchestrator.generate_with_fallback", side_effect=RuntimeError("Groq down"))
def test_orchestrator_groq_failure(mock_generate):
    """Falha total do Groq deve retornar status error."""
    orch = Orchestrator(model="test-model")
    result = orch.run([{"role": "user", "content": "Crie um SDD"}])
    assert result["status"] == "error"
    assert "Groq down" in result["message"]


# -----------------------------------------------------------------------
# 6. Testes de Integração (API Flask)
# -----------------------------------------------------------------------

@pytest.fixture
def client():
    """Cria um cliente de teste Flask."""
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """GET /api/health deve retornar version 4.1."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert "version" in data
    assert data["version"] == "4.1"


def test_models_endpoint(client):
    """GET /api/models deve retornar llama-3.3-70b-versatile."""
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.get_json()
    assert "models" in data
    assert "llama-3.3-70b-versatile" in data["models"]
