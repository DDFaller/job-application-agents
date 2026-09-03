# Guia de perfis

Um perfil define para quem e para qual família profissional o ranking é executado.
Presets públicos nunca devem conter dados pessoais. Personalizações individuais
devem ficar em `config/profile.local.json` ou em outro arquivo ignorado pelo Git.

## Criar a partir de um preset

```bash
npm run profile:list
npm run profile:init -- --preset administrative-fr
npm run profile:check
```

Para criar uma nova família profissional:

```bash
npm run profile:init -- --preset custom-template
```

Edite todos os valores `SUBSTITUA...` antes de usar o template.

## Seleção e precedência

O carregador usa, nesta ordem:

1. caminho em `JOB_SEARCH_PROFILE`;
2. `config/profile.local.json`;
3. `config/profiles/administrative-fr.json`.

Caminhos relativos são resolvidos a partir da raiz do projeto. Caminhos absolutos
são aceitos em configuração local, mas não devem entrar em presets públicos.

## Campos do schema versão 1

| Campo | Uso |
| --- | --- |
| `id` | Identificador estável, sem identidade pessoal. |
| `display_name` | Nome legível do perfil. |
| `profile_version` | Versão das regras. Atualize quando mudar pesos ou critérios. |
| `career_profile_current` | Manifesto privado opcional do currículo. Deixe vazio no preset público. |
| `top_count` | Quantidade máxima de vagas na shortlist. |
| `minimum_notion_score` | Score mínimo para `notion-ready.json`. |
| `preliminary_threshold` | Score mínimo antes de chamar Gemini. |
| `candidate_experience_years` | Anos completos de experiência relevante comprovada; opcional e somente para perfil local. |
| `required_departments` | Allowlist obrigatória de departamentos para todas as fontes; vagas fora dela são rejeitadas. |
| `required_regions` | Regiões aceitas quando a fonte não fornece código departamental. |
| `france_travail` | Palavras-chave e departamentos enviados à API France Travail. |
| `excluded_terms` | Termos que rejeitam a vaga imediatamente. |
| `blocked_title_terms` | Títulos incompatíveis com o objetivo. |
| `preliminary_title_rules` | Termos de título e score-base do pré-filtro. |
| `preliminary_bonus_rules` | Bônus derivados do título ou conteúdo combinado. |
| `direct_match_rules` | Sinais que somam aderência direta no ranking. |
| `gap_rules` | Expressões regulares que apontam requisitos a verificar. |
| `sector_signals` | Termos tecnológicos e bônus de carreira associados. |
| `career_bonus_terms` | Sinais de formação, evolução ou modernização. |
| `practical_locations` | Localidades em três níveis de preferência. |
| `evidence` | IDs privados que sustentam cada regra direta. |

Termos são normalizados para minúsculas pelo carregador. Expressões regulares usam
as flags informadas em cada `gap_rule`.

## Pesquisa no France Travail

Todo perfil precisa declarar pesquisas próprias para não ficar implicitamente
preso ao preset administrativo:

```json
"france_travail": {
  "keywords": [
    "technicien support informatique",
    "support utilisateurs"
  ],
  "departments": ["75", "92"]
}
```

Cada item de `keywords` gera uma consulta. A API usa blocos de 20 resultados por
palavra-chave e por `--pages`. Os resultados repetidos são deduplicados pelo ID da
oferta.

`departments` aceita no máximo cinco códigos departamentais por exigência da API
France Travail. Use uma lista vazia para pesquisar em toda a França. Presets públicos devem expressar apenas a família profissional;
preferências geográficas individuais pertencem a `config/profile.local.json`.

As palavras-chave aumentam a precisão da descoberta, mas não substituem as regras
do pré-filtro. Uma vaga retornada pela API ainda precisa passar por
`excluded_terms`, `blocked_title_terms`, `preliminary_title_rules` e pelo limite
`preliminary_threshold`.

## Regras de pré-filtro

Cada `preliminary_title_rule` contém:

```json
{
  "source": "title",
  "terms": ["technicien support", "support informatique"],
  "points": 42
}
```

O maior score-base entre as regras correspondentes é usado. Bônus compatíveis são
somados depois. Se a lista de regras de título estiver vazia, nenhum título é
rejeitado por ausência de correspondência; use essa opção com cautela.

## Regras de aderência direta

```json
{
  "source": "all",
  "terms": ["support utilisateurs", "assistance utilisateurs"],
  "points": 10,
  "reason": "suporte a usuários",
  "evidence_key": "user_support"
}
```

`source` aceita `title`, `all` ou `requirements`. `exclusive_group` é opcional e
impede somar mais de uma regra do mesmo grupo, útil para variações de título.

O total de aderência direta é limitado a 50, mesmo que as regras somem mais.

## Lacunas

```json
{
  "source": "requirements",
  "pattern": "certification (?:itil|microsoft)",
  "flags": "i",
  "label": "certificação técnica a verificar"
}
```

Lacunas são alertas para revisão, não conclusões sobre o candidato. O perfil deve
usar rótulos como “a verificar” quando não consultar evidências individuais.

## Localização

Os presets públicos deixam as três listas vazias, produzindo uma avaliação neutra.
Um perfil local pode definir:

```json
"practical_locations": {
  "excellent": ["cidade preferida"],
  "strong": ["região preferida"],
  "acceptable": ["região aceitável"]
}
```

Para impor uma região em vez de apenas dar bônus, use uma allowlist:

```json
"required_departments": ["75", "77", "78", "91", "92", "93", "94", "95"],
"required_regions": ["île-de-france"]
```

Uma localização conhecida fora da allowlist é rejeitada no pré-filtro. Localizações
que a fonte não permite confirmar são rejeitadas no ranking final.

## Evidências e master curriculum

As chaves em `evidence` correspondem a `evidence_key` nas regras. Exemplo local:

```json
"evidence": {
  "user_support": ["MC-EXP-001", "MC-SKILL-004"]
}
```

Ao configurar qualquer ID, forneça também um manifesto em
`CAREER_PROFILE_CURRENT`. O loader verifica se os IDs aparecem entre colchetes nas
fontes aprovadas do manifesto. Não publique o manifesto nem as fontes pessoais.

## Validação

```bash
npm run profile:check
npm test
```

A validação bloqueia schema desconhecido, campos ausentes, pesquisas France Travail
vazias, scores fora dos limites, listas inválidas, fontes de texto desconhecidas e
expressões regulares quebradas.
