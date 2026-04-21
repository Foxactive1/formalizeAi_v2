# prompt_engine.py
from config import SYSTEM_PROMPT

class PromptEngine:
    @staticmethod
    def initial_interview(user_message: str) -> str:
        """Retorna a mensagem do usuário para continuar a entrevista.
        O SYSTEM_PROMPT já fornece todas as diretrizes."""
        return user_message

    @staticmethod
    def force_generation() -> str:
        """Prompt para forçar a geração do SDD completo."""
        return (
            "Com base em TUDO que foi discutido nesta entrevista, "
            "gere agora o Software Design Document completo e atualizado. "
            "Responda exatamente com [FINALIZANDO SDD] seguido do documento inteiro em Markdown."
        )

    @staticmethod
    def fix_prompt(validation: dict, score: int, max_score: int) -> str:
        """Prompt de correção para o ciclo de orquestração."""
        missing_list = "\n".join(f"  - {s}" for s in validation["missing"])
        return (
            f"O SDD gerado não atingiu o padrão mínimo.\n\n"
            f"Score atual: {score}/{max_score}.\n"
            f"Seções faltando ou com conteúdo insuficiente:\n{missing_list}\n\n"
            "**INSTRUÇÕES CRÍTICAS DE CORREÇÃO:**\n"
            "1. Preencha TODAS as seções obrigatórias.\n"
            "2. **SUBSTITUA QUALQUER DESCRIÇÃO DE ARQUITETURA POR CÓDIGO MERMAID VÁLIDO.**\n"
            "3. Inclua exemplos de código de API (JSON) reais.\n\n"
            "Regenere o SDD completo agora."
        )