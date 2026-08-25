# Avaliação do LinkedIn AI Job Applier Ultimate

Repositório avaliado:
[beatwad/LinkedIn-AI-Job-Applier-Ultimate](https://github.com/beatwad/LinkedIn-AI-Job-Applier-Ultimate)

- branch auditada: `release`;
- commit auditado: `0eac32651d6f89b3420fe5cb452678a9d1a6e2f9`;
- licença declarada: MIT;
- data da auditoria local: 25 de agosto de 2026.

## O que é útil

- separação dos fluxos LinkedIn e Indeed;
- noção de modo de teste sem envio;
- registro do currículo usado e do resultado por vaga;
- tratamento explícito de formulários de múltiplas etapas;
- reconhecimento de que o Indeed redireciona muitas vagas para ATS externos.

## O que não foi incorporado

- Patchright e técnicas para evitar detecção de automação;
- login automático ou armazenamento de senha, cookies e sessão;
- resolução automatizada de CAPTCHA;
- preenchimento ou envio automático de formulários;
- criação automática de contas em sites de terceiros;
- automação de mensagens ou conexões no LinkedIn;
- código-fonte do projeto externo.

Não copiamos código do upstream. A licença e o commit ficam registrados para
reprodutibilidade da avaliação e para deixar clara a origem das ideias gerais.

## Decisão de arquitetura

Este projeto usa um fluxo assistido:

1. recebe uma URL específica de vaga;
2. identifica LinkedIn, Indeed ou site do empregador;
3. cria um handoff para as skills prepararem documentos verdadeiros;
4. exige que o bundle seja anexado à fila local;
5. abre a URL no navegador padrão;
6. a pessoa revisa o formulário e clica em enviar;
7. o status `APPLIED` só é registrado com confirmação explícita.

Esse desenho reduz risco de candidatura incorreta, exposição de credenciais e
quebra causada por mudanças frequentes nas interfaces dos sites.
