"""Contrato A4: testa métricas e executa as CLIs em processos isolados para não deixar threads bloqueadas.

Executar: python3 -m unittest discover -s ponderada/codigo -v.
A instrumentação de V3 pertence só ao teste; o programa não força o escalonamento.
"""

import dataclasses
import importlib
import json
from pathlib import Path
import subprocess
import sys
import unittest



CODIGO = Path(__file__).resolve().parent


def executar_cli(versao, *argumentos, roteiro=None):
    """Executa versao com argumentos e roteiro opcional em processo isolado; retorna CompletedProcess.

    O limite externo de 12 s evita que uma regressão no watchdog trave os testes.
    """
    comando = [sys.executable, str(CODIGO / f"versao{versao}.py")]
    if roteiro is not None:
        comando = [sys.executable, "-c", roteiro]
    return subprocess.run(
        [*comando, *argumentos], cwd=CODIGO, capture_output=True,
        text=True, timeout=12, check=False,
    )


class ContratoModulo(unittest.TestCase):
    """Adia a importação da implementação para que os testes da CLI possam ser descobertos."""

    def setUp(self):
        """Carrega a implementação nos atributos de self e retorna None; falha se o módulo estiver ausente."""
        try:
            modulo = importlib.import_module("experimento")
        except ModuleNotFoundError as erro:
            if erro.name != "experimento":
                raise
            self.fail("implementação experimento ausente")
        self.configuracao = modulo.Configuracao
        self.calcular_metricas = modulo.calcular_metricas


class ContratoConfiguracao(ContratoModulo):
    """Confere os valores padrão individuais e a rejeição de configurações inválidas."""

    def test_defaults_individuais(self):
        """Verifica os padrões de 20 mil amostras, N=4 e watchdog de 1 s e a imutabilidade; retorna None."""
        config = self.configuracao()
        self.assertEqual((config.total, config.capacidade, config.timeout), (20000, 4, 1.0))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.total = 1

    def test_configuracao_rejeita_numeros_invalidos(self):
        """Exige ValueError para valores não positivos ou não finitos, antes de iniciar threads; retorna None."""
        casos = (
            {"total": 0}, {"total": -1}, {"total": 1.5}, {"total": True},
            {"capacidade": 0}, {"capacidade": -1}, {"capacidade": 2.5},
            {"timeout": 0}, {"timeout": -1}, {"timeout": float("nan")},
            {"timeout": float("inf")},
        )
        for parametros in casos:
            with self.subTest(parametros=parametros), self.assertRaises(ValueError):
                self.configuracao(**parametros)


class ContratoMetricas(ContratoModulo):
    """Distingue perdas antes e depois da produção e conta as retiradas repetidas."""

    def test_metricas_contam_retiradas_e_ids_distintos(self):
        """Valida as oito métricas para 10 amostras solicitadas, 8 produzidas e os IDs 0, 1, 1, 7; retorna None."""
        metricas = self.calcular_metricas(10, 8, (0, 1, 1, 7))
        esperado = {
            "total": 10, "produzidas": 8, "consumidas": 4, "unicas": 3,
            "perdidas": 7, "duplicadas": 1, "nao_produzidas": 2,
            "perdidas_apos_producao": 5,
        }
        self.assertEqual(dataclasses.asdict(metricas), esperado)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            metricas.perdidas = 0

    def test_metricas_sem_retiradas(self):
        """Verifica perdas totais sem retiradas, sem duplicatas ou divisão por zero; retorna None."""
        metricas = self.calcular_metricas(5, 4, ())
        self.assertEqual((metricas.perdidas, metricas.duplicadas, metricas.unicas), (5, 0, 0))
        self.assertEqual(metricas.perdidas_apos_producao, 4)

    def test_metricas_rejeitam_ids_impossiveis(self):
        """Rejeita IDs negativos, não inteiros ou ainda não produzidos e contagens inválidas; retorna None."""
        for recebidas in ((-1,), (4,), (1.5,), (True,)):
            with self.subTest(recebidas=recebidas), self.assertRaises(ValueError):
                self.calcular_metricas(5, 4, recebidas)
        for produzidas in (-1, 6):
            with self.subTest(produzidas=produzidas), self.assertRaises(ValueError):
                self.calcular_metricas(5, produzidas, ())


class ContratoCLI(unittest.TestCase):
    """Executa cada experimento em um processo separado, inclusive quando ocorre deadlock real."""

    def resultado(self, processo):
        """Confere se processo terminou com sucesso e retorna o JSON da última linha de sua saída."""
        self.assertEqual(processo.returncode, 0, processo.stderr + processo.stdout)
        return json.loads(processo.stdout.strip().splitlines()[-1])

    def conferir_identidades(self, dados):
        """Confere as métricas de dados pela sequência de IDs, sem prever a corrida; retorna None."""
        ids = dados["sequencia_consumida"]
        self.assertTrue(all(type(item) is int and 0 <= item < dados["produzidas"] for item in ids))
        self.assertEqual(dados["consumidas"], len(ids))
        self.assertEqual(dados["unicas"], len(set(ids)))
        self.assertEqual(dados["duplicadas"], len(ids) - len(set(ids)))
        self.assertEqual(dados["perdidas"], dados["total"] - len(set(ids)))
        self.assertEqual(dados["nao_produzidas"], dados["total"] - dados["produzidas"])
        self.assertEqual(dados["perdidas_apos_producao"], dados["produzidas"] - len(set(ids)))
        self.assertEqual(dados["perdidas"], dados["nao_produzidas"] + dados["perdidas_apos_producao"])
        self.assertIsInstance(dados["travou"], bool)

    def test_versao2_integra_em_ordem(self):
        """Com N=1 e N=4, verifica que os 500 IDs saem uma vez, em FIFO e sem travar; retorna None."""
        for capacidade in (1, 4):
            with self.subTest(capacidade=capacidade):
                dados = self.resultado(executar_cli(
                    2, "--total", "500", "--capacidade", str(capacidade),
                    "--timeout", "1", "--json", "--incluir-sequencia",
                ))
                self.conferir_identidades(dados)
                self.assertEqual(dados["sequencia_consumida"], list(range(500)))
                self.assertEqual(dados["produzidas"], 500)
                self.assertFalse(dados["travou"])

    def test_versao1_metricas_sem_exigir_corrida_especifica(self):
        """Valida contagens, término e consistência sem fixar um resultado para a corrida; retorna None."""
        dados = self.resultado(executar_cli(
            1, "--total", "300", "--timeout", "0.2", "--json", "--incluir-sequencia",
        ))
        self.conferir_identidades(dados)
        self.assertEqual(dados["total"], 300)
        self.assertLessEqual(dados["produzidas"], 300)

    def test_versao3_deadlock_quando_produtor_enche_antes_consumidor(self):
        """Só no teste, atrasa o consumidor até o produtor bloquear em wait(vazio); verifica o deadlock e retorna None."""
        roteiro = '''import runpy, threading
original_start = threading.Thread.start
original_acquire = threading.Semaphore.acquire
chegou_ao_bloqueio = threading.Event()
def acquire(self, *args, **kwargs):
    """Recebe semáforo/args; avisa wait bloqueante e devolve acquire original."""
    if threading.current_thread().name == "produtor" and self._value == 0:
        chegou_ao_bloqueio.set()
    return original_acquire(self, *args, **kwargs)
def start(self):
    """Recebe thread; inicia consumidor somente após o cenário de teste existir."""
    if self.name == "consumidor" and not chegou_ao_bloqueio.wait(2):
        raise RuntimeError("produtor não alcançou buffer cheio no teste")
    return original_start(self)
threading.Semaphore.acquire = acquire
threading.Thread.start = start
runpy.run_path("versao3.py", run_name="__main__")
'''
        dados = self.resultado(executar_cli(
            3, "--total", "100", "--capacidade", "4", "--timeout", "0.15",
            "--json", "--incluir-sequencia", roteiro=roteiro,
        ))
        self.conferir_identidades(dados)
        self.assertTrue(dados["travou"])
        self.assertEqual((dados["produzidas"], dados["consumidas"]), (4, 0))

    def test_saida_legivel_tambem_termina_com_json(self):
        """Verifica que a saída sem --json traz um resumo legível seguido de um objeto JSON; retorna None."""
        processo = executar_cli(2, "--total", "5")
        dados = self.resultado(processo)
        self.assertGreater(len(processo.stdout.strip().splitlines()), 1)
        self.assertEqual(dados["consumidas"], 5)
        self.assertNotIn("sequencia_consumida", dados)

    def test_versao3_nao_declara_travamento_sem_buffer_cheio(self):
        """Com total menor que N, verifica que V3 termina mesmo com a ordem errada dos waits; retorna None."""
        dados = self.resultado(executar_cli(
            3, "--total", "3", "--capacidade", "4", "--json", "--incluir-sequencia",
        ))
        self.assertEqual(dados["sequencia_consumida"], [0, 1, 2])
        self.assertFalse(dados["travou"])

    def test_erro_na_thread_nao_e_rotulado_como_deadlock(self):
        """Injeta uma exceção no produtor e exige falha com diagnóstico em stderr; retorna None."""
        roteiro = '''import runpy, threading
original_acquire = threading.Semaphore.acquire
def acquire(self, *args, **kwargs):
    """Recebe semáforo/args; falha só no produtor, delegando demais aquisições."""
    if threading.current_thread().name == "produtor":
        raise RuntimeError("falha_injetada_no_produtor")
    return original_acquire(self, *args, **kwargs)
threading.Semaphore.acquire = acquire
runpy.run_path("versao2.py", run_name="__main__")
'''
        processo = executar_cli(2, "--total", "5", "--timeout", "0.2", roteiro=roteiro)
        self.assertEqual(processo.returncode, 1)
        self.assertIn("falha_injetada_no_produtor", processo.stderr)

    def test_argumentos_invalidos_retornam_erro(self):
        """Exige que as CLIs rejeitem contagens inválidas e timeout não finito antes de iniciar; retorna None."""
        casos = (("--total", "0"), ("--capacidade", "-1"), ("--total", "x"),
                 ("--timeout", "0"), ("--timeout", "nan"), ("--timeout", "inf"))
        for versao in (1, 2, 3):
            for argumentos in casos:
                with self.subTest(versao=versao, argumentos=argumentos):
                    processo = executar_cli(versao, *argumentos)
                    self.assertEqual(processo.returncode, 2)
                    self.assertIn("error", processo.stderr.lower())


if __name__ == "__main__":
    unittest.main()
