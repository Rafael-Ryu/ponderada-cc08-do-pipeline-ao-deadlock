"""A4: três protocolos de produtor e consumidor com um buffer circular explícito.

V1 tem uma corrida intencional; V2 usa vazio, cheio e mutex; V3 inverte dois waits.
As simulações não emulam 100 Hz nem demonstram o cumprimento do prazo de 5 ms.
Só o estado compartilhado do experimento é mutável; os relatórios são imutáveis.
Execute cada CLI em um processo separado: o watchdog não desfaz deadlocks.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import math
import queue
import sys
import threading
import time
import traceback


@dataclass(frozen=True)
class Configuracao:
    """Parâmetros individuais: 20 mil amostras, N=4 e 1 s sem retirada."""

    total: int = 20000
    capacidade: int = 4
    timeout: float = 1.0

    def __post_init__(self):
        """Valida os campos de self; retorna None ou lança ValueError antes de iniciar threads."""
        for nome, valor in (("total", self.total), ("capacidade", self.capacidade)):
            if type(valor) is not int or valor <= 0:
                raise ValueError(f"{nome} deve ser inteiro positivo")
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or self.timeout <= 0):
            raise ValueError("timeout deve ser número positivo e finito")


@dataclass(frozen=True)
class Metricas:
    """Contagens observadas: perdas incluem IDs ausentes, não só itens sobrescritos."""

    total: int
    produzidas: int
    consumidas: int
    unicas: int
    perdidas: int
    duplicadas: int
    nao_produzidas: int
    perdidas_apos_producao: int


def calcular_metricas(total, produzidas, recebidas):
    """Retorna Metricas imutável a partir de total, produzidas e dos IDs em recebidas.

    Os IDs devem ser inteiros no intervalo produzido [0, produzidas).
    Erros de instrumentação geram exceções e não são contados como deadlock.
    """
    if type(total) is not int or total <= 0:
        raise ValueError("total deve ser inteiro positivo")
    if type(produzidas) is not int or not 0 <= produzidas <= total:
        raise ValueError("quantidade produzida fora do intervalo solicitado")
    if any(type(item) is not int or not 0 <= item < produzidas for item in recebidas):
        raise ValueError("sequência contém ID não produzido ou inválido")
    unicas = len(set(recebidas))
    return Metricas(total, produzidas, len(recebidas), unicas, total - unicas,
                    len(recebidas) - unicas, total - produzidas, produzidas - unicas)


@dataclass(frozen=True)
class _Resultado:
    """Registro final: as métricas e a sequência não mudam após a captura."""

    metricas: Metricas
    recebidas: tuple
    travou: bool
    duracao: float


class _Estado:
    """Único estado mutável: lista de N posições, índices e contagem de ocupação."""

    def __init__(self, config, versao):
        """Usa config e versao para criar o buffer e os controles; retorna None sem iniciar threads."""
        self.config, self.versao = config, versao
        self.buffer = [None] * config.capacidade
        self.entrada = self.saida = self.ocupadas = self.produzidas = 0
        self.recebidas = []
        self.produtor_acabou = False
        self.ultima_retirada = time.monotonic()
        self.parar = threading.Event()
        self.erros = queue.SimpleQueue()
        if versao != 1:
            self.vazio = threading.Semaphore(config.capacidade)
            self.cheio = threading.Semaphore(0)
            self.mutex = threading.Semaphore(1)

    def _alterar_contador(self, variacao):
        """Soma variacao (+1 ou -1) à ocupação e retorna None; V1 separa leitura e escrita com sleep(0)."""
        anterior = self.ocupadas                 # lê o contador compartilhado
        if self.versao == 1:
            time.sleep(0)                        # cede a CPU entre a leitura e a escrita
        self.ocupadas = anterior + variacao      # a escrita pode perder outra atualização

    def _colocar(self, amostra):
        """Grava o ID amostra, avança a entrada e atualiza as contagens; retorna None sem limpar posições."""
        self.buffer[self.entrada] = amostra
        self.entrada = (self.entrada + 1) % self.config.capacidade
        self.produzidas += 1
        self._alterar_contador(1)
        if self.produzidas == self.config.total:
            # Sinaliza o fim antes de cheio.release(), permitindo retirar o último item.
            self.produtor_acabou = True

    def _retirar(self):
        """Retira a amostra na saída de self, registra o ID e avança o índice; retorna None sem apagar a posição."""
        amostra = self.buffer[self.saida]
        if type(amostra) is not int:
            raise RuntimeError("leitura de slot ainda não inicializado")
        self.saida = (self.saida + 1) % self.config.capacidade
        self.recebidas.append(amostra)
        self.ultima_retirada = time.monotonic()
        self._alterar_contador(-1)

    def produtor(self):
        """Produz os IDs crescentes de self.config pelo protocolo escolhido; retorna None ao parar."""
        for amostra in range(self.config.total):
            if self.parar.is_set():
                return
            if self.versao == 1:
                while self.ocupadas >= self.config.capacidade:
                    if self.parar.is_set():
                        return
                    time.sleep(0)                # espera ocupada, sem lock
                self._colocar(amostra)
                continue
            if self.versao == 2:
                self.vazio.acquire()             # wait(vazio) antes de mutex
                self.mutex.acquire()
            else:
                self.mutex.acquire()             # inversão intencional em V3
                self.vazio.acquire()             # pode bloquear enquanto mantém o mutex
            if self.parar.is_set():
                return
            self._colocar(amostra)
            self.mutex.release()
            self.cheio.release()

    def consumidor(self):
        """Retira amostras de self até a produção terminar e o buffer esvaziar; retorna None ao parar."""
        while not self.parar.is_set():
            if self.produtor_acabou and self.ocupadas == 0:
                return
            if self.versao == 1:
                if self.ocupadas <= 0:
                    time.sleep(0)                # espera ocupada, sem lock
                    continue
                self._retirar()
                continue
            self.cheio.acquire()                 # wait(cheio) antes de mutex
            self.mutex.acquire()
            if self.parar.is_set():
                return
            self._retirar()
            self.mutex.release()
            self.vazio.release()

    def proteger_thread(self, funcao):
        """Executa funcao sem argumentos e retorna None; se ela falhar, envia o traceback ao supervisor."""
        try:
            funcao()
        except BaseException:
            self.erros.put(traceback.format_exc())
            self.parar.set()

    def supervisionar(self):
        """Supervisiona as threads de self e retorna _Resultado ao terminarem ou vencer o watchdog; propaga erros.

        As CLIs usam threads daemon porque V3 mantém os waits reais,
        sem timeout no acquire, sentinela, cancelamento ou liberações artificiais.
        Em V1, pede a parada e aguarda as threads com join antes de copiar
        as retiradas, para que a lista não mude durante a leitura. Cada CLI encerra seu processo.
        """
        inicio = time.monotonic()
        self.ultima_retirada = inicio
        produtor = threading.Thread(target=self.proteger_thread, args=(self.produtor,),
                                    name="produtor", daemon=True)
        consumidor = threading.Thread(target=self.proteger_thread, args=(self.consumidor,),
                                      name="consumidor", daemon=True)
        produtor.start()                         # mesma ordem de início nas três versões
        consumidor.start()
        travou = False
        while produtor.is_alive() or consumidor.is_alive():
            if not self.erros.empty():
                break
            if time.monotonic() - self.ultima_retirada >= self.config.timeout:
                travou = True
                break
            time.sleep(min(0.005, self.config.timeout / 10))
        self.parar.set()
        for thread in (produtor, consumidor):
            thread.join(None if self.versao == 1 else 0.05)
        if not self.erros.empty():
            raise RuntimeError(self.erros.get())
        recebidas = tuple(self.recebidas)
        metricas = calcular_metricas(self.config.total, self.produzidas, recebidas)
        if self.versao == 2 and not travou and recebidas != tuple(range(self.config.total)):
            raise RuntimeError("V2 violou integridade ou ordem FIFO")
        return _Resultado(metricas, recebidas, travou, time.monotonic() - inicio)


def main(versao):
    """Recebe versao (1, 2 ou 3), lê os argumentos da CLI, imprime o relatório e retorna o código de saída.

    Execute em processo isolado: as threads daemon bloqueadas de V3
    terminam com o processo; o protocolo continua sujeito ao deadlock.
    """
    parser = argparse.ArgumentParser(description=f"A4 — versão {versao}")
    parser.add_argument("--total", type=int, default=20000)
    parser.add_argument("--capacidade", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=1.0, help="segundos sem retirada")
    parser.add_argument("--json", action="store_true", help="imprimir somente o JSON final")
    parser.add_argument("--incluir-sequencia", action="store_true", help="incluir IDs retirados no JSON")
    args = parser.parse_args()
    try:
        config = Configuracao(args.total, args.capacidade, args.timeout)
    except ValueError as erro:
        parser.error(str(erro))
    if versao not in (1, 2, 3):
        parser.error("versão deve ser 1, 2 ou 3")
    try:
        resultado = _Estado(config, versao).supervisionar()
    except Exception as erro:
        print(f"Erro no experimento: {erro}", file=sys.stderr)
        return 1
    dados = {**asdict(resultado.metricas), "versao": versao, "capacidade": config.capacidade,
             "timeout": config.timeout, "travou": resultado.travou,
             "duracao_s": round(resultado.duracao, 6),
             **({"sequencia_consumida": resultado.recebidas} if args.incluir_sequencia else {})}
    if not args.json:
        print(f"Versão {versao} | N={config.capacidade} | solicitadas={config.total}")
        print(f"Produzidas: {dados['produzidas']} | consumidas: {dados['consumidas']} | únicas: {dados['unicas']}")
        print(f"Perdidas: {dados['perdidas']} | duplicadas: {dados['duplicadas']} | travou: {dados['travou']}")
        print(f"Não produzidas: {dados['nao_produzidas']} | perdidas após produção: {dados['perdidas_apos_producao']}")
    print(json.dumps(dados, ensure_ascii=False))
    return 0
