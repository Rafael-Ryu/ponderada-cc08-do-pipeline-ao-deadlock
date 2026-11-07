# Do pipeline ao deadlock

Rafael Ryu Tati Nakahara.

Estudo de uma pulseira sensorial: escolha de processador, pipeline e concorrência, com três versões de um buffer circular e uma decisão de produção.

## Entrega

A resolução está em [ponderada/ponderada-tato.md](ponderada/ponderada-tato.md), com as questões A1 a A5 e o memorando do dilema 2.

Parâmetros individuais: Rafael (6) + Ryu (3) + Tati (4) + Nakahara (8) = 21 letras. D1 = 6; D2 = 1; N = 4.

## Rodar as três versões da A4

Use Python 3.10 ou superior, sem instalar pacotes adicionais. Na raiz do repositório, execute:

```bash
# Versão 1: contador sem proteção, corrida intencional e espera ocupada
python3 ponderada/codigo/versao1.py

# Versão 2: vazio(4), cheio(0) e mutex(1), na ordem correta
python3 ponderada/codigo/versao2.py

# Versão 3: produtor adquire mutex antes de vazio, podendo causar deadlock
python3 ponderada/codigo/versao3.py
```

Cada comando solicita 20.000 amostras, numeradas de 0 a 19.999, e usa um buffer circular de quatro posições. Se o consumidor passar um segundo sem receber, o programa registra travamento. A saída traz um resumo e, na última linha, o JSON com as contagens.

O watchdog encerra a simulação sem corrigir o defeito. Se houver threads bloqueadas nos waits, elas são descartadas quando o processo termina, pois são daemon. Execute cada versão em seu próprio processo pelos comandos acima; não importe as CLIs para repetir os experimentos dentro de um único processo.

Para reproduzir a entrega, execute cada comando três vezes. Os resultados de V1 variam com o escalonamento, e uma rodada sem erros não comprova a correção do algoritmo. A simulação não emula os 100 Hz da pulseira nem mede o prazo de 5 ms do firmware.

Opções úteis:

```bash
# Incluir todos os IDs consumidos para conferir perdas, repetições e ordem
python3 ponderada/codigo/versao2.py --total 20000 --capacidade 4 --timeout 1 --incluir-sequencia

# Emitir somente JSON
python3 ponderada/codigo/versao1.py --json
```

`consumidas` conta todas as retiradas, inclusive repetições, e pode ultrapassar 20.000 em V1. `perdidas` conta os IDs solicitados que não chegaram ao consumidor. Como um deadlock pode interromper a geração antes de 20.000 amostras, o relatório distingue `nao_produzidas` de `perdidas_apos_producao`. A questão A4 explica essas contagens e apresenta os resultados.

## Testes

Na raiz:

```bash
python3 -m unittest discover -s ponderada/codigo -v
```

A suíte verifica entradas, métricas, execução dos três programas, ordem FIFO e encerramento pelo watchdog. O teste de deadlock controla o escalonamento apenas no subprocesso de teste; as nove rodadas da entrega não usam esse controle. Exceções durante a execução são registradas separadamente dos travamentos.

A medição de cobertura é opcional e usa `coverage` 7.10 ou superior. Os comandos com `uv` mantêm esse pacote em um ambiente isolado, sem acrescentar dependências às três versões:

```bash
uv run --no-project --with coverage python -m coverage erase --rcfile=ponderada/codigo/cobertura.ini
uv run --no-project --with coverage python -m coverage run --rcfile=ponderada/codigo/cobertura.ini -m unittest discover -s ponderada/codigo -v
uv run --no-project --with coverage python -m coverage combine --rcfile=ponderada/codigo/cobertura.ini
uv run --no-project --with coverage python -m coverage report --rcfile=ponderada/codigo/cobertura.ini
```

## Estrutura

```text
.
├── .gitignore
├── README.md
└── ponderada/
    ├── ponderada-tato.md
    ├── codigo/
    │   ├── experimento.py
    │   ├── cobertura.ini
    │   ├── versao1.py
    │   ├── versao2.py
    │   ├── versao3.py
    │   └── test_experimento.py
    ├── img/                     # prints reais de caches e das três versões
    └── resultados/              # nove execuções, sequências e validações
```

Os arquivos `ponderada/resultados/v*-execucao-*.json` guardam os comandos e as sequências observadas. Os resumos dos prints estão em `v*-terminal.txt`. Os arquivos `lscpu.txt` e `ambiente.json` registram a máquina usada nas execuções.

A versão de entrega recebe a tag local `PONDERADA-CC08`. Para publicar no GitHub, inclua a branch `main` e essa tag.
