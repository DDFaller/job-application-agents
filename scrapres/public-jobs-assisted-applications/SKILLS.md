# Integração com skills do Codex

As skills de candidatura são uma camada opcional sobre o pipeline local. Este
repositório encontra e prioriza oportunidades; as skills validam a vaga, consultam
evidências do usuário, produzem documentos e acompanham a candidatura.

## Skills esperadas

| Operação | Skill |
| --- | --- |
| Candidatura completa | `$prepare-job-application` |
| Fila de candidaturas | `$manage-job-applications` |
| Extração independente da vaga | `$extract-job-opening` |
| Documentos a partir de vaga validada | `$tailor-application-bundle` |
| Perfil profissional aprovado | `$my-career-profile` |
| Correções no currículo canônico | `$maintain-master-curriculum` |
| Criação ou atualização no Notion | `$notion-track-application` |

Essas skills não são copiadas para este projeto porque podem pertencer a outro
repositório ou plugin e ter ciclo de versão próprio.

## Quando este projeto está dentro do repositório de skills

Estrutura recomendada:

```text
repo-raiz/
├── .agents/skills/
│   └── ...
└── public-jobs-assisted-applications/
    ├── AGENTS.md
    └── ...
```

Inicie o Codex no diretório do projeto. O Codex procura `.agents/skills` do
diretório atual até a raiz do Git, então as skills do repositório pai ficam
disponíveis.

## Quando este projeto é um repositório independente

Instale o plugin companion de job applications ou use `$skill-installer` para
instalar as skills a partir do repositório que as distribui. Reinicie o Codex se
elas não aparecerem.

Para distribuição pública de várias skills ou de skills com conectores, prefira um
plugin. Skills exclusivamente ligadas a este repositório também podem ser colocadas
em `.agents/skills`.

## Verificação

Em uma nova sessão na raiz do projeto:

```bash
codex --ask-for-approval never "Liste as instruções do projeto e as skills de candidatura disponíveis."
```

Se uma skill esperada estiver ausente, o pipeline local continua disponível, mas
o agente deve interromper somente a etapa de candidatura que depende dela e
explicar como instalar o companion correto.

## Handoff seguro

1. Selecione uma vaga em `data/notion-ready.json`.
2. Resolva a `source_url` pública.
3. Entregue a URL a `$extract-job-opening` ou `$prepare-job-application`.
4. Trate o JSON Gemini como pista de ranking, não como autoridade final.
5. Use apenas fatos do usuário atual, nunca exemplos do repositório.
6. Não envie candidatura nem marque `APPLIED` sem autorização explícita.

## Handoff pela fila assistida

Para LinkedIn, Indeed ou ATS externo:

```bash
npm run applications:add -- --url "URL_DA_VAGA" --title "TITULO" --employer "EMPRESA"
npm run applications:handoff -- --reference REFERENCIA
```

O segundo comando grava um JSON privado em `data/application-handoffs/` e imprime
o prompt para `$prepare-job-application`. O comando Node.js não executa a skill;
ele apenas cria um contrato de passagem claro.

Depois que a skill gerar e revisar os documentos, registre o bundle e abra a URL:

```bash
npm run applications:attach -- --reference REFERENCIA --bundle "/caminho/do/bundle"
npm run applications:open -- --reference REFERENCIA --launch
```

O formulário e o clique final permanecem sob controle da pessoa.

Documentação oficial: [Build skills](https://learn.chatgpt.com/docs/build-skills)
e [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
