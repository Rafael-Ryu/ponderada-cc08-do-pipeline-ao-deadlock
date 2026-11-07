"""A4 V1: contador compartilhado, espera ocupada e corrida com sleep(0).

Uso: python3 ponderada/codigo/versao1.py [--total 20000 --capacidade 4 --timeout 1].
Simula concorrência; não emula 100 Hz nem comprova o cumprimento do prazo de 5 ms.
"""

from experimento import main


if __name__ == "__main__":
    raise SystemExit(main(1))
