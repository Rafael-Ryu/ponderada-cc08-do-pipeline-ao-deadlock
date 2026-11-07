"""A4 V3: o produtor adquire mutex antes de esperar por vazio, o que pode causar deadlock.

Uso: python3 ponderada/codigo/versao3.py [--total 20000 --capacidade 4 --timeout 1].
Simula concorrência; o watchdog relata o bloqueio sem liberar os semáforos.
"""

from experimento import main


if __name__ == "__main__":
    raise SystemExit(main(3))
