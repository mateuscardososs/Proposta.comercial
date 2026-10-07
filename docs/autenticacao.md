# Autenticação local

## Comportamento

- A aplicação exige login para páginas, APIs, voz, uploads, downloads e arquivos estáticos, incluindo `/assets` e `/output`.
- Permanecem públicos apenas `GET /login`, `POST /login` e `GET`/`HEAD /healthz`. O POST de login é público por necessidade do próprio fluxo.
- Não há papéis de autorização no modelo atual. Cada conta ativa autenticada tem o mesmo acesso operacional; a conta inicial é identificada como administradora apenas para fins de provisionamento.
- As senhas novas são armazenadas com Argon2id. Hashes legados que não sejam Argon2id não autenticam. A inicialização não cria usuário ou senha padrão.
- A sessão usa cookie assinado, `HttpOnly`, `SameSite=Lax`, validade padrão de 8 horas e chave `AUTH_SESSION_SECRET`. No uso atual em loopback HTTP, o cookie não tem atributo `Secure`; para operação atrás de HTTPS, habilite `https_only` na configuração do middleware.
- O login limita cinco tentativas por IP a cada 15 minutos no processo local. O estado é em memória e, portanto, é apropriado para a instância local de um processo; uma implantação com vários workers deve usar um limitador compartilhado.
- Escritas de formulário exigem `Origin` ou `Referer` da mesma origem e SameSite=Lax. Escritas `/api/*` também exigem o cabeçalho `X-CSRF-Token`, fornecido pelo frontend autenticado.
- A sessão é verificada contra o usuário ativo em toda solicitação. Desativar a conta invalida sua sessão na próxima requisição.

## Primeiro administrador na instância 8013

O bootstrap usa o PostgreSQL já configurado para a instância e não executa migrações. Ele não muda o `.env`, não desativa ou remove contas existentes e não imprime a senha. A senha é solicitada duas vezes com `getpass` (entrada oculta), exige pelo menos 12 caracteres, é persistida como Argon2id e o próprio fluxo de login é validado contra o banco antes da mensagem de sucesso.

No diretório do repositório, execute:

```bash
.venv/bin/python -m scripts.bootstrap_first_admin
```

O script requer o arquivo privado já utilizado para conectar a 8013 em `../local-data/adbalancas-8013/private/database-url`, com permissão `0600`. Ele cria, se necessário, uma chave aleatória em `../local-data/adbalancas-8013/private/auth-session-secret`, também com permissão `0600`. Esses arquivos ficam fora do repositório. A 8013 só deve ser reiniciada depois de o comando informar que o usuário foi criado e o login foi validado; o launcher falha fechado se a chave ou uma conta Argon2id ativa estiver ausente.

O cadastro legado encontrado na auditoria é preservado. Como sua senha está em formato SHA-256 legado, ela não é aceita pelo login novo. O bootstrap exige um e-mail que não colida com registro existente e não altera essa conta; revise-a depois de entrar, sem reutilizar a senha antiga.

## Outras instalações

Configure `AUTH_ENABLED=true` e injete `AUTH_SESSION_SECRET` por variável de ambiente ou gerenciador de segredos, com pelo menos 32 caracteres aleatórios. Não coloque o segredo em código, logs, argumentos de terminal ou arquivos versionados. Execute um bootstrap equivalente conectado ao banco de destino antes de iniciar a aplicação. O script acima foi desenhado para a instância local 8013, pois usa o arquivo privado de conexão local.

Não há migração de esquema para autenticação: são reutilizados os campos existentes da tabela `users`, e a sessão é stateless. As validações automatizadas usam o banco SQLite isolado da suíte; nenhuma conta foi criada no PostgreSQL operacional durante a implementação.

## Limites

Autenticação não substitui autorização por função: usuários ativos têm acesso completo ao sistema. O servidor deve permanecer em `127.0.0.1` até que uma política de autorização, TLS e proteção contra abuso adequada a acesso compartilhado seja implantada. Arquivos em `/output` agora exigem sessão mesmo quando o caminho é conhecido.
