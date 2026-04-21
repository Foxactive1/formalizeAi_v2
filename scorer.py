class Scorer:
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
    MAX_SCORE = 18

    @staticmethod
    def _base_score(sdd: str) -> int:
        """Cálculo original do score (seções + profundidade)."""
        if not sdd:
            return 0
        section_score = sum(pts for term, pts in Scorer._SECTION_CRITERIA if term in sdd)
        depth_score = sum(pts for term, pts in Scorer._DEPTH_CRITERIA if term in sdd)
        return section_score + depth_score

    @staticmethod
    def score(sdd: str) -> int:
        """Score com bônus por qualidade estrutural (Mermaid, JSON, tabelas)."""
        if not sdd:
            return 0
        base = Scorer._base_score(sdd)
        bonus = 0
        if "```mermaid" in sdd:
            bonus += 2
        # Presença de objeto JSON (exemplo de API)
        if '{"' in sdd and '}' in sdd:
            bonus += 1
        # Presença de tabela Markdown (indica requisitos bem estruturados)
        if "|" in sdd and "-|-" in sdd:
            bonus += 1
        return min(base + bonus, Scorer.MAX_SCORE)

    @staticmethod
    def evaluate_with_llm(section_content: str) -> int:
        """Avalia uma seção do SDD via LLM e retorna nota de 1 a 5."""
        from groq_client import generate_response
        prompt = f"""
    Avalie a qualidade técnica da seção abaixo de um SDD de 1 a 5.
    Critérios: Clareza, Detalhamento Técnico, Completude.
    Responda APENAS com o número (ex: 4).

    Seção:
    {section_content}
    """
        response = generate_response(
            [{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )
        try:
            return int(response.strip())
        except Exception:
            return 2  # Nota mínima se falhar

    @staticmethod
    def breakdown(sdd: str) -> dict:
        if not sdd:
            return {
                "section_score": 0,
                "depth_score": 0,
                "bonus": 0,
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
        bonus_details = []
        if "```mermaid" in sdd:
            bonus += 2
            bonus_details.append({"criterion": "Diagrama Mermaid", "points": 2})
        if '{"' in sdd and '}' in sdd:
            bonus += 1
            bonus_details.append({"criterion": "Exemplo JSON", "points": 1})
        if "|" in sdd and "-|-" in sdd:
            bonus += 1
            bonus_details.append({"criterion": "Tabela Markdown", "points": 1})

        total = section_score + depth_score + bonus
        return {
            "section_score": section_score,
            "depth_score": depth_score,
            "bonus": bonus,
            "total": min(total, Scorer.MAX_SCORE),
            "max": Scorer.MAX_SCORE,
            "details": details + bonus_details,
        }