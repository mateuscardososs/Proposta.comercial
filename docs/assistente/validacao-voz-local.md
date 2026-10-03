# Validacao local do assistente por voz

## Resultado

Em 30/09/2026, o fluxo local completo foi executado com audio sintetico gerado pelo
Piper, transcricao real pelo faster-whisper, interpretacao real pelo Ollama,
persistencia em SQLite temporario e resposta de voz real pelo Piper. Nenhum banco,
documento ou volume operacional foi usado.

O roteiro automatizado executou:

1. "Crie uma tarefa para revisar o relatorio amanha."
2. "Na verdade, depois de amanha."
3. "Pode criar."

Resultado: uma unica tarefa `revisar relatorio`, com prazo `02/10/2026`. A resposta
de sucesso foi produzida somente depois da persistencia. Repetir a confirmacao nao
criou outra tarefa.

Esta evidencia usa fala **sintetica**, nao uma gravacao humana. O teste com microfone
humano no navegador e a medicao no Windows/Ryzen continuam pendentes.

## Hardware e software medidos

| Item | Valor |
|---|---|
| Maquina | Apple M5, arm64, 16 GB RAM, SSD com 150 GiB livres antes do download |
| Sistema | macOS 26.6.2 |
| Python | 3.12.14, apenas na `.venv` do projeto |
| Ollama | 0.35.0, `127.0.0.1:11434`, sem nuvem |
| Interpretador | `qwen3:4b-instruct-2507-q4_K_M`, Q4_K_M, 2.497.293.803 bytes |
| STT | `Systran/faster-whisper-small`, multilingue, CPU, INT8 |
| TTS | Piper 1.8.0, `pt_BR-faber-medium`, 22.050 Hz |
| Modelos de voz | 549.422.275 bytes no manifesto; 524 MiB em disco |

Nao se estima o desempenho do Ryzen a partir destes tempos. A CPU Windows precisa
ser medida diretamente.

## Tempos observados

| Etapa | Primeiro uso | Usos seguintes |
|---|---:|---:|
| Piper, fala do usuario sintetica | 0,644 s | 0,076 s e 0,026 s |
| faster-whisper | 1,852 s | 0,925 s e 0,992 s |
| Ollama, interpretacao | 1,006 s | 0,906 s |
| Confirmacao deterministica | - | 0,007 s |

O primeiro tempo de Piper inclui carregamento preguicoso da voz. O primeiro tempo de
STT inclui carregamento preguicoso do modelo. Os numeros sao de uma unica rodada
controlada e nao constituem benchmark.

## Evidencias e casos

| Caso | Resultado real |
|---|---|
| Criacao, correcao e confirmacao | Passou; uma tarefa com data corrigida |
| Confirmacao repetida | Passou; contagem permaneceu em uma tarefa nova |
| Criacao seguida de cancelamento falado | Passou; nenhum segundo card foi criado |
| Audio invalido | `422`; o transcritor nao recebeu conteudo aceito |
| Silencio | `422`; nenhuma mensagem ou tarefa foi criada |
| Resposta falada apos gravacao | Passou; WAV iniciado por `RIFF` |
| Cliente/responsavel ficticios | Alfa Servicos, Alfa Industria, Empresa Beta, Carlos e Ana em banco temporario |
| Falha de TTS depois de salvar | Validada por teste automatizado com falha injetada; repetir audio nao reenvia a solicitacao |
| Encerramento com resposta tardia | Validado por teste JavaScript; nao reproduz nem retoma microfone |
| Fila e timeout | Validado por teste automatizado; um ativo, um pendente e rejeicao imediata do terceiro |

Relatorio bruto da rodada: `/tmp/assistente-voz-validacao.json`. Esse caminho e
temporario e nao faz parte do repositorio.

## Erros encontrados e correcoes

1. `faster-whisper 1.2.1` falhou com PyAV 19 porque essa versao removeu o argumento
   `metadata_errors`. A dependencia opcional foi limitada a `av>=11,<19`; PyAV
   18.1.0 foi instalado e ganhou teste de decodificacao real.
2. Sem vocabulario guiado, o Whisper entendeu a voz Faber dizendo "Pode criar" como
   "Obrigado" ou "O que e que e?". Foi configurado um `initial_prompt` pequeno,
   restrito a confirmacao e cancelamento. O backend ainda aplica limiares mais
   rigorosos a comandos curtos e nunca transforma uma transcricao arbitraria em
   confirmacao.
3. Uma rodada posterior produziu o texto incorreto "Ojectiva" para a mesma fala curta.
   O servico foi endurecido para aceitar confirmacao/cancelamento somente quando o
   texto do usuario corresponde ao vocabulario explicito; uma classificacao do Ollama
   nao pode mais transformar outro texto em confirmacao. A rodada final voltou a
   transcrever "Pode criar" corretamente e passou com essa trava ativa.
4. A voz Piper usa ruido gerativo e variou a primeira palavra em rodadas sinteticas.
   O runner fixa `noise_scale=0` e `noise_w_scale=0` apenas para a regressao
   sintetica reproduzivel; a execucao normal omite esses valores e conserva a voz
   natural. Qualidade com fala humana permanece como aceite manual.

## Modelos, origem e licencas

| Componente | Versao/modelo | Licenca declarada | Observacao |
|---|---|---|---|
| faster-whisper | 1.2.1 | MIT | Adaptador STT substituivel |
| faster-whisper-small | snapshot `536b066...` | MIT | 99 idiomas, incluindo portugues |
| CTranslate2 | 4.8.2 | MIT | Inferencia CPU/INT8 |
| PyAV | 18.1.0 | BSD-3-Clause | Fixado abaixo de 19 por compatibilidade |
| Piper | 1.8.0 | GPL-3.0-or-later | Carregado dentro do processo FastAPI |
| ONNX Runtime | 1.30.0 | MIT | Runtime usado pelo Piper |
| voz Faber medium | `pt_BR-faber-medium` | dataset CC0; repositorio de vozes MIT | Voz brasileira, um locutor |
| Hugging Face Hub | 1.33.0 | Apache-2.0 | Usado somente pelo script de download |
| Ollama | 0.35.0 | MIT | Servidor local separado |
| Qwen3 4B Instruct | Q4_K_M | Apache-2.0 | Interpretador configuravel |

O ONNX da voz possui 63.201.294 bytes e SHA-256
`858555e3a064209c57088fe6bd70c4c3dc54d03eaa00c45d5ecaf43a33f95aa7`.
O script de download verifica esse hash e recusa mais de 2 GB de modelos.

O escopo aprovado e uso interno nos computadores da AD Balancas, sem venda ou
distribuicao. Como o Piper e GPL-3.0-or-later e esta integrado em processo, qualquer
distribuicao futura exige nova analise das obrigacoes do conjunto antes de entregar
binarios, instaladores ou acesso a terceiros. O sintetizador implementa um protocolo
substituivel e pode ser trocado sem mudar o fluxo de tarefas.

Fontes oficiais consultadas:

- <https://github.com/SYSTRAN/faster-whisper>
- <https://huggingface.co/Systran/faster-whisper-small>
- <https://github.com/OHF-Voice/piper1-gpl>
- <https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md>
- <https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/pt/pt_BR/faber/medium/MODEL_CARD>
- <https://github.com/ollama/ollama>

## Roteiro manual no navegador

1. Inicie Ollama e FastAPI conforme `execucao.md`.
2. Abra `http://127.0.0.1:8000/web/assistente` em Chrome, Edge ou Safari atual.
3. Clique **Iniciar conversa** e permita o microfone somente para `127.0.0.1`.
4. Diga: "Crie uma tarefa para revisar o relatorio amanha."
5. Aguarde a previa falada e diga: "Na verdade, depois de amanha."
6. Confira na tela a data resolvida e diga: "Pode criar."
7. Aguarde a confirmacao falada, abra o link da tarefa e confirme que existe apenas
   um card com a data corrigida.
8. Durante uma resposta, use **Interromper audio** e confirme que o microfone volta.
9. Use **Repetir audio**; a tarefa nao deve ser reenviada nem duplicada.
10. Clique **Encerrar conversa**; o indicador deve ficar encerrado e o navegador deve
    parar de mostrar uso do microfone.

O microfone em navegador exige contexto seguro. `http://127.0.0.1` e `localhost` sao
aceitos localmente; nao use IP de rede nem exponha o servidor.

## Pendencias

- executar o roteiro acima com fala humana e registrar erros reais de microfone;
- medir carga, latencia e qualidade no Ryzen 7 3700U com 20-24 GB de RAM;
- validar voz dentro de Docker; a instalacao nativa e a unica configuracao medida;
- implementar autenticacao antes de qualquer acesso de rede, publicacao ou uso externo.
