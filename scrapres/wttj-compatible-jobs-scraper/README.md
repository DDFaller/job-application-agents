# WTTJ Compatible Jobs Scraper

Scraper Python com Playwright para vagas públicas do Welcome to the Jungle. Ele
descobre ofertas, abre cada página individual, extrai os dados e grava em JSON
somente as vagas compatíveis com o perfil profissional aprovado.

O projeto não usa Gemini, outro LLM, login nem candidatura automática.

## Perímetro atual

- Perfil: master curriculum `v002`.
- Nota mínima: `75/100`.
- Localização obrigatória: `93`, `75` (Paris), `94`, `77` ou `92`.
- Contratos aceitos: CDI, CDD, temporário e intérim.
- Estágio, alternância e aprendizagem são rejeitados.
- Vagas comerciais, contábeis, jurídicas, RH, gerenciais e técnicas são
  rejeitadas quando essa especialização aparece no título.
- Requisitos sem evidência, como permis B, Bac+4/Bac+5, Master ou inglês
  avançado, geram rejeição obrigatória.

As regras ficam em [`config/profile.json`](config/profile.json). Os IDs `MC-*`
permitem rastrear cada correspondência ao currículo canônico, sem copiar dados
de contato para o scraper.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/playwright install chromium
```

## Executar

```bash
.venv/bin/wttj-scrape --pages 2 --max-jobs 60
```

Execução pequena para validação:

```bash
.venv/bin/wttj-scrape --pages 1 --max-jobs 5 --delay 1
```

O arquivo é criado em `output/compatible-jobs-AAAA-MM-DD_HHMMSS.json`. Para
escolher o nome:

```bash
.venv/bin/wttj-scrape --output output/vagas.json
```

Opções úteis:

```text
--pages N       páginas por fonte pública de descoberta
--max-jobs N    máximo de páginas individuais de vaga abertas
--min-score N   sobrescreve o corte apenas nesta execução
--delay N       intervalo entre acessos em segundos
--headed        mostra o navegador
--seed-url URL  usa uma página pública específica; pode ser repetida
```

Quando `--seed-url` é informado, ele substitui as fontes padrão. As fontes
padrão são as páginas públicas de Assistant Administratif, Assistant
Administratif em Paris e vagas em Île-de-France.

## Formato da saída

O JSON contém metadados da execução e a lista `jobs`. Cada vaga inclui título,
empresa, localização, contrato, descrição, URL original, nota, motivos da
correspondência, lacunas e IDs de evidência. Ofertas rejeitadas não são gravadas;
apenas suas quantidades entram no resumo. Páginas temporariamente vazias ou com
HTTP `202` são novamente consultadas uma vez e, se continuarem incompletas,
entram em `errors` sem serem avaliadas como vagas.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Uso responsável

O coletor acessa somente páginas públicas, limita paginação e volume, espera
entre requisições e não tenta contornar autenticação, bloqueios ou CAPTCHA. A
estrutura do site pode mudar; nesse caso, o JSON registra os avisos em `errors`.
