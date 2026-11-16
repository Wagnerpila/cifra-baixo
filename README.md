# Padrões no braço do baixo

App web (Flask) que lê cifras (PDF, Word, foto/print, link do Cifra Club ou texto) e desenha o padrão do campo
harmônico no braço do baixo de 5 cordas, separado por verso e refrão, com troca de tom.

## EasyPanel
- Fonte: este repositório (build por Dockerfile)
- Porta do app: 8000
- Volume: montar em `/data` (guarda as músicas)
- Variáveis: `CIFRA_PASS` (senha de acesso; usuário padrão `baixo`, mude com `CIFRA_USER`)
- Verificação de saúde: `/healthz`
