"""A4 V2: usa vazio(N), cheio(0) e mutex(1); espera pelo semáforo de contagem antes do mutex.

Uso: python3 ponderada/codigo/versao2.py [--total 20000 --capacidade 4 --timeout 1].
Simula concorrência; não emula 100 Hz nem comprova o cumprimento do prazo de 5 ms.
"""

from experimento import main


if __name__ == "__main__":
    raise SystemExit(main(2))
