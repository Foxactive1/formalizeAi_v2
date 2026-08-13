# scorer.py — FormalizeAI v4.1
#
# MUDANÇAS v4.1:
# - evaluate_with_llm() integrado ao score() via parâmetro use_llm=True
# - Novo método score_sections_with_llm() avalia as 5 seções críticas individualmente
# - LLM scoring usa llama-3.1-8b-instant (rápido/barato) para não impactar latência
# - Fallback automático: se o LLM falhar, o score heurístico original é mantido
# - MAX_SCORE expandido para 28 quando use_llm=True (18 heurístico + 10 LLM)
# - score() sem argumentos mantém comportamento original — zero breaking change nos testes

import logging
import re

log = logging.getLogger("formalizeai")


class Scorer:
    # --- Critérios heurísticos (comportamento original, não alterado) ---

    _SECTION_CRITERIA = [
        ("Arquitetura", 2),
        ("API", 2),
        ("Modelo de Dados", 2),
        ("Segurança", 2),
        ("Testes", 2),
    ]
    _DEPTH_CRITERIA = [
        ("POST", 1),
        ("GET", 1),
        ("VARCHAR", 1),
        ("INTEGER", 1),
        ("JWT", 1),
        ("bcrypt", 1),
        ("ADR-", 1),
        ("v1.", 1),
    ]

    # Seções críticas avaliadas pelo LLM (nome → header Markdown esperado)
    _LLM_SECTIONS = {
        "Arquitetura":     "## 6. Arquitetura",
        "Modelo de Dados": "## 7. Modelo de Dados",
        "APIs":            "## 8. APIs",
        "Segurança":       "## 9. Segurança",
        "Testes":          "## 13. Testes",
    }

    # Score máximo heurístico (sem LLM) — mantido para não quebrar testes existentes
    MAX_SCORE = 18

    # Score máximo com LLM habilitado (18 heurístico + até 10 do LLM, 2 pts por seção)
    MAX_SCORE_WITH_LLM = 28

    # -------------------------------------------------------------------
    # Métodos privados
    # -------------------------------------------------------------------

    @staticmethod
    def _base_score(sdd: str) -> int:
        """Cálculo heurístico original (seções + profundidade técnica)."""
        if not sdd:
            return 0
        section_score = sum(pts for term, pts in Scorer._SECTION_CRITERIA if term in sdd)
        depth_score = sum(pts for term, pts in Scorer._DEPTH_CRITERIA if term in sdd)
        return section_score + depth_score

    @staticmethod
    def _extract_section(sdd: str, header: str) -> str:
        """
        Extrai o conteúdo de uma seção do SDD a partir do header Markdown.
        Retorna o texto entre o header e o próximo header de mesmo nível (## ).
        """
        pattern = re.compile(
            rf"^{re.escape(header)}.*?(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(sdd)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _llm_score_section(section_name: str, section_content: str) -> int:
        """
        Avalia uma seção do SDD via LLM e retorna nota de 0 a 2.
        Usa llama-3.1-8b-instant (modelo leve) para minimizar latência e custo.

        Escala de retorno:
          0 — seção ausente ou sem conteúdo técnico relevante
          1 — seção presente mas superficial / genérica
          2 — seção completa, detalhada e tecnicamente precisa

        Retorna 0 em caso de falha (degradação graciosa).
        """
        if not section_content or len(section_content.strip()) < 50:
            log.debug(f"Seção '{section_name}' vazia ou muito curta — LLM score = 0")
            return 0

        try:
            from groq_client import generate_response

            prompt = (
                f"Avalie a qualidade técnica da seção '{section_name}' abaixo de um "
                f"Software Design Document (SDD).\n\n"
                f"Critérios de avaliação:\n"
                f"- Clareza: a seção é compreensível sem ambiguidades?\n"
                f"- Detalhamento Técnico: há especificações concretas (tecnologias, padrões, exemplos)?\n"
                f"- Completude: cobre os aspectos essenciais esperados para essa seção?\n\n"
                f"Retorne APENAS um número inteiro:\n"
                f"  0 = ausente ou irrelevante\n"
                f"  1 = superficial ou genérico\n"
                f"  2 = completo e tecnicamente preciso\n\n"
                f"Seção:\n{section_content[:1500]}"  # limita tokens enviados
            )

            response = generate_response(
                [{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
            )

            # Extrai o primeiro dígito válido da resposta
            match = re.search(r"\b([012])\b", response.strip())
            score = int(match.group(1)) if match else 0
            log.debug(f"LLM score seção '{section_name}': {score}/2")
            return score

        except Exception as e:
            log.warning(f"evaluate_with_llm falhou para '{section_name}': {e} — usando score 0")
            return 0

    # -------------------------------------------------------------------
    # API pública
    # -------------------------------------------------------------------

    @staticmethod
    def evaluate_with_llm(section_content: str) -> int:
        """
        API original mantida para compatibilidade retroativa.
        Avalia um bloco de conteúdo genérico e retorna nota de 1 a 5.

        Para avaliação integrada ao ciclo de scoring, use score(use_llm=True).
        """
        if not section_content or len(section_content.strip()) < 50:
            return 1

        try:
            from groq_client import generate_response

            prompt = (
                "Avalie a qualidade técnica da seção abaixo de um SDD de 1 a 5.\n"
                "Critérios: Clareza, Detalhamento Técnico, Completude.\n"
                "Responda APENAS com o número (ex: 4).\n\n"
                f"Seção:\n{section_content}"
            )
            response = generate_response(
                [{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
            )
            match = re.search(r"\b([1-5])\b", response.strip())
            return int(match.group(1)) if match else 2

        except Exception as e:
            log.warning(f"evaluate_with_llm falhou: {e}")
            return 2  # nota mínima de fallback

    @staticmethod
    def score_sections_with_llm(sdd: str) -> dict:
        """
        Avalia individualmente as 5 seções críticas do SDD via LLM.
        Retorna um dict com o score por seção e o total LLM (0–10).

        Usado pelo Orchestrator quando use_llm=True.
        """
        results = {}
        total = 0
        for section_name, header in Scorer._LLM_SECTIONS.items():
            content = Scorer._extract_section(sdd, header)
            section_score = Scorer._llm_score_section(section_name, content)
            results[section_name] = {"score": section_score, "max": 2}
            total += section_score

        return {
            "by_section": results,
            "llm_total": total,
            "llm_max": len(Scorer._LLM_SECTIONS) * 2,  # 10
        }

    @staticmethod
    def score(sdd: str, use_llm: bool = False) -> int:
        """
        Score total do SDD.

        use_llm=False (padrão):
            Retorna score heurístico 0–18 (comportamento original — zero breaking change).

        use_llm=True:
            Retorna score combinado 0–28:
              - 0–18: score heurístico (seções + profundidade + bônus estrutural)
              - +0–10: score LLM (2 pts por seção crítica bem avaliada)

        O Orchestrator usa use_llm=True no ciclo final (quando o heurístico já passou).
        """
        if not sdd:
            return 0

        base = Scorer._base_score(sdd)
        bonus = 0

        if "```mermaid" in sdd:
            bonus += 2
        if '{"' in sdd and "}" in sdd:
            bonus += 1
        if "|" in sdd and "-|-" in sdd:
            bonus += 1

        heuristic = min(base + bonus, Scorer.MAX_SCORE)

        if not use_llm:
            return heuristic

        # LLM scoring — executado apenas quando solicitado
        llm_result = Scorer.score_sections_with_llm(sdd)
        combined = min(heuristic + llm_result["llm_total"], Scorer.MAX_SCORE_WITH_LLM)
        log.info(
            f"Score heurístico: {heuristic}/{Scorer.MAX_SCORE} | "
            f"Score LLM: {llm_result['llm_total']}/{llm_result['llm_max']} | "
            f"Total combinado: {combined}/{Scorer.MAX_SCORE_WITH_LLM}"
        )
        return combined

    @staticmethod
    def breakdown(sdd: str, use_llm: bool = False) -> dict:
        """
        Detalhamento completo do score por critério.
        Inclui seção LLM quando use_llm=True.
        """
        if not sdd:
            return {
                "section_score": 0,
                "depth_score": 0,
                "bonus": 0,
                "llm_score": 0,
                "total": 0,
                "max": Scorer.MAX_SCORE,
                "details": [],
            }

        details = []

        section_score = 0
        for term, pts in Scorer._SECTION_CRITERIA:
            hit = term in sdd
            if hit:
                section_score += pts
            details.append({"criterion": term, "type": "section", "points": pts, "hit": hit})

        depth_score = 0
        for term, pts in Scorer._DEPTH_CRITERIA:
            hit = term in sdd
            if hit:
                depth_score += pts
            details.append({"criterion": term, "type": "depth", "points": pts, "hit": hit})

        bonus = 0
        if "```mermaid" in sdd:
            bonus += 2
            details.append({"criterion": "Diagrama Mermaid", "type": "bonus", "points": 2, "hit": True})
        if '{"' in sdd and "}" in sdd:
            bonus += 1
            details.append({"criterion": "Exemplo JSON", "type": "bonus", "points": 1, "hit": True})
        if "|" in sdd and "-|-" in sdd:
            bonus += 1
            details.append({"criterion": "Tabela Markdown", "type": "bonus", "points": 1, "hit": True})

        heuristic = min(section_score + depth_score + bonus, Scorer.MAX_SCORE)

        llm_result = {"by_section": {}, "llm_total": 0, "llm_max": 0}
        if use_llm:
            llm_result = Scorer.score_sections_with_llm(sdd)
            for name, data in llm_result["by_section"].items():
                details.append({
                    "criterion": f"[LLM] {name}",
                    "type": "llm",
                    "points": data["score"],
                    "max_points": data["max"],
                    "hit": data["score"] > 0,
                })

        total = min(
            heuristic + llm_result["llm_total"],
            Scorer.MAX_SCORE_WITH_LLM if use_llm else Scorer.MAX_SCORE,
        )

        return {
            "section_score": section_score,
            "depth_score": depth_score,
            "bonus": bonus,
            "llm_score": llm_result["llm_total"],
            "total": total,
            "max": Scorer.MAX_SCORE_WITH_LLM if use_llm else Scorer.MAX_SCORE,
            "details": details,
        }
