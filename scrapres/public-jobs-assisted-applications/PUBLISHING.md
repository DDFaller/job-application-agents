# Checklist de publicação

Execute esta revisão antes de cada publicação ou release.

## Segredos e dados pessoais

- `.env` não está versionado.
- `config/profile.local.json` não está versionado.
- Não existem nomes, e-mails, telefones, endereços ou caminhos de usuário nos
  arquivos públicos.
- Presets públicos têm `career_profile_current` vazio.
- Presets públicos não contêm IDs de evidência pessoais.
- `data/`, `output/` e `imports/` contêm somente `.gitkeep` no commit.
- `data/application-queue.json` e `data/application-handoffs/` não estão
  versionados; eles podem conter URLs e caminhos de bundles privados.
- Nenhuma senha, cookie ou sessão de LinkedIn/Indeed está presente.
- Nenhum token Gemini ou Notion aparece no histórico.

Verificação local sugerida:

```bash
rg -n "GEMINI_API_KEY=.+|NOTION_(TOKEN|KEY)=.+|/Users/|/home/" \
  --glob '!node_modules/**' \
  --glob '!PUBLISHING.md' \
  --glob '!.env' .
```

Revise manualmente qualquer resultado; valores de exemplo podem ser legítimos.

## Qualidade

```bash
npm ci
npm run profile:list
npm run profile:check
npm test
```

Confirme também que os três presets são válidos:

```bash
npm run profile:check -- --profile config/profiles/administrative-fr.json
npm run profile:check -- --profile config/profiles/it-support-fr.json
npm run profile:check -- --profile config/profiles/custom-template.json
```

## GitHub

- Escolha uma licença antes da publicação. Este template não presume autorização
  para licenciar o trabalho em nome do proprietário.
- Defina descrição, tópicos, suporte e política de contribuições do repositório.
- Configure proteção de branch e exija o workflow de testes quando apropriado.
- Informe a URL do plugin/repositório companion de skills em `SKILLS.md` quando
  estiver disponível.
- Revise dependências e alertas do Dependabot.
- Mantenha `UPSTREAM_ASSESSMENT.md` atualizado se uma decisão passar a reutilizar
  código do projeto externo; nesse caso, preserve também os avisos da licença MIT.

## Release

- Atualize a versão em `package.json` e `package-lock.json`.
- Descreva alterações de schema ou migração de perfis.
- Nunca inclua um `profile.local.json` em artefatos de release.
