# FormalizeAI v4.1

> Assistente inteligente de arquitetura que entrevista desenvolvedores e gera **Software Design Documents (SDD)** completos, validados e prontos para uso por equipes de desenvolvimento.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-2.3-black?logo=flask)
![Groq](https://img.shields.io/badge/Groq-LLaMA%203.3-orange)
![Railway](https://img.shields.io/badge/Deploy-Railway-blueviolet?logo=railway)
![License](https://img.shields.io/badge/License-MIT-green)

---

## 🧠 Como Funciona

```
Usuário → Entrevista conversacional → Orchestrator (até 3 ciclos)
              ↓                               ↓
         PromptEngine              Groq LLM (llama-3.3-70b)
                                            ↓
                                    Validator + Scorer
                                            ↓
                                  SDD Markdown + PDF Export
                                            ↓
                                  Supabase (ou /tmp local)
```

O **Orchestrator** gera o SDD, valida as 15 seções obrigatórias e avalia a qualidade com o **Scorer** (score 0–18). Se o threshold não for atingido, regenera automaticamente até 3 ciclos.

---

## 🚀 Quickstart

### Pré-requisitos

- Python 3.11+
- Conta Groq (gratuita): [console.groq.com](https://console.groq.com)
- (Opcional) Conta Supabase + Redis para persistência em produção

### Instalação local

```bash
git clone https://github.com/Foxactive1/formalizeAi_v2.git
cd formalizeAi_v2

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edite .env e adicione sua GROQ_API_KEY

python app.py
# Acesse: http://127.0.0.1:5000
```

### Produção (Railway)

```bash
railway login
railway init
railway add redis          # Opcional — habilita cache persistente
railway up
```

> ⚠️ **Não use Vercel** para este projeto. A dependência `weasyprint` (geração de PDF) requer Cairo/Pango, que não está disponível no ambiente serverless da Vercel. Use Railway.

---

## 📁 Estrutura do Projeto

```
formalizeAi_v2/
├── app.py               # Entry point Flask — cria a aplicação
├── routes.py            # Endpoints da API (Blueprint /api)
├── orchestrator.py      # Loop de geração + validação (até 3 ciclos)
├── groq_client.py       # Cliente Groq com fallback e retry exponencial
├── scorer.py            # Avaliação de qualidade do SDD (0–18 pts)
├── validator.py         # Valida presença das 15 seções obrigatórias
├── prompt_engine.py     # Prompts de entrevista, geração e correção
├── auth.py              # Autenticação JWT + API Key
├── cache.py             # Cache híbrido Redis / memória
├── rate_limit.py        # Rate limiting por IP ou API Key
├── config.py            # Configurações via variáveis de ambiente
├── supabase_client.py   # Persistência Supabase com fallback /tmp
├── templates/
│   └── index.html       # Frontend da aplicação
├── static/              # Assets (CSS, JS, imagens)
├── test_formalizeai.py  # Suite de testes (pytest)
├── requirements.txt
├── .env.example         # Template de variáveis de ambiente
└── vercel.json          # Config de headers (uso apenas como referência)
```

---

## 🔌 API Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/health` | Status da aplicação e versão |
| `GET` | `/api/models` | Lista de modelos Groq disponíveis |
| `POST` | `/api/chat` | Envia mensagem para o assistente |
| `POST` | `/api/gerar` | Força a geração do SDD completo |
| `GET` | `/api/projeto/<nome>` | Carrega um projeto salvo |
| `GET` | `/api/exportar/<nome>` | Exporta o SDD como PDF |

### Exemplo de uso

```bash
# Iniciar uma conversa
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"project": "meu-projeto", "message": "Quero criar um app de delivery"}'

# Forçar geração do SDD
curl -X POST http://localhost:5000/api/gerar \
  -H "Content-Type: application/json" \
  -d '{"project": "meu-projeto"}'
```

---

## 🧩 Variáveis de Ambiente

Copie `.env.example` para `.env` e configure:

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `GROQ_API_KEY` | ✅ Sim | Chave da API Groq |
| `SECRET_KEY` | ✅ Em produção | Chave para assinar tokens JWT |
| `SUPABASE_URL` | ⚠️ Recomendado | URL do projeto Supabase |
| `SUPABASE_KEY` | ⚠️ Recomendado | Chave anon do Supabase |
| `REDIS_URL` | ⚠️ Recomendado | URL do Redis para cache persistente |
| `X_API_KEY` | Opcional | Chave para auth de serviço |
| `DEFAULT_MODEL` | Opcional | Modelo Groq padrão |
| `QUALITY_THRESHOLD` | Opcional | Score mínimo do SDD (padrão: 12/18) |

---

## 🧪 Testes

```bash
# Rodar toda a suite
pytest test_formalizeai.py -v

# Com relatório de cobertura
pip install pytest-cov
pytest test_formalizeai.py --cov=. --cov-report=term-missing
```

A suite cobre: Validator, Scorer (com bônus), Orchestrator (mock de ciclos), e endpoints Flask.

---

## 🏗️ Arquitetura de Qualidade do SDD

O **Scorer** avalia o documento gerado em dois eixos:

| Critério | Pontos |
|----------|--------|
| Presença de seção Arquitetura | 2 |
| Presença de seção API | 2 |
| Presença de seção Modelo de Dados | 2 |
| Presença de seção Segurança | 2 |
| Presença de seção Testes | 2 |
| Detalhamento (POST, JWT, bcrypt, ADR…) | até 8 |
| Bônus: diagrama Mermaid | +2 |
| Bônus: exemplo JSON de API | +1 |
| Bônus: tabela Markdown | +1 |
| **Total máximo** | **18** |

O threshold padrão é **12/18**. Se não atingido, o Orchestrator regenera automaticamente.

---

## 🔐 Segurança

- Autenticação via JWT (Bearer token) ou API Key (`X-Api-Key`)
- Rate limiting: 60 req/min por IP (configurável)
- Headers de segurança: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`
- Secrets via variáveis de ambiente — nunca hardcoded

---

## 🗺️ Roadmap

### v4.1 (atual)
- [x] Orchestrator com até 3 ciclos de refinamento
- [x] Fallback automático entre 4 modelos Groq
- [x] Export PDF com WeasyPrint
- [x] Cache híbrido Redis/memória
- [x] Persistência Supabase com fallback local

### v4.2 (planejado)
- [ ] Deploy recomendado migrado para Railway
- [ ] Rate limit com backend Redis
- [ ] Upsert atômico no Supabase (evitar perda de histórico)
- [ ] Integração do `evaluate_with_llm` no ciclo de scoring
- [ ] Dashboard de projetos com histórico de SDDs

---

## 👤 Autor

**Dione Castro Alves** — [InNovaIdeia Assessoria em Tecnologia](https://linkedin.com/in/dione-castro-alves)  
GitHub: [@Foxactive1](https://github.com/Foxactive1) · Email: innovaideia2023@gmail.com  
Franca, SP, Brasil — Fundada em 2009

---

## 📄 Licença

MIT License — veja [LICENSE](LICENSE) para detalhes.
